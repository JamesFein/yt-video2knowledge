"""Orchestrate a Digest Run through the domain modules."""
from __future__ import annotations

import time
from datetime import date
from pathlib import Path
from typing import Any

from yt_video2knowledge.digest.artifacts import (
    _duration_seconds,
    cleanup_media,
    update_state,
    write_video_outputs,
)
from yt_video2knowledge.digest.config import (
    DigestConfig,
    _read_json,
    _write_json,
    beijing_now,
    ensure_output_dirs,
    load_config,
    load_state,
    save_state,
)
from yt_video2knowledge.digest.errors import DigestError
from yt_video2knowledge.digest.manifest import (
    _build_manifest,
    _default_incremental_stats,
    _manifest_has_pending_summaries,
    load_run_manifest,
    merge_run_results,
    plan_run_entries,
)
from yt_video2knowledge.digest.playlist import (
    bootstrap_managed_chrome_login,
    bootstrap_youtube_auth,
    fetch_playlist_entries,
    seed_automation_profile_from_current,
    select_entries_for_processing,
)
from yt_video2knowledge.digest.summary import (
    SUMMARY_INLINE_ATTEMPTS,
    SUMMARY_MAX_ATTEMPTS,
    _append_summary_retry_history,
    is_transient_network_error,
    resolve_openai_settings,
    summarize_transcript_with_retries,
)
from yt_video2knowledge.digest.transcript import (
    TranscriptResult,
    download_audio,
    download_thumbnail,
    download_transcript,
    fetch_video_info,
    transcribe_audio,
)
from yt_video2knowledge.paths import PLAYWRIGHT_TMP_DIR

def retry_pending_summaries(
    config: DigestConfig,
    target_date: date,
    video_id: str | None = None,
    *,
    force_summary_retry: bool = False,
    regenerate_all: bool = False,
) -> dict[str, Any]:
    run_dir = config.output_root_path / target_date.isoformat()
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        raise DigestError(f"No existing run manifest found for {target_date.isoformat()}: {manifest_path}")

    settings = resolve_openai_settings(config)
    manifest = _read_json(manifest_path, {})
    processed_videos = manifest.get("processed_videos", [])
    failed_videos = manifest.get("failed_videos", [])
    needs_review = manifest.get("needs_review_videos", [])

    selected_ids = {video_id} if video_id else None
    updated_processed: list[dict[str, Any]] = []
    retried_count = 0
    regenerated_success_count = 0
    regeneration_failed_count = 0
    for video in processed_videos:
        should_retry = regenerate_all or video.get("processing_status") != "summary_ready"
        if selected_ids is not None:
            should_retry = should_retry and video.get("id") in selected_ids
        if not should_retry:
            updated_processed.append(video)
            continue

        transcript_path = run_dir / str(video.get("transcript_path") or "")
        if not transcript_path.exists():
            if regenerate_all:
                regeneration_failed_count += 1
                updated_processed.append(
                    {
                        **video,
                        "summary_regeneration_error": f"Missing transcript file: {transcript_path}",
                    }
                )
                continue
            updated_processed.append(
                {
                    **video,
                    "processing_status": "pending_summary",
                    "summary_error": f"Missing transcript file: {transcript_path}",
                }
            )
            continue

        transcript = TranscriptResult(
            text=transcript_path.read_text(encoding="utf-8"),
            language=video.get("transcript_language", "unknown"),
            source=video.get("transcript_source", "unknown"),
            segments=[],
            details=video.get("transcription_details", {}),
        )
        merged = dict(video)
        processing_metrics = dict(merged.get("processing_metrics", {}))
        processing_metrics.setdefault("summary_seconds", 0.0)
        merged["processing_metrics"] = processing_metrics

        previous_attempt_count = int((merged.get("summary_retry") or {}).get("attempt_count") or 0)
        summary_started = time.monotonic()
        summary_text, summary_retry = summarize_transcript_with_retries(
            transcript.text,
            merged["title"],
            settings,
            config.playlist_name,
            existing_retry=merged.get("summary_retry") or {},
            max_attempts=SUMMARY_MAX_ATTEMPTS,
            run_attempt_limit=SUMMARY_INLINE_ATTEMPTS if regenerate_all else 1,
            force_retry=force_summary_retry or regenerate_all,
            force_retry_attempts=SUMMARY_INLINE_ATTEMPTS if regenerate_all else 1,
        )
        merged["processing_metrics"]["summary_seconds"] = _duration_seconds(summary_started)
        merged["summary_retry"] = summary_retry
        if int(summary_retry.get("attempt_count") or 0) > previous_attempt_count:
            retried_count += 1
        if summary_text is not None:
            merged.pop("summary_regeneration_error", None)
            if regenerate_all:
                regenerated_success_count += 1
            updated_processed.append(
                write_video_outputs(
                    run_dir,
                    merged,
                    transcript,
                    summary_text,
                    summary_status="summary_ready",
                    summary_error=None,
                )
            )
        elif regenerate_all:
            regeneration_failed_count += 1
            updated_processed.append(
                {
                    **video,
                    "summary_retry": summary_retry,
                    "summary_regeneration_error": summary_retry.get("last_error")
                    or summary_retry.get("stopped_reason"),
                }
            )
        else:
            updated_processed.append(
                write_video_outputs(
                    run_dir,
                    merged,
                    transcript,
                    None,
                    summary_status="pending_summary",
                    summary_error=summary_retry.get("last_error") or summary_retry.get("stopped_reason"),
                )
            )

    manifest = _build_manifest(
        target_date,
        config,
        manifest.get("browser_mode", "managed"),
        updated_processed,
        failed_videos,
        needs_review,
        run_mode=manifest.get("run_mode", "full"),
        incremental_stats=manifest.get("incremental_stats"),
    )
    _write_json(manifest_path, manifest)
    save_state(update_state(load_state(), target_date, updated_processed))
    manifest["retried_summary_count"] = retried_count
    if regenerate_all:
        manifest["regenerated_summary_count"] = regenerated_success_count
        manifest["regeneration_failed_count"] = regeneration_failed_count
    _write_json(manifest_path, manifest)
    return manifest


def adopt_summary_for_video(
    config: DigestConfig,
    target_date: date,
    video_id: str,
    summary_file: Path,
) -> dict[str, Any]:
    run_dir = config.output_root_path / target_date.isoformat()
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        raise DigestError(f"No existing run manifest found for {target_date.isoformat()}: {manifest_path}")
    if not summary_file.exists():
        raise DigestError(f"Manual summary file does not exist: {summary_file}")

    manual_summary = summary_file.read_text(encoding="utf-8").strip()
    if not manual_summary:
        raise DigestError(f"Manual summary file is empty: {summary_file}")

    manifest = _read_json(manifest_path, {})
    processed_videos = manifest.get("processed_videos", [])
    failed_videos = manifest.get("failed_videos", [])
    needs_review = manifest.get("needs_review_videos", [])

    updated_processed: list[dict[str, Any]] = []
    adopted = False
    for video in processed_videos:
        if video.get("id") != video_id:
            updated_processed.append(video)
            continue

        transcript_path = run_dir / str(video.get("transcript_path") or "")
        if not transcript_path.exists():
            raise DigestError(f"Missing transcript file for {video_id}: {transcript_path}")

        retry_state = dict(video.get("summary_retry") or {})
        if retry_state:
            retry_state = _append_summary_retry_history(retry_state)
        retry_state.update(
            {
                "manual_adopted_at": beijing_now().isoformat(),
                "last_error": None,
                "stopped_reason": None,
                "next_step": None,
            }
        )
        retry_state.pop("next_retry_after", None)

        transcript = TranscriptResult(
            text=transcript_path.read_text(encoding="utf-8"),
            language=video.get("transcript_language", "unknown"),
            source=video.get("transcript_source", "unknown"),
            segments=[],
            details=video.get("transcription_details", {}),
        )
        merged = {
            **video,
            "summary_source": "manual",
            "summary_retry": retry_state,
        }
        updated_processed.append(
            write_video_outputs(
                run_dir,
                merged,
                transcript,
                manual_summary,
                summary_status="summary_ready",
                summary_error=None,
                prebuilt_summary_markdown=True,
            )
        )
        adopted = True

    if not adopted:
        raise DigestError(f"Video {video_id} was not found in manifest for {target_date.isoformat()}")

    manifest = _build_manifest(
        target_date,
        config,
        manifest.get("browser_mode", "managed"),
        updated_processed,
        failed_videos,
        needs_review,
        run_mode=manifest.get("run_mode", "full"),
        incremental_stats=manifest.get("incremental_stats"),
    )
    manifest["adopted_summary_count"] = 1
    _write_json(manifest_path, manifest)

    save_state(update_state(load_state(), target_date, updated_processed))
    _write_json(manifest_path, manifest)
    return manifest


def run_knowledge_digest(
    target_date: date,
    playlist_url: str | None = None,
    youtube_auth: bool = False,
    seed_from_current_profile: bool = False,
    bootstrap_login: bool = False,
    attach_current_chrome: bool = False,
    retry_summaries: bool = False,
    regenerate_summaries: bool = False,
    allow_fallback_first_seen: bool = False,
    full_reprocess: bool = False,
    video_id: str | None = None,
    force_summary_retry: bool = False,
    adopt_summary_file: Path | None = None,
) -> dict[str, Any]:
    config = load_config(playlist_url=playlist_url)
    ensure_output_dirs(config)
    if youtube_auth:
        return bootstrap_youtube_auth(config)
    if seed_from_current_profile:
        return seed_automation_profile_from_current(config)
    if bootstrap_login:
        return bootstrap_managed_chrome_login(config)
    if adopt_summary_file is not None:
        if not video_id:
            raise DigestError("--adopt-summary-file requires --video-id.")
        return adopt_summary_for_video(config, target_date, video_id, adopt_summary_file)
    if retry_summaries:
        return retry_pending_summaries(
            config,
            target_date,
            video_id=video_id,
            force_summary_retry=force_summary_retry,
        )
    if regenerate_summaries:
        return retry_pending_summaries(
            config,
            target_date,
            video_id=video_id,
            force_summary_retry=True,
            regenerate_all=True,
        )

    run_dir = config.output_root_path / target_date.isoformat()
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "videos").mkdir(parents=True, exist_ok=True)
    settings = resolve_openai_settings(config)
    state = load_state()
    existing_manifest = load_run_manifest(run_dir)

    browser_mode = "managed"
    yt_dlp_cookies_path: Path | None = None
    delete_yt_dlp_cookies = False
    run_mode = "full"
    incremental_stats = _default_incremental_stats()

    try:
        if video_id:
            existing_cookie_file = PLAYWRIGHT_TMP_DIR / "yt-dlp-cookies.txt"
            if existing_cookie_file.exists() and existing_cookie_file.stat().st_size > 0:
                browser_mode = "existing-cookies"
                yt_dlp_cookies_path = existing_cookie_file
            else:
                fetch_result = fetch_playlist_entries(config, attach_current_chrome=attach_current_chrome, interactive_login=False)
                browser_mode = fetch_result.browser_mode
                yt_dlp_cookies_path = fetch_result.cookie_file
                delete_yt_dlp_cookies = yt_dlp_cookies_path is not None
            entries = [{"id": video_id, "url": f"https://www.youtube.com/watch?v={video_id}", "title": video_id}]
            needs_review: list[dict[str, Any]] = []
            incremental_stats = _default_incremental_stats(selected_count=1, to_process_count=1)
        else:
            try:
                fetch_result = fetch_playlist_entries(config, attach_current_chrome=attach_current_chrome, interactive_login=False)
            except DigestError as exc:
                if (
                    not full_reprocess
                    and is_transient_network_error(exc)
                    and _manifest_has_pending_summaries(existing_manifest)
                ):
                    return retry_pending_summaries(
                        config,
                        target_date,
                        force_summary_retry=force_summary_retry,
                    )
                raise
            browser_mode = fetch_result.browser_mode
            yt_dlp_cookies_path = fetch_result.cookie_file
            delete_yt_dlp_cookies = yt_dlp_cookies_path is not None
            selected_entries, needs_review = select_entries_for_processing(
                fetch_result.entries,
                target_date,
                state,
                allow_fallback_first_seen=allow_fallback_first_seen,
            )
            run_mode, entries, incremental_stats = plan_run_entries(
                selected_entries,
                existing_manifest,
                full_reprocess=full_reprocess,
            )

        processed_videos: list[dict[str, Any]] = []
        failed_videos: list[dict[str, Any]] = []

        for entry in entries:
            temp_paths: list[Path] = []
            try:
                info_started = time.monotonic()
                info = fetch_video_info(entry["id"], browser=config.browser, cookies_path=yt_dlp_cookies_path)
                info_fetch_seconds = _duration_seconds(info_started)
                merged = {
                    **entry,
                    "title": info.get("title") or entry.get("title") or entry["id"],
                    "channel_name": info.get("channel") or entry.get("channel_name", ""),
                    "upload_date": info.get("upload_date"),
                    "duration_string": info.get("duration_string"),
                    "duration": info.get("duration"),
                    "url": f"https://www.youtube.com/watch?v={entry['id']}",
                }

                video_dir = run_dir / "videos" / entry["id"]
                video_dir.mkdir(parents=True, exist_ok=True)
                download_thumbnail(entry["id"], video_dir, browser=config.browser, cookies_path=yt_dlp_cookies_path)

                subtitle_started = time.monotonic()
                transcript, transcript_diagnostics = download_transcript(
                    entry["id"],
                    video_dir,
                    browser=config.browser,
                    cookies_path=yt_dlp_cookies_path,
                )
                subtitle_fetch_seconds = _duration_seconds(subtitle_started)
                audio_download_seconds = 0.0
                transcription_seconds = 0.0
                if transcript is None:
                    audio_started = time.monotonic()
                    source_audio = download_audio(
                        entry["id"],
                        video_dir,
                        browser=config.browser,
                        cookies_path=yt_dlp_cookies_path,
                    )
                    audio_download_seconds = _duration_seconds(audio_started)
                    temp_paths.append(source_audio)

                    transcription_started = time.monotonic()
                    transcript = transcribe_audio(source_audio, config.mlx_whisper_model)
                    transcription_seconds = _duration_seconds(transcription_started)
                    if transcript.details.get("used_wav_fallback"):
                        temp_paths.append(source_audio.with_suffix(".wav"))
                    transcript_diagnostics["fallback_reason"] = transcript_diagnostics.get("fallback_reason") or "subtitle_unavailable"
                transcript.details = {
                    **transcript.details,
                    "subtitle_attempts": transcript_diagnostics.get("attempts", []),
                }
                merged["transcript_source"] = transcript.source
                merged["transcript_diagnostics"] = transcript_diagnostics
                merged["processing_metrics"] = {
                    "info_fetch_seconds": info_fetch_seconds,
                    "subtitle_fetch_seconds": subtitle_fetch_seconds,
                    "audio_download_seconds": audio_download_seconds,
                    "transcription_seconds": transcription_seconds,
                    "summary_seconds": 0.0,
                }

                summary_started = time.monotonic()
                summary_text, summary_retry = summarize_transcript_with_retries(
                    transcript.text,
                    merged["title"],
                    settings,
                    config.playlist_name,
                    existing_retry=merged.get("summary_retry") or {},
                    max_attempts=SUMMARY_MAX_ATTEMPTS,
                    run_attempt_limit=SUMMARY_INLINE_ATTEMPTS,
                )
                merged["processing_metrics"]["summary_seconds"] = _duration_seconds(summary_started)
                merged["summary_retry"] = summary_retry
                if summary_text is not None:
                    processed_videos.append(
                        write_video_outputs(
                            run_dir,
                            merged,
                            transcript,
                            summary_text,
                            summary_status="summary_ready",
                            summary_error=None,
                        )
                    )
                else:
                    processed_videos.append(
                        write_video_outputs(
                            run_dir,
                            merged,
                            transcript,
                            None,
                            summary_status="pending_summary",
                            summary_error=summary_retry.get("last_error") or summary_retry.get("stopped_reason"),
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                failed_videos.append(
                    {
                        "id": entry["id"],
                        "title": entry.get("title", entry["id"]),
                        "url": entry.get("url"),
                        "failure_stage": "transcript_failed",
                        "error": str(exc),
                    }
                )
            finally:
                cleanup_media(temp_paths)

        merged_processed_videos, merged_failed_videos = merge_run_results(
            existing_manifest,
            processed_videos,
            failed_videos,
        )
        manifest = _build_manifest(
            target_date,
            config,
            browser_mode,
            merged_processed_videos,
            merged_failed_videos,
            needs_review,
            run_mode=run_mode,
            incremental_stats=incremental_stats,
        )
        _write_json(run_dir / "manifest.json", manifest)

        save_state(update_state(state, target_date, processed_videos))
        if not video_id and int(manifest.get("pending_summary_count") or 0) > 0:
            manifest = retry_pending_summaries(config, target_date)
        return manifest
    finally:
        if delete_yt_dlp_cookies and yt_dlp_cookies_path is not None:
            yt_dlp_cookies_path.unlink(missing_ok=True)
