"""Device-scoped, immutable, content-addressed images on persistent disk."""
import json
import os
import sqlite3
import tempfile
from pathlib import Path
from images import inspect
from protocol import ID


class Assets:
    def __init__(self, root, device_quota=256 * 1024 * 1024):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)
        self.quota = device_quota
        self.db = self.root / "assets.sqlite"
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS assets (device TEXT, hash TEXT, descriptor TEXT NOT NULL, "
                       "bytes INTEGER NOT NULL, PRIMARY KEY(device,hash))")

    def connect(self):
        return sqlite3.connect(self.db, timeout=10)

    def path(self, device, sha):
        import re
        if not ID.fullmatch(device) or not re.fullmatch("[0-9a-f]{64}", sha):
            raise ValueError("invalid asset key")
        return self.root / device / sha

    def put(self, device, data, expected_mime=None):
        description = inspect(data)
        if expected_mime is not None and expected_mime != description["mime"]:
            raise ValueError("content type does not match image")
        target = self.path(device, description["sha256"])
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")  # Serialize quota checks across all gunicorn workers.
            row = db.execute("SELECT descriptor FROM assets WHERE device=? AND hash=?", (device, description["sha256"])).fetchone()
            if row:
                # Restore missing/corrupt bytes from this verified upload if needed.
                if target.exists() and target.read_bytes() == data:
                    return json.loads(row[0])
            total = db.execute("SELECT COALESCE(SUM(bytes),0) FROM assets WHERE device=?", (device,)).fetchone()[0]
            if not row and total + len(data) > self.quota:
                raise ValueError("device storage quota exceeded")
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(dir=target.parent)
            try:
                with os.fdopen(fd, "wb") as out:
                    out.write(data); out.flush(); os.fsync(out.fileno())
                os.replace(temporary, target)
                directory = os.open(target.parent, os.O_RDONLY)
                try: os.fsync(directory)
                finally: os.close(directory)
            finally:
                Path(temporary).unlink(missing_ok=True)
            db.execute("INSERT OR IGNORE INTO assets VALUES (?,?,?,?)", (device, description["sha256"], json.dumps(description, sort_keys=True), len(data)))
        return description

    def descriptor(self, device, sha):
        with self.connect() as db:
            row = db.execute("SELECT descriptor FROM assets WHERE device=? AND hash=?", (device, sha)).fetchone()
        if not row:
            raise ValueError("asset is not uploaded for this device")
        return json.loads(row[0])

    def get(self, device, sha):
        d = self.descriptor(device, sha)
        data = self.path(device, sha).read_bytes()
        if inspect(data) != d:
            raise ValueError("stored asset corrupted")
        return data, d["mime"]
