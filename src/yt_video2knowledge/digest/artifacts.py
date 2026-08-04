"""Persist Transcript, Video Summary, metadata, and local run state."""
from __future__ import annotations

import shutil
import time
from datetime import date
from pathlib import Path
from typing import Any

from yt_video2knowledge.digest.config import (
    _atomic_write_text,
    _write_json,
    beijing_now,
)
from yt_video2knowledge.digest.summary import _extract_display_title
from yt_video2knowledge.digest.transcript import TranscriptResult

def build_video_summary_markdown(
    video: dict[str, Any],
    summary_text: str,
    transcript_relative_path: str,
    display_title: str | None = None,
) -> str:
    added_text = video.get("playlist_added_text") or "未解析到"
    transcript_source = video.get("transcript_source", "unknown")
    title = display_title or video["title"]
    return (
        f"# {title}\n\n"
        "## 视频信息\n"
        f"- 频道: {video.get('channel_name') or 'Unknown'}\n"
        f"- 链接: {video.get('url')}\n"
        f"- 发布时间: {video.get('upload_date') or 'Unknown'}\n"
        f"- 时长: {video.get('duration_string') or video.get('duration') or 'Unknown'}\n"
        f"- 加入播放列表时间: {added_text}\n"
        f"- Transcript 来源: {transcript_source}\n\n"
        "## 中文总结\n"
        f"{summary_text.strip()}\n\n"
        "## 原始 Transcript\n"
        f"- 完整文本: `{transcript_relative_path}`\n"
    )


def _duration_seconds(started_at: float) -> float:
    return round(time.monotonic() - started_at, 3)


def write_video_outputs(
    run_dir: Path,
    video: dict[str, Any],
    transcript: TranscriptResult,
    summary_text: str | None,
    summary_status: str,
    summary_error: str | None = None,
    prebuilt_summary_markdown: bool = False,
) -> dict[str, Any]:
    video_dir = run_dir / "videos" / video["id"]
    video_dir.mkdir(parents=True, exist_ok=True)

    transcript_path = video_dir / "transcript.original.txt"
    transcript_path.write_text(transcript.text, encoding="utf-8")

    summary_path = video_dir / "summary.zh-CN.md"
    legacy_report = video_dir / "report.md"
    cleaned_summary_text = summary_text.strip() if summary_text else ""
    display_title = str(video.get("display_title") or video["title"])
    if summary_text:
        if not prebuilt_summary_markdown:
            display_title, cleaned_summary_text = _extract_display_title(summary_text, video["title"])
        summary_markdown = (
            summary_text.strip() + "\n"
            if prebuilt_summary_markdown
            else build_video_summary_markdown(
                video,
                cleaned_summary_text,
                "transcript.original.txt",
                display_title=display_title,
            )
        )
        _atomic_write_text(legacy_report, summary_markdown)
        _atomic_write_text(summary_path, summary_markdown)
    else:
        summary_path.unlink(missing_ok=True)
        legacy_report.unlink(missing_ok=True)

    metadata_path = video_dir / "metadata.json"
    metadata_payload = {
        "id": video["id"],
        "title": video["title"],
        "display_title": display_title,
        "url": video["url"],
        "channel_name": video.get("channel_name"),
        "upload_date": video.get("upload_date"),
        "duration": video.get("duration_string") or video.get("duration"),
        "playlist_added_text": video.get("playlist_added_text"),
        "playlist_added_date": video.get("playlist_added_date").isoformat()
        if isinstance(video.get("playlist_added_date"), date)
        else None,
        "transcript_source": transcript.source,
        "transcript_language": transcript.language,
        "summary_path": str(summary_path.relative_to(run_dir)) if summary_text else None,
        "transcript_path": str(transcript_path.relative_to(run_dir)),
        "processed_at": beijing_now().isoformat(),
        "processing_status": summary_status,
        "summary_error": summary_error,
        "summary_source": video.get("summary_source"),
        "summary_retry": video.get("summary_retry", {}),
        "processing_metrics": video.get("processing_metrics", {}),
        "transcription_details": transcript.details,
        "transcript_diagnostics": video.get("transcript_diagnostics", {}),
    }
    _write_json(metadata_path, metadata_payload)

    return {
        **video,
        "display_title": display_title,
        "summary_text": cleaned_summary_text,
        "summary_path": str(summary_path.relative_to(run_dir)) if summary_text else None,
        "transcript_path": str(transcript_path.relative_to(run_dir)),
        "metadata_path": str(metadata_path.relative_to(run_dir)),
        "transcript_source": transcript.source,
        "transcript_language": transcript.language,
        "processing_status": summary_status,
        "summary_error": summary_error,
        "summary_source": video.get("summary_source"),
        "summary_retry": video.get("summary_retry", {}),
        "processing_metrics": video.get("processing_metrics", {}),
        "transcription_details": transcript.details,
        "transcript_diagnostics": video.get("transcript_diagnostics", {}),
    }


def cleanup_media(paths: list[Path]) -> None:
    for path in paths:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)


def update_state(state: dict[str, Any], target_date: date, processed_videos: list[dict[str, Any]]) -> dict[str, Any]:
    state["last_run_at"] = beijing_now().isoformat()
    state["last_target_date"] = target_date.isoformat()
    video_state = state.setdefault("videos", {})
    for video in processed_videos:
        previous = video_state.get(video["id"], {})
        video_state[video["id"]] = {
            "title": video["title"],
            "last_status": video.get("processing_status") or "success",
            "last_processed_at": beijing_now().isoformat(),
            "last_target_date": target_date.isoformat(),
            "transcript_source": video.get("transcript_source"),
            "summary_path": video.get("summary_path"),
            "playlist_added_text": video.get("playlist_added_text"),
            "first_seen_at": previous.get("first_seen_at") or beijing_now().isoformat(),
            "first_seen_target_date": previous.get("first_seen_target_date") or target_date.isoformat(),
        }
    return state
