from __future__ import annotations

import sys
import tempfile
import unittest
import json
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from generate_report import generate_markdown
from knowledge_digest import (
    BEIJING_TZ,
    _normalize_playlist_payload,
    _write_json,
    extract_playlist_id,
    filter_entries_for_date,
    load_config,
    normalize_playlist_url,
    parse_added_date_text,
    parse_target_date,
    parse_vtt,
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


def json_text(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    unittest.main()
