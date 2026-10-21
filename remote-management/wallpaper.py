"""Chat attachment -> sanitized image upload -> GitHub dispatch -> authenticated receipt.

Never holds the task signing key. This command cannot succeed before deployment and pairing.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import time
import uuid
import warnings
from PIL import Image, ImageOps
from http_client import origin, request
from images import inspect
from protocol import ID


def prepare_image(path):
    path = Path(path)
    if not 0 < path.stat().st_size <= 32 * 1024 * 1024:
        raise ValueError("source must be at most 32 MiB")
    raw = path.read_bytes()
    previous_limit = Image.MAX_IMAGE_PIXELS
    try:
        Image.MAX_IMAGE_PIXELS = 64_000_000
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as im:
                if im.format not in ("JPEG", "PNG") or getattr(im, "n_frames", 1) != 1 or max(im.size) > 16384 or im.width * im.height > 64_000_000:
                    raise ValueError("unsupported source image")
                fmt = im.format
                im.draft("RGB", (3840, 2160))
                im = ImageOps.exif_transpose(im)
                im.thumbnail((3840, 2160), Image.Resampling.LANCZOS)
                if im.mode in ("RGBA", "LA") or "transparency" in im.info:
                    background = Image.new("RGBA", im.size, (0, 0, 0, 255))
                    background.alpha_composite(im.convert("RGBA")); im = background.convert("RGB")
                else:
                    im = im.convert("RGB")
                clean = Image.frombytes("RGB", im.size, im.tobytes())  # Drop GPS/EXIF, comments and embedded metadata.
                output = io.BytesIO()
                clean.save(output, format=fmt, **({"quality": 92} if fmt == "JPEG" else {}))
    finally:
        Image.MAX_IMAGE_PIXELS = previous_limit
    data = output.getvalue()
    return data, inspect(data)


def verify_receipt(row, descriptor, task_id, device):
    if row.get("id") != task_id or row.get("device") != device:
        raise ValueError("receipt belongs to a different request/device")
    result = row["result"]; d = result.get("data", {})
    if result["status"] != "succeeded" or d.get("wallpaper_sha256") != descriptor["sha256"] or d.get("applied") is not True:
        raise ValueError("no matching applied-image receipt")
    if d.get("simulated"):
        raise ValueError("a simulated receipt is not a real device result")
    return d.get("display_confirmed") is True and d.get("evidence") == "image_view_pre_draw"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--image", type=Path, required=True)
    p.add_argument("--device", default="x5pro")
    p.add_argument("--wait-seconds", type=int, default=300)
    p.add_argument("--prepare-only", type=Path, help="local-only sanitized image + descriptor; no network")
    a = p.parse_args()
    if not ID.fullmatch(a.device): p.error("invalid device")
    data, descriptor = prepare_image(a.image)
    if a.prepare_only:
        a.prepare_only.write_bytes(data)
        print(json.dumps(descriptor)); return
    needed = ("PROJECTOR_BROKER_URL", "PROJECTOR_UPLOAD_TOKEN", "PROJECTOR_READER_TOKEN", "PROJECTOR_GITHUB_TOKEN")
    if any(not os.environ.get(k) for k in needed):
        raise SystemExit("Not configured: broker/upload/reader/GitHub credentials; no network request sent")
    base = origin(os.environ["PROJECTOR_BROKER_URL"])
    uploaded = request(base + f"/v1/devices/{a.device}/assets", os.environ["PROJECTOR_UPLOAD_TOKEN"], data, descriptor["mime"])
    if uploaded != descriptor:
        raise ValueError("broker returned a different image descriptor")
    task_id = "wall-" + uuid.uuid4().hex
    from dispatch import dispatch
    task = {"device": a.device, "op": "apply_wallpaper", "args": descriptor, "request_id": task_id}
    dispatch(task)
    print(json.dumps({"id": task_id, "state": "dispatched", "sha256": descriptor["sha256"]}), flush=True)
    deadline = time.monotonic() + max(0, min(a.wait_seconds, 1800))
    while time.monotonic() < deadline:
        report = request(base + "/v1/tasks/" + task_id, os.environ["PROJECTOR_READER_TOKEN"])
        if report["tasks"]:
            row = report["tasks"][0]
            if row["result"]:
                result = row["result"]
                print(json.dumps(row, ensure_ascii=False))
                # Distinguish actual decoded/pre-draw evidence from mere queue acceptance or preference commit.
                if not verify_receipt(row, descriptor, task_id, a.device):
                    raise SystemExit("Applied on device; launcher display not yet confirmed. Open HOME and run a status task.")
                return
            if row["state"] == "expired": raise SystemExit("Task expired without a device result")
        time.sleep(3)
    raise SystemExit("Timed out waiting for a device result; inspect this task ID; do not assume success or resubmit automatically")


if __name__ == "__main__":
    main()
