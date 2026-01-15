#!/usr/bin/env python3
"""生成 Markdown 报告"""
import json
import argparse
import subprocess
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
OUTPUT_DIR = DATA_DIR / "output"

def get_video_info(video_id):
    """使用 yt-dlp 获取视频信息"""
    cmd = ["yt-dlp", "--dump-json", "--no-download", f"https://www.youtube.com/watch?v={video_id}"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as e:
        print(f"Error fetching video info: {e}")
        return {}

def download_thumbnail(video_id, output_path):
    """下载视频封面"""
    cmd = ["yt-dlp", "--write-thumbnail", "--skip-download", "-o", str(output_path / "thumbnail"),
           f"https://www.youtube.com/watch?v={video_id}"]
    subprocess.run(cmd, capture_output=True)

def generate_markdown(video_id, info, transcript_file, screenshots=None, summary=None):
    """生成 Markdown 报告"""
    title = info.get("title", "Unknown")
    channel = info.get("channel", "Unknown")
    upload_date = info.get("upload_date", "")
    duration = info.get("duration_string", "")
    url = f"https://www.youtube.com/watch?v={video_id}"

    md = f"""# {title}

![封面](thumbnail.webp)

## 视频信息
- 频道: {channel}
- 发布时间: {upload_date}
- 时长: {duration}
- 链接: {url}

## 内容摘要
{summary or "[请使用 Claude 根据字幕生成摘要]"}

"""
    # 添加字幕内容
    if transcript_file and Path(transcript_file).exists():
        md += "## 字幕内容\n\n"
        md += "```\n"
        md += Path(transcript_file).read_text()[:3000]  # 限制长度
        md += "\n```\n\n"

    # 添加截图
    if screenshots:
        md += "## 关键截图\n\n"
        for i, ss in enumerate(screenshots, 1):
            md += f"![截图{i}]({ss})\n\n"

    return md

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--output", default=str(OUTPUT_DIR))
    parser.add_argument("--summary", help="摘要内容")
    args = parser.parse_args()

    output_dir = Path(args.output) / args.video_id
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"获取视频信息: {args.video_id}")
    info = get_video_info(args.video_id)

    print("下载封面...")
    download_thumbnail(args.video_id, output_dir)

    transcript_file = DATA_DIR / f"transcript_{args.video_id}.txt"

    md = generate_markdown(args.video_id, info, transcript_file, summary=args.summary)

    report_file = output_dir / "report.md"
    report_file.write_text(md, encoding="utf-8")
    print(f"报告已生成: {report_file}")

if __name__ == "__main__":
    main()
