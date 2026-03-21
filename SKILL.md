---
name: youtube-ai-digest
description: Process a local YouTube playlist into Chinese Markdown knowledge notes. Use this skill whenever the user wants to sync a specific YouTube playlist, extract transcripts, summarize newly added videos, generate a daily digest, or recover transcripts for videos that may require local MLX Whisper transcription on macOS. Target-date matching should use the YouTube Data API as the primary source of playlist-added time, while browser automation remains a dedicated Playwright-managed Chrome helper for cookies and page fallback.
---

# YouTube AI Digest

Use this skill to process the local `knowledge` playlist into Chinese Markdown outputs on macOS.

This repository is meant for local use. Do not assume plugin marketplace packaging or remote distribution is relevant.

## What This Skill Does

- Reads the configured YouTube playlist URL from `data/knowledge_config.json`
- Interprets target dates in `Asia/Shanghai`
- Uses the YouTube Data API to determine playlist items added on the requested day
- Tries official subtitles first, then auto subtitles
- Falls back to local audio transcription with `mlx-whisper` when no subtitles exist
- Calls an OpenAI-compatible API to generate Chinese Markdown summaries
- Keeps transcript results even when summary generation fails, and supports later summary retries
- Writes:
  - `data/runs/YYYY-MM-DD/daily-overview.zh-CN.md`
  - `data/runs/YYYY-MM-DD/manifest.json`
  - `data/runs/YYYY-MM-DD/videos/<video-id>/summary.zh-CN.md`
  - `data/runs/YYYY-MM-DD/videos/<video-id>/transcript.original.txt`

## Local Prerequisites

- macOS on Apple Silicon
- `uv`
- `yt-dlp`
- `ffmpeg`
- `mlx-whisper`
- `playwright`
- `google-auth`
- `google-auth-oauthlib`
- `google-api-python-client`
- Google Chrome installed locally

## Runtime Configuration

1. Create or update `.env.local` with:

```bash
OPENAI_API_KEY=...
OPENAI_BASE_URL=...
OPENAI_MODEL=...
```

If the custom gateway has certificate issues in Python, optionally set:

```bash
OPENAI_ALLOW_INSECURE_SSL=true
```

2. Update `data/knowledge_config.json` as needed.

3. Save a Google Cloud Desktop OAuth client JSON to:

```bash
data/youtube-oauth-client.json
```

4. Sync the project environment:

```bash
uv sync
```

5. Run one-time YouTube API auth:

```bash
uv run python scripts/run_knowledge_digest.py --youtube-auth
```

6. If you want the shared browser skill available to other AI tools too:

```bash
npx skills add https://github.com/microsoft/playwright-cli --skill playwright-cli -g --all -y
```

## Default Workflow

Initialize the managed Chrome profile in two steps:

```bash
uv run python scripts/run_knowledge_digest.py --seed-from-current-profile
```

This requires the user's normal Google Chrome to be fully closed first.

If you need to verify the managed browser profile itself:

```bash
uv run python scripts/run_knowledge_digest.py --bootstrap-login
```

Do not rely on interactive Google login inside the Playwright browser for production automation. Google may block it as an automated sign-in.

Run the digest:

```bash
uv run python scripts/run_knowledge_digest.py --target-date YYYY-MM-DD
```

If you explicitly want the older first-seen fallback:

```bash
uv run python scripts/run_knowledge_digest.py --target-date YYYY-MM-DD --allow-fallback-first-seen
```

If you specifically need to debug against your current Chrome session:

```bash
uv run python scripts/run_knowledge_digest.py --target-date YYYY-MM-DD --attach-current-chrome
```

This is not the default automation path and may still require CDP permissions.

If you need to reprocess a single video:

```bash
uv run python scripts/run_knowledge_digest.py --video-id VIDEO_ID --target-date YYYY-MM-DD
```

If you need to retry pending summaries from an existing run:

```bash
uv run python scripts/run_knowledge_digest.py --target-date YYYY-MM-DD --retry-summaries
```

## Compatible Legacy Commands

These older commands are still supported:

```bash
uv run python scripts/fetch_videos.py --days 7 --keyword AI
uv run python scripts/get_transcript.py --video-id VIDEO_ID
uv run python scripts/generate_report.py --video-id VIDEO_ID --summary "..."
```

## How To Use This Skill In Practice

When the user asks for a digest run:

1. Verify `uv sync` has already been run and the project environment matches `uv.lock`.
2. Check the three required env vars:
   - `OPENAI_API_KEY`
   - `OPENAI_BASE_URL`
   - `OPENAI_MODEL`
3. Run `uv run python scripts/run_knowledge_digest.py`.
4. Report:
   - output directory
   - processed video count
   - pending summary count
   - any `needs_review` items
   - any transcript-failed videos and the error message
   - transcript source and timing metrics when relevant
   - subtitle detection results and ASR fallback reasons when relevant
   - browser diagnostics path if YouTube self-check failed

If the digest cannot continue because system tools are missing, tell the user exactly which dependency to install next.
