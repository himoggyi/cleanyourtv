"""Prepare a new private pairing bundle; never enable tasks or update the projector.

Use a fresh directory outside every Git checkout. Private keys/tokens must not be
uploaded in chat. An absent device token produces an explicitly invalid template.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from github_queue import REPOSITORY, REPOSITORY_ID


def prepare(directory, device, token=None):
    root = Path(directory).resolve()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", device) or device == "cloud-probe":
        raise ValueError("invalid device")
    if token is not None and not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", token):
        raise ValueError("invalid device token")
    # Managed runtimes can mount empty read-only .git placeholders at /tmp and
    # /workspace. They are not repositories. Detect real metadata/worktree links.
    if any((parent / ".git").is_file() or (parent / ".git" / "HEAD").is_file()
           or ((parent / "HEAD").is_file() and (parent / "objects").is_dir())
           for parent in (root, *root.parents)):
        raise ValueError("private material must be outside Git checkouts")
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    # The directory must be new: never overwrite an existing controller key or pairing.
    key = root / "task-private.pem"
    subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:3072",
                    "-out", str(key)], check=True, capture_output=True)
    key.chmod(0o600)
    public = subprocess.run(["openssl", "pkey", "-in", str(key), "-pubout"],
                            check=True, capture_output=True, text=True).stdout
    der = subprocess.run(["openssl", "pkey", "-in", str(key), "-pubout", "-outform", "DER"],
                         check=True, capture_output=True).stdout
    fingerprint = hashlib.sha256(der).hexdigest()
    (root / "task-public.pem").write_text(public)
    pairing = {"transport": "github-issues", "repository": REPOSITORY, "repository_id": REPOSITORY_ID,
               "device": device, "token": token or "DEVICE_TOKEN_REQUIRED", "public_key": public}
    output = root / ("pairing.json" if token else "pairing-template.INVALID.json")
    output.write_text(json.dumps(pairing, indent=2))
    output.chmod(0o600)
    info = {"rsa_spki_sha256": fingerprint, "device": device,
            "pairing_ready": token is not None, "production_secret_configured": False,
            "installed_apk_signature": "UNVERIFIED", "device_tasks_enabled": False}
    (root / "PREPARATION.json").write_text(json.dumps(info, indent=2))
    return info


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", required=True)
    p.add_argument("--device", default="x5pro")
    a = p.parse_args()
    # Read only an explicitly configured variable; never discover or print secret values.
    print(json.dumps(prepare(a.out, a.device, os.environ.get("PROJECTOR_DEVICE_GITHUB_TOKEN"))))


if __name__ == "__main__":
    main()
