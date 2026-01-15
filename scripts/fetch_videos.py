#!/usr/bin/env python3
"""获取关注频道的最新视频列表"""
import json
import subprocess
from datetime import datetime
from pathlib import Path
import argparse

DATA_DIR = Path(__file__).parent.parent / "data"
CHANNELS_FILE = DATA_DIR / "channels.json"
OUTPUT_FILE = DATA_DIR / "videos.json"

def load_channels():
    if not CHANNELS_FILE.exists():
        return []
    with open(CHANNELS_FILE) as f:
        return json.load(f).get("channels", [])

def fetch_channel_videos(channel_id, days=1):  # noqa: ARG001
    """使用 yt-dlp 获取频道视频 (days 参数预留用于时间过滤)"""
    cmd = [
        "yt-dlp", "--flat-playlist", "--dump-json",
        f"https://www.youtube.com/channel/{channel_id}/videos"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        videos = []
        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
            video = json.loads(line)
            videos.append({
                "id": video.get("id"),
                "title": video.get("title"),
                "url": f"https://www.youtube.com/watch?v={video.get('id')}",
                "channel_id": channel_id
            })
            if len(videos) >= 10:  # 限制每个频道最多10个
                break
        return videos
    except Exception as e:
        print(f"Error fetching {channel_id}: {e}")
        return []

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--keyword", default="AI")
    args = parser.parse_args()

    channels = load_channels()
    if not channels:
        print("No channels configured. Edit data/channels.json")
        return

    all_videos = []
    for ch in channels:
        print(f"Fetching: {ch['name']}...")
        videos = fetch_channel_videos(ch["id"], args.days)
        for v in videos:
            v["channel_name"] = ch["name"]
        all_videos.extend(videos)

    # 过滤 AI 相关
    keyword = args.keyword.lower()
    filtered = [v for v in all_videos if keyword in v.get("title", "").lower()]

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump({"videos": filtered, "fetched_at": datetime.now().isoformat()}, f, indent=2, ensure_ascii=False)

    print(f"\nFound {len(filtered)} AI-related videos")
    for v in filtered:
        print(f"  - {v['title']} ({v['channel_name']})")

if __name__ == "__main__":
    main()
