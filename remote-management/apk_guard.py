"""Offline Android 9 update gate. Never installs, uninstalls, clears or changes HOME."""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path


def inspect(apk, tools):
    apk = Path(apk).resolve()
    certs = subprocess.check_output([str(tools / "apksigner"), "verify", "--min-sdk-version", "28", "--print-certs", str(apk)], text=True)
    signers = sorted(re.findall(r"Signer #\d+ certificate SHA-256 digest: ([0-9a-fA-F]{64})", certs))
    badging = subprocess.check_output([str(tools / "aapt"), "dump", "badging", str(apk)], text=True)
    package = re.search(r"package: name='([^']+)' versionCode='(\d+)'", badging)
    minimum = re.search(r"sdkVersion:'(\d+)'", badging)
    if not package or not minimum or not signers:
        raise ValueError("cannot verify APK identity")
    return {"package": package[1], "version_code": int(package[2]), "min_sdk": int(minimum[1]),
            "signers_sha256": [s.lower() for s in signers], "sha256": hashlib.sha256(apk.read_bytes()).hexdigest()}


def compatible(installed, candidate):
    if installed["package"] != candidate["package"]:
        raise ValueError("package mismatch; do not uninstall the current launcher")
    if installed["signers_sha256"] != candidate["signers_sha256"]:
        raise ValueError("signing certificate mismatch; obtain the original signing key; do not uninstall")
    if candidate["min_sdk"] > 28:
        raise ValueError("candidate does not support Android 9")
    if candidate["version_code"] <= installed["version_code"]:
        raise ValueError("require a strictly higher versionCode; do not use a downgrade flag")
    return {"compatible": True, "method": "in-place update only", "preserves_data": "PackageManager update; no clear/uninstall/migration"}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--installed-apk", type=Path, required=True, help="base.apk extracted from the ACTUAL projector")
    p.add_argument("--candidate", type=Path, required=True)
    p.add_argument("--build-tools", type=Path, required=True)
    a = p.parse_args()
    old, new = inspect(a.installed_apk, a.build_tools), inspect(a.candidate, a.build_tools)
    report = {"installed": old, "candidate": new}
    try:
        report.update(compatible(old, new))
    except ValueError as e:
        report.update(compatible=False, reason=str(e)); print(json.dumps(report, indent=2)); raise SystemExit(2)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
