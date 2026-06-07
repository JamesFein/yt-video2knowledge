from __future__ import annotations

import json
import re
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Settings
from .database import connect_db, initialize_database, utc_now


READY_STATUS = "summary_ready"
PENDING_STATUS = "pending_summary"
FAILED_STATUS = "transcript_failed"
THUMBNAIL_EXTENSIONS = (".webp", ".jpg", ".jpeg", ".png")


@dataclass(frozen=True)
class DaySyncResult:
    day_date: str
    imported_video_count: int
    skipped_pending_count: int
    skipped_failed_count: int


@dataclass(frozen=True)
class SyncReport:
    days: list[DaySyncResult]

    @property
    def imported_video_count(self) -> int:
        return sum(day.imported_video_count for day in self.days)


def sync_knowledge_site(settings: Settings, runs_dir: Path | None = None) -> SyncReport:
    source_dir = runs_dir or settings.root_dir / "data" / "runs"
    initialize_database(settings.db_path)
    settings.assets_dir.mkdir(parents=True, exist_ok=True)

    day_dirs = list(_iter_day_dirs(source_dir))
    conn = connect_db(settings.db_path)
    try:
        with conn:
            results = [_sync_day(conn, settings, day_dir) for day_dir in day_dirs]
    finally:
        conn.close()
    return SyncReport(days=results)


def _iter_day_dirs(runs_dir: Path) -> list[Path]:
    if not runs_dir.exists():
        return []
    return [
        path
        for path in sorted(runs_dir.iterdir())
        if path.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.name)
    ]


def _sync_day(
    conn: sqlite3.Connection,
    settings: Settings,
    day_dir: Path,
) -> DaySyncResult:
    synced_at = utc_now()
    day_date = day_dir.name
    manifest = _load_json(day_dir / "manifest.json")
    manifest_records, manifest_failures = _manifest_indexes(manifest)
    pending_ids = {
        video_id
        for video_id, record in manifest_records.items()
        if record.get("processing_status") == PENDING_STATUS
    }
    failed_ids = set(manifest_failures)

    overview = _read_text(day_dir / "daily-overview.zh-CN.md")
    conn.execute(
        """
        INSERT INTO days (day_date, daily_summary_markdown, synced_at)
        VALUES (?, ?, ?)
        ON CONFLICT(day_date) DO UPDATE SET
            daily_summary_markdown = excluded.daily_summary_markdown,
            synced_at = excluded.synced_at
        """,
        (day_date, overview, synced_at),
    )
    conn.execute("DELETE FROM day_videos WHERE day_date = ?", (day_date,))

    imported = 0
    videos_dir = day_dir / "videos"
    if videos_dir.exists():
        for position, video_dir in enumerate(sorted(path for path in videos_dir.iterdir() if path.is_dir())):
            video_id = video_dir.name
            metadata = _load_json(video_dir / "metadata.json")
            record = {**manifest_records.get(video_id, {}), **metadata}
            record.setdefault("id", video_id)
            status = record.get("processing_status")
            if not status and video_id in manifest_failures:
                status = FAILED_STATUS

            if status == PENDING_STATUS:
                pending_ids.add(video_id)
                continue
            if status == FAILED_STATUS or record.get("failure_stage") == FAILED_STATUS:
                failed_ids.add(video_id)
                continue
            if status != READY_STATUS:
                continue

            summary_path = video_dir / "summary.zh-CN.md"
            if not summary_path.exists():
                pending_ids.add(video_id)
                continue

            _upsert_video(conn, settings, day_date, position, video_dir, record, summary_path)
            imported += 1

    conn.execute(
        """
        INSERT INTO sync_runs (
            run_date,
            synced_at,
            imported_video_count,
            skipped_pending_count,
            skipped_failed_count
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (day_date, synced_at, imported, len(pending_ids), len(failed_ids)),
    )
    return DaySyncResult(
        day_date=day_date,
        imported_video_count=imported,
        skipped_pending_count=len(pending_ids),
        skipped_failed_count=len(failed_ids),
    )


def _manifest_indexes(manifest: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    records: dict[str, dict[str, Any]] = {}
    failures: dict[str, dict[str, Any]] = {}

    videos = manifest.get("videos")
    if isinstance(videos, dict):
        for video_id, record in videos.items():
            if isinstance(record, dict):
                records[str(video_id)] = {**record, "id": str(video_id)}
    elif isinstance(videos, list):
        _merge_records(records, videos)

    _merge_records(records, manifest.get("processed_videos", []))
    for item in manifest.get("failed_videos", []):
        if isinstance(item, dict) and item.get("id"):
            failures[str(item["id"])] = {**item, "processing_status": FAILED_STATUS}

    return records, failures


def _merge_records(target: dict[str, dict[str, Any]], items: Any) -> None:
    if not isinstance(items, list):
        return
    for item in items:
        if isinstance(item, dict) and item.get("id"):
            target[str(item["id"])] = dict(item)


def _upsert_video(
    conn: sqlite3.Connection,
    settings: Settings,
    day_date: str,
    position: int,
    video_dir: Path,
    record: dict[str, Any],
    summary_path: Path,
) -> None:
    video_id = str(record.get("id") or video_dir.name)
    duration_label, duration_seconds = _duration_fields(record.get("duration"))
    transcript_path = _copy_transcript(settings, video_id, video_dir)
    thumbnail_path = _copy_thumbnail(settings, video_id, video_dir)
    now = utc_now()

    conn.execute(
        """
        INSERT INTO videos (
            video_id,
            title,
            channel_name,
            url,
            duration_seconds,
            duration_label,
            upload_date,
            summary_markdown,
            transcript_path,
            thumbnail_path,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(video_id) DO UPDATE SET
            title = excluded.title,
            channel_name = excluded.channel_name,
            url = excluded.url,
            duration_seconds = excluded.duration_seconds,
            duration_label = excluded.duration_label,
            upload_date = excluded.upload_date,
            summary_markdown = excluded.summary_markdown,
            transcript_path = excluded.transcript_path,
            thumbnail_path = excluded.thumbnail_path,
            updated_at = excluded.updated_at
        """,
        (
            video_id,
            str(record.get("title") or video_id),
            str(record.get("channel_name") or record.get("uploader") or record.get("channel") or ""),
            str(record.get("url") or record.get("webpage_url") or f"https://www.youtube.com/watch?v={video_id}"),
            duration_seconds,
            duration_label,
            _normalize_upload_date(record.get("upload_date")),
            _read_text(summary_path),
            transcript_path,
            thumbnail_path,
            now,
        ),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO video_meta_summaries (video_id, content, updated_at)
        VALUES (?, '', ?)
        """,
        (video_id, now),
    )
    conn.execute(
        """
        INSERT INTO day_videos (day_date, video_id, position)
        VALUES (?, ?, ?)
        ON CONFLICT(day_date, video_id) DO UPDATE SET position = excluded.position
        """,
        (day_date, video_id, position),
    )


def _copy_transcript(settings: Settings, video_id: str, video_dir: Path) -> str | None:
    source = video_dir / "transcript.original.txt"
    if not source.exists():
        return None
    destination = settings.assets_dir / "transcripts" / f"{video_id}.txt"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return _relative_to_root(settings, destination)


def _copy_thumbnail(settings: Settings, video_id: str, video_dir: Path) -> str | None:
    for extension in THUMBNAIL_EXTENSIONS:
        source = video_dir / f"thumbnail{extension}"
        if not source.exists():
            continue
        destination = settings.assets_dir / "thumbnails" / f"{video_id}{extension}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return _relative_to_root(settings, destination)
    return None


def _relative_to_root(settings: Settings, path: Path) -> str:
    return path.resolve().relative_to(settings.root_dir.resolve()).as_posix()


def _duration_fields(value: Any) -> tuple[str | None, int | None]:
    if value is None:
        return None, None
    if isinstance(value, bool):
        return None, None
    if isinstance(value, int):
        return str(value), value
    if isinstance(value, float):
        return str(int(value)), int(value)

    label = str(value).strip()
    if not label:
        return None, None
    if label.isdigit():
        return label, int(label)
    parts = label.split(":")
    if all(part.isdigit() for part in parts):
        seconds = 0
        for part in parts:
            seconds = seconds * 60 + int(part)
        return label, seconds
    return label, None


def _normalize_upload_date(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if re.fullmatch(r"\d{8}", text):
        return f"{text[0:4]}-{text[4:6]}-{text[6:8]}"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    return None


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")

