<div align="center">

# 📺 YouTube AI Digest

**让 Claude 帮你追踪 AI 领域最新动态**

[![Claude Code Skill](https://img.shields.io/badge/Claude%20Code-Skill-blueviolet?style=for-the-badge&logo=anthropic)](https://claude.ai/code)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9+-blue?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)

[English](./README.en.md) | **简体中文**

---

*自动浏览订阅频道、获取字幕、生成摘要报告 — 再也不错过任何 AI 热点*

</div>

## ✨ 功能特性

- 🔍 **智能抓取** — 从订阅频道获取最新 AI 相关视频
- 📝 **字幕提取** — 自动下载视频字幕（支持自动生成字幕）
- 📊 **报告生成** — 生成结构化的 Markdown 报告
- 🖼️ **缩略图下载** — 自动保存视频封面

## 🚀 快速开始

### 安装

**方式一：通过 Claude Code Plugin 安装（推荐）**

```bash
# 添加 marketplace
claude plugin marketplace add https://github.com/yizhiyanhua-ai/youtube-ai-digest

# 安装插件
claude plugin install youtube-ai-digest@youtube-ai-digest
```

**方式二：手动克隆**

```bash
# 克隆到 Claude Code 技能目录
git clone https://github.com/yizhiyanhua-ai/youtube-ai-digest.git \
  ~/.claude/skills/youtube-ai-digest
```

**安装依赖**

```bash
pip install yt-dlp
```

### 配置频道

编辑 `data/channels.json` 添加你关注的 YouTube 频道：

```json
{
  "channels": [
    {"name": "Two Minute Papers", "id": "UCbfYPyITQ-7l4upoX8nvctg"},
    {"name": "AI Explained", "id": "UCNJ1Ymd5yFuUPtn21xtRbbw"},
    {"name": "Yannic Kilcher", "id": "UCZHmQk67mN31gbHey6BVyNw"}
  ]
}
```

> 💡 **如何获取频道 ID？** 打开 YouTube 频道页面，URL 格式为 `youtube.com/channel/{CHANNEL_ID}`

### 使用方式

在 Claude Code 中直接对话：

```
用户: 今天有什么 AI 新视频？
用户: 总结一下第一个视频
用户: 把这个视频的要点整理成报告
```

## 📖 手动使用

```bash
# 1. 获取最近 7 天的视频列表
python scripts/fetch_videos.py --days 7 --keyword AI

# 2. 获取指定视频的字幕
python scripts/get_transcript.py --video-id dQw4w9WgXcQ

# 3. 生成 Markdown 报告
python scripts/generate_report.py --video-id dQw4w9WgXcQ --summary "视频摘要内容"
```

## 📁 目录结构

```
youtube-ai-digest/
├── .claude-plugin/
│   └── marketplace.json  # Plugin marketplace 配置
├── SKILL.md              # Claude Code 技能定义
├── README.md             # 说明文档（中文）
├── README.en.md          # 说明文档（英文）
├── scripts/
│   ├── fetch_videos.py   # 获取频道视频列表
│   ├── get_transcript.py # 下载视频字幕
│   └── generate_report.py# 生成 Markdown 报告
└── data/
    ├── channels.json     # 订阅频道配置
    ├── videos.json       # 视频列表缓存（自动生成）
    └── output/           # 报告输出目录（自动生成）
```

## 📋 输出示例

```markdown
# Understanding GPT-4's Reasoning

![封面](thumbnail.webp)

## 视频信息
- 频道: AI Explained
- 发布时间: 2024-01-15
- 时长: 12:34
- 链接: https://youtube.com/watch?v=...

## 内容摘要
本视频深入分析了 GPT-4 的推理能力...

## 字幕内容
[00:00] Welcome back to AI Explained...
[01:30] Today we're going to discuss...
```

## 🔧 依赖要求

| 依赖 | 版本 | 说明 |
|------|------|------|
| Python | 3.9+ | 运行环境 |
| yt-dlp | latest | YouTube 视频/字幕下载 |

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

[MIT License](LICENSE)

---

<div align="center">

**如果这个项目对你有帮助，请给个 ⭐ Star！**

</div>
