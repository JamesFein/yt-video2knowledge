from __future__ import annotations

import sys
import tempfile
import unittest
import json
from datetime import date, datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import run_knowledge_digest as cli_module
import knowledge_digest as knowledge_digest_module
from generate_report import generate_markdown
from knowledge_digest import (
    BEIJING_TZ,
    _normalize_playlist_payload,
    _write_json,
    extract_playlist_id,
    filter_entries_for_date,
    load_config,
    merge_run_results,
    normalize_playlist_url,
    parse_added_date_text,
    parse_target_date,
    parse_vtt,
    plan_run_entries,
    select_entries_for_processing,
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


class CliTests(unittest.TestCase):
    def test_cli_passes_full_reprocess_flag(self) -> None:
        with mock.patch.object(cli_module, "run_knowledge_digest", return_value={"ok": True}) as mocked_run:
            with mock.patch.object(sys, "argv", ["run_knowledge_digest.py", "--target-date", "2026-03-21", "--full-reprocess"]):
                exit_code = cli_module.main()
        self.assertEqual(exit_code, 0)
        self.assertTrue(mocked_run.call_args.kwargs["full_reprocess"])

    def test_cli_video_id_still_bypasses_incremental_skip_decision(self) -> None:
        with mock.patch.object(cli_module, "run_knowledge_digest", return_value={"ok": True}) as mocked_run:
            with mock.patch.object(sys, "argv", ["run_knowledge_digest.py", "--target-date", "2026-03-21", "--video-id", "abc123xyz89"]):
                exit_code = cli_module.main()
        self.assertEqual(exit_code, 0)
        self.assertEqual(mocked_run.call_args.kwargs["video_id"], "abc123xyz89")
        self.assertFalse(mocked_run.call_args.kwargs["full_reprocess"])


def json_text(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    unittest.main()
