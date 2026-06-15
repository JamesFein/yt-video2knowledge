---
name: youtube-ai-digest
description: Process the local knowledge playlist into Chinese Markdown knowledge notes through the yt-video2knowledge repository on this Mac. Use this skill whenever the user asks OpenClaw to handle the knowledge playlist, process videos added on a date, generate a Chinese daily digest, recover YouTube transcripts, retry failed summaries, inspect an existing run state, or transcribe no-subtitle videos with MLX Whisper. This skill is for the local repository-backed workflow, not casual YouTube chat, unrelated browser automation, or generic video summarization outside this repository. Prefer the repository's real CLI entrypoint and existing manifest state over guessed wrappers or full reruns.
---

# YouTube AI Digest For OpenClaw

Use this skill when OpenClaw should route a request into the local repository-backed YouTube digest workflow on this Mac.

This skill is global in OpenClaw, but its execution target is fixed:

- Repository root: `/Users/administrator/projects/yt-video2knowledge`

## Core Operating Principle

Treat this repository as a **stateful local pipeline**, not a stateless black-box command.

That means:

- trust the repository's actual CLI and files over older wrapper examples
- inspect existing run state before choosing a mode
- prefer incremental recovery over full reruns
- shrink failures to `--retry-summaries` or `--video-id` whenever possible

If the skill instructions and the repository disagree, **the repository is the source of truth**.

## What This Skill Does

- Processes the local `knowledge` playlist into Chinese Markdown notes.
- Uses the YouTube Data API as the primary source for playlist-added dates.
- Uses the repository's existing workflow for subtitles, MLX Whisper fallback transcription, and Chinese summary generation.
- Supports full date runs, pending-summary retries, single-video reruns, and explicit first-seen fallback mode.
- Reuses existing run artifacts and manifest state to avoid unnecessary work and token burn.

## When To Use This Skill

Use this skill whenever the user is clearly asking OpenClaw to do one of these things:

- Sync or process the `knowledge` playlist.
- Handle videos added yesterday or on a specific date.
- Generate a Chinese YouTube digest or daily report.
- Recover transcripts from playlist videos.
- Retry failed summaries.
- Transcribe a no-subtitle video with MLX Whisper.
- Re-run a specific date while preserving as much completed work as possible.
- Diagnose why a previous digest run is stuck or incomplete.

Typical trigger phrases include:

- `knowledge 播放列表`
- `昨天新增视频`
- `YouTube 摘要`
- `中文日报`
- `补跑总结`
- `无字幕转写`
- `再跑一下昨天`
- `为什么卡住了`

## When Not To Use This Skill

Do not use this skill for:

- Casual YouTube conversation or content discussion.
- Generic browser automation.
- A standalone video summary task that does not depend on this repository.
- Cross-platform packaging or marketplace distribution.

## Local Requirements

Before running, assume these should already exist on the machine:

- `uv`
- `yt-dlp`
- `ffmpeg`
- Google Chrome
- repository path `/Users/administrator/projects/yt-video2knowledge`
- Python dependencies installed through `uv`
- `.env.local` in that repository with:
  - `OPENAI_API_KEY`
  - `OPENAI_BASE_URL`
  - `OPENAI_MODEL`
- `data/youtube-oauth-client.json`
- one-time YouTube OAuth already completed when API access is needed

Do **not** assume bare `python3` is enough. Prefer the project environment:

```bash
uv run python scripts/run_knowledge_digest.py --help
```

## Real CLI Entry Point

Do not default to an old wrapper script name.

Use the repository's actual CLI entrypoint:

```bash
uv run python scripts/run_knowledge_digest.py --target-date YYYY-MM-DD
```

Use `uv run` by default so repository-pinned dependencies are available.

When this workflow is triggered from OpenClaw for a full-day knowledge playlist run, prefer the local queue worker instead of running the digest command directly from the chat session. Queueing keeps long video/ASR work out of the LLM response path and avoids chat idle timeouts.

Run queue and status commands separately. Do not combine them with `&&`; OpenClaw may reject chained interpreter invocations.

Queue a date:

```bash
python3 /Users/administrator/.openclaw/workspace/automation/knowledge-digest/queue_request.py YYYY-MM-DD --requested-by openclaw --note "knowledge digest"
```

Check queued/worker status:

```bash
python3 /Users/administrator/.openclaw/workspace/automation/knowledge-digest/show_status.py
```

## Default Decision Flow

For a request like "process YYYY-MM-DD" or "rerun yesterday", do this in order before choosing the run mode.

### Step 1. Confirm CLI shape

```bash
uv run python scripts/run_knowledge_digest.py --help
```

### Step 2. Inspect existing run state

```bash
find data/runs/YYYY-MM-DD -maxdepth 2 -type f | sort
```

If needed, inspect deeper when diagnosing a stuck run:

```bash
find data/runs/YYYY-MM-DD -maxdepth 4 -type f | sort
```

### Step 3. Choose the smallest correct mode

- If no run directory exists, use the default date run.
- If transcripts already exist and summaries are pending, prefer `--retry-summaries`.
- If one video is the problem, prefer `--video-id VIDEO_ID`.
- Only use `--full-reprocess` when the user explicitly wants a full rebuild, or when the manifest/run state is clearly unusable.

## Execution Modes

Default run:

```bash
uv run python scripts/run_knowledge_digest.py --target-date YYYY-MM-DD
```

Retry pending summaries:

```bash
uv run python scripts/run_knowledge_digest.py --target-date YYYY-MM-DD --retry-summaries
```

Force one more bounded single-video summary retry:

```bash
uv run python scripts/run_knowledge_digest.py --target-date YYYY-MM-DD --retry-summaries --video-id VIDEO_ID --force-summary-retry
```

Single-video reprocess or debugging:

```bash
uv run python scripts/run_knowledge_digest.py --target-date YYYY-MM-DD --video-id VIDEO_ID
```

Adopt a manually prepared summary through the repository workflow:

```bash
uv run python scripts/run_knowledge_digest.py --target-date YYYY-MM-DD --video-id VIDEO_ID --adopt-summary-file /absolute/path/to/summary.zh-CN.md
```

Explicit compatibility fallback:

```bash
uv run python scripts/run_knowledge_digest.py --target-date YYYY-MM-DD --allow-fallback-first-seen
```

Full rebuild, only when truly needed:

```bash
uv run python scripts/run_knowledge_digest.py --target-date YYYY-MM-DD --full-reprocess
```

## Token-Saving and Recovery Rules

Follow these rules by default:

- Do not default to full reruns.
- Do not re-transcribe videos when the transcript already exists and only summary generation failed.
- Do not use the whole day as a probe when a single video can isolate the issue.
- Prefer reading `manifest.json` and existing outputs over lengthy speculative explanation.
- If a pending summary has reached `max_attempts`, use `--force-summary-retry --video-id VIDEO_ID` for one explicit extra attempt, or `--adopt-summary-file` for repository-tracked manual completion.
- If output files show progress is stuck at download artifacts like `.part` or `.ytdl`, treat it as a download-stage problem and move to single-video diagnosis instead of repeatedly waiting.

This repository already supports incremental behavior through manifest-backed run state. Use that design instead of fighting it.

## Decision Boundaries

- Prefer the YouTube Data API for playlist-added dates.
- Keep transcript priority in this order:
  - official subtitles
  - auto subtitles
  - audio download
  - MLX Whisper
- If summary generation fails, keep transcript outputs and use retry mode later.
- Do not default to `--allow-fallback-first-seen`.
- Do not default to `--attach-current-chrome`.
- Do not try to perform interactive Google login inside Playwright for production use.
- If the repository's documented command and the live repository contents disagree, follow the live repository contents.

## Reporting Style

Prefer short state-based reports over long process narration.

Use a compact structure like this when helpful:

```md
已检查 / 已运行：
- 日期: YYYY-MM-DD
- run_mode: full / incremental
- processed: X
- summary_ready: X
- pending_summary: X
- failed: X
- needs_review: X

下一步：
- 若只缺总结，跑 `--retry-summaries`
- 若卡在单个视频，跑 `--video-id`
- 若需要彻底重建，跑 `--full-reprocess`
```

## How To Report Results

After running, report:

- repository path used
- output directory
- run mode when available
- processed count
- failed count
- pending summary count
- any `needs_review` items
- transcript source or ASR fallback reason when relevant
- the next concrete fix if the run is blocked by missing setup

Prefer fields already present in `manifest.json` or `daily-overview.zh-CN.md` instead of reconstructing the story from scratch.
