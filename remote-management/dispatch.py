"""Optional future sender. --probe is read-only and never claims actual dispatch readiness.

Requires a separately provisioned fine-grained token, Actions:write for this repo.
Never paste a PAT into chat. Use the cloud environment's secure secret configuration.
"""
import argparse
import json
import os
import urllib.request
from protocol import loads


def dispatch(task=None, probe=False):
    token = os.environ.get("PROJECTOR_GITHUB_TOKEN")
    if not token:
        raise ValueError("PROJECTOR_GITHUB_TOKEN is not securely configured")
    endpoint = "https://api.github.com/repos/himoggyi/cleanyourtv/actions/workflows/projector-relay.yml"
    data = None
    if not probe:
        from protocol import validate, ID
        import time
        if type(task) is not dict or set(task) not in ({"device", "op", "args"}, {"device", "op", "args", "request_id"}):
            raise ValueError("invalid task fields")
        now = int(time.time()); task_id = task.get("request_id", "validation")
        if type(task_id) is not str or not ID.fullmatch(task_id): raise ValueError("invalid request ID")
        validate({"v": 1, "id": task_id, "device": task["device"], "op": task["op"], "args": task["args"], "issued_at": now, "expires_at": now + 600})
        endpoint += "/dispatches"
        data = json.dumps({"ref": "main", "inputs": {"task": json.dumps(task)}}).encode()
    req = urllib.request.Request(endpoint, data=data, headers={"Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"})
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs): raise ValueError("redirect refused")
    with urllib.request.build_opener(NoRedirect).open(req, timeout=20) as r:
        if probe:
            info = loads(r.read(16385))
            return {"workflow": info.get("name"), "state": info.get("state"), "dispatch_write_permission": "not proven by a read-only request"}
        if r.status != 204: raise ValueError("GitHub did not accept workflow dispatch")
        return {"dispatch": "accepted", "device_execution": "unconfirmed"}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--probe", action="store_true")
    p.add_argument("--task", help="strict device/op/args JSON")
    a = p.parse_args()
    if not a.probe and a.task is None: p.error("--task required unless --probe")
    print(json.dumps(dispatch(loads(a.task) if a.task else None, probe=a.probe)))


if __name__ == "__main__":
    main()
