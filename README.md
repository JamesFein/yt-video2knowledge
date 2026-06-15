# YouTube Knowledge Digest

这是一个只面向 macOS / Apple Silicon 用户的本地项目，用来自动处理 YouTube 播放列表 `knowledge` 中新增的视频，并把结果整理成中文 Markdown 知识笔记。

它的目标不是做一个通用跨平台工具，也不是做插件市场分发包，而是做一套你在自己 Mac 上能稳定长期运行的本地工作流。

## README 和 SKILL 的分工

- `README.md` 是给人看的完整实战手册，负责解释思路、技术栈、踩坑和首次跑通流程。
- `SKILL.md` 是给 agent 调用的执行说明，负责定义何时触发、何时不要触发、默认执行路径和结果汇报方式。

这两个文件现在是刻意分开的：

- 如果你想理解整个项目怎么工作，看 `README.md`
- 如果你想让 agent 在当前仓库里稳定复用这条流程，看 `SKILL.md`

另外，这个仓库现在还提供了一套 **OpenClaw 专用安装副本**：

- 仓库内协作用根目录 `SKILL.md`
- 给本机 OpenClaw 全局注册时，用 `openclaw-skill/youtube-ai-digest/`

这样做的原因是：OpenClaw 的技能目录有自己的路径边界规则，不能稳定地直接把当前仓库外链进去。

## 这个项目现在到底能做什么

当前已经验证通过的主流程是：

1. 读取固定播放列表 `knowledge`
2. 用 YouTube Data API 精确判断视频是哪一天加入播放列表的
3. 优先尝试获取官方字幕
4. 官方字幕拿不到时，再尝试自动字幕
5. 如果连自动字幕都没有，就下载音频并用 `mlx-whisper` 本地转写
6. 把 transcript 交给 OpenAI-compatible 接口生成中文总结
7. 生成日报和单视频总结文档

输出结果会落在：

- `data/runs/YYYY-MM-DD/daily-overview.zh-CN.md`
- `data/runs/YYYY-MM-DD/manifest.json`
- `data/runs/YYYY-MM-DD/videos/<video-id>/summary.zh-CN.md`
- `data/runs/YYYY-MM-DD/videos/<video-id>/transcript.original.txt`
- `data/runs/YYYY-MM-DD/videos/<video-id>/metadata.json`

## 当前真实可用的实现思路

这套系统现在采用的是下面这条已经跑通的链路：

`playlist -> YouTube Data API 判定加入日期 -> Playwright 管理 Chrome profile 并导出 cookies -> yt-dlp 获取视频信息/字幕/音频 -> mlx-whisper 本地转写 -> OpenAI-compatible Responses API 生成中文总结 -> manifest / markdown 落盘`

这个顺序很重要，因为它解决了三个关键问题：

- “哪一天加入播放列表”不能再靠页面猜，必须优先信 YouTube API
- YouTube 私有会话和 cookies 不能靠纯 HTTP 生造，所以浏览器层仍然需要 Playwright
- 转写和总结必须解耦，这样外部总结接口短暂失败时，不会把整批 transcript 一起废掉

## 技术栈与职责分工

这不是简单地把很多工具堆在一起，而是每个组件都承担一个明确角色。

### 1. `Python + uv`

- 项目的主入口和主编排层
- 负责把浏览器、YouTube API、字幕、ASR、总结、落盘这些步骤串起来
- 项目声明的 Python 下限是 `>=3.11`
- 当前真实验证通过、推荐运行的主版本线是 `Python 3.13`
- 所有 Python 依赖由 `pyproject.toml + uv.lock` 锁定
- `uv sync` 会生成和维护 `.venv`，但 `.venv` 只是 uv 管理出来的环境，不再是手工 `pip` 主入口

### 2. `Playwright Python`

- 管理自动化 Chrome profile
- 在浏览器上下文中导出 cookies 给 `yt-dlp`
- 作为页面抓取和浏览器诊断的兜底能力
- 默认使用专用 profile，不直接把当前个人 Chrome 当成长期自动化主路径

### 3. `YouTube Data API + OAuth`

- 用来精确读取 playlist item 的加入时间
- 当前日期判定的真值来源是 `playlistItems`
- 这一步解决了“页面上看不出到底是哪天加入播放列表”的根本问题

### 4. `yt-dlp`

- 获取视频元信息
- 尝试下载官方字幕或自动字幕
- 无字幕时下载音频

### 5. `ffmpeg`

- 只在必要时做音频格式规范化
- 当前默认策略是优先直接把下载到的音频交给 `mlx-whisper`
- 只有转写失败时才回退到 `ffmpeg` 转 wav

### 6. `mlx-whisper`

- 本地 ASR 引擎
- 当前默认模型是 `mlx-community/whisper-small-mlx`
- 选择这个模型的原因是：
  - 对 Apple Silicon 友好
  - 实际测试已经跑通
  - 速度比更大的模型更适合日常批处理

### 7. `OpenAI-compatible Responses API`

- 负责把 transcript 整理成中文 Markdown 总结
- 也负责把多个单视频总结再聚合成日报
- 当前这条网关真实可用的协议是 `/v1/responses`，不是旧的 `/v1/chat/completions`

### 8. `manifest.json` / `metadata.json`

- 负责记录运行状态
- 记录 transcript 来源、字幕探测结果、ASR 回退原因、各阶段耗时
- 也是后续 `--retry-summaries` 补跑的依据
- `manifest.json` 还会记录 `run_mode` 和 `incremental_stats`

## 我们已经验证过的错误方向

下面这些不是理论推演，而是这次真实踩过的坑。README 特意写出来，就是为了以后不要再绕回去。

### 错误方向 1：直接把当前个人 Chrome 的 CDP 当成默认自动化方案

为什么错：

- Chrome 会反复弹“是否允许调试连接”的权限框
- 这种模式不适合每天定时自动化
- 它更适合人工调试，不适合无人值守

正确做法：

- 当前个人 Chrome 的 CDP 只保留给调试
- 默认自动化走专用 Playwright profile

### 错误方向 2：在 Playwright 控制的浏览器里做人机交互式 Google 登录

为什么错：

- Google 会把这种浏览器识别成自动化环境
- 你会看到类似：
  - `this browser or app may not be secure`
  - `Couldn't sign you in`
- 所以“打开 Playwright 浏览器 -> 手工登录 Google”不是可靠路径

正确做法：

- Google 登录动作放在普通 Chrome 或独立 OAuth 授权页里完成
- 项目正式方案是：
  - YouTube Data API 用本机 OAuth 授权
  - 浏览器会话通过克隆普通 Chrome profile 来复用

### 错误方向 3：依赖播放列表页面文本去精确判断“哪一天加入播放列表”

为什么错：

- YouTube 页面经常拿不到稳定、可解析的“加入播放列表时间”
- 即便拿到部分文本，也不适合当作严格判日依据

正确做法：

- 页面只用于浏览器兜底和 cookies 导出
- 精确日期默认必须走 YouTube Data API

### 错误方向 4：继续使用旧式 `/v1/chat/completions`

为什么错：

- 当前你这条网关已经明确返回：
  - `Unsupported legacy protocol: /v1/chat/completions is not supported. Please use /v1/responses.`
- 也就是说协议不是“可能不推荐”，而是“已经不支持”

正确做法：

- 总结接口必须走 `Responses API`
- 这也是当前项目已经切到的真实路径

### 错误方向 5：随便拿别人的 OAuth client JSON 来用

为什么错：

- 很容易遇到 `access_denied`
- 很容易遇到“未验证应用”
- 很容易出现“测试用户没有包含你自己的 Gmail”
- 你看到别的应用名时，往往就说明这个 JSON 根本不是你自己的项目生成的

正确做法：

- 必须使用你自己 Google Cloud 项目里创建的 `Desktop app` OAuth client
- 文件必须放到：
  - `data/youtube-oauth-client.json`

## 重点坑位：如何正确获取 `youtube-oauth-client.json`

这一步是整个项目里最容易踩坑的地方。

你需要的不是任意一个 Google OAuth JSON，而是：

- 你自己 Google Cloud 项目创建的
- 类型为 `Desktop app`
- 对应 YouTube Data API
- 并且你的 Gmail 已被加入测试用户

### 先理解这个文件到底是什么

`youtube-oauth-client.json` 本质上是一个 **Google OAuth Desktop Client 配置文件**。

它不是 token。
它也不是 API key。

它的作用是告诉本地程序：

- 这个 OAuth 应用的 `client_id`
- 这个应用的 `client_secret`
- 应该把用户带去哪里授权
- 授权后 token 应该向哪里换取

真正授权完成后，程序还会再生成另一个文件：

- `data/youtube-oauth-token.json`

这个 token 文件才是后续自动续期和访问 YouTube API 用的。

### 为什么必须是 `Desktop app`

因为这个项目的授权方式是“本机启动一个本地回调端口，然后弹浏览器授权”。

这正是 Google 给桌面程序设计的 OAuth 流程。

如果你用的是别的类型，比如 Web application，就很容易在回调地址、授权策略或者客户端配置上出问题。

### 为什么必须是你自己的 Google Cloud 项目

因为：

- 别人的项目可能还在 `Testing`
- 你自己的 Gmail 可能不在它的 `Test users` 里
- 它的应用名、权限范围、限制策略都不受你控制

这就是为什么我们之前会遇到：

- `access_denied`
- `has not completed the Google verification process`

只要应用还没发布为正式生产，Google 就会限制只有测试用户能访问。

### 一步一步获取正确的 JSON

#### 1. 打开 Google Cloud Console

浏览器打开：

- `https://console.cloud.google.com/`

#### 2. 新建你自己的项目

1. 点击顶部项目选择器
2. 点击 `New Project`
3. 项目名建议填：`yt-video2knowledge`
4. 创建后切换到这个项目

#### 3. 启用 `YouTube Data API v3`

进入：

- `APIs & Services` -> `Library`

然后：

1. 搜索 `YouTube Data API v3`
2. 点进去
3. 点击 `Enable`

#### 4. 配置 OAuth consent screen

进入：

- `APIs & Services` -> `OAuth consent screen`

按下面填写：

1. `User type` 选 `External`
2. 点击继续
3. `App name` 填：`yt-video2knowledge`
4. `User support email` 选你自己的 Gmail
5. `Developer contact information` 填你自己的 Gmail
6. 保存并继续

#### 5. 一定要把你自己加进 `Test users`

这是最关键的坑。

在 `OAuth consent screen` 里找到：

- `Test users`

然后：

1. 点击 `Add users`
2. 填入你自己的 Gmail
3. 保存

如果这一步没做，你后面几乎一定会遇到 403 或 `access_denied`。

#### 6. 创建 OAuth Client

进入：

- `APIs & Services` -> `Credentials`

然后：

1. 点击 `Create Credentials`
2. 选择 `OAuth client ID`
3. `Application type` 选择 `Desktop app`
4. 名字建议填：`yt-video2knowledge-local`
5. 创建

#### 7. 下载 JSON

创建完成后点击 `Download JSON`。

Google 下载下来的文件名通常像这样：

- `client_secret_xxx.apps.googleusercontent.com.json`

#### 8. 把它放到项目指定位置

把下载好的文件复制或改名到：

- `data/youtube-oauth-client.json`

也就是最终路径应该是：

- `/Users/administrator/projects/yt-video2knowledge/data/youtube-oauth-client.json`

### 如何判断这个 JSON 是对的

你可以用文本编辑器打开它，重点看三件事：

1. 顶层应该有 `installed`
2. 里面应该有 `client_id`
3. `client_id` 应该是你自己 Google Cloud 项目生成的，不应该是别人项目的 client

一个正常的结构大概长这样：

```json
{
  "installed": {
    "client_id": "...apps.googleusercontent.com",
    "project_id": "yt-video2knowledge",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token"
  }
}
```

### 如果你拿错了文件，通常会出现什么现象

- 浏览器授权页显示陌生的 app 名字
- Google 提示该应用未验证
- 你的 Gmail 明明是你自己的，却提示没有权限
- 最终报 `403 access_denied`

只要出现这些情况，优先怀疑：

- 不是你自己的 Google Cloud 项目
- 或者测试用户没加你自己

### 这一步的验收标准

做到下面三条，就说明 OAuth 基本打通了：

1. `data/youtube-oauth-client.json` 已就位
2. 运行下面命令：

```bash
uv run python scripts/run_knowledge_digest.py --youtube-auth
```

3. 授权成功后生成：

- `data/youtube-oauth-token.json`

## 项目依赖

### 系统依赖

项目现在用 `Brewfile` 锁定 macOS 系统依赖，推荐直接执行：

```bash
brew bundle
```

当前 Brewfile 至少会安装：

- `uv`
- `yt-dlp`
- `ffmpeg`

### Python 依赖

项目现在用 `pyproject.toml + uv.lock` 锁定 Python 依赖，推荐直接执行：

```bash
uv sync
```

这一步会按锁文件创建并维护项目自己的 `.venv`，保证新机器和当前已验证环境尽量一致。

### 浏览器前提

- 本地已安装 Google Chrome
- 自动化默认用克隆后的 Chrome profile
- `--attach-current-chrome` 只是调试模式，不是正式自动化模式

## 环境变量

先复制模板：

```bash
cp .env.local.example .env.local
```

至少填写：

```bash
OPENAI_API_KEY=...
OPENAI_BASE_URL=...
OPENAI_MODEL=...
```

如果你的网关证书链不被本机 Python 默认信任，可额外加：

```bash
OPENAI_ALLOW_INSECURE_SSL=true
```

## macOS 首次跑通指南

下面这套顺序是当前已经验证过能跑通的路径。

### 第 1 步：确认 Python 版本

```bash
cd /Users/administrator/projects/yt-video2knowledge
python3 --version
```

项目对外声明是 `>=3.11`，但当前实际验证通过并推荐的主运行线是：

- `Python 3.13`

仓库根目录里有一个：

- `.python-version`

它的作用是帮助本地工具自动选择 `3.13`。

### 第 2 步：安装系统依赖

```bash
brew bundle
```

### 第 3 步：安装 Python 依赖

```bash
uv sync
```

### 第 4 步：准备 `.env.local`

```bash
cp .env.local.example .env.local
```

然后填写：

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_MODEL`

### 第 5 步：准备 `youtube-oauth-client.json`

按上一节的方法，从你自己的 Google Cloud 项目下载，并放到：

- `data/youtube-oauth-client.json`

### 第 6 步：执行一次 YouTube OAuth 授权

```bash
uv run python scripts/run_knowledge_digest.py --youtube-auth
```

授权成功后应生成：

- `data/youtube-oauth-token.json`

### 第 7 步：克隆普通 Chrome profile

先完全退出 Google Chrome，然后执行：

```bash
uv run python scripts/run_knowledge_digest.py --seed-from-current-profile
```

### 第 8 步：跑目标日期

例如：

```bash
uv run python scripts/run_knowledge_digest.py --target-date 2026-03-21
```

如果当天已经跑过一次，再次执行同一个 `target-date` 时会默认走增量模式：

- 已经 `summary_ready` 的视频直接复用并跳过
- 新视频和之前非成功状态的视频会继续处理

如果你明确想整天全部重跑：

```bash
uv run python scripts/run_knowledge_digest.py --target-date 2026-03-21 --full-reprocess
```

### 第 9 步：如果总结失败，用补跑模式恢复

```bash
uv run python scripts/run_knowledge_digest.py --target-date 2026-03-21 --retry-summaries
```

如果只想补一条：

```bash
uv run python scripts/run_knowledge_digest.py --target-date 2026-03-21 --retry-summaries --video-id VIDEO_ID
```

如果某条 summary 已经因为临时网络错误达到重试上限，但你确认要再定向尝试一次：

```bash
uv run python scripts/run_knowledge_digest.py --target-date 2026-03-21 --retry-summaries --video-id VIDEO_ID --force-summary-retry
```

如果需要人工接管最后一条 summary，也通过仓库导入，保证 `manifest.json` 和日报同步重建：

```bash
uv run python scripts/run_knowledge_digest.py --target-date 2026-03-21 --video-id VIDEO_ID --adopt-summary-file /absolute/path/to/summary.zh-CN.md
```

## 当前推荐命令清单

### 1. 一次性 OAuth 授权

```bash
uv run python scripts/run_knowledge_digest.py --youtube-auth
```

### 2. 克隆当前 Chrome profile

```bash
uv run python scripts/run_knowledge_digest.py --seed-from-current-profile
```

### 3. 处理某一天加入播放列表的视频

```bash
uv run python scripts/run_knowledge_digest.py --target-date YYYY-MM-DD
```

默认同日重复执行会增量处理，只补新视频和非成功视频。

### 4. 强制整天全量重跑

```bash
uv run python scripts/run_knowledge_digest.py --target-date YYYY-MM-DD --full-reprocess
```

### 5. 显式允许旧的 `first_seen` 回退逻辑

```bash
uv run python scripts/run_knowledge_digest.py --target-date YYYY-MM-DD --allow-fallback-first-seen
```

### 6. 补跑待总结视频

```bash
uv run python scripts/run_knowledge_digest.py --target-date YYYY-MM-DD --retry-summaries
```

### 7. 定向恢复卡住的单条总结

```bash
uv run python scripts/run_knowledge_digest.py --target-date YYYY-MM-DD --retry-summaries --video-id VIDEO_ID --force-summary-retry
```

### 8. 导入人工摘要并重建运行状态

```bash
uv run python scripts/run_knowledge_digest.py --target-date YYYY-MM-DD --video-id VIDEO_ID --adopt-summary-file /absolute/path/to/summary.zh-CN.md
```

## 给 OpenClaw 安装并调用这个 Skill

这个项目现在支持把一份 **OpenClaw 专用 skill 副本** 安装到你本机的：

- `~/.openclaw/skills/youtube-ai-digest`

### 为什么要单独装一份 OpenClaw skill

因为你真正使用的软件是 `openclaw`，而且它的技能加载有两个现实约束：

- 它认自己的 managed skills 目录：`~/.openclaw/skills`
- 如果 skill 路径解析到配置根目录之外，日志里会出现：
  - `Skipping skill path that resolves outside its configured root`

所以最稳的方式不是把当前仓库软链接进去，而是安装一份真实的 OpenClaw skill 副本。

### 安装 OpenClaw skill

在仓库根目录执行：

```bash
bash scripts/install_openclaw_skill.sh
```

这个脚本会把仓库里的模板目录：

- `openclaw-skill/youtube-ai-digest/`

复制到：

- `~/.openclaw/skills/youtube-ai-digest/`

### 安装后如何验证

执行下面三条命令：

```bash
openclaw skills list --json
openclaw skills check --json
openclaw skills info youtube-ai-digest
```

你应该能看到：

- `youtube-ai-digest` 出现在 skills 列表里
- 不再因为安装方式触发路径越界报错
- `info` 里能看到它的描述和来源

### OpenClaw 里怎么调用

这个 skill 现在支持三种你会实际使用的入口：

#### 1. GUI

在 OpenClaw GUI 里直接说这类话：

- `处理 knowledge 播放列表昨天新增的视频，给我中文日报`
- `knowledge 列表里昨天那批视频帮我补一下总结`
- `把 2026-03-21 新加的视频都整理成知识笔记`

#### 2. Telegram

Telegram 里可以更短一点，但最好保留这些关键词中的几个：

- `knowledge`
- `昨天新增`
- `中文日报`
- `补跑总结`
- `无字幕转写`

例如：

- `knowledge 昨天新增的视频帮我跑一下，出中文日报`
- `knowledge 那条没字幕的视频也继续转写`

#### 3. CLI

CLI 可以显式点名 skill 意图，最直接的模板是：

```bash
openclaw agent --local --message "请用 youtube-ai-digest 处理 knowledge 播放列表 2026-03-21 新增的视频，并生成中文日报。"
```

如果你要补跑总结，可以这样说：

```bash
openclaw agent --local --message "请用 youtube-ai-digest 补跑 knowledge 播放列表 2026-03-21 那批视频里待补的中文总结，不要重新下载全部视频。"
```

### OpenClaw skill 实际调用的是什么

OpenClaw 版 skill 自己不重写业务逻辑，它只是一个很薄的包装层。

它最终固定调用的还是当前仓库：

- `/Users/administrator/projects/yt-video2knowledge`

实际运行入口仍然是：

- `uv run python scripts/run_knowledge_digest.py ...`

这样做的好处是：

- OpenClaw 全局能发现这个 skill
- 业务逻辑仍只有当前仓库这一份，不会出现双份实现漂移
- GUI / Telegram / CLI 三个入口最终都走同一套脚本和配置
```

## 常见报错速查

### 1. `Missing dependencies for YouTube Data API OAuth`

原因：

- 你还没有执行 `uv sync`
- 或当前环境不是按 `uv.lock` 创建出来的

怎么做：

```bash
uv sync
```

### 2. Google `access_denied` / 未验证 app / 403

原因：

- `youtube-oauth-client.json` 不是你自己的项目生成的
- 或者你的 Gmail 没有被加入 `Test users`

怎么做：

- 回到 Google Cloud Console
- 确认用的是你自己的项目
- 确认你自己的 Gmail 已加入 `Test users`
- 重新下载 `Desktop app` 类型的 JSON

### 3. `Unsupported legacy protocol: /v1/chat/completions`

原因：

- 当前网关不支持旧的 chat completions 协议

怎么做：

- 使用项目当前版本
- 当前版本已经切到 `Responses API`

### 4. `CERTIFICATE_VERIFY_FAILED`

原因：

- 你的 OpenAI-compatible 网关证书链不被本机 Python 默认信任

怎么做：

在 `.env.local` 里加入：

```bash
OPENAI_ALLOW_INSECURE_SSL=true
```

### 5. Playwright 浏览器打开 YouTube 异常

原因：

- 自动化 profile 状态异常
- 或 profile 不是从你当前可用的普通 Chrome 克隆来的

怎么做：

1. 完全退出 Chrome
2. 重新执行：

```bash
uv run python scripts/run_knowledge_digest.py --seed-from-current-profile
```

如果仍失败，检查：

- `data/browser-diagnostics/`

### 6. 跑了一个日期却命中 `0` 条，但你觉得应该有视频

原因：

- 严格模式下，项目会信 YouTube API 返回的 playlist-added 日期
- 这和视频发布日期不是一回事
- 也可能和你记忆中的“昨天”不一致

怎么做：

- 先检查当天 `manifest.json`
- 确认 YouTube API 返回的 `playlist_added_date`
- 如果只是想做增量兜底，而不是严格判日，可显式加：

```bash
--allow-fallback-first-seen
```

## 输出文件说明

### 1. `daily-overview.zh-CN.md`

- 当天所有处理成功视频的日报总览

### 2. `manifest.json`

- 当天批处理的总清单
- 可看到：
  - `run_mode`
  - `incremental_stats`
  - `summary_ready_count`
  - `pending_summary_count`
  - `failed_count`
  - `needs_review_count`

### 3. `videos/<video-id>/metadata.json`

- 每条视频的详细状态
- 可以看到：
  - `transcript_source`
  - `official_subtitle_available`
  - `auto_subtitle_available`
  - `fallback_reason`
  - `summary_error`
  - 各阶段耗时

## 这个项目现在的实际结论

截至目前，这个项目已经验证过下面这些关键能力：

- YouTube OAuth 已打通
- YouTube API 精确判日已打通
- Playwright + 克隆 Chrome profile 已打通
- `yt-dlp` 字幕优先策略已打通
- `mlx-whisper` 本地转写已打通
- Responses API 中文总结已打通
- `--retry-summaries` 补跑机制已打通

如果你后续继续维护这个项目，最值得优先保持稳定的三件事是：

1. `youtube-oauth-client.json` 和 `youtube-oauth-token.json` 的本地有效性
2. Chrome profile 克隆链路的可用性
3. OpenAI-compatible 网关是否继续支持当前 `Responses API`

现在再补一条新的环境管理事实来源顺序：

1. `pyproject.toml`
2. `uv.lock`
3. `Brewfile`

以后如果环境出问题，优先检查这三处，而不是先看 `.venv` 里装了什么。
