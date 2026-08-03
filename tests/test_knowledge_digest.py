from __future__ import annotations

import sys
import tempfile
import unittest
import json
import os
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import run_knowledge_digest as cli_module
import knowledge_digest as knowledge_digest_module
import recover_run_manifest as recover_module
from generate_report import generate_markdown
from knowledge_digest import (
    BEIJING_TZ,
    TranscriptResult,
    _extract_display_title,
    _normalize_playlist_payload,
    _write_json,
    adopt_summary_for_video,
    extract_playlist_id,
    filter_entries_for_date,
    load_config,
    merge_run_results,
    is_manifest_complete,
    manifest_completion_status,
    normalize_playlist_url,
    parse_added_date_text,
    parse_target_date,
    parse_vtt,
    plan_run_entries,
    retry_pending_summaries,
    select_entries_for_processing,
    summarize_transcript_with_retries,
    write_video_outputs,
)


def make_test_config(output_root: str) -> knowledge_digest_module.DigestConfig:
    return knowledge_digest_module.DigestConfig(
        playlist_url="https://www.youtube.com/playlist?list=PL123",
        playlist_name="knowledge",
        timezone="Asia/Shanghai",
        browser="chrome",
        browser_mode="managed",
        chrome_channel="chrome",
        chrome_user_data_dir="data/chrome-automation-profile",
        chrome_source_profile_dir="/tmp/chrome",
        chrome_automation_profile_dir="data/chrome-automation-profile",
        chrome_cdp_url="http://127.0.0.1:9222",
        youtube_client_secrets_path="data/youtube-oauth-client.json",
        youtube_token_path="data/youtube-oauth-token.json",
        openai_base_url="",
        openai_model="",
        summary_language="zh-CN",
        mlx_whisper_model="mlx-community/whisper-small-mlx",
        output_root=output_root,
    )


class ParseAddedDateTextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.reference = datetime(2026, 3, 21, 10, 0, tzinfo=BEIJING_TZ)

    def test_parses_yesterday_in_chinese(self) -> None:
        self.assertEqual(parse_added_date_text("昨天添加到播放列表", self.reference), date(2026, 3, 20))

    def test_parses_relative_english_date(self) -> None:
        self.assertEqual(parse_added_date_text("Added 2 days ago", self.reference), date(2026, 3, 19))

    def test_parses_absolute_chinese_date(self) -> None:
        self.assertEqual(parse_added_date_text("添加于 2026年3月18日", self.reference), date(2026, 3, 18))


class ParseVttTests(unittest.TestCase):
    def test_parse_vtt_extracts_timestamps_and_text(self) -> None:
        sample = """WEBVTT

00:00:00.000 --> 00:00:03.000
Hello world

00:00:03.000 --> 00:00:06.000
<c.colorE5E5E5>This is a test</c>
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sample.vtt"
            path.write_text(sample, encoding="utf-8")
            parsed = parse_vtt(path)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]["text"], "Hello world")
        self.assertEqual(parsed[1]["text"], "This is a test")


class FilterEntriesTests(unittest.TestCase):
    def test_filter_entries_routes_unknown_dates_to_needs_review(self) -> None:
        matched, needs_review = filter_entries_for_date(
            [
                {"id": "a", "playlist_added_date": date(2026, 3, 20)},
                {"id": "b", "playlist_added_date": None},
            ],
            date(2026, 3, 20),
        )
        self.assertEqual([item["id"] for item in matched], ["a"])
        self.assertEqual([item["id"] for item in needs_review], ["b"])


class ConfigTests(unittest.TestCase):
    def test_load_config_sets_managed_browser_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "knowledge_config.json"
            path.write_text(json_text({
                "playlist_url": "https://www.youtube.com/watch?v=aaa&list=bbb",
                "playlist_name": "knowledge"
            }), encoding="utf-8")
            config = load_config(path)
        self.assertEqual(config.playlist_url, "https://www.youtube.com/playlist?list=bbb")
        self.assertEqual(config.browser_mode, "managed")
        self.assertEqual(config.chrome_channel, "chrome")
        self.assertTrue(config.chrome_source_profile_dir.endswith("Library/Application Support/Google/Chrome"))
        self.assertEqual(config.chrome_automation_profile_dir, "data/chrome-automation-profile")
        self.assertEqual(config.chrome_cdp_url, "http://127.0.0.1:9222")
        self.assertEqual(config.youtube_client_secrets_path, "data/youtube-oauth-client.json")
        self.assertEqual(config.youtube_token_path, "data/youtube-oauth-token.json")
        self.assertEqual(config.mlx_whisper_model, "mlx-community/whisper-small-mlx")


class PlaylistUrlTests(unittest.TestCase):
    def test_normalize_playlist_url_prefers_playlist_page(self) -> None:
        self.assertEqual(
            normalize_playlist_url("https://www.youtube.com/watch?v=aaa&list=PL123&index=4"),
            "https://www.youtube.com/playlist?list=PL123",
        )

    def test_extract_playlist_id(self) -> None:
        self.assertEqual(
            extract_playlist_id("https://www.youtube.com/watch?v=aaa&list=PL123&index=4"),
            "PL123",
        )


class PlaylistPayloadTests(unittest.TestCase):
    def test_normalize_playlist_payload_extracts_video_and_added_date(self) -> None:
        payload = [
            {
                "title": "  Test Video  ",
                "href": "/watch?v=abc123xyz89&list=PL123",
                "channel_name": " Demo Channel ",
                "duration": " 10:00 ",
                "raw_text_fragments": ["昨天添加到播放列表", "其他信息"],
            }
        ]
        reference = datetime(2026, 3, 21, 10, 0, tzinfo=BEIJING_TZ)
        with mock.patch.object(knowledge_digest_module, "beijing_now", return_value=reference):
            normalized = _normalize_playlist_payload(payload)
        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0]["id"], "abc123xyz89")
        self.assertEqual(normalized[0]["channel_name"], "Demo Channel")
        self.assertEqual(normalized[0]["playlist_added_date"], date(2026, 3, 20))


class ProcessingSelectionTests(unittest.TestCase):
    def test_select_entries_is_strict_by_default(self) -> None:
        target_date = parse_target_date(None)
        matched, needs_review = select_entries_for_processing(
            [{"id": "abc123xyz89", "title": "Video", "playlist_added_date": None}],
            target_date,
            {"videos": {}},
        )
        self.assertEqual(len(matched), 0)
        self.assertEqual(len(needs_review), 1)

    def test_select_entries_can_use_first_seen_fallback_when_enabled(self) -> None:
        target_date = parse_target_date(None)
        matched, needs_review = select_entries_for_processing(
            [{"id": "abc123xyz89", "title": "Video", "playlist_added_date": None}],
            target_date,
            {"videos": {}},
            allow_fallback_first_seen=True,
        )
        self.assertEqual(len(matched), 1)
        self.assertEqual(len(needs_review), 0)
        self.assertEqual(matched[0]["playlist_added_date"], target_date)

    def test_plan_run_entries_skips_existing_summary_ready(self) -> None:
        run_mode, to_process, stats = plan_run_entries(
            [
                {"id": "ready", "title": "Ready"},
                {"id": "pending", "title": "Pending"},
                {"id": "failed", "title": "Failed"},
                {"id": "new", "title": "New"},
            ],
            {
                "processed_videos": [
                    {"id": "ready", "processing_status": "summary_ready"},
                    {"id": "pending", "processing_status": "pending_summary"},
                ],
                "failed_videos": [
                    {"id": "failed", "error": "boom"},
                ],
            },
        )
        self.assertEqual(run_mode, "incremental")
        self.assertEqual([item["id"] for item in to_process], ["pending", "failed", "new"])
        self.assertEqual(
            stats,
            {
                "selected_count": 4,
                "to_process_count": 3,
                "new_video_count": 1,
                "retried_non_success_count": 2,
                "skipped_summary_ready_count": 1,
            },
        )

    def test_plan_run_entries_can_force_full_reprocess(self) -> None:
        run_mode, to_process, stats = plan_run_entries(
            [{"id": "ready", "title": "Ready"}],
            {"processed_videos": [{"id": "ready", "processing_status": "summary_ready"}]},
            full_reprocess=True,
        )
        self.assertEqual(run_mode, "full")
        self.assertEqual([item["id"] for item in to_process], ["ready"])
        self.assertEqual(stats["selected_count"], 1)
        self.assertEqual(stats["to_process_count"], 1)
        self.assertEqual(stats["skipped_summary_ready_count"], 0)


class MergeRunResultsTests(unittest.TestCase):
    def test_merge_run_results_preserves_old_success_and_replaces_updated_entries(self) -> None:
        merged_processed, merged_failed = merge_run_results(
            {
                "processed_videos": [
                    {"id": "kept", "processing_status": "summary_ready", "title": "Kept"},
                    {"id": "retry-success", "processing_status": "pending_summary", "title": "Retry success old"},
                    {"id": "stale-pending", "processing_status": "pending_summary", "title": "Stale pending"},
                ],
                "failed_videos": [
                    {"id": "retry-fail", "title": "Retry fail old", "error": "old"},
                    {"id": "becomes-success", "title": "Becomes success old", "error": "old"},
                ],
            },
            [
                {"id": "retry-success", "processing_status": "summary_ready", "title": "Retry success new"},
                {"id": "becomes-success", "processing_status": "summary_ready", "title": "Becomes success new"},
                {"id": "new", "processing_status": "pending_summary", "title": "New pending"},
            ],
            [
                {"id": "retry-fail", "title": "Retry fail new", "error": "new"},
                {"id": "new-fail", "title": "New fail", "error": "new"},
            ],
        )
        self.assertEqual(
            [item["id"] for item in merged_processed],
            ["kept", "retry-success", "stale-pending", "becomes-success", "new"],
        )
        self.assertEqual(
            [item["processing_status"] for item in merged_processed if item["id"] == "retry-success"],
            ["summary_ready"],
        )
        self.assertEqual(
            [item["id"] for item in merged_failed],
            ["retry-fail", "new-fail"],
        )
        self.assertNotIn("becomes-success", [item["id"] for item in merged_failed])


class DisplayTitleTests(unittest.TestCase):
    def test_extract_display_title_removes_marker_from_summary(self) -> None:
        display_title, summary = _extract_display_title(
            "中文标题：AI 评测中的提示污染\n\n## 一句话总结\n\n模型评测被提示污染影响。",
            "The Miranda Hypothesis",
        )

        self.assertEqual(display_title, "AI 评测中的提示污染")
        self.assertEqual(summary, "## 一句话总结\n\n模型评测被提示污染影响。")

    def test_extract_display_title_falls_back_without_marker(self) -> None:
        display_title, summary = _extract_display_title(
            "## 一句话总结\n\n模型评测被提示污染影响。",
            "The Miranda Hypothesis",
        )

        self.assertEqual(display_title, "The Miranda Hypothesis")
        self.assertEqual(summary, "## 一句话总结\n\n模型评测被提示污染影响。")

    def test_write_video_outputs_uses_display_title_for_summary_heading(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            video = {
                "id": "abc123",
                "title": "The Miranda Hypothesis",
                "url": "https://www.youtube.com/watch?v=abc123",
                "channel_name": "Results Gen",
                "upload_date": "20260601",
                "duration_string": "10:00",
            }
            transcript = TranscriptResult(
                text="Transcript",
                language="en",
                source="official",
                segments=[],
            )

            result = write_video_outputs(
                run_dir,
                video,
                transcript,
                "中文标题：AI 评测中的提示污染\n\n## 一句话总结\n\n模型评测被提示污染影响。",
                summary_status="summary_ready",
            )

            summary_path = run_dir / "videos" / "abc123" / "summary.zh-CN.md"
            metadata_path = run_dir / "videos" / "abc123" / "metadata.json"
            summary_markdown = summary_path.read_text(encoding="utf-8")
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

            self.assertTrue(summary_markdown.startswith("# AI 评测中的提示污染\n\n"))
            self.assertNotIn("中文标题：", summary_markdown)
            self.assertEqual(metadata["title"], "The Miranda Hypothesis")
            self.assertEqual(metadata["display_title"], "AI 评测中的提示污染")
            self.assertEqual(result["title"], "The Miranda Hypothesis")
            self.assertEqual(result["display_title"], "AI 评测中的提示污染")
            self.assertEqual(result["summary_text"], "## 一句话总结\n\n模型评测被提示污染影响。")

    def test_pending_summary_does_not_leave_markdown_for_the_frontend(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            video = {
                "id": "pending",
                "title": "Pending",
                "url": "https://www.youtube.com/watch?v=pending",
                "channel_name": "Channel",
            }
            transcript = TranscriptResult(text="Transcript", language="en", source="official", segments=[])

            result = write_video_outputs(
                run_dir,
                video,
                transcript,
                None,
                summary_status="pending_summary",
                summary_error="incomplete_response",
            )

            video_dir = run_dir / "videos" / "pending"
            self.assertFalse((video_dir / "summary.zh-CN.md").exists())
            self.assertFalse((video_dir / "report.md").exists())
            self.assertEqual(result["processing_status"], "pending_summary")


class SummaryRetryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 6, 10, 12, 0, tzinfo=BEIJING_TZ)

    def test_transient_summary_error_retries_and_clears_error_on_success(self) -> None:
        calls = []
        sleeps = []

        def fake_summary(transcript_text: str, video_title: str, settings: dict, playlist_name: str) -> str:
            calls.append(video_title)
            if len(calls) < 3:
                raise knowledge_digest_module.DigestError("OpenAI Responses API returned an empty response")
            return "final summary"

        summary, retry_state = summarize_transcript_with_retries(
            "transcript",
            "Video",
            {},
            "Knowledge",
            clock=lambda: self.now,
            sleep_fn=sleeps.append,
            summarize_fn=fake_summary,
        )

        self.assertEqual(summary, "final summary")
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleeps, [30, 120])
        self.assertEqual(retry_state["attempt_count"], 3)
        self.assertIsNone(retry_state["last_error"])

    def test_transient_summary_error_stops_at_max_attempts(self) -> None:
        calls = []
        sleeps = []

        def fake_summary(transcript_text: str, video_title: str, settings: dict, playlist_name: str) -> str:
            calls.append(video_title)
            raise knowledge_digest_module.DigestError("IncompleteRead during summary")

        summary, retry_state = summarize_transcript_with_retries(
            "transcript",
            "Video",
            {},
            "Knowledge",
            max_attempts=3,
            run_attempt_limit=3,
            clock=lambda: self.now,
            sleep_fn=sleeps.append,
            summarize_fn=fake_summary,
        )

        self.assertIsNone(summary)
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleeps, [30, 120])
        self.assertEqual(retry_state["attempt_count"], 3)
        self.assertEqual(retry_state["stopped_reason"], "max_attempts")
        self.assertEqual(retry_state["next_step"], "manual_review")
        self.assertEqual(retry_state["last_error"], "IncompleteRead during summary")

    def test_non_retryable_summary_error_stops_immediately(self) -> None:
        calls = []
        sleeps = []

        def fake_summary(transcript_text: str, video_title: str, settings: dict, playlist_name: str) -> str:
            calls.append(video_title)
            raise knowledge_digest_module.ConfigurationError("Missing runtime configuration: OPENAI_API_KEY")

        summary, retry_state = summarize_transcript_with_retries(
            "transcript",
            "Video",
            {},
            "Knowledge",
            clock=lambda: self.now,
            sleep_fn=sleeps.append,
            summarize_fn=fake_summary,
        )

        self.assertIsNone(summary)
        self.assertEqual(len(calls), 1)
        self.assertEqual(sleeps, [])
        self.assertEqual(retry_state["stopped_reason"], "non_retryable_error")
        self.assertEqual(retry_state["next_step"], "manual_review")

    def test_retry_window_stops_without_calling_summary(self) -> None:
        calls = []
        existing_retry = {
            "attempt_count": 1,
            "first_failed_at": (self.now - timedelta(hours=25)).isoformat(),
            "last_error": "temporary failure",
        }

        def fake_summary(transcript_text: str, video_title: str, settings: dict, playlist_name: str) -> str:
            calls.append(video_title)
            return "should not run"

        summary, retry_state = summarize_transcript_with_retries(
            "transcript",
            "Video",
            {},
            "Knowledge",
            existing_retry=existing_retry,
            clock=lambda: self.now,
            sleep_fn=lambda seconds: None,
            summarize_fn=fake_summary,
        )

        self.assertIsNone(summary)
        self.assertEqual(calls, [])
        self.assertEqual(retry_state["stopped_reason"], "retry_window_exceeded")
        self.assertEqual(retry_state["next_step"], "manual_review")

    def test_existing_max_attempts_stops_without_calling_summary(self) -> None:
        calls = []
        existing_retry = {
            "attempt_count": 3,
            "last_error": "SSL EOF",
            "stopped_reason": "max_attempts",
            "next_step": "manual_review",
        }

        def fake_summary(transcript_text: str, video_title: str, settings: dict, playlist_name: str) -> str:
            calls.append(video_title)
            return "should not run"

        summary, retry_state = summarize_transcript_with_retries(
            "transcript",
            "Video",
            {},
            "Knowledge",
            existing_retry=existing_retry,
            max_attempts=3,
            run_attempt_limit=1,
            clock=lambda: self.now,
            sleep_fn=lambda seconds: None,
            summarize_fn=fake_summary,
        )

        self.assertIsNone(summary)
        self.assertEqual(calls, [])
        self.assertEqual(retry_state["stopped_reason"], "max_attempts")

    def test_force_retry_bypasses_max_attempts_once_and_preserves_history(self) -> None:
        calls = []
        existing_retry = {
            "attempt_count": 3,
            "last_error": "SSL EOF",
            "stopped_reason": "max_attempts",
            "next_step": "manual_review",
        }

        def fake_summary(transcript_text: str, video_title: str, settings: dict, playlist_name: str) -> str:
            calls.append(video_title)
            return "forced summary"

        summary, retry_state = summarize_transcript_with_retries(
            "transcript",
            "Video",
            {},
            "Knowledge",
            existing_retry=existing_retry,
            max_attempts=3,
            run_attempt_limit=1,
            force_retry=True,
            clock=lambda: self.now,
            sleep_fn=lambda seconds: None,
            summarize_fn=fake_summary,
        )

        self.assertEqual(summary, "forced summary")
        self.assertEqual(calls, ["Video"])
        self.assertEqual(retry_state["attempt_count"], 4)
        self.assertIsNone(retry_state["last_error"])
        self.assertEqual(retry_state["history"][0]["stopped_reason"], "max_attempts")

    def test_incomplete_response_uses_short_backoff_and_records_only_metadata(self) -> None:
        calls = []
        sleeps = []

        def fake_summary(transcript_text: str, video_title: str, settings: dict, playlist_name: str):
            calls.append(video_title)
            if len(calls) == 1:
                raise knowledge_digest_module.IncompleteModelResponseError(
                    "missing completion marker",
                    response_id="resp_partial",
                    provider="anthropic",
                    provider_status="completed",
                    stop_reason="end_turn",
                    output_chars=321,
                    validation_errors=["missing_or_misplaced_completion_marker"],
                )
            return knowledge_digest_module.GeneratedSummary(
                "中文标题：完成\n\n## 核心结论\n\n完整正文",
                knowledge_digest_module.ModelResponse(
                    text="raw response with marker",
                    provider="anthropic",
                    response_id="resp_complete",
                    provider_status="completed",
                    stop_reason="end_turn",
                ),
            )

        summary, retry_state = summarize_transcript_with_retries(
            "transcript",
            "Video",
            {},
            "Knowledge",
            clock=lambda: self.now,
            sleep_fn=sleeps.append,
            summarize_fn=fake_summary,
        )

        self.assertIn("完整正文", summary)
        self.assertEqual(sleeps, [2])
        self.assertEqual(retry_state["response_id"], "resp_complete")
        failed_attempt = retry_state["attempt_history"][0]
        self.assertEqual(failed_attempt["failure_kind"], "incomplete_response")
        self.assertEqual(failed_attempt["response_id"], "resp_partial")
        self.assertEqual(failed_attempt["output_chars"], 321)
        self.assertNotIn("raw", json.dumps(retry_state, ensure_ascii=False).lower())

    def test_three_incomplete_responses_stop_without_returning_a_partial(self) -> None:
        sleeps = []

        def fake_summary(transcript_text: str, video_title: str, settings: dict, playlist_name: str):
            raise knowledge_digest_module.IncompleteModelResponseError(
                "truncated",
                response_id="resp_partial",
                provider="openai",
                provider_status="incomplete",
                stop_reason="max_output_tokens",
                output_chars=500,
            )

        summary, retry_state = summarize_transcript_with_retries(
            "transcript",
            "Video",
            {},
            "Knowledge",
            clock=lambda: self.now,
            sleep_fn=sleeps.append,
            summarize_fn=fake_summary,
        )

        self.assertIsNone(summary)
        self.assertEqual(sleeps, [2, 5])
        self.assertEqual(retry_state["attempt_count"], 3)
        self.assertEqual(retry_state["stopped_reason"], "max_attempts")
        self.assertEqual(len(retry_state["attempt_history"]), 3)


class DownloadAudioTests(unittest.TestCase):
    def test_download_audio_success_does_not_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            calls = []

            def fake_run_command(cmd, timeout=120, cwd=None):
                calls.append(cmd)
                (output_dir / "source_audio.webm").write_text("audio", encoding="utf-8")
                return subprocess.CompletedProcess(cmd, 0)

            with mock.patch.object(knowledge_digest_module, "_run_command", side_effect=fake_run_command):
                result = knowledge_digest_module.download_audio("video123", output_dir, browser="chrome")

        self.assertEqual(result.name, "source_audio.webm")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][calls[0].index("-f") + 1], "bestaudio/best")

    def test_download_audio_reuses_existing_source_audio(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            existing = output_dir / "source_audio.webm"
            existing.write_text("audio", encoding="utf-8")

            with mock.patch.object(knowledge_digest_module, "_run_command") as run_command:
                result = knowledge_digest_module.download_audio("video123", output_dir, cookies_path=Path("cookies.txt"))

        self.assertEqual(result, existing)
        run_command.assert_not_called()

    def test_download_audio_uses_yt_dlp_bin_env_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            calls = []

            def fake_run_command(cmd, timeout=120, cwd=None):
                calls.append(cmd)
                (output_dir / "source_audio.webm").write_text("audio", encoding="utf-8")
                return subprocess.CompletedProcess(cmd, 0)

            with mock.patch.dict(os.environ, {"YT_DLP_BIN": "/tmp/custom-yt-dlp"}):
                with mock.patch.object(knowledge_digest_module, "_run_command", side_effect=fake_run_command):
                    knowledge_digest_module.download_audio("video123", output_dir, browser="chrome")

        self.assertEqual(calls[0][0], "/tmp/custom-yt-dlp")

    def test_download_audio_retries_transient_403_for_same_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            calls = []

            def fake_run_command(cmd, timeout=120, cwd=None):
                calls.append(cmd)
                if len(calls) == 1:
                    (output_dir / "source_audio.webm.part").write_text("partial", encoding="utf-8")
                    raise knowledge_digest_module.ExternalCommandError("ERROR: unable to download video data: HTTP Error 403: Forbidden")
                (output_dir / "source_audio.webm").write_text("audio", encoding="utf-8")
                return subprocess.CompletedProcess(cmd, 0)

            with mock.patch.object(knowledge_digest_module, "_run_command", side_effect=fake_run_command):
                result = knowledge_digest_module.download_audio("video123", output_dir, cookies_path=Path("cookies.txt"))

            self.assertFalse((output_dir / "source_audio.webm.part").exists())

        self.assertEqual(result.name, "source_audio.webm")
        self.assertEqual(len(calls), 2)

    def test_download_audio_retries_403_with_explicit_formats_and_cleans_partials(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            formats = []

            def fake_run_command(cmd, timeout=120, cwd=None):
                format_selector = cmd[cmd.index("-f") + 1]
                formats.append(format_selector)
                if len(formats) > 1:
                    self.assertFalse(list(output_dir.glob("*.part")))
                if format_selector in {"bestaudio/best", "251", "92", "93"}:
                    (output_dir / "source_audio.webm.part").write_text("partial", encoding="utf-8")
                    raise knowledge_digest_module.ExternalCommandError(
                        "ERROR: unable to download video data: HTTP Error 403: Forbidden"
                    )
                (output_dir / "source_audio.m4a").write_text("audio", encoding="utf-8")
                return subprocess.CompletedProcess(cmd, 0)

            with mock.patch.object(knowledge_digest_module, "_run_command", side_effect=fake_run_command):
                result = knowledge_digest_module.download_audio("video123", output_dir, browser="chrome")

        self.assertEqual(result.name, "source_audio.m4a")
        self.assertEqual(formats, ["bestaudio/best", "bestaudio/best", "251", "251", "140"])

    def test_download_audio_retries_not_a_bot_with_next_credential_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            cookies_path = output_dir / "cookies.txt"
            cookies_path.write_text("cookies", encoding="utf-8")
            calls = []

            def fake_run_command(cmd, timeout=120, cwd=None):
                calls.append(cmd)
                if "--cookies" in cmd:
                    raise knowledge_digest_module.ExternalCommandError(
                        "ERROR: [youtube] video123: Sign in to confirm you’re not a bot. Use --cookies-from-browser or --cookies for the authentication."
                    )
                (output_dir / "source_audio.webm").write_text("audio", encoding="utf-8")
                return subprocess.CompletedProcess(cmd, 0)

            with mock.patch.object(knowledge_digest_module, "_run_command", side_effect=fake_run_command):
                result = knowledge_digest_module.download_audio(
                    "video123",
                    output_dir,
                    browser="chrome",
                    cookies_path=cookies_path,
                )

        self.assertEqual(result.name, "source_audio.webm")
        self.assertIn("--cookies", calls[0])
        self.assertIn("--cookies-from-browser", calls[-1])

    def test_download_audio_reports_all_fallback_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            def fake_run_command(cmd, timeout=120, cwd=None):
                raise knowledge_digest_module.ExternalCommandError("HTTP Error 403: Forbidden")

            with mock.patch.object(knowledge_digest_module, "_run_command", side_effect=fake_run_command):
                with self.assertRaises(knowledge_digest_module.ExternalCommandError) as raised:
                    knowledge_digest_module.download_audio("video123", output_dir, browser="chrome")

        message = str(raised.exception)
        self.assertIn("Unable to download audio for video123", message)
        self.assertIn("bestaudio/best", message)
        self.assertIn("251", message)
        self.assertIn("140", message)
        self.assertIn("94", message)
        self.assertIn("250", message)
        self.assertIn("249", message)


class SummarizeTranscriptTests(unittest.TestCase):
    def test_single_chunk_prompt_omits_rewatch_and_returns_simplified_chinese(self) -> None:
        calls = []

        def fake_openai_request(messages, settings, max_tokens=1200):
            calls.append(messages)
            return knowledge_digest_module.ModelResponse(
                "中文標題：總結\n\n## 核心結論\n\n這個臺灣資料很重要。\n\n<!-- SUMMARY_COMPLETE -->",
                provider="anthropic",
                provider_status="missing",
            )

        with mock.patch.object(knowledge_digest_module, "_openai_request", side_effect=fake_openai_request):
            summary = knowledge_digest_module.summarize_transcript("transcript", "Video", {}, "Knowledge")

        self.assertEqual(summary.text, "中文标题：总结\n\n## 核心结论\n\n这个台湾资料很重要。")
        self.assertNotIn("SUMMARY_COMPLETE", summary.text)
        expected_prompt = (
            knowledge_digest_module.PROMPT_DIR / knowledge_digest_module.SUMMARY_ARTICLE_PROMPT_PATH
        ).read_text(encoding="utf-8").strip()
        self.assertEqual(calls[0][0]["content"], expected_prompt)
        prompt_text = "\n".join(message["content"] for message in calls[0])
        self.assertIn("简体中文", prompt_text)
        self.assertIn("具体代价", prompt_text)
        self.assertIn("人物背景", prompt_text)
        self.assertIn("全文通常 10–18 处", prompt_text)
        self.assertIn("中文标题：", prompt_text)
        self.assertNotIn("回看", prompt_text)
        self.assertNotIn("回看片段", prompt_text)
        self.assertNotIn("值得回看的时间点", prompt_text)

    def test_multi_chunk_summaries_and_final_output_are_simplified_chinese(self) -> None:
        calls = []
        responses = [
            "第一段總結：這個臺灣資料。\n<!-- EVIDENCE_COMPLETE -->",
            "第二段總結：關鍵啟發。\n<!-- EVIDENCE_COMPLETE -->",
            "中文標題：最終\n\n## 核心結論\n\n這個臺灣資料有關鍵啟發。\n<!-- SUMMARY_COMPLETE -->",
        ]

        def fake_openai_request(messages, settings, max_tokens=1200):
            calls.append(messages)
            return knowledge_digest_module.ModelResponse(
                responses[len(calls) - 1],
                provider="anthropic",
                provider_status="completed",
                stop_reason="end_turn",
            )

        with mock.patch.object(knowledge_digest_module, "_chunk_text", return_value=["chunk one", "chunk two"]):
            with mock.patch.object(knowledge_digest_module, "_openai_request", side_effect=fake_openai_request):
                summary = knowledge_digest_module.summarize_transcript("transcript", "Video", {}, "Knowledge")

        self.assertEqual(summary.text, "中文标题：最终\n\n## 核心结论\n\n这个台湾资料有关键启发。")
        expected_article_prompt = (
            knowledge_digest_module.PROMPT_DIR / knowledge_digest_module.SUMMARY_ARTICLE_PROMPT_PATH
        ).read_text(encoding="utf-8").strip()
        expected_evidence_prompt = (
            knowledge_digest_module.PROMPT_DIR / knowledge_digest_module.SUMMARY_EVIDENCE_PROMPT_PATH
        ).read_text(encoding="utf-8").strip()
        self.assertEqual(calls[0][0]["content"], expected_evidence_prompt)
        self.assertEqual(calls[1][0]["content"], expected_evidence_prompt)
        self.assertEqual(calls[2][0]["content"], expected_article_prompt)
        final_prompt = calls[2][1]["content"]
        all_prompts = "\n".join(message["content"] for messages in calls for message in messages)
        self.assertIn("第一段总结：这个台湾资料。", final_prompt)
        self.assertIn("第二段总结：关键启发。", final_prompt)
        self.assertIn("简体中文", all_prompts)
        self.assertNotIn("回看", all_prompts)

    def test_rejects_empty_level_two_heading(self) -> None:
        malformed = knowledge_digest_module.ModelResponse(
            "中文标题：测试\n\n## 核心结论\n\n内容\n\n##\n<!-- SUMMARY_COMPLETE -->",
            provider="anthropic",
            provider_status="completed",
            stop_reason="end_turn",
        )
        with mock.patch.object(knowledge_digest_module, "_openai_request", return_value=malformed):
            with self.assertRaisesRegex(knowledge_digest_module.InvalidSummaryArticleError, "empty_level_two_heading"):
                knowledge_digest_module.summarize_transcript("transcript", "Video", {}, "Knowledge")

    def test_rejects_completed_response_without_completion_marker(self) -> None:
        response = knowledge_digest_module.ModelResponse(
            "中文标题：测试\n\n## 核心结论\n\n内容",
            provider="anthropic",
            provider_status="completed",
            stop_reason="end_turn",
        )
        with mock.patch.object(knowledge_digest_module, "_openai_request", return_value=response):
            with self.assertRaises(knowledge_digest_module.IncompleteModelResponseError):
                knowledge_digest_module.summarize_transcript("transcript", "Video", {}, "Knowledge")

    def test_rejects_dangling_heading_and_unclosed_markdown(self) -> None:
        malformed_articles = [
            "中文标题：测试\n\n## 核心结论\n\n内容\n\n## 下一节",
            "中文标题：测试\n\n## 核心结论\n\n**未闭合",
            "中文标题：测试\n\n## 核心结论\n\n```python\nprint('x')",
        ]
        for article in malformed_articles:
            with self.subTest(article=article):
                response = knowledge_digest_module.ModelResponse(
                    article + "\n<!-- SUMMARY_COMPLETE -->",
                    provider="openai",
                    provider_status="missing",
                )
                with mock.patch.object(knowledge_digest_module, "_openai_request", return_value=response):
                    with self.assertRaises(knowledge_digest_module.InvalidSummaryArticleError):
                        knowledge_digest_module.summarize_transcript("transcript", "Video", {}, "Knowledge")

    def test_missing_or_empty_production_prompt_fails_before_model_request(self) -> None:
        for create_empty_file in (False, True):
            with self.subTest(create_empty_file=create_empty_file):
                with tempfile.TemporaryDirectory() as tmpdir:
                    prompt_dir = Path(tmpdir)
                    if create_empty_file:
                        prompt_path = prompt_dir / knowledge_digest_module.SUMMARY_ARTICLE_PROMPT_PATH
                        prompt_path.parent.mkdir(parents=True)
                        prompt_path.write_text("", encoding="utf-8")
                    with mock.patch.object(knowledge_digest_module, "PROMPT_DIR", prompt_dir):
                        with mock.patch.object(knowledge_digest_module, "_openai_request") as request:
                            with self.assertRaises(knowledge_digest_module.ConfigurationError):
                                knowledge_digest_module.summarize_transcript(
                                    "transcript", "Video", {}, "Knowledge"
                                )
                    request.assert_not_called()

class ModelApiRoutingTests(unittest.TestCase):
    def test_claude_model_uses_anthropic_messages_endpoint(self) -> None:
        settings = {
            "api_key": "secret",
            "base_url": "https://www.dmxapi.cn",
            "model": "claude-sonnet-5-cc",
        }
        response = {
            "id": "msg_123",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 2},
            "content": [{"type": "text", "text": "完成"}],
        }
        with mock.patch.object(knowledge_digest_module, "_post_json", return_value=response) as post:
            text = knowledge_digest_module._openai_request(
                [
                    {"role": "system", "content": "system prompt"},
                    {"role": "user", "content": "transcript"},
                ],
                settings,
                max_tokens=4096,
            )

        self.assertEqual(text.text, "完成")
        self.assertEqual(text.response_id, "msg_123")
        self.assertEqual(text.provider_status, "completed")
        self.assertEqual(text.stop_reason, "end_turn")
        self.assertEqual(post.call_args.args[0], "https://www.dmxapi.cn/v1/messages")
        self.assertEqual(post.call_args.args[1]["system"], "system prompt")
        self.assertEqual(post.call_args.args[1]["max_tokens"], 4096)
        self.assertEqual(post.call_args.kwargs["headers"]["x-api-key"], "secret")

    def test_non_claude_model_uses_responses_endpoint(self) -> None:
        settings = {
            "api_key": "secret",
            "base_url": "https://www.dmxapi.cn/v1",
            "model": "gpt-5.6-sol",
        }
        response = {"id": "resp_123", "status": "completed", "output_text": "完成"}
        with mock.patch.object(knowledge_digest_module, "_post_json", return_value=response) as post:
            text = knowledge_digest_module._openai_request(
                [{"role": "user", "content": "transcript"}],
                settings,
            )

        self.assertEqual(text.text, "完成")
        self.assertEqual(text.response_id, "resp_123")
        self.assertEqual(text.provider_status, "completed")
        self.assertEqual(post.call_args.args[0], "https://www.dmxapi.cn/v1/responses")

    def test_anthropic_max_tokens_rejects_returned_text(self) -> None:
        settings = {"api_key": "secret", "base_url": "https://www.dmxapi.cn", "model": "claude-sonnet-5-cc"}
        response = {
            "id": "msg_cut",
            "stop_reason": "max_tokens",
            "usage": {"output_tokens": 4096},
            "content": [{"type": "text", "text": "partial article"}],
        }
        with mock.patch.object(knowledge_digest_module, "_post_json", return_value=response):
            with self.assertRaises(knowledge_digest_module.IncompleteModelResponseError) as raised:
                knowledge_digest_module._openai_request([{"role": "user", "content": "x"}], settings)
        self.assertEqual(raised.exception.response_id, "msg_cut")
        self.assertEqual(raised.exception.stop_reason, "max_tokens")
        self.assertEqual(raised.exception.output_chars, len("partial article"))

    def test_openai_incomplete_rejects_returned_text_and_reason(self) -> None:
        settings = {"api_key": "secret", "base_url": "https://www.dmxapi.cn/v1", "model": "gpt-5.6-sol"}
        response = {
            "id": "resp_cut",
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
            "output_text": "partial article",
        }
        with mock.patch.object(knowledge_digest_module, "_post_json", return_value=response):
            with self.assertRaises(knowledge_digest_module.IncompleteModelResponseError) as raised:
                knowledge_digest_module._openai_request([{"role": "user", "content": "x"}], settings)
        self.assertEqual(raised.exception.provider_status, "incomplete")
        self.assertEqual(raised.exception.stop_reason, "max_output_tokens")

    def test_missing_provider_status_is_allowed_for_compatible_proxies(self) -> None:
        settings = {"api_key": "secret", "base_url": "https://www.dmxapi.cn/v1", "model": "gpt-5.6-sol"}
        with mock.patch.object(
            knowledge_digest_module,
            "_post_json",
            return_value={"id": "resp_proxy", "output_text": "完成"},
        ):
            response = knowledge_digest_module._openai_request([{"role": "user", "content": "x"}], settings)
        self.assertEqual(response.text, "完成")
        self.assertEqual(response.provider_status, "missing")

    def test_openai_refusal_content_is_not_treated_as_an_empty_retryable_response(self) -> None:
        settings = {"api_key": "secret", "base_url": "https://www.dmxapi.cn/v1", "model": "gpt-5.6-sol"}
        response = {
            "id": "resp_refusal",
            "status": "completed",
            "output": [{"content": [{"type": "refusal", "refusal": "not available"}]}],
        }
        with mock.patch.object(knowledge_digest_module, "_post_json", return_value=response):
            with self.assertRaises(knowledge_digest_module.PolicyModelResponseError):
                knowledge_digest_module._openai_request([{"role": "user", "content": "x"}], settings)

    def test_invalid_json_response_is_classified_as_transport_failure(self) -> None:
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"incomplete"'
        with mock.patch.object(knowledge_digest_module.urllib.request, "urlopen", return_value=response):
            with self.assertRaises(knowledge_digest_module.TransportModelResponseError):
                knowledge_digest_module._post_json(
                    "https://example.test/v1/responses",
                    {"model": "test"},
                    {"api_key": "secret"},
                )


class ManifestCompletionTests(unittest.TestCase):
    def test_manifest_is_complete_only_when_no_failed_or_pending_summaries(self) -> None:
        self.assertTrue(is_manifest_complete({"failed_count": 0, "pending_summary_count": 0}))
        self.assertFalse(is_manifest_complete({"failed_count": 0, "pending_summary_count": 1}))
        self.assertEqual(
            manifest_completion_status({"failed_count": 0, "pending_summary_count": 1}),
            "partial",
        )


class RetryPendingSummariesTests(unittest.TestCase):
    def test_retry_pending_summaries_only_processes_pending_videos(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = knowledge_digest_module.DigestConfig(
                playlist_url="https://www.youtube.com/playlist?list=PL123",
                playlist_name="knowledge",
                timezone="Asia/Shanghai",
                browser="chrome",
                browser_mode="managed",
                chrome_channel="chrome",
                chrome_user_data_dir="data/chrome-automation-profile",
                chrome_source_profile_dir="/tmp/chrome",
                chrome_automation_profile_dir="data/chrome-automation-profile",
                chrome_cdp_url="http://127.0.0.1:9222",
                youtube_client_secrets_path="data/youtube-oauth-client.json",
                youtube_token_path="data/youtube-oauth-token.json",
                openai_base_url="",
                openai_model="",
                summary_language="zh-CN",
                mlx_whisper_model="mlx-community/whisper-small-mlx",
                output_root=str(root / "runs"),
            )
            target_date = date(2026, 6, 10)
            run_dir = config.output_root_path / target_date.isoformat()
            pending_dir = run_dir / "videos" / "pending"
            ready_dir = run_dir / "videos" / "ready"
            pending_dir.mkdir(parents=True)
            ready_dir.mkdir(parents=True)
            (pending_dir / "transcript.original.txt").write_text("pending transcript", encoding="utf-8")
            (ready_dir / "transcript.original.txt").write_text("ready transcript", encoding="utf-8")
            overview_path = run_dir / "daily-overview.zh-CN.md"
            overview_path.write_text("legacy overview", encoding="utf-8")
            _write_json(
                run_dir / "manifest.json",
                {
                    "browser_mode": "managed",
                    "run_mode": "full",
                    "incremental_stats": {},
                    "processed_videos": [
                        {
                            "id": "ready",
                            "title": "Ready",
                            "url": "https://www.youtube.com/watch?v=ready",
                            "channel_name": "Channel",
                            "processing_status": "summary_ready",
                            "summary_text": "old",
                            "transcript_path": "videos/ready/transcript.original.txt",
                            "transcript_language": "en",
                            "transcript_source": "manual",
                        },
                        {
                            "id": "pending",
                            "title": "Pending",
                            "url": "https://www.youtube.com/watch?v=pending",
                            "channel_name": "Channel",
                            "processing_status": "pending_summary",
                            "summary_error": "old error",
                            "transcript_path": "videos/pending/transcript.original.txt",
                            "transcript_language": "en",
                            "transcript_source": "manual",
                        },
                    ],
                    "failed_videos": [],
                    "needs_review_videos": [],
                },
            )
            calls = []

            def fake_retry(transcript_text: str, video_title: str, settings: dict, playlist_name: str, **kwargs):
                calls.append(video_title)
                return "new summary", {"attempt_count": 1, "last_error": None}

            with mock.patch.object(knowledge_digest_module, "resolve_openai_settings", return_value={}):
                with mock.patch.object(knowledge_digest_module, "summarize_transcript_with_retries", side_effect=fake_retry):
                    with mock.patch.object(knowledge_digest_module, "load_state", return_value={}):
                        with mock.patch.object(knowledge_digest_module, "save_state"):
                            manifest = retry_pending_summaries(config, target_date)

            self.assertEqual(calls, ["Pending"])
            self.assertEqual(manifest["pending_summary_count"], 0)
            self.assertEqual(manifest["summary_ready_count"], 2)
            self.assertEqual(overview_path.read_text(encoding="utf-8"), "legacy overview")

    def test_retry_pending_summaries_can_force_stopped_video_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = make_test_config(str(root / "runs"))
            target_date = date(2026, 6, 10)
            run_dir = config.output_root_path / target_date.isoformat()
            pending_dir = run_dir / "videos" / "pending"
            pending_dir.mkdir(parents=True)
            (pending_dir / "transcript.original.txt").write_text("pending transcript", encoding="utf-8")
            _write_json(
                run_dir / "manifest.json",
                {
                    "browser_mode": "managed",
                    "run_mode": "full",
                    "incremental_stats": {},
                    "processed_videos": [
                        {
                            "id": "pending",
                            "title": "Pending",
                            "url": "https://www.youtube.com/watch?v=pending",
                            "channel_name": "Channel",
                            "processing_status": "pending_summary",
                            "summary_error": "SSL EOF",
                            "summary_retry": {
                                "attempt_count": 5,
                                "last_error": "SSL EOF",
                                "stopped_reason": "max_attempts",
                                "next_step": "manual_review",
                            },
                            "transcript_path": "videos/pending/transcript.original.txt",
                            "transcript_language": "en",
                            "transcript_source": "manual",
                        },
                    ],
                    "failed_videos": [],
                    "needs_review_videos": [],
                },
            )

            def fake_retry(transcript_text: str, video_title: str, settings: dict, playlist_name: str, **kwargs):
                self.assertTrue(kwargs["force_retry"])
                self.assertEqual(kwargs["run_attempt_limit"], 1)
                self.assertEqual(kwargs["force_retry_attempts"], 1)
                return "forced summary", {"attempt_count": 6, "last_error": None}

            with mock.patch.object(knowledge_digest_module, "resolve_openai_settings", return_value={}):
                with mock.patch.object(knowledge_digest_module, "summarize_transcript_with_retries", side_effect=fake_retry):
                    with mock.patch.object(knowledge_digest_module, "load_state", return_value={}):
                        with mock.patch.object(knowledge_digest_module, "save_state"):
                            manifest = retry_pending_summaries(
                                config,
                                target_date,
                                video_id="pending",
                                force_summary_retry=True,
                            )

            self.assertEqual(manifest["pending_summary_count"], 0)
            self.assertEqual(manifest["summary_ready_count"], 1)

    def test_regenerate_summaries_reuses_ready_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = make_test_config(str(root / "runs"))
            target_date = date(2026, 6, 10)
            run_dir = config.output_root_path / target_date.isoformat()
            video_dir = run_dir / "videos" / "ready"
            video_dir.mkdir(parents=True)
            (video_dir / "transcript.original.txt").write_text("ready transcript", encoding="utf-8")
            (video_dir / "summary.zh-CN.md").write_text("# Old\n", encoding="utf-8")
            _write_json(
                run_dir / "manifest.json",
                {
                    "browser_mode": "managed",
                    "run_mode": "full",
                    "incremental_stats": {},
                    "processed_videos": [
                        {
                            "id": "ready",
                            "title": "Ready",
                            "url": "https://www.youtube.com/watch?v=ready",
                            "channel_name": "Channel",
                            "processing_status": "summary_ready",
                            "summary_text": "old",
                            "transcript_path": "videos/ready/transcript.original.txt",
                            "transcript_language": "en",
                            "transcript_source": "manual",
                            "summary_retry": {"attempt_count": 1},
                        }
                    ],
                    "failed_videos": [],
                    "needs_review_videos": [],
                },
            )

            def fake_retry(transcript_text: str, video_title: str, settings: dict, playlist_name: str, **kwargs):
                self.assertEqual(transcript_text, "ready transcript")
                self.assertTrue(kwargs["force_retry"])
                self.assertEqual(kwargs["run_attempt_limit"], 3)
                self.assertEqual(kwargs["force_retry_attempts"], 3)
                return "中文标题：新标题\n\n## 核心结论\n\n新文章", {"attempt_count": 2}

            with mock.patch.object(knowledge_digest_module, "resolve_openai_settings", return_value={}):
                with mock.patch.object(knowledge_digest_module, "summarize_transcript_with_retries", side_effect=fake_retry):
                    with mock.patch.object(knowledge_digest_module, "load_state", return_value={}):
                        with mock.patch.object(knowledge_digest_module, "save_state"):
                            manifest = retry_pending_summaries(
                                config,
                                target_date,
                                regenerate_all=True,
                            )

            self.assertEqual(manifest["regenerated_summary_count"], 1)
            self.assertEqual(manifest["regeneration_failed_count"], 0)
            self.assertIn("# 新标题", (video_dir / "summary.zh-CN.md").read_text(encoding="utf-8"))

    def test_failed_regeneration_preserves_existing_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = make_test_config(str(root / "runs"))
            target_date = date(2026, 6, 10)
            run_dir = config.output_root_path / target_date.isoformat()
            video_dir = run_dir / "videos" / "ready"
            video_dir.mkdir(parents=True)
            (video_dir / "transcript.original.txt").write_text("ready transcript", encoding="utf-8")
            summary_path = video_dir / "summary.zh-CN.md"
            summary_path.write_text("# Old\n", encoding="utf-8")
            _write_json(
                run_dir / "manifest.json",
                {
                    "browser_mode": "managed",
                    "run_mode": "full",
                    "incremental_stats": {},
                    "processed_videos": [
                        {
                            "id": "ready",
                            "title": "Ready",
                            "url": "https://www.youtube.com/watch?v=ready",
                            "channel_name": "Channel",
                            "processing_status": "summary_ready",
                            "summary_text": "old",
                            "transcript_path": "videos/ready/transcript.original.txt",
                            "transcript_language": "en",
                            "transcript_source": "manual",
                        }
                    ],
                    "failed_videos": [],
                    "needs_review_videos": [],
                },
            )

            with mock.patch.object(knowledge_digest_module, "resolve_openai_settings", return_value={}):
                with mock.patch.object(
                    knowledge_digest_module,
                    "summarize_transcript_with_retries",
                    return_value=(None, {"attempt_count": 1, "last_error": "API unavailable"}),
                ):
                    with mock.patch.object(knowledge_digest_module, "load_state", return_value={}):
                        with mock.patch.object(knowledge_digest_module, "save_state"):
                            manifest = retry_pending_summaries(
                                config,
                                target_date,
                                regenerate_all=True,
                            )

            self.assertEqual(summary_path.read_text(encoding="utf-8"), "# Old\n")
            self.assertEqual(manifest["regenerated_summary_count"], 0)
            self.assertEqual(manifest["regeneration_failed_count"], 1)

    def test_adopt_summary_file_marks_pending_video_ready_without_touching_legacy_overview(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = make_test_config(str(root / "runs"))
            target_date = date(2026, 6, 10)
            run_dir = config.output_root_path / target_date.isoformat()
            video_dir = run_dir / "videos" / "pending"
            video_dir.mkdir(parents=True)
            (video_dir / "transcript.original.txt").write_text("pending transcript", encoding="utf-8")
            summary_file = root / "manual-summary.md"
            summary_file.write_text("# Manual Summary\n\n- done", encoding="utf-8")
            overview_path = run_dir / "daily-overview.zh-CN.md"
            overview_path.write_text("legacy overview", encoding="utf-8")
            _write_json(
                run_dir / "manifest.json",
                {
                    "browser_mode": "managed",
                    "run_mode": "full",
                    "incremental_stats": {},
                    "processed_videos": [
                        {
                            "id": "pending",
                            "title": "Pending",
                            "url": "https://www.youtube.com/watch?v=pending",
                            "channel_name": "Channel",
                            "processing_status": "pending_summary",
                            "summary_error": "SSL EOF",
                            "summary_retry": {
                                "attempt_count": 5,
                                "last_error": "SSL EOF",
                                "stopped_reason": "max_attempts",
                            },
                            "transcript_path": "videos/pending/transcript.original.txt",
                            "transcript_language": "en",
                            "transcript_source": "manual",
                        },
                    ],
                    "failed_videos": [],
                    "needs_review_videos": [],
                },
            )

            with mock.patch.object(knowledge_digest_module, "load_state", return_value={}):
                with mock.patch.object(knowledge_digest_module, "save_state"):
                    manifest = adopt_summary_for_video(config, target_date, "pending", summary_file)

            adopted = manifest["processed_videos"][0]
            self.assertEqual(manifest["pending_summary_count"], 0)
            self.assertEqual(manifest["summary_ready_count"], 1)
            self.assertEqual(adopted["processing_status"], "summary_ready")
            self.assertEqual(adopted["summary_source"], "manual")
            self.assertIsNone(adopted["summary_error"])
            self.assertEqual((video_dir / "summary.zh-CN.md").read_text(encoding="utf-8"), "# Manual Summary\n\n- done\n")
            self.assertEqual(overview_path.read_text(encoding="utf-8"), "legacy overview")


class GenerateMarkdownTests(unittest.TestCase):
    def test_generate_markdown_includes_summary_and_transcript_excerpt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            transcript_path = Path(tmpdir) / "transcript.txt"
            transcript_path.write_text("[00:00] hello", encoding="utf-8")
            markdown = generate_markdown(
                "abc123xyz89",
                {"title": "Video", "channel": "Channel", "upload_date": "20260320", "duration_string": "12:34"},
                transcript_path,
                "## 核心结论\n- one",
            )
        self.assertIn("# Video", markdown)
        self.assertIn("## 内容摘要", markdown)
        self.assertIn("## 字幕内容", markdown)
        self.assertIn("## 核心结论", markdown)


class JsonWriteTests(unittest.TestCase):
    def test_write_json_serializes_dates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "manifest.json"
            _write_json(
                path,
                {
                    "target_date": date(2026, 3, 20),
                    "generated_at": datetime(2026, 3, 21, 9, 0, tzinfo=BEIJING_TZ),
                },
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["target_date"], "2026-03-20")
        self.assertTrue(payload["generated_at"].startswith("2026-03-21T09:00:00"))

    def test_atomic_text_write_keeps_old_file_when_replace_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "summary.zh-CN.md"
            path.write_text("old complete summary", encoding="utf-8")
            with mock.patch.object(knowledge_digest_module.os, "replace", side_effect=OSError("interrupted")):
                with self.assertRaises(OSError):
                    knowledge_digest_module._atomic_write_text(path, "new summary")

            self.assertEqual(path.read_text(encoding="utf-8"), "old complete summary")
            self.assertEqual(list(path.parent.glob(".summary.zh-CN.md.*.tmp")), [])


class YoutubeApiPaginationToleranceTests(unittest.TestCase):
    def test_fetch_playlist_entries_via_youtube_api_keeps_partial_results_on_late_playlist_not_found(self) -> None:
        config = knowledge_digest_module.DigestConfig(
            playlist_url="https://www.youtube.com/playlist?list=PL123",
            playlist_name="knowledge",
            timezone="Asia/Shanghai",
            browser="chrome",
            browser_mode="managed",
            chrome_channel="chrome",
            chrome_user_data_dir="data/chrome-automation-profile",
            chrome_source_profile_dir="/tmp/chrome",
            chrome_automation_profile_dir="data/chrome-automation-profile",
            chrome_cdp_url="http://127.0.0.1:9222",
            youtube_client_secrets_path="data/youtube-oauth-client.json",
            youtube_token_path="data/youtube-oauth-token.json",
            openai_base_url="",
            openai_model="",
            summary_language="zh-CN",
            mlx_whisper_model="mlx-community/whisper-small-mlx",
            output_root="data/runs",
        )

        class FakePlaylistItems:
            def __init__(self) -> None:
                self.calls = 0

            def list(self, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    return mock.Mock(
                        execute=mock.Mock(
                            return_value={
                                "items": [
                                    {
                                        "id": "pli_1",
                                        "snippet": {
                                            "title": "Video 1",
                                            "publishedAt": "2026-05-29T14:53:32Z",
                                            "channelTitle": "Channel 1",
                                            "resourceId": {"videoId": "vid_1"},
                                        },
                                    }
                                ],
                                "nextPageToken": "page-2",
                            }
                        )
                    )
                raise Exception("playlistNotFound: simulated pagination failure")

        class FakeService:
            def __init__(self) -> None:
                self._playlist_items = FakePlaylistItems()

            def playlistItems(self):
                return self._playlist_items

        with mock.patch.object(knowledge_digest_module, "_load_youtube_credentials", return_value=object()):
            with mock.patch.object(
                knowledge_digest_module,
                "_load_youtube_oauth_dependencies",
                return_value=(None, None, None, mock.Mock(return_value=FakeService())),
            ):
                entries = knowledge_digest_module.fetch_playlist_entries_via_youtube_api(config)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["id"], "vid_1")
        self.assertEqual(entries[0]["playlist_added_date"], date(2026, 5, 29))

    def test_fetch_playlist_entries_via_youtube_api_still_raises_if_first_page_fails(self) -> None:
        config = knowledge_digest_module.DigestConfig(
            playlist_url="https://www.youtube.com/playlist?list=PL123",
            playlist_name="knowledge",
            timezone="Asia/Shanghai",
            browser="chrome",
            browser_mode="managed",
            chrome_channel="chrome",
            chrome_user_data_dir="data/chrome-automation-profile",
            chrome_source_profile_dir="/tmp/chrome",
            chrome_automation_profile_dir="data/chrome-automation-profile",
            chrome_cdp_url="http://127.0.0.1:9222",
            youtube_client_secrets_path="data/youtube-oauth-client.json",
            youtube_token_path="data/youtube-oauth-token.json",
            openai_base_url="",
            openai_model="",
            summary_language="zh-CN",
            mlx_whisper_model="mlx-community/whisper-small-mlx",
            output_root="data/runs",
        )

        class FakePlaylistItems:
            def list(self, **kwargs):
                raise Exception("playlistNotFound: simulated first-page failure")

        class FakeService:
            def playlistItems(self):
                return FakePlaylistItems()

        with mock.patch.object(knowledge_digest_module, "_load_youtube_credentials", return_value=object()):
            with mock.patch.object(
                knowledge_digest_module,
                "_load_youtube_oauth_dependencies",
                return_value=(None, None, None, mock.Mock(return_value=FakeService())),
            ):
                with self.assertRaises(knowledge_digest_module.DigestError):
                    knowledge_digest_module.fetch_playlist_entries_via_youtube_api(config)


class RunKnowledgeDigestRecoveryTests(unittest.TestCase):
    def test_date_run_does_not_create_or_overwrite_daily_overview(self) -> None:
        for has_legacy_overview in (False, True):
            with self.subTest(has_legacy_overview=has_legacy_overview):
                with tempfile.TemporaryDirectory() as tmpdir:
                    config = make_test_config(str(Path(tmpdir) / "runs"))
                    target_date = date(2026, 6, 10)
                    run_dir = config.output_root_path / target_date.isoformat()
                    run_dir.mkdir(parents=True)
                    overview_path = run_dir / "daily-overview.zh-CN.md"
                    if has_legacy_overview:
                        overview_path.write_text("legacy overview", encoding="utf-8")

                    fetch_result = knowledge_digest_module.PlaylistFetchResult(
                        entries=[],
                        cookie_file=None,
                        browser_mode="managed",
                    )
                    with mock.patch.object(knowledge_digest_module, "load_config", return_value=config):
                        with mock.patch.object(knowledge_digest_module, "resolve_openai_settings", return_value={}):
                            with mock.patch.object(
                                knowledge_digest_module,
                                "fetch_playlist_entries",
                                return_value=fetch_result,
                            ):
                                with mock.patch.object(knowledge_digest_module, "load_state", return_value={}):
                                    with mock.patch.object(knowledge_digest_module, "save_state"):
                                        with mock.patch.object(
                                            knowledge_digest_module,
                                            "_openai_request",
                                        ) as model_request:
                                            knowledge_digest_module.run_knowledge_digest(target_date)

                    model_request.assert_not_called()
                    if has_legacy_overview:
                        self.assertEqual(overview_path.read_text(encoding="utf-8"), "legacy overview")
                    else:
                        self.assertFalse(overview_path.exists())

    def test_transient_playlist_fetch_failure_recovers_existing_pending_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = make_test_config(str(root / "runs"))
            target_date = date(2026, 6, 10)
            run_dir = config.output_root_path / target_date.isoformat()
            run_dir.mkdir(parents=True)
            _write_json(
                run_dir / "manifest.json",
                {
                    "pending_summary_count": 1,
                    "processed_videos": [
                        {"id": "pending", "processing_status": "pending_summary"},
                    ],
                },
            )

            with mock.patch.object(knowledge_digest_module, "load_config", return_value=config):
                with mock.patch.object(knowledge_digest_module, "resolve_openai_settings", return_value={}):
                    with mock.patch.object(
                        knowledge_digest_module,
                        "fetch_playlist_entries",
                        side_effect=knowledge_digest_module.DigestError(
                            "YouTube API request failed: [SSL: UNEXPECTED_EOF_WHILE_READING]"
                        ),
                    ):
                        with mock.patch.object(
                            knowledge_digest_module,
                            "retry_pending_summaries",
                            return_value={"completion_status": "partial"},
                        ) as mocked_retry:
                            manifest = knowledge_digest_module.run_knowledge_digest(
                                target_date,
                                force_summary_retry=True,
                            )

            self.assertEqual(manifest["completion_status"], "partial")
            mocked_retry.assert_called_once()
            self.assertTrue(mocked_retry.call_args.kwargs["force_summary_retry"])

    def test_transient_playlist_fetch_failure_without_manifest_still_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = make_test_config(str(Path(tmpdir) / "runs"))
            target_date = date(2026, 6, 10)

            with mock.patch.object(knowledge_digest_module, "load_config", return_value=config):
                with mock.patch.object(knowledge_digest_module, "resolve_openai_settings", return_value={}):
                    with mock.patch.object(
                        knowledge_digest_module,
                        "fetch_playlist_entries",
                        side_effect=knowledge_digest_module.DigestError(
                            "YouTube API request failed: [SSL: UNEXPECTED_EOF_WHILE_READING]"
                        ),
                    ):
                        with mock.patch.object(knowledge_digest_module, "retry_pending_summaries") as mocked_retry:
                            with self.assertRaises(knowledge_digest_module.DigestError):
                                knowledge_digest_module.run_knowledge_digest(target_date)

            mocked_retry.assert_not_called()


class RecoverRunManifestTests(unittest.TestCase):
    def test_recovery_does_not_create_or_overwrite_daily_overview(self) -> None:
        for has_legacy_overview in (False, True):
            with self.subTest(has_legacy_overview=has_legacy_overview):
                with tempfile.TemporaryDirectory() as tmpdir:
                    config = make_test_config(str(Path(tmpdir) / "runs"))
                    run_dir = config.output_root_path / "2026-06-10"
                    video_dir = run_dir / "videos" / "ready"
                    video_dir.mkdir(parents=True)
                    (video_dir / "summary.zh-CN.md").write_text("# Summary", encoding="utf-8")
                    (video_dir / "transcript.original.txt").write_text("Transcript", encoding="utf-8")
                    overview_path = run_dir / "daily-overview.zh-CN.md"
                    if has_legacy_overview:
                        overview_path.write_text("legacy overview", encoding="utf-8")

                    with mock.patch.object(recover_module, "load_config", return_value=config):
                        recover_module.recover_run("2026-06-10")

                    if has_legacy_overview:
                        self.assertEqual(overview_path.read_text(encoding="utf-8"), "legacy overview")
                    else:
                        self.assertFalse(overview_path.exists())


class CliTests(unittest.TestCase):
    def test_cli_passes_full_reprocess_flag(self) -> None:
        with mock.patch.object(cli_module, "run_knowledge_digest", return_value={"ok": True}) as mocked_run:
            with mock.patch.object(cli_module, "_auto_sync_knowledge_site", return_value=0):
                with mock.patch.object(sys, "argv", ["run_knowledge_digest.py", "--target-date", "2026-03-21", "--full-reprocess"]):
                    exit_code = cli_module.main()
        self.assertEqual(exit_code, 0)
        self.assertTrue(mocked_run.call_args.kwargs["full_reprocess"])

    def test_cli_passes_regenerate_summaries_flag(self) -> None:
        with mock.patch.object(cli_module, "run_knowledge_digest", return_value={"ok": True}) as mocked_run:
            with mock.patch.object(cli_module, "_auto_sync_knowledge_site", return_value=0):
                with mock.patch.object(
                    sys,
                    "argv",
                    ["run_knowledge_digest.py", "--target-date", "2026-03-21", "--regenerate-summaries"],
                ):
                    exit_code = cli_module.main()
        self.assertEqual(exit_code, 0)
        self.assertTrue(mocked_run.call_args.kwargs["regenerate_summaries"])

    def test_cli_video_id_still_bypasses_incremental_skip_decision(self) -> None:
        with mock.patch.object(cli_module, "run_knowledge_digest", return_value={"ok": True}) as mocked_run:
            with mock.patch.object(sys, "argv", ["run_knowledge_digest.py", "--target-date", "2026-03-21", "--video-id", "abc123xyz89"]):
                with mock.patch.object(cli_module, "_auto_sync_knowledge_site", return_value=0):
                    exit_code = cli_module.main()
        self.assertEqual(exit_code, 0)
        self.assertEqual(mocked_run.call_args.kwargs["video_id"], "abc123xyz89")
        self.assertFalse(mocked_run.call_args.kwargs["full_reprocess"])

    def test_cli_passes_force_summary_retry_and_adopt_summary_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            summary_path = Path(tmpdir) / "summary.md"
            summary_path.write_text("# summary", encoding="utf-8")
            with mock.patch.object(cli_module, "run_knowledge_digest", return_value={"ok": True}) as mocked_run:
                with mock.patch.object(cli_module, "_auto_sync_knowledge_site", return_value=0):
                    with mock.patch.object(
                        sys,
                        "argv",
                        [
                            "run_knowledge_digest.py",
                            "--target-date",
                            "2026-03-21",
                            "--retry-summaries",
                            "--video-id",
                            "abc123xyz89",
                            "--force-summary-retry",
                            "--adopt-summary-file",
                            str(summary_path),
                        ],
                    ):
                        exit_code = cli_module.main()

        self.assertEqual(exit_code, 0)
        self.assertTrue(mocked_run.call_args.kwargs["force_summary_retry"])
        self.assertEqual(mocked_run.call_args.kwargs["adopt_summary_file"], summary_path)

    def test_cli_content_run_triggers_auto_sync_for_target_date(self) -> None:
        with mock.patch.object(cli_module, "run_knowledge_digest", return_value={"ok": True}):
            with mock.patch.object(cli_module, "_auto_sync_knowledge_site", return_value=0) as mocked_sync:
                with mock.patch.object(sys, "argv", ["run_knowledge_digest.py", "--target-date", "2026-03-21"]):
                    exit_code = cli_module.main()
        self.assertEqual(exit_code, 0)
        mocked_sync.assert_called_once_with("2026-03-21")

    def test_cli_sync_failure_returns_nonzero(self) -> None:
        with mock.patch.object(cli_module, "run_knowledge_digest", return_value={"ok": True}):
            with mock.patch.object(cli_module, "_auto_sync_knowledge_site", return_value=1) as mocked_sync:
                with mock.patch.object(sys, "argv", ["run_knowledge_digest.py", "--target-date", "2026-03-21"]):
                    exit_code = cli_module.main()
        self.assertEqual(exit_code, 1)
        mocked_sync.assert_called_once()

    def test_cli_partial_manifest_returns_partial_exit_code_after_sync(self) -> None:
        manifest = {"failed_count": 0, "pending_summary_count": 1}
        with mock.patch.object(cli_module, "run_knowledge_digest", return_value=manifest):
            with mock.patch.object(cli_module, "_auto_sync_knowledge_site", return_value=0) as mocked_sync:
                with mock.patch.object(sys, "argv", ["run_knowledge_digest.py", "--target-date", "2026-03-21"]):
                    exit_code = cli_module.main()
        self.assertEqual(exit_code, 2)
        mocked_sync.assert_called_once()

    def test_cli_non_content_mode_skips_auto_sync(self) -> None:
        with mock.patch.object(cli_module, "run_knowledge_digest", return_value={"ok": True}):
            with mock.patch.object(cli_module, "_auto_sync_knowledge_site", return_value=0) as mocked_sync:
                with mock.patch.object(sys, "argv", ["run_knowledge_digest.py", "--bootstrap-login"]):
                    exit_code = cli_module.main()
        self.assertEqual(exit_code, 0)
        mocked_sync.assert_not_called()


def json_text(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    unittest.main()
