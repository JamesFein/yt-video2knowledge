<div align="center">

# 📺 YouTube AI Digest

**Let Claude track the latest AI developments for you**

[![Claude Code Skill](https://img.shields.io/badge/Claude%20Code-Skill-blueviolet?style=for-the-badge&logo=anthropic)](https://claude.ai/code)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9+-blue?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)

**English** | [简体中文](./README.md)

---

*Auto-browse subscribed channels, fetch transcripts, generate summary reports — never miss any AI highlights*

</div>

## ✨ Features

- 🔍 **Smart Fetching** — Get latest AI-related videos from subscribed channels
- 📝 **Transcript Extraction** — Auto-download video subtitles (including auto-generated)
- 📊 **Report Generation** — Generate structured Markdown reports
- 🖼️ **Thumbnail Download** — Auto-save video thumbnails

## 🚀 Quick Start

### Installation

**Option 1: Install via Claude Code Plugin (Recommended)**

```bash
# Add marketplace
claude plugin marketplace add https://github.com/yizhiyanhua-ai/youtube-ai-digest

# Install plugin
claude plugin install youtube-ai-digest@youtube-ai-digest
```

**Option 2: Manual Clone**

```bash
# Clone to Claude Code skills directory
git clone https://github.com/yizhiyanhua-ai/youtube-ai-digest.git \
  ~/.claude/skills/youtube-ai-digest
```

**Install Dependencies**

```bash
pip install yt-dlp
```

### Configure Channels

Edit `data/channels.json` to add your subscribed YouTube channels:

```json
{
  "channels": [
    {"name": "Two Minute Papers", "id": "UCbfYPyITQ-7l4upoX8nvctg"},
    {"name": "AI Explained", "id": "UCNJ1Ymd5yFuUPtn21xtRbbw"},
    {"name": "Yannic Kilcher", "id": "UCZHmQk67mN31gbHey6BVyNw"}
  ]
}
```

> 💡 **How to find Channel ID?** Open a YouTube channel page, the URL format is `youtube.com/channel/{CHANNEL_ID}`

### Usage

Chat with Claude Code directly:

```
User: What are the latest AI videos?
User: Summarize the first video
User: Create a report with the key takeaways
```

## 📖 Manual Usage

```bash
# 1. Fetch videos from the past 7 days
python scripts/fetch_videos.py --days 7 --keyword AI

# 2. Get transcript for a specific video
python scripts/get_transcript.py --video-id dQw4w9WgXcQ

# 3. Generate Markdown report
python scripts/generate_report.py --video-id dQw4w9WgXcQ --summary "Your summary here"
```

## 📁 Directory Structure

```
youtube-ai-digest/
├── .claude-plugin/
│   └── marketplace.json  # Plugin marketplace config
├── SKILL.md              # Claude Code skill definition
├── README.md             # Documentation (Chinese)
├── README.en.md          # Documentation (English)
├── scripts/
│   ├── fetch_videos.py   # Fetch channel video list
│   ├── get_transcript.py # Download video transcripts
│   └── generate_report.py# Generate Markdown reports
└── data/
    ├── channels.json     # Subscribed channels config
    ├── videos.json       # Video list cache (auto-generated)
    └── output/           # Report output directory (auto-generated)
```

## 📋 Output Example

```markdown
# Understanding GPT-4's Reasoning

![Thumbnail](thumbnail.webp)

## Video Info
- Channel: AI Explained
- Published: 2024-01-15
- Duration: 12:34
- Link: https://youtube.com/watch?v=...

## Summary
This video provides an in-depth analysis of GPT-4's reasoning capabilities...

## Transcript
[00:00] Welcome back to AI Explained...
[01:30] Today we're going to discuss...
```

## 🔧 Requirements

| Dependency | Version | Description |
|------------|---------|-------------|
| Python | 3.9+ | Runtime environment |
| yt-dlp | latest | YouTube video/subtitle download |

## 🤝 Contributing

Issues and Pull Requests are welcome!

## 📄 License

[MIT License](LICENSE)

---

<div align="center">

**If you find this project helpful, please give it a ⭐ Star!**

</div>
