"""Fixed-origin HTTPS requests; secrets stay in headers, redirects never inherit them."""
import json
import urllib.request
from urllib.parse import urlsplit


def origin(value):
    u = urlsplit(value)
    if u.scheme != "https" or not u.hostname or u.username or u.password or u.query or u.fragment or u.path not in ("", "/"):
        raise ValueError("a fixed HTTPS origin is required")
    return value.rstrip("/")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("redirect refused")


def request(url, token, body=None, mime="application/json", context=None):
    # A private CA context is only used by integration tests. Production uses platform certificate validation.
    handlers = [NoRedirect()]
    if context is not None:
        handlers.append(urllib.request.HTTPSHandler(context=context))
    req = urllib.request.Request(url, data=body, headers={"Authorization": "Bearer " + token, "Content-Type": mime})
    with urllib.request.build_opener(*handlers).open(req, timeout=30) as response:
        data = response.read(16385)
        from protocol import loads
        return loads(data)
