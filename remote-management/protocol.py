"""Strict, versioned task protocol. No shell, URL or path supplied by a task."""
import base64
import json
import re
import subprocess
import tempfile
import time
from pathlib import Path

LIMIT = 16384
OPERATIONS = {"status", "list_apps", "set_layout", "set_wallpaper", "apply_wallpaper", "restore_desktop"}
ID = re.compile(r"[a-zA-Z0-9_-]{1,64}\Z")


def unique(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ValueError("duplicate JSON key")
        out[k] = v
    return out


def loads(data):
    if len(data) > LIMIT:
        raise ValueError("body too large")
    return json.loads(data, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite")))


def exact(obj, keys):
    if type(obj) is not dict or set(obj) != set(keys):
        raise ValueError("unexpected fields")


def validate(t, device=None, now=None):
    exact(t, ("v", "id", "device", "issued_at", "expires_at", "op", "args"))
    if type(t["v"]) is not int or t["v"] != 1:
        raise ValueError("protocol version")
    for k in ("id", "device"):
        if type(t[k]) is not str or not ID.fullmatch(t[k]):
            raise ValueError("invalid identifier")
    if device is not None and t["device"] != device:
        raise ValueError("wrong device")
    now = int(time.time()) if now is None else now
    if any(type(t[k]) is not int for k in ("issued_at", "expires_at")):
        raise ValueError("integer timestamps required")
    if not (now - 3600 <= t["issued_at"] <= now + 60
            and t["issued_at"] < t["expires_at"] <= t["issued_at"] + 3600
            and now < t["expires_at"]):
        raise ValueError("expired or invalid validity window")
    if type(t["op"]) is not str or t["op"] not in OPERATIONS:
        raise ValueError("operation not allowed (including APK installation)")
    a = t["args"]
    if t["op"] == "apply_wallpaper":
        from images import validate_descriptor
        validate_descriptor(a)
    elif t["op"] == "set_layout":
        exact(a, ("columns", "rows_below_dock"))
        if (type(a["columns"]) is not int or not 4 <= a["columns"] <= 7
                or type(a["rows_below_dock"]) is not int or not 0 <= a["rows_below_dock"] <= 3):
            raise ValueError("invalid layout")
    elif t["op"] == "set_wallpaper":
        exact(a, ("asset",))
        # Pre-staged local launcher collection only. No downloads or filesystem paths.
        if type(a["asset"]) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{1,48}\.(jpg|jpeg|png|webp)", a["asset"]):
            raise ValueError("invalid wallpaper asset")
    else:
        exact(a, ())
    return t


def encode(t, private_key):
    validate(t)
    payload = json.dumps(t, sort_keys=True, separators=(",", ":")).encode()
    signature = subprocess.run(["openssl", "dgst", "-sha256", "-sign", str(private_key)],
                               input=payload, capture_output=True, check=True).stdout
    return {"payload": base64.b64encode(payload).decode(), "signature": base64.b64encode(signature).decode()}


def verify(envelope, public_key, device=None, now=None):
    exact(envelope, ("payload", "signature"))
    payload = base64.b64decode(envelope["payload"], validate=True)
    signature = base64.b64decode(envelope["signature"], validate=True)
    if len(payload) > LIMIT or not 256 <= len(signature) <= 512:
        raise ValueError("invalid signed message size")
    with tempfile.TemporaryDirectory() as folder:
        sig = Path(folder) / "signature"
        sig.write_bytes(signature)
        result = subprocess.run(["openssl", "dgst", "-sha256", "-verify", str(public_key),
                                 "-signature", str(sig)], input=payload, capture_output=True)
    if result.returncode:
        raise ValueError("invalid signature")
    return validate(loads(payload), device, now)
