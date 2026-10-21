"""Read-only collection from an explicitly selected LOCAL ADB device; no discovery or connect."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--serial", required=True, help="an already authorized, locally connected ADB serial")
    p.add_argument("--adb", default="adb")
    p.add_argument("--package", default="com.gathin.tvhome")
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+", a.package):
        p.error("invalid package")
    os.umask(0o077); a.output.mkdir(parents=True, exist_ok=True)
    def adb(*args):
        return subprocess.check_output([a.adb, "-s", a.serial, *args], text=True, timeout=45).strip()
    sdk = adb("shell", "getprop", "ro.build.version.sdk")
    paths = adb("shell", "pm", "path", a.package).replace("\r", "").splitlines()
    # Refuse split APKs: this update path is only validated for the launcher's monolithic APK.
    if len(paths) != 1 or not re.fullmatch(r"package:/data/app/[A-Za-z0-9_./=+~-]+/base\.apk", paths[0]):
        raise SystemExit("unexpected/split APK path; no change performed")
    adb("pull", paths[0][8:], str(a.output / "installed-base.apk"))
    (a.output / "package-dump.txt").write_text(adb("shell", "dumpsys", "package", a.package))
    (a.output / "device.json").write_text(json.dumps({"sdk": sdk, "package": a.package, "private_settings_backup": False}, indent=2))
    print("Read-only APK collection complete. This is NOT a backup of private launcher preferences/order.")


if __name__ == "__main__":
    main()
