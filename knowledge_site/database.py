from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = 1


class SchemaVersionError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def initialize_database(db_path: Path) -> None:
    conn = connect_db(db_path)
    try:
        _initialize_schema(conn)
        conn.commit()
    finally:
        conn.close()


def _initialize_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            version INTEGER NOT NULL
        )
        """
    )
    row = conn.execute("SELECT version FROM schema_version WHERE id = 1").fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO schema_version (id, version) VALUES (1, ?)",
            (SCHEMA_VERSION,),
        )
    elif int(row["version"]) != SCHEMA_VERSION:
        raise SchemaVersionError(
            "Unsupported knowledge site database schema. "
            f"Expected version {SCHEMA_VERSION}, found {row['version']}. "
            "Create a migration before starting this version."
        )

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS days (
            day_date TEXT PRIMARY KEY,
            daily_summary_markdown TEXT NOT NULL,
            synced_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS videos (
            video_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            channel_name TEXT NOT NULL,
            url TEXT NOT NULL,
            duration_seconds INTEGER,
            duration_label TEXT,
            upload_date TEXT,
            summary_markdown TEXT NOT NULL,
            transcript_path TEXT,
            thumbnail_path TEXT,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS day_videos (
            day_date TEXT NOT NULL,
            video_id TEXT NOT NULL,
            position INTEGER NOT NULL,
            PRIMARY KEY (day_date, video_id),
            FOREIGN KEY (day_date) REFERENCES days(day_date) ON DELETE CASCADE,
            FOREIGN KEY (video_id) REFERENCES videos(video_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS video_meta_summaries (
            video_id TEXT PRIMARY KEY,
            content TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            FOREIGN KEY (video_id) REFERENCES videos(video_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS sync_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date TEXT NOT NULL,
            synced_at TEXT NOT NULL,
            imported_video_count INTEGER NOT NULL,
            skipped_pending_count INTEGER NOT NULL,
            skipped_failed_count INTEGER NOT NULL
        );
        """
    )

