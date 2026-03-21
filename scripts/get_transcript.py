#!/usr/bin/env python3
"""Download a video's transcript and save it to local files."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from knowledge_digest import DATA_DIR, DigestError, download_transcript


def main() -> int:
    parser = argparse.ArgumentParser(description="Download a YouTube video's transcript.")
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--output", help="Optional transcript output path.")
    parser.add_argument("--browser", default="chrome", help="Browser name for yt-dlp cookies.")
    args = parser.parse_args()

    output_dir = DATA_DIR / "transcripts" / args.video_id
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        result, _diagnostics = download_transcript(args.video_id, output_dir, browser=args.browser)
    except DigestError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if result is None:
        print("无法获取官方或自动字幕。", file=sys.stderr)
        return 1

    transcript_path = Path(args.output) if args.output else DATA_DIR / f"transcript_{args.video_id}.txt"
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_path.write_text(result.text, encoding="utf-8")

    json_path = transcript_path.with_suffix(".json")
    json_path.write_text(json.dumps(result.segments, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"字幕来源: {result.source}")
    print(f"字幕语言: {result.language}")
    print(f"已保存到: {transcript_path}")
    print(f"分段 JSON: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
