"""Private ledger gates and probe/device isolation using the existing RSA protocol."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

from github_queue import (OWNER_ID, REPOSITORY, REPOSITORY_ID, build_record, publish,
                          require_private, verify_record)


class FakeGitHub:
    def __init__(self, **changes):
        self.repo = {"id": REPOSITORY_ID, "full_name": REPOSITORY, "owner": {"id": OWNER_ID},
                     "private": True, "has_issues": True}
        self.repo.update(changes)
        self.calls = []

    def api(self, suffix="", method="GET", data=None):
        self.calls.append((suffix, method, data))
        return {"number": 1} if method == "POST" else self.repo


class GitHubQueueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.key = Path(cls.tmp.name) / "key.pem"
        subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048",
                        "-out", str(cls.key)], check=True, capture_output=True)
        cls.pub = subprocess.run(["openssl", "pkey", "-in", str(cls.key), "-pubout"],
                                 check=True, capture_output=True, text=True).stdout

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def event(self, device="cloud-probe", op="status", owner=OWNER_ID):
        return {"sender": {"id": owner}, "inputs": {"task": json.dumps({
            "device": device, "op": op, "args": {}})}}

    def build(self, event=None, mode="cloud-probe", attempt="1", device=None):
        return build_record(event or self.event(), mode, "12345", attempt, self.key, self.pub, device=device)

    def test_existing_rsa_envelope_persists_without_private_key(self):
        task, record = self.build()
        api = FakeGitHub()
        self.assertEqual(publish(api, task, record), 1)
        recovered = json.loads(api.calls[-1][2]["body"])
        self.assertEqual(verify_record(recovered, self.pub, "cloud-probe", allow_probe=True), task)
        self.assertNotIn("PRIVATE KEY", api.calls[-1][2]["body"])

    def test_visibility_owner_repository_and_issues_fail_closed(self):
        task, record = self.build()
        for changes in ({"private": False}, {"private": 1}, {"id": 1}, {"owner": {"id": 1}},
                        {"full_name": "other/repo"}, {"has_issues": False}):
            api = FakeGitHub(**changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                publish(api, task, record)
            self.assertFalse(any(method == "POST" for _, method, _ in api.calls))

    def test_probe_never_enters_device_consumer(self):
        _, record = self.build()
        for target in ("cloud-probe", "x5pro"):
            with self.assertRaises(ValueError):
                verify_record(record, self.pub, target)
        with self.assertRaises(ValueError):
            self.build(self.event("x5pro"))

    def test_status_only_owner_and_rerun_guards(self):
        for event, attempt in ((self.event(op="list_apps"), "1"), (self.event(owner=1), "1"),
                               (self.event(), "2")):
            with self.assertRaises(ValueError):
                self.build(event, attempt=attempt)

    def test_corruption_and_extra_fields_rejected(self):
        _, record = self.build()
        altered = copy.deepcopy(record)
        altered["envelope"]["signature"] = "A" * 344
        with self.assertRaises(ValueError):
            verify_record(altered, self.pub, "cloud-probe", allow_probe=True)
        record["url"] = "https://evil.invalid"
        with self.assertRaises(ValueError):
            verify_record(record, self.pub, "cloud-probe", allow_probe=True)

    def test_authorized_record_requires_independent_pinned_key(self):
        task, record = self.build(self.event("x5pro"), mode="authorized-status", device="x5pro")
        self.assertNotIn("probe_public_key", record)
        self.assertEqual(verify_record(record, self.pub, "x5pro"), task)
        with self.assertRaises(ValueError):
            verify_record(record, self.pub, "other-device")
        with self.assertRaises(ValueError):
            self.build(self.event("x5pro"), mode="authorized-status")


if __name__ == "__main__":
    unittest.main()
