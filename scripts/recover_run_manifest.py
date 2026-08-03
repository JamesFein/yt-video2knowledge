#!/usr/bin/env python3
"""Rebuild a run manifest from existing per-video artifacts.

This is intentionally conservative: it does not download, transcribe, or call
LLMs. It only records files that are already present in data/runs/YYYY-MM-DD.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from knowledge_digest import (
    _build_manifest,
    _json_default,
    _write_json,
    load_config,
    parse_target_date,
)


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
        raise SystemExit(f"Missing videos directory: {videos_dir}")

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


def main() -> int:
    parser = argparse.ArgumentParser(description="Recover a knowledge digest manifest from existing artifacts.")
    parser.add_argument("--target-date", required=True, help="Target date in YYYY-MM-DD.")
    args = parser.parse_args()
    manifest = recover_run(args.target_date)

    import json

    print(json.dumps(manifest, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
