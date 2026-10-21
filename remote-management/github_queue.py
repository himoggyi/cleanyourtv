"""Private GitHub Issues transport; reuse protocol.py RSA and relay.py authorization.

Cloud probes are explicitly separated from device tasks. No device is contacted.
All API calls go to a fixed repository, with no automatic POST retry.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from protocol import encode, exact, loads, verify
from relay import prepare_task

REPOSITORY = "himoggyi/cleanyourtv-tasks"
REPOSITORY_ID = 1428876145
OWNER_ID = 143339177


class GitHub:
    def api(self, suffix="", method="GET", data=None):
        args = ["gh", "api", "--hostname", "github.com", "--method", method,
                "repos/" + REPOSITORY + suffix]
        if data is not None:
            args += ["--input", "-"]
        try:
            result = subprocess.run(args, input=json.dumps(data) if data is not None else None,
                                    text=True, capture_output=True, timeout=20)
        except subprocess.TimeoutExpired:
            raise RuntimeError("GitHub request timed out; mutation outcome may be unknown; do not auto-retry") from None
        if result.returncode:
            # Do not echo response bodies, environment or credentials to Actions logs.
            raise RuntimeError("GitHub request failed; inspect authorization/settings; do not auto-retry mutation")
        return json.loads(result.stdout)


def require_private(api):
    repo = api.api()
    if (repo.get("id") != REPOSITORY_ID or repo.get("full_name") != REPOSITORY
            or repo.get("owner", {}).get("id") != OWNER_ID
            or repo.get("private") is not True or repo.get("has_issues") is not True):
        raise ValueError("fixed owner/private repository with Issues required")


def build_record(event, mode, run_id, attempt, key_path, public_key, now=None, device=None):
    task = prepare_task(event, OWNER_ID, "workflow_dispatch", run_id, attempt,
                        int(time.time()) if now is None else now)
    if mode not in {"cloud-probe", "authorized-status"}:
        raise ValueError("unknown queue mode")
    if task["op"] != "status":
        raise ValueError("initial GitHub transport permits only status")
    if mode == "cloud-probe":
        if task["device"] != "cloud-probe":
            raise ValueError("probe cannot target a paired device")
    elif not device or device == "cloud-probe" or task["device"] != device:
        raise ValueError("configured paired device required")
    record = {"schema": "cleanyourtv.github-task.v1",
              "kind": "cloud_probe" if mode == "cloud-probe" else "device_task",
              "run_id": run_id, "envelope": encode(task, key_path)}
    if mode == "cloud-probe":
        record["probe_public_key"] = public_key
    # Cross-check what is actually persisted, including signature and target.
    verify_record(record, public_key, task["device"], allow_probe=mode == "cloud-probe")
    return task, record


def verify_record(record, pinned_public_key, device, allow_probe=False):
    probe = record.get("kind") == "cloud_probe"
    fields = {"schema", "kind", "run_id", "envelope"}
    exact(record, fields | {"probe_public_key"} if probe else fields)
    if record["schema"] != "cleanyourtv.github-task.v1" or record["kind"] not in {"cloud_probe", "device_task"}:
        raise ValueError("unsupported queue record")
    if probe and (not allow_probe or device != "cloud-probe"):
        raise ValueError("cloud probes are never device tasks")
    # The caller supplies a pinned key. Device records never supply their own trust anchor.
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "public.pem"
        path.write_text(pinned_public_key)
        task = verify(record["envelope"], path, device)
    if task["op"] != "status":
        raise ValueError("initial GitHub transport permits only status")
    return task


def publish(api, task, record):
    require_private(api)  # Fail closed if visibility or ownership changed.
    body = json.dumps(record, sort_keys=True, separators=(",", ":"))
    if len(body.encode()) > 16000:
        raise ValueError("queue record too large")
    issue = api.api("/issues", "POST", {"title": "[signed-task] " + task["id"], "body": body})
    if type(issue.get("number")) is not int:
        raise RuntimeError("GitHub response ambiguous; inspect ledger before retry")
    return issue["number"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["cloud-probe", "authorized-status"], required=True)
    args = parser.parse_args()
    if (os.environ.get("GITHUB_REPOSITORY") != REPOSITORY
            or os.environ.get("GITHUB_REPOSITORY_ID") != str(REPOSITORY_ID)
            or os.environ.get("GITHUB_REF") != "refs/heads/main"
            or os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"):
        raise ValueError("only manual dispatch on the fixed private main branch is permitted")
    api = GitHub()
    require_private(api)
    event = loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_bytes())
    # Validate before generating/reading a key or making any mutation.
    task = prepare_task(event, OWNER_ID, "workflow_dispatch", os.environ["GITHUB_RUN_ID"],
                        os.environ.get("GITHUB_RUN_ATTEMPT", "1"), int(time.time()))
    if task["op"] != "status":
        raise ValueError("only status permitted")
    if args.mode == "cloud-probe" and task["device"] != "cloud-probe":
        raise ValueError("probe target must be cloud-probe")
    if args.mode == "authorized-status" and (os.environ.get("PROJECTOR_ENABLE_DEVICE_TASKS") != "true"
            or not os.environ.get("PROJECTOR_DEVICE_ID")
            or task["device"] != os.environ["PROJECTOR_DEVICE_ID"]):
        raise ValueError("device tasks remain disabled until owner configures pairing and signing")
    with tempfile.TemporaryDirectory() as folder:
        key = Path(folder) / "private.pem"
        if args.mode == "cloud-probe":
            subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:3072",
                            "-out", str(key)], check=True, capture_output=True)
        else:
            value = os.environ.get("PROJECTOR_TASK_SIGNING_KEY")
            if not value:
                raise ValueError("production signing secret is not configured")
            with os.fdopen(os.open(key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as output:
                output.write(value)
        key.chmod(0o600)
        public_key = subprocess.run(["openssl", "pkey", "-in", str(key), "-pubout"],
                                    check=True, capture_output=True, text=True).stdout
        task, record = build_record(event, args.mode, os.environ["GITHUB_RUN_ID"],
                                    os.environ.get("GITHUB_RUN_ATTEMPT", "1"), key, public_key,
                                    device=os.environ.get("PROJECTOR_DEVICE_ID"))
        number = publish(api, task, record)
    # Read-after-write does not substitute for an independent later read or a device receipt.
    require_private(api)
    saved = api.api("/issues/" + str(number))
    recovered = verify_record(loads(saved["body"]), public_key, task["device"],
                              allow_probe=args.mode == "cloud-probe")
    if recovered != task:
        raise ValueError("persisted task differs")
    print(json.dumps({"issue_number": number, "task_id": task["id"], "persisted_and_verified": True,
                      "kind": record["kind"], "device_execution": "not_tested"}))


if __name__ == "__main__":
    main()
