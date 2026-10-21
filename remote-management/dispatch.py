"""Optional future sender. --probe is read-only and never claims actual dispatch readiness.

Requires a separately provisioned fine-grained token, Actions:write for this repo.
Never paste a PAT into chat. Use the cloud environment's secure secret configuration.
"""
import argparse
import json
import os
import urllib.request
from protocol import loads


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--probe", action="store_true")
    p.add_argument("--task", help="strict device/op/args JSON")
    a = p.parse_args()
    token = os.environ.get("PROJECTOR_GITHUB_TOKEN")
    if not token:
        raise SystemExit("Unavailable: PROJECTOR_GITHUB_TOKEN is not securely configured; no request sent")
    endpoint = "https://api.github.com/repos/himoggyi/cleanyourtv/actions/workflows/projector-relay.yml"
    data = None
    if not a.probe:
        if a.task is None:
            p.error("--task required unless --probe")
        from protocol import validate
        import time
        task = loads(a.task)
        if set(task) != {"device", "op", "args"}:
            p.error("task fields must be device/op/args")
        now = int(time.time())
        validate(dict(task, v=1, id="validation", issued_at=now, expires_at=now + 600))
        endpoint += "/dispatches"
        data = json.dumps({"ref": "main", "inputs": {"task": json.dumps(task)}}).encode()
    req = urllib.request.Request(endpoint, data=data, headers={"Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"})
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            raise ValueError("redirect refused")
    with urllib.request.build_opener(NoRedirect).open(req, timeout=20) as r:
        if a.probe:
            info = loads(r.read(16385))
            print(json.dumps({"workflow": info.get("name"), "state": info.get("state"),
                              "dispatch_write_permission": "not proven by a read-only request"}))
        else:
            print("GitHub accepted dispatch; runner, broker and projector execution are still unconfirmed")


if __name__ == "__main__":
    main()
