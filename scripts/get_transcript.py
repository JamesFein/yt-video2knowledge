#!/usr/bin/env python3
"""获取视频字幕 - 使用 yt-dlp"""
import json
import argparse
import subprocess
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"

def get_transcript_ytdlp(video_id):
    """使用 yt-dlp 获取字幕"""
    url = f"https://www.youtube.com/watch?v={video_id}"
    output_template = str(DATA_DIR / f"sub_{video_id}")

    # 尝试获取字幕
    cmd = [
        "yt-dlp", "--skip-download",
        "--write-auto-sub", "--write-sub",
        "--sub-lang", "en,zh",
        "--sub-format", "vtt",
        "-o", output_template,
        url
    ]
    subprocess.run(cmd, capture_output=True)

    # 查找生成的字幕文件
    for suffix in [".en.vtt", ".zh.vtt", ".en-orig.vtt"]:
        sub_file = DATA_DIR / f"sub_{video_id}{suffix}"
        if sub_file.exists():
            return parse_vtt(sub_file), suffix.split('.')[1]
    return None, None

def parse_vtt(vtt_file):
    """解析 VTT 字幕文件"""
    content = vtt_file.read_text(encoding="utf-8")
    lines = content.split('\n')
    transcript = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # 查找时间戳行 (00:00:00.000 --> 00:00:00.000)
        if '-->' in line:
            parts = line.split('-->')
            start_time = parts[0].strip()
            # 解析时间
            time_parts = start_time.replace(',', '.').split(':')
            if len(time_parts) == 3:
                h, m, s = time_parts
                start_seconds = int(h) * 3600 + int(m) * 60 + float(s.split('.')[0])
            else:
                start_seconds = 0
            # 获取字幕文本
            i += 1
            text_lines = []
            while i < len(lines) and lines[i].strip() and '-->' not in lines[i]:
                text = lines[i].strip()
                # 移除 VTT 标签
                if not text.isdigit() and '<' not in text:
                    text_lines.append(text)
                i += 1
            if text_lines:
                transcript.append({"start": start_seconds, "text": ' '.join(text_lines)})
        else:
            i += 1
    return transcript

def format_transcript(transcript):
    """格式化字幕为文本"""
    lines = []
    for entry in transcript:
        start = int(entry["start"])
        mins, secs = divmod(start, 60)
        text = entry["text"]
        lines.append(f"[{mins:02d}:{secs:02d}] {text}")
    return "\n".join(lines)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--output", help="输出文件路径")
    args = parser.parse_args()

    print(f"获取字幕: {args.video_id}")
    transcript, lang = get_transcript_ytdlp(args.video_id)

    if not transcript:
        print("无法获取字幕")
        return

    formatted = format_transcript(transcript)
    print(f"字幕语言: {lang}")
    print(f"字幕条数: {len(transcript)}")

    output_file = DATA_DIR / f"transcript_{args.video_id}.txt"
    output_file.write_text(formatted, encoding="utf-8")
    print(f"已保存到: {output_file}")

    # JSON 格式
    json_file = DATA_DIR / f"transcript_{args.video_id}.json"
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(transcript, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
