"""Verify actual JPEG/PNG pixels, bound decompression, and bind immutable content hashes."""
import hashlib
import io
import warnings
from PIL import Image, UnidentifiedImageError

MAX_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 8_388_608
MAX_EDGE = 4096
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


def inspect(data):
    if not 0 < len(data) <= MAX_BYTES:
        raise ValueError("image size outside 1..8 MiB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                fmt = image.format
                width, height = image.size
                if fmt not in ("JPEG", "PNG") or getattr(image, "n_frames", 1) != 1:
                    raise ValueError("only single-frame JPEG/PNG images")
                if not (0 < width <= MAX_EDGE and 0 < height <= MAX_EDGE and width * height <= MAX_PIXELS):
                    raise ValueError("image dimensions too large")
                image.verify()
            # Verify also decodes pixels; a plausible header alone is not enough.
            with Image.open(io.BytesIO(data)) as image:
                image.load()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning) as e:
        raise ValueError("invalid or decompression-heavy image") from e
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "width": width,
            "height": height, "mime": "image/jpeg" if fmt == "JPEG" else "image/png"}


def validate_descriptor(a):
    from protocol import exact
    import re
    exact(a, ("sha256", "bytes", "width", "height", "mime"))
    if type(a["sha256"]) is not str or not re.fullmatch("[0-9a-f]{64}", a["sha256"]):
        raise ValueError("invalid content hash")
    for k in ("bytes", "width", "height"):
        if type(a[k]) is not int:
            raise ValueError("integer image limits required")
    if not (0 < a["bytes"] <= MAX_BYTES and 0 < a["width"] <= MAX_EDGE and 0 < a["height"] <= MAX_EDGE
            and a["width"] * a["height"] <= MAX_PIXELS and a["mime"] in ("image/jpeg", "image/png")):
        raise ValueError("invalid image descriptor")
    return a
