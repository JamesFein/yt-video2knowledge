from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from knowledge_site.config import Settings
from knowledge_site.main import create_app
from knowledge_site.markdown_blocks import split_markdown_blocks
from knowledge_site.routes.pages import templates
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


def write_ready_video(root: Path) -> Settings:
    settings = make_settings(root)
    day_dir = root / "data" / "runs" / "2026-06-01"
    video_dir = day_dir / "videos" / "ready"
    video_dir.mkdir(parents=True, exist_ok=True)
    (day_dir / "daily-overview.zh-CN.md").write_text("# Daily", encoding="utf-8")
    (video_dir / "summary.zh-CN.md").write_text(
        "## 一句话总结\n\nReady summary\n\n### 可执行启发\n\nTry it.",
        encoding="utf-8",
    )
    (video_dir / "transcript.original.txt").write_text("Transcript", encoding="utf-8")
    write_json(
        video_dir / "metadata.json",
        {
            "id": "ready",
            "title": "Ready Video",
            "url": "https://www.youtube.com/watch?v=ready",
            "channel_name": "Channel",
            "duration": "12:34",
            "upload_date": "20260601",
            "processing_status": "summary_ready",
        },
    )
    sync_knowledge_site(settings)
    return settings


class KnowledgeSiteApiTests(unittest.TestCase):
    def test_session_cookie_can_share_fixed_domain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = write_ready_video(root)
            settings = Settings(
                root_dir=settings.root_dir,
                db_path=settings.db_path,
                assets_dir=settings.assets_dir,
                password=settings.password,
                secret_key=settings.secret_key,
                cookie_domain=".miniaiheadlines.top",
                dev_mode=False,
            )
            client = TestClient(create_app(settings), base_url="https://miniaiheadlines.top")

            response = client.post(
                "/login",
                data={"password": "secret", "next": "/"},
                follow_redirects=False,
            )

            self.assertIn("domain=.miniaiheadlines.top", response.headers["set-cookie"])

    def test_auth_and_meta_summary_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = write_ready_video(root)
            client = TestClient(create_app(settings))

            response = client.get("/", follow_redirects=False)
            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.headers["location"], "/login?next=/")

            response = client.get("/api/v1/videos/ready/meta-summary")
            self.assertEqual(response.status_code, 401)

            response = client.post(
                "/login",
                data={"password": "wrong", "next": "/"},
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 401)

            response = client.post(
                "/login",
                data={"password": "secret", "next": "/"},
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.headers["location"], "/")
            self.assertEqual(client.get("/").status_code, 200)
            day_page = client.get("/days/2026-06-01")
            self.assertIn('<details class="daily-overview">', day_page.text)
            self.assertIn("<summary>knowledge Daily Overview</summary>", day_page.text)
            self.assertNotIn('<details class="daily-overview" open', day_page.text)
            self.assertIn('<a class="return-pill" href="/">← 返回日期列表</a>', day_page.text)
            self.assertIn('href="/videos/ready?day=2026-06-01"', day_page.text)
            video_page = client.get("/videos/ready")
            self.assertIn("Ready Video", video_page.text)
            self.assertIn('<a href="/days/2026-06-01">2026-06-01</a>', video_page.text)
            self.assertIn(
                '<a class="return-pill" href="/days/2026-06-01">← 返回视频列表</a>',
                video_page.text,
            )
            self.assertIn('aria-label="一句话总结 / 可执行启发"', video_page.text)
            self.assertIn('<p class="block-eyebrow">一句话总结</p>', video_page.text)
            self.assertIn('<h3 class="block-subhead" aria-label="一句话总结 / 可执行启发">可执行启发</h3>', video_page.text)
            self.assertIn('<p class="seg-paragraph">Try it.</p>', video_page.text)
            self.assertIn('<textarea class="block-text" hidden>Try it.</textarea>', video_page.text)
            self.assertNotIn('<textarea class="block-text" hidden>可执行启发', video_page.text)
            self.assertNotIn("直接内容", video_page.text)
            video_page_from_day = client.get("/videos/ready?day=2026-06-01")
            self.assertIn(
                '<a class="return-pill" href="/days/2026-06-01">← 返回视频列表</a>',
                video_page_from_day.text,
            )
            video_page_bad_day = client.get("/videos/ready?day=2026-06-02")
            self.assertIn(
                '<a class="return-pill" href="/days/2026-06-01">← 返回视频列表</a>',
                video_page_bad_day.text,
            )
            self.assertNotIn('href="/days/2026-06-02"', video_page_bad_day.text)

            response = client.get("/api/v1/videos/ready/meta-summary")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["content"], "")

            response = client.put(
                "/api/v1/videos/ready/meta-summary",
                json={"content": "manual note"},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["content"], "manual note")

            response = client.put(
                "/api/v1/videos/ready/meta-summary",
                json={"content": ""},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["content"], "")
            self.assertEqual(client.post("/api/v1/videos/ready/meta-summary").status_code, 405)
            self.assertEqual(client.delete("/api/v1/videos/ready/meta-summary").status_code, 405)
            self.assertEqual(client.get("/api/v1/videos/missing/meta-summary").status_code, 404)

    def test_video_template_falls_back_to_plain_text_for_legacy_blocks(self) -> None:
        video = SimpleNamespace(
            title="Ready Video",
            thumbnail_url=None,
            channel_name="Channel",
            url="https://www.youtube.com/watch?v=ready",
            video_id="ready",
            meta_content="",
        )
        block = SimpleNamespace(
            heading_path="一句话总结 / 可执行启发",
            heading_ancestors=("一句话总结",),
            heading_text="可执行启发",
            plain_text="可执行启发\n\nTry it.",
        )

        html = templates.env.get_template("video.html").render(
            request=SimpleNamespace(session={}),
            video=video,
            blocks=[block],
        )

        self.assertIn("<pre>可执行启发\n\nTry it.</pre>", html)
        self.assertIn('<textarea class="block-text" hidden>可执行启发\n\nTry it.</textarea>', html)


class MarkdownBlockTests(unittest.TestCase):
    def test_parent_block_keeps_only_direct_content(self) -> None:
        blocks = split_markdown_blocks("# Parent\n\nDirect note.\n\n## Child\n\nChild note.")
        paths = [block.heading_path for block in blocks]

        self.assertIn("Parent", paths)
        self.assertIn("Parent / Child", paths)
        self.assertNotIn("Parent / 直接内容", paths)

        parent = next(block for block in blocks if block.heading_path == "Parent")
        child = next(block for block in blocks if block.heading_path == "Parent / Child")
        self.assertEqual(parent.plain_text, "Parent\n\nDirect note.")
        self.assertEqual(child.plain_text, "Child\n\nChild note.")
        self.assertEqual(parent.body_plain_text, "Direct note.")
        self.assertEqual(child.body_plain_text, "Child note.")
        self.assertEqual(parent.heading_ancestors, ())
        self.assertEqual(child.heading_ancestors, ("Parent",))

    def test_body_plain_text_matches_plain_text_without_headings(self) -> None:
        blocks = split_markdown_blocks("Loose note.\n\nAnother line.")

        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].plain_text, "Loose note.\n\nAnother line.")
        self.assertEqual(blocks[0].body_plain_text, blocks[0].plain_text)

    def test_heading_ancestors_exclude_current_heading(self) -> None:
        blocks = split_markdown_blocks("# Parent\n\n## Child\n\n### Leaf\n\nLeaf note.")

        leaf = blocks[0]
        self.assertEqual(leaf.heading_path, "Parent / Child / Leaf")
        self.assertEqual(leaf.heading_text, "Leaf")
        self.assertEqual(leaf.heading_ancestors, ("Parent", "Child"))

    def test_empty_container_heading_has_no_direct_content_block(self) -> None:
        blocks = split_markdown_blocks("# Parent\n\n## Child\n\nChild note.")
        paths = [block.heading_path for block in blocks]

        self.assertNotIn("Parent", paths)
        self.assertIn("Parent / Child", paths)

    def test_container_with_thematic_break_has_no_block(self) -> None:
        blocks = split_markdown_blocks("# Parent\n\n---\n\n## Child\n\nChild note.")
        paths = [block.heading_path for block in blocks]

        self.assertNotIn("Parent", paths)
        self.assertIn("Parent / Child", paths)


class BodySegmentTests(unittest.TestCase):
    def _segments(self, body: str):
        from knowledge_site.markdown_blocks import parse_body_segments

        return parse_body_segments(body)

    def test_paragraph_with_inline_strong(self) -> None:
        segments = self._segments("普通文本 **加粗片段** 收尾。")
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].kind, "paragraph")
        strong_runs = [run for run in segments[0].runs if run.strong]
        self.assertEqual([run.text for run in strong_runs], ["加粗片段"])

    def test_subhead_segment(self) -> None:
        segments = self._segments("### 显式标识（水印）\n\n肉眼可见。")
        self.assertEqual(segments[0].kind, "subhead")
        self.assertEqual(segments[0].runs[0].text, "显式标识（水印）")
        self.assertEqual(segments[1].kind, "paragraph")

    def test_unordered_list(self) -> None:
        segments = self._segments("- 第一项\n- 第二项")
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].kind, "list")
        self.assertFalse(segments[0].ordered)
        self.assertEqual([item.runs[0].text for item in segments[0].items], ["第一项", "第二项"])

    def test_ordered_list(self) -> None:
        segments = self._segments("1. 甲\n2. 乙")
        self.assertEqual(segments[0].kind, "list")
        self.assertTrue(segments[0].ordered)

    def test_nested_list_levels(self) -> None:
        segments = self._segments("- 顶层\n  - 次层\n    - 三层")
        levels = [item.level for item in segments[0].items]
        self.assertEqual(levels, [0, 1, 2])

    def test_blockquote_segment(self) -> None:
        segments = self._segments("> 这是作者推断，不是结论。")
        self.assertEqual(segments[0].kind, "blockquote")
        self.assertEqual(segments[0].runs[0].text, "这是作者推断，不是结论。")

    def test_ordered_then_unordered_split_into_two_lists(self) -> None:
        segments = self._segments("1. 甲\n- 乙")
        kinds = [seg.kind for seg in segments]
        self.assertEqual(kinds, ["list", "list"])
        self.assertTrue(segments[0].ordered)
        self.assertFalse(segments[1].ordered)

    def test_code_block_does_not_break_parsing(self) -> None:
        segments = self._segments("段落。\n\n```\ncode line\n```\n\n- 列表项")
        kinds = [seg.kind for seg in segments]
        self.assertIn("paragraph", kinds)
        self.assertIn("list", kinds)

    def test_empty_body_has_no_segments(self) -> None:
        self.assertEqual(self._segments(""), ())

    def test_block_carries_body_segments(self) -> None:
        blocks = split_markdown_blocks("## 关键观点\n\n正文 **重点**。\n\n- 项目")
        block = next(b for b in blocks if b.heading_text == "关键观点")
        kinds = [seg.kind for seg in block.body_segments]
        self.assertEqual(kinds, ["paragraph", "list"])


if __name__ == "__main__":
    unittest.main()
