"""Production entrypoint: gunicorn --bind 127.0.0.1:8765 --workers 2 --threads 2 wsgi:application."""
import json
import os
from http import HTTPStatus
from broker import application_from_config
from images import MAX_BYTES
from protocol import LIMIT

_api = None


def application(environ, start_response):
    global _api
    try:
        if _api is None:
            _api = application_from_config(os.environ["PROJECTOR_CONFIG"], os.environ["PROJECTOR_DATA"])
        path = environ.get("PATH_INFO", "")
        length = int(environ.get("CONTENT_LENGTH") or "0")
        limit = MAX_BYTES if path.endswith("/assets") else LIMIT
        if environ.get("QUERY_STRING") or not 0 <= length <= limit or environ.get("HTTP_TRANSFER_ENCODING"):
            raise ValueError("invalid request size/framing")
        body = environ["wsgi.input"].read(length)
        if len(body) != length: raise ValueError("incomplete body")
        code, value, mime = _api.route(environ["REQUEST_METHOD"], path, environ.get("HTTP_AUTHORIZATION", ""),
                                       body, environ.get("CONTENT_TYPE", "").split(";")[0])
    except (ValueError, KeyError, TypeError):
        code, value, mime = 400, {"error": "invalid request"}, "application/json"
    except Exception:
        code, value, mime = 500, {"error": "internal failure"}, "application/json"
    output = value if isinstance(value, bytes) else json.dumps(value).encode()
    start_response(f"{code} {HTTPStatus(code).phrase}", [("Content-Type", mime), ("Content-Length", str(len(output))),
                   ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff")])
    return [output]
