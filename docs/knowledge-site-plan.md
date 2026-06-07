# FastAPI + Jinja2 + SQLite 知识站方案

## 关键设计意图

**存储与展示分离：**

- 每个视频的原始 summary 是一条完整的 Markdown 字符串，存储在 `videos.summary_markdown` 一个字段中。不拆分、不持久化 block。
- 每个视频有一条用户 curated 的 **meta-summary**（精华版个人总结），存储在 `video_meta_summaries.content`。这是用户从原始 summary 中挑选、编辑后产出的"精华版"。
- **Block 拆分是渲染时的 UI 行为，不是存储概念。** `markdown_blocks.py` 在页面渲染时把 `summary_markdown` 按标题拆成块，前端渲染为带 checkbox 的卡片。用户勾选感兴趣的块、累积选择、点击按钮写入 meta-summary 编辑区。Block 不存入 SQLite，不存 content_hash，刷新页面后勾选状态不保留。

**数据生命周期：**

- `data/runs/YYYY-MM-DD/` 是流水线的临时输出。同步脚本从中读取数据导入 SQLite 和 asset 目录，导入完成后 run 目录可以删除。站点运行时只依赖 SQLite + `data/knowledge-assets/`。
- summary 和 meta-summary 是长期数据，存在 SQLite。
- transcript 是独立文件资产，不写入 SQLite 正文，只保存文件路径。

---

## Summary

首版做个人私用知识站，使用 `FastAPI + Jinja2 + SQLite + 单一共享密码`。站点展示每日总览、视频总结，并为每个视频提供一条可编辑的 meta-summary（精华版个人总结）。

数据策略：

- `data/runs/YYYY-MM-DD/` 只作为同步脚本的临时输入来源。
- 同步完成后，知识站长期依赖：
  - `data/knowledge.sqlite3`：保存 daily summary、video summary、meta-summary、视频元数据。
  - `data/knowledge-assets/`：保存 transcript 等独立资产文件。
- `data/runs` 不作为站点运行依赖；导入完成后可以删除。
- transcript 不写入 SQLite 正文，只复制到资产目录并在 SQLite 中保存路径。
- logs 不导入 SQLite。

---

## Directory Structure

```text
knowledge_site/
  main.py
  config.py
  auth.py
  database.py
  markdown_blocks.py
  sync.py
  routes/
    pages.py
    api_v1.py
  templates/
    base.html
    login.html
    index.html
    day.html
    video.html
  static/
    site.css
    site.js

scripts/
  sync_knowledge_site.py

data/
  knowledge.sqlite3
  knowledge-assets/
    transcripts/
    thumbnails/

tests/
  test_knowledge_site_sync.py
  test_knowledge_site_api.py
```

职责划分：

- `main.py`：创建 FastAPI app，挂载页面路由、API 路由、静态资源。
- `config.py`：读取环境变量和默认路径。
- `auth.py`：处理单一共享密码、session 登录状态。
- `database.py`：SQLite 连接、schema 初始化、轻量 schema version 管理。
- `markdown_blocks.py`：**渲染时**把视频 summary Markdown 按标题拆成可选择文本块，供模板渲染。不涉及 SQLite 写入。
- `sync.py`：从 `data/runs` 导入 SQLite，并复制 transcript/thumbnail 到 `data/knowledge-assets`。
- `routes/pages.py`：Jinja2 页面路由。
- `routes/api_v1.py`：JSON API，统一使用 `/api/v1` 前缀。
- `scripts/sync_knowledge_site.py`：命令行同步入口。

---

## Data Model

### `days`

保存每日总览。

- `date TEXT PRIMARY KEY`（格式 `YYYY-MM-DD`）
- `daily_summary_markdown TEXT NOT NULL`
- `source_path TEXT`（相对于项目根目录的路径）
- `source_mtime INTEGER`
- `synced_at TEXT NOT NULL`

### `videos`

保存视频级展示数据。**`summary_markdown` 是一个完整的 Markdown 字符串，不拆分存储。**

- `id TEXT PRIMARY KEY`
- `title TEXT NOT NULL`
- `url TEXT NOT NULL`
- `channel_name TEXT`
- `upload_date TEXT`（格式 `YYYY-MM-DD`，同步时从 `YYYYMMDD` 转换）
- `duration_seconds INTEGER`
- `duration_label TEXT`
- `summary_markdown TEXT NOT NULL`（视频原始总结，完整 Markdown 一个字段）
- `summary_source_path TEXT`（相对于项目根目录）
- `metadata_source_path TEXT`（相对于项目根目录）
- `transcript_asset_path TEXT`（相对于项目根目录）
- `thumbnail_asset_path TEXT`（相对于项目根目录）
- `transcript_source TEXT`
- `transcript_language TEXT`
- `processing_status TEXT NOT NULL`
- `synced_at TEXT NOT NULL`

### `day_videos`

保存日期和视频的关联，允许同一视频出现在多个日期。

- `day_date TEXT NOT NULL REFERENCES days(date) ON DELETE CASCADE`
- `video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE`
- `position INTEGER NOT NULL`
- `playlist_added_at TEXT`
- `playlist_item_id TEXT`
- Primary key: `(day_date, video_id)`
- Unique: `(day_date, position)`

### `video_meta_summaries`

每个视频有且只有一条 meta-summary。**meta-summary 是该视频的"精华版个人总结"**——用户浏览原始 summary 后，勾选感兴趣的段落，累积写入编辑区，再手动精炼得到的内容。

- `video_id TEXT PRIMARY KEY REFERENCES videos(id) ON DELETE CASCADE`
- `content TEXT NOT NULL DEFAULT ''`
- `created_at TEXT NOT NULL`
- `updated_at TEXT NOT NULL`

meta-summary 语义：

- meta-summary 是视频 summary 的精华版本，由用户从原始 summary 中挑选、编辑而成。
- meta-summary 只保存纯文本。
- 视频导入时自动创建空 meta-summary（`content = ""`）。
- 清空 meta-summary 等价于把 `content` 更新为空字符串。
- 不提供 meta-summary 创建或删除概念。

### `sync_runs`

保存同步批次的聚合诊断信息，不保存 logs。

- `id INTEGER PRIMARY KEY`
- `source_root TEXT NOT NULL`
- `started_at TEXT NOT NULL`
- `finished_at TEXT`
- `days_scanned INTEGER NOT NULL`
- `days_imported INTEGER NOT NULL`
- `videos_imported INTEGER NOT NULL`
- `summary_ready_count INTEGER NOT NULL`
- `skipped_pending_count INTEGER NOT NULL`
- `skipped_failed_count INTEGER NOT NULL`

索引策略：

- 所有外键列建立索引。
- `day_videos(day_date, position)` 支持日期页排序。
- 首版不建立全文搜索索引。

---

## Sync Behavior

同步命令：

`uv run python3 scripts/sync_knowledge_site.py`

同步输入：

```text
data/runs/YYYY-MM-DD/
  daily-overview.zh-CN.md
  manifest.json
  videos/<video-id>/
    summary.zh-CN.md
    metadata.json
    transcript.original.txt
    thumbnail.webp（或 .jpg / .jpeg / .png）
```

同步规则：

- 只展示并导入 `processing_status = "summary_ready"` 的视频。
- `pending_summary` 和 `transcript_failed` 不进入视频列表，分别计入 `sync_runs.skipped_pending_count` 和 `sync_runs.skipped_failed_count`。
- 空日期（0 个视频的 run 目录）也导入 `days` 表，`/days/{date}` 页面展示概览但提示无视频。
- daily overview 导入 `days.daily_summary_markdown`。
- video summary 导入 `videos.summary_markdown`（完整 Markdown，一个字段）。
- 每个导入视频都确保存在一条 `video_meta_summaries`（`content` 初始为空字符串）。
- `duration` 优先从 `metadata.json` 的 `duration` 字符串解析为秒，原始字符串存入 `duration_label`。manifest.json 太大，不作为主要数据源。
- `upload_date` 从 `metadata.json` 的 `YYYYMMDD` 格式转换为 `YYYY-MM-DD`。
- 重复同步时，更新 `days/videos/day_videos`。
- 重复同步时，**不覆盖**已有 `video_meta_summaries.content`。
- transcript 从 `data/runs/videos/<id>/transcript.original.txt` 复制到 `data/knowledge-assets/transcripts/{video_id}.txt`。
- thumbnail 从 `data/runs/videos/<id>/` 匹配 `thumbnail.*`（优先 `.webp` > `.jpg` > `.jpeg` > `.png`），复制到 `data/knowledge-assets/thumbnails/{video_id}.{ext}`。
- SQLite 只保存 asset 路径，路径统一相对于项目根目录。
- `report.md` 是流水线遗留的重复文件（与 `summary.zh-CN.md` 内容相同），同步脚本忽略。
- VTT 字幕文件不导入。
- 同步完成后，站点不再依赖 `data/runs`，因此对应 run 目录可以删除。

---

## Web Interfaces

页面路由：

- `GET /login`
- `POST /login`
- `POST /logout`
- `GET /`
- `GET /days/{date}`
- `GET /videos/{video_id}`

页面行为：

- `/`：按日期倒序列出所有已导入日期，每个日期展示 daily overview 摘要入口。
- `/days/{date}`：展示当天 `summary_ready` 视频列表。
- `/videos/{video_id}`：展示视频 summary（按标题拆分为可勾选的 block）和该视频的 meta-summary 编辑区。
- 未登录访问页面时跳转到 `/login`。
- 登录使用单一共享密码，不做用户账号。

API 路由：

- `GET /api/v1/videos/{video_id}/meta-summary`
- `PUT /api/v1/videos/{video_id}/meta-summary`

API 语义：

- `GET meta-summary` 返回该视频的 meta-summary。请求体空，响应 `{"video_id": "...", "content": "...", "updated_at": "..."}`。
- `PUT meta-summary` 替换整条 meta-summary 内容。Content-Type: `application/json`，请求体 `{"content": "纯文本内容"}`，响应 `{"video_id": "...", "content": "...", "updated_at": "..."}`。
- `content=""` 表示清空 meta-summary。
- 未登录访问 API 返回 `401`。
- 视频不存在返回 `404`。
- 不提供 `POST meta-summary`，因为 meta-summary 随视频自动存在。
- 不提供 `DELETE meta-summary`，因为清空内容即可。

---

## Meta-Summary 交互

视频页的 UI 交互：

```
┌─ Summary 区（只读展示）───────────────────────┐
│                                                │
│  ☑ ## 一句话总结                                │
│    XXX 发布了 YYY，核心观点是...                 │
│                                                │
│  ☐ ## 关键观点                                  │
│    观点一：...                                   │
│    观点二：...                                   │
│                                                │
│  ☑ ### 可执行启发                               │
│    启发一：...                                   │
│                                                │
│  [将选中内容写入 Meta Summary]                   │
│                                                │
└────────────────────────────────────────────────┘

┌─ Meta Summary 区（可编辑）────────────────────┐
│                                                │
│  ┌──────────────────────────────────────┐      │
│  │ 用户勾选的 block 纯文本累积追加到这里    │      │
│  │ 可继续手动编辑...                      │      │
│  └──────────────────────────────────────┘      │
│                                                │
│  [保存]  [清空]                                 │
│                                                │
└────────────────────────────────────────────────┘
```

交互细节：

- `markdown_blocks.py` 在渲染时把 `videos.summary_markdown` 按 H2/H3 标题拆分为 block 列表，每个 block 带有 `heading_level`、`heading_text`、`heading_path`、`plain_text`。传给 Jinja2 模板渲染为带 checkbox 的卡片。
- 用户可以勾选任意 block（一级标题、二级标题、三级标题的整块内容均可）。
- 勾选是**累加的**——用户可以分多次选择 block，每次点击"写入"按钮都将选中 block 的 `plain_text` 追加到 meta-summary 编辑区末尾。
- 编辑区支持手动编辑修改。
- 点击"保存"调用 `PUT /api/v1/videos/{video_id}/meta-summary`，整体替换 meta-summary。
- 点击"清空"把编辑区置为空字符串并保存。
- 页面刷新后，block 勾选状态不保留（block 不持久化），但 meta-summary 内容保留。

前端只需要保留纯文本，不保存 Markdown AST、富文本结构或 block 引用关系。

---

## Authentication & Security

部署拓扑：本机 HTTP 服务（`localhost:8000`）→ Cloudflare Tunnel → 公网 HTTPS。

- 鉴权方式：单一共享密码，密码通过 `KNOWLEDGE_SITE_PASSWORD` 环境变量提供。
- 登录成功后，使用 FastAPI `SessionMiddleware` 写入 session cookie。
- Cookie 名称：`knowledge_site_session`。
- Session 有效期：15 天（`max_age = 60 * 60 * 24 * 15`）。
- Cookie 属性：`HttpOnly=True`、`SameSite=Lax`、`Secure=True`（公网通过 Cloudflare Tunnel 访问的是 HTTPS）。
- `secret_key` 必须来自 `KNOWLEDGE_SITE_SECRET_KEY` 环境变量，不允许硬编码。
- 本地开发时设置 `KNOWLEDGE_SITE_DEV=1` 环境变量，关闭 `Secure` 以支持 `http://localhost:8000` 访问。
- CSRF 策略：v1 不额外实现 CSRF token。依赖 `SameSite=Lax` 防护。后续如需多人使用或跨站场景再评估。

---

## Environment Variables

- `KNOWLEDGE_SITE_PASSWORD`：登录密码，必须由环境变量提供。
- `KNOWLEDGE_SITE_SECRET_KEY`：session 签名密钥，公网部署必须提供。
- `KNOWLEDGE_SITE_DB`：可选，默认 `data/knowledge.sqlite3`。
- `KNOWLEDGE_SITE_ASSETS_DIR`：可选，默认 `data/knowledge-assets`。
- `KNOWLEDGE_SITE_DEV=1`：本地开发模式，关闭 cookie `Secure` 标志以支持 localhost HTTP 访问。

---

## Schema Migration

- `database.py` 创建 `schema_version` 表（单行单列），记录当前数据库的 schema 版本号。
- 启动时检查 `schema_version` 是否与代码中定义的版本一致。不一致则拒绝启动，打印人类可读的迁移说明。
- v1 不做自动迁移，v2 再实现迁移脚本机制。
- 不使用 Alembic。

---

## Test Plan

同步测试：

- 能导入 `daily-overview.zh-CN.md` 到 `days`。
- 只导入 `summary_ready` 视频。
- `pending_summary` 和 `transcript_failed` 不进入视频列表。
- 空日期（0 视频）也导入 `days`。
- 同一 video 出现在多个日期时，`videos` 只有一条，`day_videos` 有多条。
- 重新同步更新 summary，但保留 meta-summary。
- 每个导入视频自动拥有一条空 meta-summary。
- transcript 被复制到 `knowledge-assets/transcripts/{video_id}.txt`，SQLite 只保存路径。
- thumbnail 按 `thumbnail.*` 通配匹配，复制到 `knowledge-assets/thumbnails/{video_id}.{ext}`。
- 删除 `data/runs` 后，页面仍可从 SQLite 和 assets 正常展示。
- logs 不进入 SQLite。
- `report.md` 被忽略。

数据约束测试：

- 每个 video 有且只有一条 `video_meta_summaries`。
- 删除 video 会级联删除 meta-summary。
- `day_videos(day_date, video_id)` 防重复。

API 测试：

- 未登录页面跳转登录。
- 未登录 API 返回 `401`。
- 正确密码可登录。
- 错误密码不可登录。
- `GET /api/v1/videos/{video_id}/meta-summary` 返回空字符串或已有内容。
- `PUT /api/v1/videos/{video_id}/meta-summary` 可替换内容。
- `PUT meta-summary` 传空字符串可清空内容。
- 不实现 `POST meta-summary` 和 `DELETE meta-summary`。

回归测试：

- 继续运行现有测试命令：`uv run python3 -m unittest`

---

## Non-Goals

首版明确不做：

- 不做多用户、账号体系、角色权限。
- 不把 summary 拆成 block 持久化存储（block 拆分是渲染时的 UI 行为）。
- 不显示 transcript 正文。
- 不把 transcript 正文写入 SQLite。
- 不把 logs、原始错误日志、完整 processing details 写入 SQLite。
- 不把 `data/runs` 作为长期运行依赖。
- 不导入 VTT 字幕文件。
- 不导入 `report.md`（流水线遗留重复文件）。
- 不做全文搜索。
- 不做标签、收藏、评论、分享链接。
- 不做 daily overview 的 meta-summary。
- 不做 meta-summary per block（每个视频只有一条 meta-summary）。
- 不做段落批注。
- 不做 meta-summary 删除接口。
- 不引入 SQLAlchemy、Alembic。
- 不引入 Django、Flask、PGLite。
- 不改现有 YouTube 摘要生成流水线。
- 不做自动重新总结。
- 不做 AI 改写 meta-summary。
- 不做 AI 合并 meta-summary。

---

## Assumptions

- 首版服务对象是个人私用。
- 单一共享密码足够。
- 部署在本机，通过 Cloudflare Tunnel 对外提供 HTTPS 访问。
- SQLite 是知识站长期数据源。
- `data/runs` 是同步临时输入，导入后可删除。
- summary 和 meta-summary 是长期数据，必须保存在 SQLite。
- transcript 是独立文件资产，v2 再设计定期删除策略。
- 所有路径相对于项目根目录（`pyproject.toml` 所在目录）。
