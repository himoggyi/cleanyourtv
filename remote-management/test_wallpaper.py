"""Security + persistent HTTPS integration tests. All devices here are explicitly simulated."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
import socket
import sys
from unittest.mock import patch
import urllib.request
from http.server import HTTPServer
from PIL import Image

from apk_guard import compatible
from asset_store import Assets
from broker import API, Queue, handler, load_config
from images import inspect, validate_descriptor
from protocol import encode, validate, verify
from relay import prepare_task
from wallpaper import prepare_image, verify_receipt
from http_client import origin, request


def picture(fmt="PNG", size=(24, 16)):
    out = io.BytesIO(); Image.new("RGB", size, (28, 90, 140)).save(out, format=fmt); return out.getvalue()


class WallpaperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(); cls.root = Path(cls.tmp.name)
        cls.key, cls.pub = cls.root / "task.pem", cls.root / "task-public.pem"
        subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-out", str(cls.key)], capture_output=True, check=True)
        subprocess.run(["openssl", "pkey", "-in", str(cls.key), "-pubout", "-out", str(cls.pub)], capture_output=True, check=True)
        cls.cert, cls.tlskey = cls.root / "tls.pem", cls.root / "tls-key.pem"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=localhost",
                        "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1", "-keyout", str(cls.tlskey), "-out", str(cls.cert)], capture_output=True, check=True)
        cls.tls = ssl.create_default_context(cafile=str(cls.cert))

    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(dir=self.root))
        self.assets = Assets(self.work / "assets")
        self.queue = Queue(self.work / "queue.sqlite")
        self.api = API(self.queue, "writer", {"x5pro": "device", "other": "other-device"}, self.pub,
                       self.assets, {"x5pro": "upload", "other": "other-upload"}, "reader")

    def route(self, method, path, token, body=b"", mime="application/json"):
        return self.api.route(method, path, "Bearer " + token, body, mime)

    def task(self, descriptor, task_id="image-task"):
        now = int(time.time())
        return {"v": 1, "id": task_id, "device": "x5pro", "issued_at": now, "expires_at": now + 600,
                "op": "apply_wallpaper", "args": descriptor}

    def test_jpg_png_real_pixels_and_unicode_source_filename(self):
        for fmt in ("JPEG", "PNG"):
            source = self.work / ("壁纸 $(id); '图片'." + fmt.lower())
            source.write_bytes(picture(fmt))
            normalized, d = prepare_image(source)
            self.assertEqual(d, inspect(normalized)); self.assertEqual(d["width"], 24)
            self.assertEqual(d["mime"], "image/jpeg" if fmt == "JPEG" else "image/png")

    def test_metadata_is_removed_and_large_source_is_resized(self):
        source = self.work / "photo.jpg"
        exif = Image.Exif(); exif[274] = 6; exif[315] = "PRIVATE NAME"
        Image.new("RGB", (4000, 2000), (1, 2, 3)).save(source, exif=exif)
        clean, d = prepare_image(source)
        with Image.open(io.BytesIO(clean)) as image:
            self.assertFalse(image.getexif()); self.assertLessEqual(image.width, 3840); self.assertLessEqual(image.height, 2160)
        self.assertNotIn(b"PRIVATE NAME", clean); self.assertNotEqual(d["sha256"], hashlib.sha256(source.read_bytes()).hexdigest())

    def test_transparent_png_is_composited_on_black(self):
        source = self.work / "transparent.png"
        im = Image.new("RGBA", (2, 2), (255, 0, 0, 0)); im.putpixel((1, 1), (0, 255, 0, 255)); im.save(source)
        data, _ = prepare_image(source)
        with Image.open(io.BytesIO(data)) as result:
            self.assertEqual(result.getpixel((0, 0)), (0, 0, 0)); self.assertEqual(result.getpixel((1, 1)), (0, 255, 0))

    def test_fake_truncated_animated_and_oversized_images_are_refused(self):
        animated = io.BytesIO()
        Image.new("RGB", (3, 3), "red").save(animated, format="PNG", save_all=True, append_images=[Image.new("RGB", (3, 3), "blue")], duration=100, loop=0)
        for data in (b"<svg></svg>", b"\x89PNG\r\n\x1a\n", picture()[:30], picture("BMP"), picture(size=(4097, 1)), animated.getvalue()):
            with self.subTest(length=len(data)), self.assertRaises(ValueError): inspect(data)

    def test_image_descriptor_rejects_urls_paths_extra_fields_and_booleans(self):
        d = inspect(picture())
        for changes in ({"sha256": "../private"}, {"sha256": "https://evil/img.png"}, {"bytes": True},
                        {"width": 4097}, {"mime": "application/vnd.android.package-archive"}, {"url": "https://evil"}):
            with self.assertRaises(ValueError): validate(self.task(dict(d, **changes)))

    def test_origins_and_role_configuration_fail_closed(self):
        for url in ("http://example.com", "https://user:secret@example.com", "https://example.com/path", "https://example.com/?token=secret"):
            with self.assertRaises(ValueError): origin(url)
        cfg = self.work / "config.json"
        cfg.write_text(json.dumps({"writer_token": "a" * 32, "reader_token": "a" * 32, "devices": {"x5pro": "b" * 32},
                                  "upload_tokens": {"x5pro": "c" * 32}, "public_key": str(self.pub)}))
        with self.assertRaises(ValueError): load_config(cfg)

    def test_upload_is_scoped_and_cannot_execute_any_task(self):
        data = picture()
        for role in ("device", "writer", "reader", "other-upload"):
            self.assertEqual(self.route("POST", "/v1/devices/x5pro/assets", role, data, "image/png")[0], 403)
        code, d, _ = self.route("POST", "/v1/devices/x5pro/assets", "upload", data, "image/png")
        self.assertEqual(code, 201)
        self.assertEqual(self.route("GET", "/v1/devices/x5pro/next", "device")[1], {"task": None})
        for role in ("upload", "reader", "writer", "other-device"):
            self.assertEqual(self.route("GET", "/v1/devices/x5pro/assets/" + d["sha256"], role)[0], 403)
        self.assertEqual(self.route("GET", "/v1/devices/x5pro/assets/" + d["sha256"], "device")[1], data)
        self.assertEqual(self.route("GET", "/v1/devices/other/assets/" + d["sha256"], "other-device")[0], 400)

    def test_mime_mismatch_is_not_persisted_and_quota_is_atomic(self):
        data = picture()
        self.assertEqual(self.route("POST", "/v1/devices/x5pro/assets", "upload", data, "image/jpeg")[0], 400)
        with self.assertRaises(ValueError): self.assets.descriptor("x5pro", inspect(data)["sha256"])
        small = Assets(self.work / "small", device_quota=len(data))
        d = small.put("x5pro", data); self.assertEqual(small.put("x5pro", data), d)
        with self.assertRaises(ValueError): small.put("x5pro", picture(size=(25, 16)))

    def test_signing_binds_every_image_attribute_and_device(self):
        d = self.assets.put("x5pro", picture())
        changed = dict(d, width=d["width"] + 1)
        self.assertEqual(self.route("POST", "/v1/tasks", "writer", json.dumps(encode(self.task(changed), self.key)).encode())[0], 400)
        valid = encode(self.task(d), self.key)
        self.assertEqual(self.route("POST", "/v1/tasks", "upload", json.dumps(valid).encode())[0], 403)
        self.assertEqual(self.route("POST", "/v1/tasks", "writer", json.dumps(valid).encode())[0], 201)
        self.assertEqual(self.route("GET", "/v1/tasks/image-task", "writer")[0], 403)
        self.assertEqual(self.route("GET", "/v1/tasks/image-task", "reader")[0], 200)

    def test_storage_corruption_cannot_be_downloaded_as_valid_image(self):
        d = self.assets.put("x5pro", picture())
        self.assets.path("x5pro", d["sha256"]).write_bytes(b"corrupted")
        self.assertEqual(self.route("GET", "/v1/devices/x5pro/assets/" + d["sha256"], "device")[0], 400)

    def test_client_request_id_remains_queryable_after_actions_signing(self):
        task = {"device": "x5pro", "op": "apply_wallpaper", "args": inspect(picture()), "request_id": "wall-owner-123"}
        event = {"sender": {"id": 143339177}, "inputs": {"task": json.dumps(task)}}
        self.assertEqual(prepare_task(event, 143339177, "workflow_dispatch", "123456", "1", int(time.time()))["id"], task["request_id"])

    def test_delegated_wallpaper_environment_cannot_sign_other_operations(self):
        import relay
        event_file = self.work / "event.json"
        event_file.write_text(json.dumps({"sender": {"id": 143339177}, "inputs": {"task": json.dumps({"device": "x5pro", "op": "restore_desktop", "args": {}})}}))
        env = {"GITHUB_EVENT_PATH": str(event_file), "OWNER_ID": "143339177", "GITHUB_EVENT_NAME": "workflow_dispatch",
               "GITHUB_RUN_ID": "1234", "GITHUB_RUN_ATTEMPT": "1", "ALLOWED_OPERATION": "apply_wallpaper"}
        with patch.dict(os.environ, env, clear=True), patch("relay.os.open") as key_file, patch("relay.urllib.request.build_opener") as network:
            with self.assertRaisesRegex(ValueError, "delegated"): relay.main()
            key_file.assert_not_called(); network.assert_not_called()

    def test_apk_update_gate_requires_identity_signer_version_and_android9(self):
        old = {"package": "com.gathin.tvhome", "version_code": 6, "min_sdk": 26, "signers_sha256": ["a" * 64]}
        remote = dict(old, version_code=7); self.assertTrue(compatible(old, remote)["compatible"])
        self.assertTrue(compatible(remote, dict(remote, version_code=8))["compatible"])
        for changes in ({"package": "other.app"}, {"signers_sha256": ["b" * 64]}, {"version_code": 6}, {"version_code": 5}, {"min_sdk": 29}):
            with self.assertRaises(ValueError): compatible(old, dict(remote, **changes))

    def test_client_requires_correct_task_hash_device_and_real_display_evidence(self):
        descriptor = inspect(picture())
        row = {"id": "task-1", "device": "x5pro", "result": {"status": "succeeded", "data": {
            "applied": True, "wallpaper_sha256": descriptor["sha256"], "display_confirmed": True, "evidence": "image_view_pre_draw"}}}
        self.assertTrue(verify_receipt(row, descriptor, "task-1", "x5pro"))
        for key, value in (("simulated", True), ("wallpaper_sha256", "0" * 64), ("applied", False)):
            changed = copy.deepcopy(row); changed["result"]["data"][key] = value
            with self.assertRaises(ValueError): verify_receipt(changed, descriptor, "task-1", "x5pro")
        with self.assertRaises(ValueError): verify_receipt(row, descriptor, "task-other", "x5pro")
        with self.assertRaises(ValueError): verify_receipt(row, descriptor, "task-1", "other")
        row["result"]["data"]["display_confirmed"] = False
        self.assertFalse(verify_receipt(row, descriptor, "task-1", "x5pro"))

    def test_wsgi_persistent_endpoint_and_request_size_limit(self):
        import wsgi
        old = wsgi._api; wsgi._api = self.api
        try:
            status = []
            body = wsgi.application({"PATH_INFO": "/healthz", "REQUEST_METHOD": "GET", "wsgi.input": io.BytesIO(b"")}, lambda s, _: status.append(s))
            self.assertEqual(status, ["200 OK"]); self.assertTrue(json.loads(b"".join(body))["ok"])
            status.clear()
            wsgi.application({"PATH_INFO": "/v1/tasks", "CONTENT_LENGTH": "16385", "REQUEST_METHOD": "POST", "wsgi.input": io.BytesIO(b"")}, lambda s, _: status.append(s))
            self.assertEqual(status, ["400 Bad Request"])
        finally: wsgi._api = old

    def test_production_gunicorn_entrypoint_with_persistent_configuration(self):
        cfg = self.work / "deployment.json"
        cfg.write_text(json.dumps({"writer_token": "w" * 43, "reader_token": "r" * 43, "devices": {"x5pro": "d" * 43},
                                  "upload_tokens": {"x5pro": "u" * 43}, "public_key": str(self.pub)}))
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0)); port = reservation.getsockname()[1]
        env = dict(os.environ, PROJECTOR_CONFIG=str(cfg), PROJECTOR_DATA=str(self.work / "production-data"))
        with (self.work / "gunicorn.log").open("wb") as log:
            process = subprocess.Popen([sys.executable, "-m", "gunicorn", "--bind", "127.0.0.1:" + str(port),
                                        "--workers", "2", "--threads", "2", "--umask", "0077", "wsgi:application"],
                                       cwd=Path(__file__).parent, env=env, stdout=log, stderr=log)
            try:
                response = None
                for _ in range(100):
                    if process.poll() is not None: self.fail("gunicorn exited before readiness")
                    try:
                        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1) as r: response = json.loads(r.read())
                        break
                    except urllib.error.URLError: time.sleep(0.1)
                self.assertEqual(response, {"ok": True})
                self.assertTrue((self.work / "production-data/tasks.sqlite").exists())
                self.assertTrue((self.work / "production-data/assets/assets.sqlite").exists())
            finally:
                process.terminate()
                try: process.wait(timeout=8)
                except subprocess.TimeoutExpired: process.kill(); process.wait()

    def test_https_image_execution_receipt_and_restart_simulated_device(self):
        def start():
            server = HTTPServer(("127.0.0.1", 0), handler(Queue(self.work / "queue.sqlite"), "writer", {"x5pro": "device"}, self.pub,
                                   Assets(self.work / "assets"), {"x5pro": "upload"}, "reader"))
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(self.cert, self.tlskey); server.socket = context.wrap_socket(server.socket, server_side=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            return server, thread, "https://localhost:" + str(server.server_port)
        server, thread, base = start()
        try:
            with self.assertRaises(urllib.error.URLError): request(base + "/healthz", "unused")
            image = self.work / "source.png"; image.write_bytes(picture())
            data, descriptor = prepare_image(image)
            uploaded = request(base + "/v1/devices/x5pro/assets", "upload", data, descriptor["mime"], self.tls)
            self.assertEqual(uploaded, descriptor)
            # This emulates Actions signing. No GitHub event is sent, no Android or projector is present.
            event = {"sender": {"id": 143339177}, "inputs": {"task": json.dumps({"device": "x5pro", "op": "apply_wallpaper", "args": descriptor, "request_id": "wall-https-test"})}}
            signed = encode(prepare_task(event, 143339177, "workflow_dispatch", "1", "1", int(time.time())), self.key)
            request(base + "/v1/tasks", "writer", json.dumps(signed).encode(), context=self.tls)
            # Restart broker and reopen both databases BEFORE execution.
            server.shutdown(); thread.join(); server.server_close(); server, thread, base = start()
            envelope = request(base + "/v1/devices/x5pro/next", "device", context=self.tls)["task"]
            task = verify(envelope, self.pub, "x5pro")
            req = urllib.request.Request(base + "/v1/devices/x5pro/assets/" + task["args"]["sha256"], headers={"Authorization": "Bearer device"})
            with urllib.request.urlopen(req, context=self.tls, timeout=5) as response: received = response.read()
            self.assertEqual(inspect(received), task["args"])
            simulated_files = self.work / "simulated-device"; simulated_files.mkdir()
            (simulated_files / "wallpaper.png").write_bytes(received)
            (simulated_files / "preferences.json").write_text(json.dumps({"wallpaper_sha256": descriptor["sha256"]}))
            result = {"status": "succeeded", "data": {"simulated": True, "wallpaper_sha256": descriptor["sha256"], "display_confirmed": False}}
            request(base + "/v1/devices/x5pro/results/wall-https-test", "device", json.dumps(result).encode(), context=self.tls)
            request(base + "/v1/devices/x5pro/results/wall-https-test", "device", json.dumps(result).encode(), context=self.tls)
            receipt = request(base + "/v1/tasks/wall-https-test", "reader", context=self.tls)["tasks"][0]
            self.assertEqual(receipt["result"], result)
            self.assertEqual((simulated_files / "wallpaper.png").read_bytes(), data)
            self.assertIsNone(request(base + "/v1/devices/x5pro/next", "device", context=self.tls)["task"])
        finally:
            server.shutdown(); thread.join(); server.server_close()


if __name__ == "__main__": unittest.main(verbosity=2)
