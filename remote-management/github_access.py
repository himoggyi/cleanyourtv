"""Diagnose actual dispatch permission, without changing repository/OAuth permissions."""
import argparse
import json
import os
import subprocess
import urllib.error
from dispatch import dispatch


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dispatch-status", action="store_true", help="actual harmless status task; requires deployed relay + pairing")
    a = p.parse_args()
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
        r = subprocess.run(["gh", "api", "repos/himoggyi/cleanyourtv/actions/workflows", "--jq", ".workflows[] | {name,path,state}"], capture_output=True, text=True)
        print(json.dumps({"configured_dedicated_token": False, "workflow_read": r.returncode == 0,
                          "dispatch_permission": "not proven by this read", "next_step": "configure PROJECTOR_GITHUB_TOKEN through secure secrets"}))


if __name__ == "__main__":
    main()
