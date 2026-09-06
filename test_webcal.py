"""Synthetic HTTP and local publication tests. These do not test iPhone refresh."""
import base64
import copy
import hashlib
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from deploy.webcal_server import Server, Store, atomic_json, validate
from core import export_ics, reconcile
import test_sync
import sync
import webcal


READ = "r" * 43
WRITE = "w" * 43


def example():
    snapshot = test_sync.TimetableTests().baseline()
    ics = export_ics(snapshot)
    return {"schema": 1, "run_id": "2026-09-05T120000Z_1234abcd", "source_fetched_at": "2026-09-05T12:00:00Z",
            "sha256": hashlib.sha256(ics).hexdigest(), "event_count": 1,
            "ics_base64": base64.b64encode(ics).decode()}


class WebCalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "remote")
        config = {"read_sha256": hashlib.sha256(READ.encode()).hexdigest(),
                  "write_sha256": hashlib.sha256(WRITE.encode()).hexdigest()}
        self.server = Server(("127.0.0.1", 0), config, self.store)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, method, path, body=None, token=None, extra=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        headers = {"Content-Type": "application/json", **(extra or {})}
        if token:
            headers["Authorization"] = "Bearer " + token
        if isinstance(body, dict):
            body = json.dumps(body).encode()
        conn.request(method, path, body, headers)
        response = conn.getresponse()
        result = response.status, response.read(), dict(response.getheaders())
        conn.close()
        return result

    def test_access_protection_and_read_write_separation(self):
        self.store.commit(example())
        for path in ("/calendar.ics", "/status", "/" + WRITE + "/calendar.ics", "/../current.json"):
            self.assertEqual(self.request("GET", path)[0], 404)
        for token in (None, READ, "bad"):
            self.assertEqual(self.request("PUT", "/upload", example(), token)[0], 404)
        status, content, headers = self.request("GET", "/" + READ + "/calendar.ics")
        self.assertEqual(status, 200)
        self.assertEqual(content, base64.b64decode(example()["ics_base64"]))
        self.assertTrue(headers["Content-Type"].startswith("text/calendar"))
        self.assertEqual(self.request("GET", "/" + READ + "/calendar.ics", extra={"If-None-Match": headers["ETag"]})[0], 304)

    def test_first_upload_and_identical_retry_are_idempotent(self):
        self.assertEqual(self.request("GET", "/" + READ + "/calendar.ics")[0], 503)
        self.assertEqual(self.request("PUT", "/upload", example(), WRITE)[0], 200)
        path = self.store.directory / "current.json"
        before = path.stat().st_mtime_ns
        self.assertEqual(self.request("PUT", "/upload", example(), WRITE)[0], 200)
        self.assertEqual(before, path.stat().st_mtime_ns)
        self.assertFalse((self.store.directory / "previous.json").exists())

    def test_newer_version_then_stale_version_preserves_latest(self):
        self.store.commit(example())
        new = example()
        new["source_fetched_at"] = "2026-09-05T13:00:00Z"
        new["run_id"] = "2026-09-05T130000Z_abcd1234"
        self.assertEqual(self.request("PUT", "/upload", new, WRITE)[0], 200)
        self.assertEqual(self.request("PUT", "/upload", example(), WRITE)[0], 409)
        self.assertEqual(self.store.read(), new)
        self.assertEqual(json.loads((self.store.directory / "previous.json").read_text()), example())

    def test_bad_payloads_never_replace_good_calendar(self):
        original = example()
        self.store.commit(original)
        variants = []
        for key, value in (("sha256", "0" * 64), ("event_count", 0), ("ics_base64", "!!!"),
                           ("source_fetched_at", "2026-09-05T12:00:00"), ("run_id", "../../bad")):
            bad = copy.deepcopy(original)
            bad[key] = value
            variants.append(bad)
        for bad in variants:
            self.assertEqual(self.request("PUT", "/upload", bad, WRITE)[0], 400)
            self.assertEqual(self.store.read(), original)

    def test_same_source_time_conflicting_content_is_rejected(self):
        self.store.commit(example())
        changed = example()
        data = base64.b64decode(changed["ics_base64"]).replace(b"VERSION:2.0", b"VERSION:2.0\r\nX-TEST:changed")
        changed.update(ics_base64=base64.b64encode(data).decode(), sha256=hashlib.sha256(data).hexdigest())
        self.assertEqual(self.request("PUT", "/upload", changed, WRITE)[0], 409)
        self.assertEqual(self.store.read(), example())

    def test_failed_atomic_replace_keeps_current(self):
        self.store.commit(example())
        new = example()
        new["source_fetched_at"] = "2026-09-05T13:00:00Z"
        from deploy import webcal_server
        original_replace = webcal_server.os.replace
        def fail_current(source, target):
            if Path(target).name == "current.json":
                raise OSError("synthetic disk fault")
            original_replace(source, target)
        with patch.object(webcal_server.os, "replace", side_effect=fail_current):
            self.assertEqual(self.request("PUT", "/upload", new, WRITE)[0], 503)
        self.assertEqual(self.store.read(), example())

    def prepare_local(self):
        snapshot, diff = reconcile(test_sync.normalized([test_sync.fixture()]), None, test_sync.SCOPE, test_sync.NOW)
        snapshot["capture_fetched_at"] = example()["source_fetched_at"]
        run = self.root / "data/runs" / example()["run_id"]
        sync.publish(self.root, run, snapshot, diff, None)
        config = {"enabled": True, "origin": "https://calendar.example.com:8443", "read_token": READ, "write_token": WRITE}
        sync.atomic_write(self.root / "local/webcal.json", sync.json_bytes(config))
        return config

    def fake_transport(self, config, method, path, body=None, writer=False):
        status, content, _ = self.request(method, path, body, WRITE if writer else None)
        return status, content

    def test_local_committed_version_upload_and_readback(self):
        self.prepare_local()
        with patch.object(webcal, "request", side_effect=self.fake_transport):
            result = webcal.publish_current(self.root)
        self.assertEqual(result["sha256"], example()["sha256"])
        self.assertTrue((self.root / "local/webcal-last-success.json").exists())

    def test_corrupt_local_output_blocks_network(self):
        self.prepare_local()
        (self.root / "output/calendar.ics").write_bytes(b"bad")
        with patch.object(webcal, "request") as transport:
            with self.assertRaises(webcal.UploadError):
                webcal.publish_current(self.root)
            transport.assert_not_called()

    def test_unacknowledged_upload_keeps_local_and_returns_exit_four(self):
        self.prepare_local()
        before = (self.root / "data/current.json").read_bytes()
        with patch.object(sync, "ROOT", self.root), patch.object(webcal, "request", side_effect=OSError("synthetic")), patch.object(webcal.time, "sleep"):
            self.assertEqual(sync.main(["--upload-only"]), 4)
        self.assertEqual((self.root / "data/current.json").read_bytes(), before)
        self.assertFalse((self.root / "local/webcal-last-success.json").exists())

    def test_disabled_upload_never_uses_network(self):
        with patch.object(webcal, "request") as transport:
            self.assertIsNone(webcal.publish_current(self.root))
            with self.assertRaises(webcal.UploadError):
                webcal.publish_current(self.root, required=True)
            transport.assert_not_called()

    def test_http_or_embedded_credentials_are_rejected(self):
        config = self.prepare_local()
        for origin in ("http://calendar.example.com", "https://user:password@calendar.example.com", "https://calendar.example.com/?token=x"):
            config["origin"] = origin
            sync.atomic_write(self.root / "local/webcal.json", sync.json_bytes(config))
            with self.assertRaises(webcal.UploadError):
                webcal.load_config(self.root)


if __name__ == "__main__":
    unittest.main()
