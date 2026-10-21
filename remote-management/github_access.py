"""Diagnose actual dispatch permission, without changing repository/OAuth permissions."""
import argparse
import json
import os
import subprocess
import datetime
import urllib.error
from dispatch import dispatch


def probe_ci(run=subprocess.run):
    """Opt-in real CI dispatch using the configured gh identity; never a device task.

    Reading metadata is insufficient. Even an accepted CI dispatch proves neither
    a durable task queue nor a projector receipt. Do not retry an ambiguous POST.
    """
    report = {"checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "repository": "himoggyi/cleanyourtv", "workflow": "ci.yml",
              "dispatch": "not_attempted", "device_execution": "unverified",
              "free_task_channel": "not_verified"}
    def call(args):
        return run(["gh", "api", *args], capture_output=True, text=True, timeout=20)
    try:
        identity = call(["user"])
        if identity.returncode or json.loads(identity.stdout).get("id") != 143339177:
            report["reason"] = "owner_identity_not_verified"
            return report
        workflows = call(["repos/himoggyi/cleanyourtv/actions/workflows"])
        if workflows.returncode:
            report["reason"] = "workflow_read_failed"
            return report
        items = json.loads(workflows.stdout)["workflows"]
        report["relay_deployed"] = any(w.get("path") == ".github/workflows/projector-relay.yml"
                                        and w.get("state") == "active" for w in items)
        if not any(w.get("path") == ".github/workflows/ci.yml" and w.get("state") == "active" for w in items):
            report["reason"] = "probe_workflow_missing"
            return report
        report["dispatch"] = "outcome_unknown"
        result = call(["--method", "POST", "repos/himoggyi/cleanyourtv/actions/workflows/ci.yml/dispatches",
                       "-f", "ref=main"])
        if result.returncode == 0:
            report["dispatch"] = "accepted"
            report["reason"] = "CI_only_not_a_device_receipt"
        else:
            try:
                status = json.loads(result.stdout).get("status")
            except (ValueError, AttributeError):
                status = None
            if str(status) in {"401", "403", "404", "422"}:
                report["dispatch"] = "rejected"
                report["http_status"] = int(status)
                report["reason"] = "Actions_write_required" if str(status) == "403" else "GitHub_rejected_request"
            else:
                report["reason"] = "transport_or_response_failure_do_not_auto_retry"
    except subprocess.TimeoutExpired:
        report["reason"] = "timeout_do_not_auto_retry"
    except (ValueError, KeyError, TypeError, AttributeError, OSError):
        report["reason"] = "invalid_response_or_local_tool_unavailable"
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dispatch-status", action="store_true", help="actual harmless status task; requires deployed relay + pairing")
    p.add_argument("--dispatch-ci", action="store_true", help="actually trigger existing main CI to test configured gh write access; no device task")
    a = p.parse_args()
    if a.dispatch_ci:
        if a.dispatch_status:
            p.error("choose only one dispatch probe")
        report = probe_ci()
        print(json.dumps(report, ensure_ascii=False))
        raise SystemExit(0 if report["dispatch"] == "accepted" else 2)
    if os.environ.get("PROJECTOR_GITHUB_TOKEN"):
        try:
            print(json.dumps(dispatch({"device": "x5pro", "op": "status", "args": {}} if a.dispatch_status else None, probe=not a.dispatch_status)))
        except urllib.error.HTTPError as e:
            hint = ("single-repository fine-grained token: Actions write; do not expand GITHUB_TOKEN workflow permissions" if e.code == 403
                    else "check that projector-relay.yml exists on main and this token can access the repository" if e.code == 404
                    else "refresh the dedicated credential in the secure secret store" if e.code == 401
                    else "inspect GitHub availability and dispatch validation")
            print(json.dumps({"http_status": e.code, "dispatch_permission": "not proven" if not a.dispatch_status else "blocked",
                              "next_step": hint}))
            raise SystemExit(2)
    else:
        if a.dispatch_status:
            raise SystemExit("PROJECTOR_GITHUB_TOKEN is absent; no task sent")
        # Use the configured gh connection normally. Never inspect token values or credential files.
        try:
            r = subprocess.run(["gh", "api", "repos/himoggyi/cleanyourtv/actions/workflows", "--jq", ".workflows[] | {name,path,state}"], capture_output=True, text=True, timeout=20)
        except subprocess.TimeoutExpired:
            print(json.dumps({"workflow_read": "timeout", "dispatch_permission": "not proven"}))
            raise SystemExit(2)
        print(json.dumps({"configured_dedicated_token": False, "workflow_read": r.returncode == 0,
                          "dispatch_permission": "not proven by this read", "next_step": "configure PROJECTOR_GITHUB_TOKEN through secure secrets"}))


if __name__ == "__main__":
    main()
