---
name: youtube-ai-digest
description: Process the local knowledge playlist into Chinese Markdown knowledge notes through the yt-video2knowledge repository on this Mac. Use this skill whenever the user asks OpenClaw to handle the knowledge playlist, process videos added on a date, generate a Chinese daily digest, recover YouTube transcripts, retry failed summaries, or transcribe no-subtitle videos with MLX Whisper. This skill is for the local repository-backed workflow, not casual YouTube chat, unrelated browser automation, or generic video summarization outside this repository.
---

# YouTube AI Digest For OpenClaw

Use this skill when OpenClaw should route a request into the local repository-backed YouTube digest workflow on this Mac.

This skill is global in OpenClaw, but its execution target is fixed:

- Repository root: `/Users/administrator/projects/yt-video2knowledge`

## What This Skill Does

- Processes the local `knowledge` playlist into Chinese Markdown notes.
- Uses the YouTube Data API as the primary source for playlist-added dates.
- Uses the repository's existing workflow for subtitles, MLX Whisper fallback transcription, and Chinese summary generation.
- Supports full date runs, pending-summary retries, single-video reruns, and explicit first-seen fallback mode.

## When To Use This Skill

Use this skill whenever the user is clearly asking OpenClaw to do one of these things:

- Sync or process the `knowledge` playlist.
- Handle videos added yesterday or on a specific date.
- Generate a Chinese YouTube digest or daily report.
- Recover transcripts from playlist videos.
- Retry failed summaries.
- Transcribe a no-subtitle video with MLX Whisper.

Typical trigger phrases include:

- `knowledge 播放列表`
- `昨天新增视频`
- `YouTube 摘要`
- `中文日报`
- `补跑总结`
- `无字幕转写`

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
- `.env.local` in that repository with:
  - `OPENAI_API_KEY`
  - `OPENAI_BASE_URL`
  - `OPENAI_MODEL`
- `data/youtube-oauth-client.json`
- one-time YouTube OAuth already completed

The default managed-skill preflight script is:

```bash
scripts/check_repo_ready.sh
```

## Execution Rules

Use the wrapper scripts in this skill directory. They already point at the fixed repository.

Default run:

```bash
scripts/run_digest.sh --target-date YYYY-MM-DD
```

Retry pending summaries:

```bash
scripts/run_digest.sh --target-date YYYY-MM-DD --retry-summaries
```

Single-video reprocess:

```bash
scripts/run_digest.sh --target-date YYYY-MM-DD --video-id VIDEO_ID
```

Explicit compatibility fallback:

```bash
scripts/run_digest.sh --target-date YYYY-MM-DD --allow-fallback-first-seen
```

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

## How To Report Results

After running, report:

- repository path used
- output directory
- processed count
- failed count
- pending summary count
- any `needs_review` items
- transcript source or ASR fallback reason when relevant
- the next concrete fix if the run is blocked by missing setup
