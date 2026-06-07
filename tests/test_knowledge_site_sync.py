from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from knowledge_site.config import Settings
from knowledge_site.database import connect_db
from knowledge_site.sync import sync_knowledge_site


def make_settings(root: Path) -> Settings:
    return Settings(
        root_dir=root,
        db_path=root / "data" / "knowledge.sqlite3",
        assets_dir=root / "data" / "knowledge-assets",
        password="secret",
        secret_key="test-secret",
        dev_mode=True,
    )


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def write_video(
    day_dir: Path,
    video_id: str,
    *,
    status: str = "summary_ready",
    title: str | None = None,
    summary: str | None = None,
    thumbnail_ext: str | None = ".webp",
) -> None:
    video_dir = day_dir / "videos" / video_id
    video_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "id": video_id,
        "title": title or f"Video {video_id}",
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "channel_name": "Channel",
        "upload_date": "20260601",
        "duration": "1:02:03",
        "processing_status": status,
    }
    write_json(video_dir / "metadata.json", payload)
    (video_dir / "transcript.original.txt").write_text(f"Transcript {video_id}", encoding="utf-8")
    if summary is not None:
        (video_dir / "summary.zh-CN.md").write_text(summary, encoding="utf-8")
        (video_dir / "report.md").write_text("legacy duplicate", encoding="utf-8")
    if thumbnail_ext:
        (video_dir / f"thumbnail{thumbnail_ext}").write_bytes(b"image")


class KnowledgeSiteSyncTests(unittest.TestCase):
    def test_sync_imports_ready_videos_assets_and_skip_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(root)
            day_dir = root / "data" / "runs" / "2026-06-01"
            day_dir.mkdir(parents=True)
            (day_dir / "daily-overview.zh-CN.md").write_text("# Daily\n\nOverview", encoding="utf-8")
            write_video(day_dir, "ready", summary="## 一句话总结\n\nReady summary", thumbnail_ext=".jpg")
            write_video(day_dir, "pending", status="pending_summary", summary=None)
            write_json(
                day_dir / "manifest.json",
                {
                    "processed_videos": [
                        {"id": "ready", "processing_status": "summary_ready"},
                        {"id": "pending", "processing_status": "pending_summary"},
                    ],
                    "failed_videos": [
                        {"id": "failed", "failure_stage": "transcript_failed"},
                    ],
                },
            )

            report = sync_knowledge_site(settings)

            self.assertEqual(report.imported_video_count, 1)
            self.assertEqual(report.days[0].skipped_pending_count, 1)
            self.assertEqual(report.days[0].skipped_failed_count, 1)

            conn = connect_db(settings.db_path)
            try:
                day = conn.execute("SELECT * FROM days WHERE day_date = '2026-06-01'").fetchone()
                self.assertEqual(day["daily_summary_markdown"], "# Daily\n\nOverview")
                videos = conn.execute("SELECT * FROM videos").fetchall()
                self.assertEqual([row["video_id"] for row in videos], ["ready"])
                self.assertIn("Ready summary", videos[0]["summary_markdown"])
                self.assertNotIn("legacy duplicate", videos[0]["summary_markdown"])
                self.assertEqual(videos[0]["duration_seconds"], 3723)
                self.assertEqual(videos[0]["upload_date"], "2026-06-01")
                self.assertEqual(videos[0]["transcript_path"], "data/knowledge-assets/transcripts/ready.txt")
                self.assertEqual(videos[0]["thumbnail_path"], "data/knowledge-assets/thumbnails/ready.jpg")
                self.assertTrue((root / videos[0]["transcript_path"]).exists())
                self.assertTrue((root / videos[0]["thumbnail_path"]).exists())
                meta = conn.execute("SELECT * FROM video_meta_summaries WHERE video_id = 'ready'").fetchone()
                self.assertEqual(meta["content"], "")
                sync_run = conn.execute("SELECT * FROM sync_runs").fetchone()
                self.assertEqual(sync_run["imported_video_count"], 1)
                self.assertEqual(sync_run["skipped_pending_count"], 1)
                self.assertEqual(sync_run["skipped_failed_count"], 1)
            finally:
                conn.close()

    def test_empty_days_and_duplicate_videos_are_imported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(root)
            runs = root / "data" / "runs"
            empty_day = runs / "2026-06-01"
            first_day = runs / "2026-06-02"
            second_day = runs / "2026-06-03"
            empty_day.mkdir(parents=True)
            (empty_day / "daily-overview.zh-CN.md").write_text("Empty day", encoding="utf-8")
            first_day.mkdir(parents=True)
            second_day.mkdir(parents=True)
            write_video(first_day, "shared", summary="## First\n\nSummary")
            write_video(second_day, "shared", summary="## Second\n\nSummary")

            sync_knowledge_site(settings)

            conn = connect_db(settings.db_path)
            try:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM days").fetchone()[0], 3)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM day_videos").fetchone()[0], 2)
                empty_count = conn.execute(
                    "SELECT COUNT(*) FROM day_videos WHERE day_date = '2026-06-01'"
                ).fetchone()[0]
                self.assertEqual(empty_count, 0)
            finally:
                conn.close()

    def test_resync_preserves_meta_summary_and_constraints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = make_settings(root)
            day_dir = root / "data" / "runs" / "2026-06-01"
            day_dir.mkdir(parents=True)
            write_video(day_dir, "ready", summary="## Old\n\nOld summary")
            sync_knowledge_site(settings)

            conn = connect_db(settings.db_path)
            try:
                with conn:
                    conn.execute(
                        """
                        UPDATE video_meta_summaries
                        SET content = 'kept'
                        WHERE video_id = 'ready'
                        """
                    )
            finally:
                conn.close()

            (day_dir / "videos" / "ready" / "summary.zh-CN.md").write_text(
                "## New\n\nNew summary",
                encoding="utf-8",
            )
            sync_knowledge_site(settings)

            conn = connect_db(settings.db_path)
            try:
                video = conn.execute("SELECT * FROM videos WHERE video_id = 'ready'").fetchone()
                self.assertIn("New summary", video["summary_markdown"])
                meta = conn.execute(
                    "SELECT * FROM video_meta_summaries WHERE video_id = 'ready'"
                ).fetchone()
                self.assertEqual(meta["content"], "kept")
                with self.assertRaises(sqlite3.IntegrityError):
                    with conn:
                        conn.execute(
                            "INSERT INTO day_videos (day_date, video_id, position) VALUES (?, ?, ?)",
                            ("2026-06-01", "ready", 99),
                        )
                with conn:
                    conn.execute("DELETE FROM videos WHERE video_id = 'ready'")
                remaining = conn.execute(
                    "SELECT COUNT(*) FROM video_meta_summaries WHERE video_id = 'ready'"
                ).fetchone()[0]
                self.assertEqual(remaining, 0)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()

