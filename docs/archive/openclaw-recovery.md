# 2026-06-24 OpenClaw 视频恢复复盘

> **文档性质**：这是一次历史故障复盘，不是当前操作手册，也不能作为当前依赖版本的依据。当前恢复行为以仓库 [`SKILL.md`](../../SKILL.md)、真实 CLI、正式代码和相关 ADR 为准；OpenClaw queue worker 位于仓库外的 `~/.openclaw/workspace/automation/knowledge-digest/`。

## 复盘结论

2026-06-24 这批视频最初是部分成功、部分失败：一共有 34 个视频，最开始 19 个处理成功，15 个失败。失败集中在“获取字幕/下载音频/转写”之前，不是摘要生成阶段失败。

最终通过临时 yt-dlp 恢复环境逐个补跑失败视频后，当天 manifest 已恢复为成功状态：

- `processed_count = 34`
- `failed_count = 0`
- `pending_summary_count = 0`
- `completion_status = success`
- Knowledge Site 同步记录显示 2026-06-24 已导入 34 条视频

## 问题是什么

OpenClaw 调用 Digest 流程处理 YouTube 视频时，需要先拿到字幕，或者下载音频后用本地 Whisper 转写。6 月 24 日失败的视频卡在这个入口阶段，典型错误是 `yt-dlp` 请求 YouTube 音视频流时返回 `HTTP 403 Forbidden`。

这表示 YouTube 没有允许当前下载请求访问真实媒体流。它通常不等于视频被删除，也不等于 LLM 摘要接口坏了，而是 YouTube 对媒体链接、浏览器登录态、客户端挑战或 token 校验更严格了。

因此，单纯重跑摘要没有意义。`pending_summary_count = 0` 说明没有“已有 transcript 但摘要没生成”的视频；真正缺的是 transcript/audio。

## 尝试过的方案

1. 先确认 manifest 和产物目录

   失败视频大多只有缩略图，没有 `transcript.original.txt`、`summary.zh-CN.md` 和 `report.md`，说明失败点在转写/摘要之前。

2. 停掉重复的旧补跑进程

   避免多个 digest 进程同时写同一个日期的 manifest，造成状态混乱。

3. 用稳定版 `yt-dlp 2026.06.09` 加 Chrome cookies 探测

   重新登录 YouTube 后，稳定版 `yt-dlp` 能看到音频/视频格式，但直接下载仍然遇到 `HTTP 403`。

4. 尝试 `yt-dlp nightly 2026.06.24.234707`

   nightly 在这台机器上效果更差：有些视频只能看到 storyboard，拿不到可用音频格式。因此没有把 nightly 作为主路径。

5. 搭建临时 PO Token / EJS 恢复环境

   在 `/tmp/openclaw-pot-ytdlp` 创建临时 venv，使用稳定版 `yt-dlp`、当前 Chrome 登录态、`bgutil-ytdlp-pot-provider` 相关组件，以及 EJS challenge solver。这个组合成功下载了测试视频 `Iqs6MCfGPEY` 的音频。

## 最终解决方案

最终可用的恢复路径是：

1. 使用你重新登录后的 Chrome 登录态，而不是旧 cookie 文件。
2. 使用稳定版 `yt-dlp 2026.06.09`，不使用 nightly 作为主路径。
3. 在临时环境中启用 YouTube challenge 处理组件，让 `yt-dlp` 能拿到仍然有效的媒体 URL。
4. 先用一个失败视频做下载探测，确认可下载音频。
5. 只对 manifest 里失败的视频逐个 `--video-id` 补跑，而不是重跑整天。
6. 每处理完一批后检查 `manifest.json` 和 `knowledge.sqlite3` 的同步记录。

这次恢复没有修改 digest 主代码。临时工具、日志和 provider 环境都放在 `/tmp`。最终结果以 `data/runs/2026-06-24/manifest.json` 为准。

## 当前 implementation 对应位置

| 问题 | 当前第一检查点 |
| --- | --- |
| Playlist Entry 和 Target Date | `src/yt_video2knowledge/digest/playlist.py` |
| 字幕、音频下载、ASR 和清理 | `src/yt_video2knowledge/digest/transcript.py` |
| Video Summary 和 retry metadata | `src/yt_video2knowledge/digest/summary.py` |
| Digest Run 完成与恢复 | `src/yt_video2knowledge/digest/manifest.py` |
| 整体编排 | `src/yt_video2knowledge/digest/run.py` |
| OpenClaw 排队和 worker 状态 | `~/.openclaw/workspace/automation/knowledge-digest/` |

当前正式恢复入口是：

```bash
uv run yt-video2knowledge digest --target-date YYYY-MM-DD --retry-summaries
uv run yt-video2knowledge digest --target-date YYYY-MM-DD --video-id VIDEO_ID
uv run yt-video2knowledge recover-manifest --target-date YYYY-MM-DD
```

不要恢复已经删除的脚本式入口，也不要把仓库外 queue worker 的实现复制回 `src/`。

## 后续判断规则

如果以后再遇到类似问题，可以先用下面的心智模型判断：

- `pending_summary_count > 0`：通常是 transcript 已有，但摘要阶段没完成，应该补跑摘要。
- `transcript_failed_count > 0` 或视频目录没有 transcript：通常是字幕/音频下载/转写阶段失败，应该先查 `yt-dlp`、cookies、YouTube 访问策略。
- `HTTP 403` 出现在 `yt-dlp` 下载媒体流时：优先检查 Chrome 登录态、cookies、yt-dlp 稳定版、challenge/PO token 相关组件。
- nightly 不一定更好；它只是更新，不代表在当前 YouTube 行为下更稳定。
- 不要让多个补跑进程同时处理同一天 manifest。

## 术语表

- OpenClaw：本机自动化入口，负责触发或调度这个 YouTube Digest 工作流。完整 queue/worker implementation 位于仓库外。
- Digest workflow：把 YouTube 视频变成 transcript、中文摘要、报告和 Knowledge Site 数据的整条流水线。
- Manifest：`data/runs/YYYY-MM-DD/manifest.json`，记录某天每个视频的处理状态，是判断成功与否的主要依据。
- `processed_count`：manifest 中已经完整处理成功的视频数量。
- `failed_count`：manifest 中仍然失败的视频数量。
- `pending_summary_count`：已经有 transcript，但中文摘要还没完成的视频数量。
- `transcript_failed_count`：在字幕获取、音频下载或本地转写阶段失败的视频数量。
- yt-dlp：用于读取 YouTube 元数据、字幕和音视频流的命令行工具。
- yt-dlp stable：yt-dlp 的正式稳定版。这次稳定版 `2026.06.09` 比 nightly 更适合作为主路径。
- yt-dlp nightly：yt-dlp 的每日/实验构建，更新更快，但不保证对当前环境更稳定。
- Cookies：浏览器保存的登录态信息。yt-dlp 可以借用 Chrome cookies，以登录用户身份访问 YouTube。
- `--cookies-from-browser chrome`：让 yt-dlp 直接读取 Chrome 登录态的方式。
- HTTP 403 Forbidden：服务器拒绝当前请求。这里表示 YouTube 拒绝了媒体流下载请求。
- Format：YouTube 对同一个视频提供的具体音频或视频流版本，例如不同清晰度或编码格式。
- Storyboard：视频预览缩略图序列，不是真正的音频或视频内容，不能用于转写。
- EJS challenge solver：帮助 yt-dlp 处理 YouTube JavaScript 挑战的组件，使媒体链接保持可用。
- PO Token：Proof-of-Origin token，YouTube 用来验证请求来源/客户端可信度的一类 token。
- PO Token provider：给 yt-dlp 提供 PO Token 的辅助服务或插件，例如 `bgutil-ytdlp-pot-provider`。
- MLX Whisper：本机 Apple Silicon 上运行的语音转文字工具，用来在没有字幕时从音频生成 transcript。
- Knowledge Site sync：把成功生成的摘要和报告导入 `data/knowledge.sqlite3`，供本地知识站点展示。
