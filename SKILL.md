---
name: youtube-ai-digest
description: Browse AI-related YouTube videos from subscribed channels, summarize content, capture screenshots, and generate Markdown reports. Triggers on "youtube ai digest", "summarize youtube ai", "browse youtube ai videos".
---

# YouTube AI Digest

浏览关注博主的 AI 相关 YouTube 视频，获取字幕/内容总结，截取关键画面，生成 Markdown 文档。

## Prerequisites

- Python 3.9+
- yt-dlp (`pip install yt-dlp`)
- youtube-transcript-api (`pip install youtube-transcript-api`)
- playwright-skill (用于浏览器操作和截图)

## 配置

编辑 `~/.claude/skills/youtube-ai-digest/data/channels.json` 添加关注的频道：

```json
{
  "channels": [
    {"name": "3Blue1Brown", "id": "UCYO_jab_esuFRV4b17AJtAw"},
    {"name": "Two Minute Papers", "id": "UCbfYPyITQ-7l4upoX8nvctg"}
  ]
}
```

## Scripts

### 1. fetch_videos.py
获取频道最新视频列表

```bash
python scripts/fetch_videos.py --days 1
```

### 2. get_transcript.py
获取视频字幕

```bash
python scripts/get_transcript.py --video-id VIDEO_ID
```

### 3. generate_report.py
生成 Markdown 报告

```bash
python scripts/generate_report.py --video-id VIDEO_ID --output ~/reports/
```

## Workflow

1. **获取视频列表**: `python scripts/fetch_videos.py --days 1`
2. **获取字幕**: `python scripts/get_transcript.py --video-id VIDEO_ID`
3. **截图**: 使用 playwright-skill 截取视频画面
4. **生成报告**: `python scripts/generate_report.py`

## 浏览器操作

截图时调用 playwright-skill：
```
使用 playwright 打开 https://youtube.com/watch?v=VIDEO_ID
跳转到 1:30 并截图保存
```

## Output Format

```markdown
# [视频标题]

![封面](thumbnail.jpg)

## 视频信息
- 频道: [频道名]
- 发布时间: [日期]
- 链接: [URL]

## 内容摘要
[摘要内容]

## 关键时间点
- 00:00 - [主题1]
- 05:30 - [主题2]

## 截图
![截图1](screenshot_1.png)
```
