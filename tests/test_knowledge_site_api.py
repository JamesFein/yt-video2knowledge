from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from knowledge_site.config import Settings
from knowledge_site.main import create_app
from knowledge_site.markdown_blocks import split_markdown_blocks
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
            video_page = client.get("/videos/ready")
            self.assertIn("Ready Video", video_page.text)
            self.assertIn("一句话总结 / 可执行启发", video_page.text)
            self.assertNotIn("直接内容", video_page.text)

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


if __name__ == "__main__":
    unittest.main()
