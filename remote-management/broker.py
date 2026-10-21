"""Persistent queue core and loopback debug adapter; production WSGI is in wsgi.py.

Expose ONLY through a TLS reverse proxy with rate/body limits.

No device connection and no subprocess execution other than RSA verification.
"""
import argparse
import hmac
import json
import os
import re
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from protocol import LIMIT, loads, verify
from images import MAX_BYTES


class Queue:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, device TEXT NOT NULL, "
                       "envelope TEXT NOT NULL, expires INTEGER NOT NULL, result TEXT)")

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def submit(self, task, envelope):
        body = json.dumps(envelope, sort_keys=True, separators=(",", ":"))
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT envelope FROM tasks WHERE id=?", (task["id"],)).fetchone()
            if old:
                if old[0] != body:
                    raise ValueError("task id collision")
                return False
            if db.execute("SELECT COUNT(*) FROM tasks WHERE device=? AND result IS NULL AND expires>?",
                          (task["device"], int(time.time()))).fetchone()[0] >= 100:
                raise ValueError("pending task quota exceeded")
            db.execute("INSERT INTO tasks VALUES (?,?,?,?,NULL)",
                       (task["id"], task["device"], body, task["expires_at"]))
        return True

    def next(self, device):
        with self.connect() as db:
            row = db.execute("SELECT envelope FROM tasks WHERE device=? AND result IS NULL "
                             "AND expires>? ORDER BY rowid LIMIT 1", (device, int(time.time()))).fetchone()
        return json.loads(row[0]) if row else None

    def report(self, task_id=None):
        with self.connect() as db:
            rows = (db.execute("SELECT id,device,expires,result FROM tasks WHERE id=?", (task_id,)).fetchall()
                    if task_id else db.execute("SELECT id,device,expires,result FROM tasks ORDER BY rowid DESC LIMIT 100").fetchall())
        return {"tasks": [{"id": r[0], "device": r[1], "expires_at": r[2],
                           "state": "completed" if r[3] else "expired" if r[2] <= int(time.time()) else "queued",
                           "result": json.loads(r[3]) if r[3] else None} for r in rows]}

    def finish(self, device, task_id, result):
        # Report is a bounded opaque object. Device cannot submit tasks or read another device.
        if type(result) is not dict or set(result) != {"status", "data"}:
            raise ValueError("invalid result")
        if result["status"] not in ("succeeded", "failed", "unknown") or type(result["data"]) is not dict:
            raise ValueError("invalid result state")
        body = json.dumps(result, sort_keys=True)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT result FROM tasks WHERE device=? AND id=?", (device, task_id)).fetchone()
            if not row:
                raise ValueError("unknown task")
            if row[0] is not None and row[0] != body:
                raise ValueError("immutable result")
            db.execute("UPDATE tasks SET result=? WHERE device=? AND id=?", (body, device, task_id))


class API:
    def __init__(self, queue, writer_token, devices, public_key, assets=None, upload_tokens=None, reader_token=None):
        self.queue, self.writer, self.devices, self.public_key = queue, writer_token, devices, public_key
        self.assets, self.uploaders = assets, upload_tokens or {}
        if reader_token is None or reader_token == writer_token:
            raise ValueError("a distinct read-only receipt token is required")
        self.reader = reader_token

    def route(self, method, path, authorization, body, content_type):
        def authorized(token):
            return token is not None and hmac.compare_digest(authorization, "Bearer " + token)
        try:
            if path == "/healthz" and method == "GET":
                return 200, {"ok": True}, "application/json"
            if re.fullmatch(r"/v1/tasks(?:/[A-Za-z0-9_-]{1,64})?", path):
                if method == "GET" and authorized(self.reader):
                    task_id = path.split("/")[3] if path.count("/") == 3 else None
                    return 200, self.queue.report(task_id), "application/json"
                if method == "POST" and path == "/v1/tasks" and authorized(self.writer):
                    envelope = loads(body); task = verify(envelope, self.public_key)
                    if task["device"] not in self.devices:
                        raise ValueError("unpaired device")
                    if task["op"] == "apply_wallpaper":
                        if self.assets is None or self.assets.descriptor(task["device"], task["args"]["sha256"]) != task["args"]:
                            raise ValueError("signed image descriptor does not match uploaded bytes")
                    created = self.queue.submit(task, envelope)
                    return (201 if created else 200), {"id": task["id"], "queued": True}, "application/json"
                return 403, {"error": "forbidden"}, "application/json"
            m = re.fullmatch(r"/v1/devices/([A-Za-z0-9_-]{1,64})/(next|results/([A-Za-z0-9_-]{1,64})|assets(?:/([0-9a-f]{64}))?)", path)
            if not m or m[1] not in self.devices:
                return 403, {"error": "forbidden"}, "application/json"
            device = m[1]
            if m[2] == "assets" and method == "POST":
                if not authorized(self.uploaders.get(device)):
                    return 403, {"error": "forbidden"}, "application/json"
                if self.assets is None:
                    raise ValueError("assets disabled")
                descriptor = self.assets.put(device, body, expected_mime=content_type)
                return 201, descriptor, "application/json"
            if not authorized(self.devices[device]):
                return 403, {"error": "forbidden"}, "application/json"
            if method == "GET" and m[2] == "next":
                return 200, {"task": self.queue.next(device)}, "application/json"
            if method == "GET" and m[4] and self.assets is not None:
                data, mime = self.assets.get(device, m[4]); return 200, data, mime
            if method == "POST" and m[3]:
                self.queue.finish(device, m[3], loads(body))
                return 200, {"recorded": True}, "application/json"
            return 405, {"error": "method"}, "application/json"
        except (ValueError, TypeError, KeyError, FileNotFoundError):
            return 400, {"error": "invalid request"}, "application/json"


def handler(queue, writer_token, devices, public_key, assets=None, upload_tokens=None, reader_token=None):
    api = API(queue, writer_token, devices, public_key, assets, upload_tokens, reader_token)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Do not log Authorization, payloads, package inventory or URLs.

        def reply(self, code, value, content_type="application/json"):
            body = value if isinstance(value, bytes) else json.dumps(value).encode()
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def read_body(self):
            if self.headers.get("Transfer-Encoding"):
                raise ValueError("chunked requests disabled")
            size = int(self.headers.get("Content-Length", "-1"))
            limit = MAX_BYTES if self.path.endswith("/assets") else LIMIT
            if not 0 <= size <= limit:
                raise ValueError("invalid body size")
            body = self.rfile.read(size)
            if len(body) != size: raise ValueError("incomplete body")
            return body

        def do_GET(self):
            self.route(False)

        def do_POST(self):
            self.route(True)

        def route(self, post):
            self.connection.settimeout(10)
            try:
                self.reply(*api.route("POST" if post else "GET", self.path,
                                     self.headers.get("Authorization", ""), self.read_body() if post else b"",
                                     self.headers.get("Content-Type", "").split(";")[0]))
            except (ValueError, TypeError, KeyError):
                self.reply(400, {"error": "invalid request"})
            except Exception:
                self.reply(500, {"error": "internal failure"})
    return Handler


def load_config(path):
    c = loads(Path(path).read_bytes())
    tokens = [c["writer_token"], c["reader_token"], *c["devices"].values(), *c["upload_tokens"].values()]
    if (len(set(tokens)) != len(tokens) or any(not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", t) for t in tokens)
            or set(c["devices"]) != set(c["upload_tokens"]) or not c["devices"]
            or any(not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", d) for d in c["devices"])):
        raise ValueError("distinct strong role tokens and matching device/upload identities required")
    return c


def application_from_config(config, root):
    from asset_store import Assets
    c = load_config(config); root = Path(root); root.mkdir(parents=True, exist_ok=True)
    return API(Queue(root / "tasks.sqlite"), c["writer_token"], c["devices"], c["public_key"],
               Assets(root / "assets"), c["upload_tokens"], c["reader_token"])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--db", type=Path, required=True)
    p.add_argument("--port", type=int, default=8765)
    a = p.parse_args()
    c = load_config(a.config)
    os.umask(0o077)
    a.db.parent.mkdir(parents=True, exist_ok=True)
    from asset_store import Assets
    ThreadingHTTPServer(("127.0.0.1", a.port), handler(Queue(a.db), c["writer_token"], c["devices"], c["public_key"],
                        Assets(a.db.parent / "assets"), c["upload_tokens"], c["reader_token"])).serve_forever()


if __name__ == "__main__":
    main()
