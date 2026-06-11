from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from knowledge_queue import (  # noqa: E402
    BEIJING_TZ,
    acquire_worker_lock,
    classify_digest_manifest,
    format_worker_status,
    inspect_worker_lock,
    record_worker_interrupted,
    release_worker_lock,
    write_worker_lock,
)


class KnowledgeQueueLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 6, 10, 12, 0, tzinfo=BEIJING_TZ)

    def test_live_lock_is_not_acquired_or_released_by_another_worker(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "worker.lock"
            write_worker_lock(lock_path, pid=123, started_at=self.now, heartbeat=self.now)

            acquired = acquire_worker_lock(
                lock_path,
                pid=456,
                clock=lambda: self.now,
                pid_exists=lambda pid: True,
            )
            released = release_worker_lock(lock_path, pid=456)

            self.assertFalse(acquired)
            self.assertFalse(released)
            self.assertEqual(json.loads(lock_path.read_text(encoding="utf-8"))["pid"], 123)

    def test_stale_lock_can_be_recovered(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "worker.lock"
            old_heartbeat = self.now - timedelta(minutes=30)
            write_worker_lock(lock_path, pid=123, started_at=old_heartbeat, heartbeat=old_heartbeat)

            inspection = inspect_worker_lock(
                lock_path,
                clock=lambda: self.now,
                pid_exists=lambda pid: True,
            )
            acquired = acquire_worker_lock(
                lock_path,
                pid=456,
                clock=lambda: self.now,
                pid_exists=lambda pid: True,
            )

            self.assertEqual(inspection["status"], "stale")
            self.assertEqual(inspection["reason"], "heartbeat_expired")
            self.assertTrue(acquired)
            self.assertEqual(json.loads(lock_path.read_text(encoding="utf-8"))["pid"], 456)

    def test_interruption_releases_lock_but_keeps_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            lock_path = root / "worker.lock"
            state_path = root / "status.json"
            request_path = root / "requests" / "2026-06-10.json"
            request_path.parent.mkdir()
            request_path.write_text("{}", encoding="utf-8")
            write_worker_lock(lock_path, pid=123, started_at=self.now, heartbeat=self.now)

            state = record_worker_interrupted(
                state_path,
                lock_path,
                target_date="2026-06-10",
                request_path=request_path,
                clock=lambda: self.now,
            )

            self.assertEqual(state["status"], "interrupted")
            self.assertFalse(lock_path.exists())
            self.assertTrue(request_path.exists())


class KnowledgeQueueStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 6, 10, 12, 0, tzinfo=BEIJING_TZ)

    def test_status_output_reports_partial_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_path = root / "status.json"
            lock_path = root / "worker.lock"
            manifest_path = root / "manifest.json"
            state_path.write_text(json.dumps({"status": "idle", "target_date": "2026-06-10"}), encoding="utf-8")
            manifest_path.write_text(
                json.dumps({"failed_count": 0, "pending_summary_count": 1}),
                encoding="utf-8",
            )

            output = format_worker_status(
                state_path,
                lock_path,
                manifest_path=manifest_path,
                clock=lambda: self.now,
                pid_exists=lambda pid: False,
            )

            self.assertIn("status: idle", output)
            self.assertIn("digest: partial", output)
            self.assertIn("pending_summary_count: 1", output)

    def test_status_output_reports_stale_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_path = root / "status.json"
            lock_path = root / "worker.lock"
            write_worker_lock(lock_path, pid=123, started_at=self.now, heartbeat=self.now)

            output = format_worker_status(
                state_path,
                lock_path,
                clock=lambda: self.now,
                pid_exists=lambda pid: False,
            )

            self.assertIn("status: stale lock", output)
            self.assertIn("action: recover", output)

    def test_manifest_classifier_uses_failed_and_pending_counts(self) -> None:
        self.assertEqual(classify_digest_manifest({"failed_count": 0, "pending_summary_count": 0}), "success")
        self.assertEqual(classify_digest_manifest({"failed_count": 1, "pending_summary_count": 0}), "partial")


if __name__ == "__main__":
    unittest.main()
