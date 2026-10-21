"""Generate deployment credentials OUTSIDE the source checkout; never print secrets."""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
from http_client import origin
from protocol import ID


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--broker", required=True)
    p.add_argument("--device", default="x5pro")
    a = p.parse_args()
    url = origin(a.broker); out = a.output.resolve()
    if out.is_relative_to(Path(__file__).resolve().parents[1]) or not ID.fullmatch(a.device):
        p.error("use a valid device ID and a private directory outside the checkout")
    os.umask(0o077); out.mkdir(mode=0o700, parents=True, exist_ok=True)
    if any(out.iterdir()): raise SystemExit("refusing to overwrite existing credentials")
    private, public = out / "task-signing.pem", out / "task-public.pem"
    subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:3072", "-out", str(private)], capture_output=True, check=True)
    subprocess.run(["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)], capture_output=True, check=True)
    writer, reader, uploader, device = (secrets.token_urlsafe(32) for _ in range(4))
    config = {"writer_token": writer, "reader_token": reader, "devices": {a.device: device},
              "upload_tokens": {a.device: uploader}, "public_key": "/etc/cleanyourtv/task-public.pem"}
    (out / "broker.json").write_text(json.dumps(config, indent=2))
    (out / "pairing.json").write_text(json.dumps({"device": a.device, "broker": url, "token": device, "public_key": public.read_text()}, indent=2))
    for name, data in (("writer-token", writer), ("reader-token", reader), ("upload-token", uploader)):
        (out / name).write_text(data)
    for f in out.iterdir(): f.chmod(0o600)
    print("Private files generated. Transfer only broker.json + task-public.pem to the server, pairing.json to the device,")
    print("task-signing.pem + writer-token to GitHub Environment secrets, reader/upload tokens to the cloud secret store.")


if __name__ == "__main__":
    main()
