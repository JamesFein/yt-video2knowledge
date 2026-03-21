#!/usr/bin/env python3
"""Generate a Markdown report for a single YouTube video."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from knowledge_digest import DATA_DIR, DigestError, download_thumbnail, fetch_video_info

OUTPUT_DIR = DATA_DIR / "output"


def generate_markdown(video_id: str, info: dict, transcript_file: str | Path | None, summary: str | None) -> str:
    transcript_path = Path(transcript_file) if transcript_file else None
    thumbnail_name = "thumbnail.webp"
    if transcript_path and transcript_path.parent.joinpath("thumbnail.webp").exists():
        thumbnail_name = "thumbnail.webp"

    markdown = [
        f"# {info.get('title', 'Unknown')}",
        "",
        f"![封面]({thumbnail_name})",
        "",
        "## 视频信息",
        f"- 频道: {info.get('channel', 'Unknown')}",
        f"- 发布时间: {info.get('upload_date', 'Unknown')}",
        f"- 时长: {info.get('duration_string', info.get('duration', 'Unknown'))}",
        f"- 链接: https://www.youtube.com/watch?v={video_id}",
        "",
        "## 内容摘要",
        summary.strip() if summary else "[请补充中文摘要]",
        "",
    ]
    if transcript_path and transcript_path.exists():
        excerpt = transcript_path.read_text(encoding="utf-8", errors="ignore")[:4000]
        markdown.extend(["## 字幕内容", "", "```text", excerpt, "```", ""])
    return "\n".join(markdown).strip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a single-video Markdown report.")
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--output", default=str(OUTPUT_DIR))
    parser.add_argument("--summary", help="Chinese summary text.")
    parser.add_argument("--transcript-file", help="Transcript file path override.")
    parser.add_argument("--browser", default="chrome", help="Browser name for yt-dlp cookies.")
    args = parser.parse_args()

    output_dir = Path(args.output) / args.video_id
    output_dir.mkdir(parents=True, exist_ok=True)

    transcript_file = args.transcript_file or (DATA_DIR / f"transcript_{args.video_id}.txt")

    try:
        info = fetch_video_info(args.video_id, browser=args.browser)
        download_thumbnail(args.video_id, output_dir, browser=args.browser)
    except DigestError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    report = generate_markdown(args.video_id, info, transcript_file, args.summary)
    report_path = output_dir / "report.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"报告已生成: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
