# YouTube AI Digest

Claude Code Skill：浏览关注博主的 AI 相关 YouTube 视频，获取字幕、生成摘要、截取关键画面。

## 功能

- 获取关注频道的最新 AI 视频列表
- 自动下载视频字幕
- 生成 Markdown 格式报告
- 配合 playwright-skill 截取视频关键画面

## 安装

```bash
# 克隆到 Claude skills 目录
git clone https://github.com/yizhiyanhua-ai/youtube-ai-digest.git \
  ~/.claude/skills/youtube-ai-digest

# 安装依赖
pip install yt-dlp
```

## 配置

编辑 `data/channels.json` 添加关注的频道：

```json
{
  "channels": [
    {"name": "Two Minute Papers", "id": "UCbfYPyITQ-7l4upoX8nvctg"},
    {"name": "AI Explained", "id": "UCNJ1Ymd5yFuUPtn21xtRbbw"}
  ]
}
```

## 使用

在 Claude Code 中直接对话：

```
用户: 今天有什么 AI 新视频？
用户: 总结一下第一个视频
用户: 截取关键画面
```

## 手动使用

```bash
# 获取视频列表
python scripts/fetch_videos.py --days 1 --keyword AI

# 获取字幕
python scripts/get_transcript.py --video-id VIDEO_ID

# 生成报告
python scripts/generate_report.py --video-id VIDEO_ID
```

## 依赖

- Python 3.9+
- yt-dlp
- playwright-skill（截图功能）

## License

MIT
