"""GitHub Actions entrypoint. All untrusted inputs are read as JSON, never shell."""
import json
import os
import time
import urllib.request
import uuid
from pathlib import Path

from protocol import encode, loads, validate


def prepare_task(event, owner_id, event_name, run_id, attempt, now):
    if event.get("sender", {}).get("id") != owner_id:
        raise ValueError("sender is not the paired owner")
    if event_name != "workflow_dispatch":
        raise ValueError("unsupported event")
    # Deterministic per-run ID prevents rerun from applying a task twice.
    task = loads(event["inputs"]["task"])
    task_id = task.get("request_id", "gh-" + run_id)
    full = {"v": 1, "id": task_id, "device": task["device"], "op": task["op"],
            "args": task["args"], "issued_at": now, "expires_at": now + 1800}
    if set(task) not in ({"device", "op", "args"}, {"device", "op", "args", "request_id"}):
        raise ValueError("unexpected submission fields")
    validate(full, now=now)
    # Forbid a rerun: a regenerated signature/timestamp with the same ID would collide.
    if attempt != "1":
        raise ValueError("rerun disabled; inspect status and submit a new authorized task")
    return full


def main():
    event = loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_bytes())
    full = prepare_task(event, int(os.environ["OWNER_ID"]), os.environ["GITHUB_EVENT_NAME"],
                        os.environ["GITHUB_RUN_ID"], os.environ.get("GITHUB_RUN_ATTEMPT", "1"), int(time.time()))
    task_id = full["id"]
    allowed = os.environ.get("ALLOWED_OPERATION", "")
    if allowed and full["op"] != allowed:
        raise ValueError("operation is outside the delegated environment scope")
    url = os.environ["BROKER_URL"]
    from urllib.parse import urlsplit
    u = urlsplit(url)
    if u.scheme != "https" or not u.netloc or u.username or u.password or u.query or u.fragment or u.path not in ("", "/"):
        raise ValueError("broker must be a fixed HTTPS origin")
    # Keys are written only to the runner's ephemeral private directory.
    key = Path(os.environ["RUNNER_TEMP"]) / (str(uuid.uuid4()) + ".pem")
    with os.fdopen(os.open(key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as output:
        output.write(os.environ["TASK_SIGNING_KEY"])
    try:
        body = json.dumps(encode(full, key)).encode()
    finally:
        key.unlink(missing_ok=True)
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            raise ValueError("redirect refused")
    req = urllib.request.Request(url.rstrip("/") + "/v1/tasks", data=body,
                                 headers={"Authorization": "Bearer " + os.environ["BROKER_WRITER_TOKEN"],
                                          "Content-Type": "application/json"})
    with urllib.request.build_opener(NoRedirect).open(req, timeout=20) as response:
        if response.status not in (200, 201):
            raise ValueError("submission failed")
    print("Queued " + task_id + "; device execution is not yet confirmed")


if __name__ == "__main__":
    main()
