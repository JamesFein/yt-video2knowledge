"""Own the Digest Run manifest lifecycle and completion rules."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from yt_video2knowledge.digest.config import (
    DigestConfig,
    _read_json,
    _write_json,
    beijing_now,
    load_config,
    parse_target_date,
)
from yt_video2knowledge.digest.errors import DigestError

def load_run_manifest(run_dir: Path) -> dict[str, Any]:
    return _read_json(run_dir / "manifest.json", {})


def index_manifest_videos(
    manifest: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Normalize supported manifest shapes for downstream consumers."""
    records: dict[str, dict[str, Any]] = {}
    failures: dict[str, dict[str, Any]] = {}

    videos = manifest.get("videos")
    if isinstance(videos, dict):
        for video_id, record in videos.items():
            if isinstance(record, dict):
                records[str(video_id)] = {**record, "id": str(video_id)}
    elif isinstance(videos, list):
        _merge_manifest_records(records, videos)

    _merge_manifest_records(records, manifest.get("processed_videos", []))
    for item in manifest.get("failed_videos", []):
        if isinstance(item, dict) and item.get("id"):
            failures[str(item["id"])] = {**item, "processing_status": "transcript_failed"}

    return records, failures


def _merge_manifest_records(target: dict[str, dict[str, Any]], items: Any) -> None:
    if not isinstance(items, list):
        return
    for item in items:
        if isinstance(item, dict) and item.get("id"):
            target[str(item["id"])] = dict(item)


def _index_videos_by_id(videos: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for video in videos:
        video_id = video.get("id")
        if video_id:
            indexed[video_id] = video
    return indexed


def _default_incremental_stats(
    *,
    selected_count: int = 0,
    to_process_count: int = 0,
    new_video_count: int = 0,
    retried_non_success_count: int = 0,
    skipped_summary_ready_count: int = 0,
) -> dict[str, int]:
    return {
        "selected_count": selected_count,
        "to_process_count": to_process_count,
        "new_video_count": new_video_count,
        "retried_non_success_count": retried_non_success_count,
        "skipped_summary_ready_count": skipped_summary_ready_count,
    }


def plan_run_entries(
    entries: list[dict[str, Any]],
    existing_manifest: dict[str, Any],
    *,
    full_reprocess: bool = False,
) -> tuple[str, list[dict[str, Any]], dict[str, int]]:
    selected_count = len(entries)
    if full_reprocess or not existing_manifest:
        return (
            "full",
            entries,
            _default_incremental_stats(
                selected_count=selected_count,
                to_process_count=len(entries),
            ),
        )

    processed_index = _index_videos_by_id(existing_manifest.get("processed_videos", []))
    failed_index = _index_videos_by_id(existing_manifest.get("failed_videos", []))
    entries_to_process: list[dict[str, Any]] = []
    new_video_count = 0
    retried_non_success_count = 0
    skipped_summary_ready_count = 0

    for entry in entries:
        existing_processed = processed_index.get(entry["id"])
        if existing_processed and existing_processed.get("processing_status") == "summary_ready":
            skipped_summary_ready_count += 1
            continue
        if existing_processed or entry["id"] in failed_index:
            retried_non_success_count += 1
        else:
            new_video_count += 1
        entries_to_process.append(entry)

    return (
        "incremental",
        entries_to_process,
        _default_incremental_stats(
            selected_count=selected_count,
            to_process_count=len(entries_to_process),
            new_video_count=new_video_count,
            retried_non_success_count=retried_non_success_count,
            skipped_summary_ready_count=skipped_summary_ready_count,
        ),
    )


def merge_run_results(
    existing_manifest: dict[str, Any],
    processed_videos: list[dict[str, Any]],
    failed_videos: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    merged_processed = _index_videos_by_id(existing_manifest.get("processed_videos", []))
    merged_failed = _index_videos_by_id(existing_manifest.get("failed_videos", []))

    for video in processed_videos:
        video_id = video["id"]
        merged_failed.pop(video_id, None)
        merged_processed[video_id] = video

    for video in failed_videos:
        video_id = video["id"]
        merged_processed.pop(video_id, None)
        merged_failed[video_id] = video

    return list(merged_processed.values()), list(merged_failed.values())


def _summary_ready_videos(processed_videos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in processed_videos if item.get("processing_status") == "summary_ready"]


def _pending_summary_videos(processed_videos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in processed_videos if item.get("processing_status") == "pending_summary"]


def _manifest_has_pending_summaries(manifest: dict[str, Any]) -> bool:
    return int(manifest.get("pending_summary_count") or 0) > 0 or bool(
        _pending_summary_videos(manifest.get("processed_videos", []))
    )


def is_manifest_complete(manifest: dict[str, Any]) -> bool:
    return int(manifest.get("failed_count") or 0) == 0 and int(manifest.get("pending_summary_count") or 0) == 0


def manifest_completion_status(manifest: dict[str, Any]) -> str:
    return "success" if is_manifest_complete(manifest) else "partial"


def _build_manifest(
    target_date: date,
    config: DigestConfig,
    browser_mode: str,
    processed_videos: list[dict[str, Any]],
    failed_videos: list[dict[str, Any]],
    needs_review: list[dict[str, Any]],
    *,
    run_mode: str = "full",
    incremental_stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pending_summary_videos = _pending_summary_videos(processed_videos)
    normalized_incremental_stats = _default_incremental_stats()
    if incremental_stats:
        for key in normalized_incremental_stats:
            value = incremental_stats.get(key, normalized_incremental_stats[key])
            normalized_incremental_stats[key] = int(value)
    manifest = {
        "target_date": target_date.isoformat(),
        "playlist_name": config.playlist_name,
        "playlist_url": config.playlist_url,
        "generated_at": beijing_now().isoformat(),
        "browser_mode": browser_mode,
        "run_mode": run_mode,
        "incremental_stats": normalized_incremental_stats,
        "processed_count": len(processed_videos),
        "summary_ready_count": len(_summary_ready_videos(processed_videos)),
        "pending_summary_count": len(pending_summary_videos),
        "failed_count": len(failed_videos),
        "transcript_failed_count": len(failed_videos),
        "needs_review_count": len(needs_review),
        "date_unverified_count": len(needs_review),
        "processed_videos": processed_videos,
        "pending_summary_videos": pending_summary_videos,
        "failed_videos": failed_videos,
        "needs_review_videos": needs_review,
    }
    manifest["completion_status"] = manifest_completion_status(manifest)
    manifest["needs_retry"] = manifest["completion_status"] != "success"
    return manifest


def read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def load_json_if_exists(path: Path) -> dict:
    if not path.exists():
        return {}
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def recover_run(target_date_text: str) -> dict:
    target_date = parse_target_date(target_date_text)
    config = load_config()
    run_dir = config.output_root_path / target_date.isoformat()
    videos_dir = run_dir / "videos"
    if not videos_dir.is_dir():
        raise DigestError(f"Missing videos directory: {videos_dir}")

    processed_videos: list[dict] = []
    failed_videos: list[dict] = []
    needs_review: list[dict] = []

    for video_dir in sorted(path for path in videos_dir.iterdir() if path.is_dir()):
        video_id = video_dir.name
        metadata = load_json_if_exists(video_dir / "metadata.json")
        summary_path = video_dir / "summary.zh-CN.md"
        transcript_path = video_dir / "transcript.original.txt"
        summary_text = read_text_if_exists(summary_path)
        title = metadata.get("title") or video_id
        url = metadata.get("url") or f"https://www.youtube.com/watch?v={video_id}"

        if summary_path.exists() and transcript_path.exists():
            video = {
                **metadata,
                "id": video_id,
                "title": title,
                "url": url,
                "summary_path": str(summary_path.relative_to(run_dir)),
                "transcript_path": str(transcript_path.relative_to(run_dir)),
                "processing_status": "summary_ready",
                "summary_error": None,
                "summary_text": summary_text,
            }
            processed_videos.append(video)
            if not video.get("playlist_added_date") and video.get("playlist_added_text"):
                needs_review.append(video)
            continue

        if transcript_path.exists():
            video = {
                **metadata,
                "id": video_id,
                "title": title,
                "url": url,
                "summary_path": None,
                "transcript_path": str(transcript_path.relative_to(run_dir)),
                "processing_status": "pending_summary",
                "summary_error": "Recovered transcript without summary",
                "summary_text": "",
            }
            processed_videos.append(video)
            continue

        failed_videos.append(
            {
                "id": video_id,
                "title": title,
                "url": url,
                "failure_stage": "transcript_failed",
                "error": "Recovered incomplete artifact: missing transcript.original.txt",
            }
        )

    incremental_stats = {
        "selected_count": len(processed_videos) + len(failed_videos),
        "to_process_count": 0,
        "new_video_count": 0,
        "retried_non_success_count": 0,
        "skipped_summary_ready_count": len(
            [item for item in processed_videos if item.get("processing_status") == "summary_ready"]
        ),
    }
    manifest = _build_manifest(
        target_date,
        config,
        "recovered",
        processed_videos,
        failed_videos,
        needs_review,
        run_mode="recovered",
        incremental_stats=incremental_stats,
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_json(run_dir / "manifest.json", manifest)
    return manifest
