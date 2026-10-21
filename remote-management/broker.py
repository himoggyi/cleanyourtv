"""Loopback prototype. Expose ONLY through a TLS reverse proxy with rate/body limits.

No device connection and no subprocess execution other than RSA verification.
"""
import argparse
import hmac
import json
import os
import re
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from protocol import LIMIT, loads, verify


class Queue:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, device TEXT NOT NULL, "
                       "envelope TEXT NOT NULL, expires INTEGER NOT NULL, result TEXT)")

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def submit(self, task, envelope):
        body = json.dumps(envelope, sort_keys=True, separators=(",", ":"))
        with self.connect() as db:
            old = db.execute("SELECT envelope FROM tasks WHERE id=?", (task["id"],)).fetchone()
            if old:
                if old[0] != body:
                    raise ValueError("task id collision")
                return False
            db.execute("INSERT INTO tasks VALUES (?,?,?,?,NULL)",
                       (task["id"], task["device"], body, task["expires_at"]))
        return True

    def next(self, device):
        with self.connect() as db:
            row = db.execute("SELECT envelope FROM tasks WHERE device=? AND result IS NULL "
                             "AND expires>? ORDER BY rowid LIMIT 1", (device, int(time.time()))).fetchone()
        return json.loads(row[0]) if row else None

    def finish(self, device, task_id, result):
        # Report is a bounded opaque object. Device cannot submit tasks or read another device.
        if type(result) is not dict or set(result) != {"status", "data"}:
            raise ValueError("invalid result")
        if result["status"] not in ("succeeded", "failed", "unknown"):
            raise ValueError("invalid result state")
        body = json.dumps(result, sort_keys=True)
        with self.connect() as db:
            row = db.execute("SELECT result FROM tasks WHERE device=? AND id=?", (device, task_id)).fetchone()
            if not row:
                raise ValueError("unknown task")
            if row[0] is not None and row[0] != body:
                raise ValueError("immutable result")
            db.execute("UPDATE tasks SET result=? WHERE device=? AND id=?", (body, device, task_id))


def handler(queue, writer_token, devices, public_key):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Do not log Authorization, payloads, package inventory or URLs.

        def reply(self, code, value):
            body = json.dumps(value).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def authorized(self, token):
            return hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token)

        def read_json(self):
            if self.headers.get("Transfer-Encoding"):
                raise ValueError("chunked requests disabled")
            size = int(self.headers.get("Content-Length", "-1"))
            if not 0 <= size <= LIMIT:
                raise ValueError("invalid body size")
            return loads(self.rfile.read(size))

        def do_GET(self):
            self.route(False)

        def do_POST(self):
            self.route(True)

        def route(self, post):
            self.connection.settimeout(10)
            try:
                if self.path == "/v1/tasks" and self.authorized(writer_token):
                    if not post:
                        with queue.connect() as db:
                            rows = db.execute("SELECT id,device,expires,result FROM tasks ORDER BY rowid DESC LIMIT 100").fetchall()
                        self.reply(200, {"tasks": [{"id": r[0], "device": r[1], "expires_at": r[2],
                                                  "result": json.loads(r[3]) if r[3] else None} for r in rows]})
                        return
                    envelope = self.read_json()
                    task = verify(envelope, public_key)
                    if task["device"] not in devices:
                        raise ValueError("unpaired device")
                    created = queue.submit(task, envelope)
                    self.reply(201 if created else 200, {"id": task["id"], "queued": True})
                    return
                m = re.fullmatch(r"/v1/devices/([A-Za-z0-9_-]{1,64})/(next|results/([A-Za-z0-9_-]{1,64}))", self.path)
                if not m or m[1] not in devices or not self.authorized(devices[m[1]]):
                    self.reply(403, {"error": "forbidden"})
                    return
                if not post and m[2] == "next":
                    self.reply(200, {"task": queue.next(m[1])})
                elif post and m[3]:
                    queue.finish(m[1], m[3], self.read_json())
                    self.reply(200, {"recorded": True})
                else:
                    self.reply(405, {"error": "method"})
            except (ValueError, TypeError, KeyError):
                self.reply(400, {"error": "invalid request"})
            except Exception:
                self.reply(500, {"error": "internal failure"})
    return Handler


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--db", type=Path, required=True)
    p.add_argument("--port", type=int, default=8765)
    a = p.parse_args()
    c = loads(a.config.read_bytes())
    tokens = [c["writer_token"], *c["devices"].values()]
    if len(set(tokens)) != len(tokens) or any(len(t) < 32 for t in tokens):
        raise ValueError("use distinct random tokens of at least 32 characters")
    os.umask(0o077)
    a.db.parent.mkdir(parents=True, exist_ok=True)
    HTTPServer(("127.0.0.1", a.port), handler(Queue(a.db), c["writer_token"], c["devices"], c["public_key"])).serve_forever()


if __name__ == "__main__":
    main()
