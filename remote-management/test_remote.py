"""Device-free unittest security checks, pinned image dependencies and OpenSSL."""
import base64
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer

from broker import Queue, handler
from protocol import encode, loads, validate, verify
from relay import prepare_task


class RemoteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.key = cls.root / "private.pem"
        cls.pub = cls.root / "public.pem"
        subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048",
                        "-out", str(cls.key)], capture_output=True, check=True)
        subprocess.run(["openssl", "pkey", "-in", str(cls.key), "-pubout", "-out", str(cls.pub)],
                       capture_output=True, check=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def task(self, **changes):
        now = int(time.time())
        t = {"v": 1, "id": "test-1", "device": "x5pro", "issued_at": now,
             "expires_at": now + 600, "op": "status", "args": {}}
        t.update(changes)
        return t

    def test_signed_round_trip_and_target_binding(self):
        t = self.task()
        e = encode(t, self.key)
        self.assertEqual(verify(e, self.pub, "x5pro"), t)
        with self.assertRaises(ValueError):
            verify(e, self.pub, "other-device")

    def test_tampering_is_rejected(self):
        e = encode(self.task(), self.key)
        e["payload"] = base64.b64encode(json.dumps(self.task(op="restore_desktop")).encode()).decode()
        with self.assertRaises(ValueError):
            verify(e, self.pub)

    def test_expired_future_long_ttl_and_boolean_numbers(self):
        now = int(time.time())
        for changes in ({"expires_at": now}, {"issued_at": now + 61}, {"expires_at": now + 3601},
                        {"v": True}, {"issued_at": True},
                        {"op": "set_layout", "args": {"columns": True, "rows_below_dock": 1}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate(self.task(**changes))

    def test_unknown_operations_extra_fields_and_injections(self):
        for op in ("shell", "install_apk", "uninstall", "disable", "reboot", "status; reboot"):
            with self.subTest(op=op), self.assertRaises(ValueError):
                validate(self.task(op=op))
        for args in ({"shell": "id"}, {"url": "https://evil.invalid/a.apk"}):
            with self.assertRaises(ValueError):
                validate(self.task(args=args))
        for asset in ("../a.jpg", "/a.jpg", "a.jpg;reboot", "$(id).jpg", "https://evil/a.jpg", ".hidden.jpg"):
            with self.subTest(asset=asset), self.assertRaises(ValueError):
                validate(self.task(op="set_wallpaper", args={"asset": asset}))
        with self.assertRaises(ValueError):
            validate(self.task(extra="untrusted"))

    def test_valid_layout_wallpaper_and_restore(self):
        for op, args in (("set_layout", {"columns": 7, "rows_below_dock": 0}),
                         ("set_wallpaper", {"asset": "aurora.jpg"}), ("restore_desktop", {}), ("list_apps", {})):
            self.assertEqual(validate(self.task(op=op, args=args))["op"], op)

    def test_duplicate_json_and_nonfinite(self):
        for body in ('{"op":"status","op":"shell"}', '{"n":NaN}', 'x' * 16385):
            with self.assertRaises(ValueError):
                loads(body)

    def test_relay_owner_event_allowlist_and_rerun_guard(self):
        task = {"device": "x5pro", "op": "status", "args": {}}
        event = {"sender": {"id": 143339177}, "inputs": {"task": json.dumps(task)}}
        now = int(time.time())
        prepared = prepare_task(event, 143339177, "workflow_dispatch", "1234", "1", now)
        self.assertEqual(prepared["id"], "gh-1234")
        self.assertEqual(prepared["expires_at"], now + 1800)
        for owner, name, attempt in ((99, "workflow_dispatch", "1"),
                                     (143339177, "issue_comment", "1"),
                                     (143339177, "workflow_dispatch", "2")):
            with self.assertRaises(ValueError):
                prepare_task(event, owner, name, "1234", attempt, now)
        for op in ("shell", "install_apk", "status; reboot"):
            event["inputs"]["task"] = json.dumps(dict(task, op=op))
            with self.assertRaises(ValueError):
                prepare_task(event, 143339177, "workflow_dispatch", "1234", "1", now)

    def test_durable_queue_idempotency_and_immutable_results(self):
        path = self.root / "queue-test.sqlite"
        q = Queue(path); t = self.task(id="durable"); e = encode(t, self.key)
        self.assertTrue(q.submit(t, e))
        self.assertFalse(q.submit(t, e))
        changed = encode(self.task(id="durable", op="list_apps"), self.key)
        with self.assertRaises(ValueError):
            q.submit(t, changed)
        q = Queue(path)
        self.assertEqual(q.next("x5pro"), e)
        self.assertIsNone(q.next("other"))
        result = {"status": "succeeded", "data": {"sdk": 28}}
        q.finish("x5pro", "durable", result)
        q.finish("x5pro", "durable", result)
        self.assertIsNone(q.next("x5pro"))
        with self.assertRaises(ValueError):
            q.finish("other", "durable", result)
        with self.assertRaises(ValueError):
            q.finish("x5pro", "durable", {"status": "failed", "data": {}})

    def test_http_submit_poll_receipt_and_permissions(self):
        q = Queue(self.root / "http.sqlite")
        server = HTTPServer(("127.0.0.1", 0), handler(q, "writer", {"x5pro": "reader", "other": "other-reader"}, self.pub, reader_token="observer"))
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        origin = "http://127.0.0.1:" + str(server.server_port)
        def request(path, token, body=None):
            req = urllib.request.Request(origin + path, data=json.dumps(body).encode() if body is not None else None,
                                         headers={"Authorization": "Bearer " + token})
            try:
                with urllib.request.urlopen(req, timeout=3) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())
        try:
            envelope = encode(self.task(id="http-1"), self.key)
            self.assertEqual(request("/v1/tasks", "reader", envelope)[0], 403)
            self.assertEqual(request("/v1/tasks", "writer", envelope)[0], 201)
            self.assertEqual(request("/v1/tasks", "writer", envelope)[0], 200)
            self.assertEqual(request("/v1/devices/x5pro/next", "writer")[0], 403)
            self.assertEqual(request("/v1/devices/x5pro/next", "other-reader")[0], 403)
            code, body = request("/v1/devices/x5pro/next", "reader")
            self.assertEqual(code, 200)
            task = verify(body["task"], self.pub, "x5pro")
            self.assertEqual(task["op"], "status")
            # A second pull before receipt redelivers the same ID. Device journal must deduplicate it.
            self.assertEqual(request("/v1/devices/x5pro/next", "reader")[1], body)
            result = {"status": "succeeded", "data": {"simulated": True, "sdk": 28}}
            self.assertEqual(request("/v1/devices/x5pro/results/http-1", "reader", result)[0], 200)
            self.assertIsNone(request("/v1/devices/x5pro/next", "reader")[1]["task"])
            self.assertEqual(request("/v1/tasks", "observer")[1]["tasks"][0]["result"], result)
            self.assertEqual(request("/v1/tasks", "writer")[0], 403)
            self.assertEqual(request("/v1/tasks", "reader")[0], 403)
            bad = copy.deepcopy(envelope); bad["signature"] = base64.b64encode(b"x" * 256).decode()
            self.assertEqual(request("/v1/tasks", "writer", bad)[0], 400)
            self.assertEqual(request("/v1/tasks", "writer", encode(self.task(device="unpaired"), self.key))[0], 400)
        finally:
            server.shutdown(); thread.join(); server.server_close()

    def test_expired_queue_task_is_not_delivered(self):
        q = Queue(self.root / "expired.sqlite")
        t = self.task(id="expired", expires_at=int(time.time()) - 1)
        q.submit(t, {"payload": "not used", "signature": "not used"})
        self.assertIsNone(q.next("x5pro"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
