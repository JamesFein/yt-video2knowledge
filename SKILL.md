---
name: youtube-ai-digest
description: Process the local knowledge playlist into Chinese Markdown knowledge notes on macOS. Use this skill whenever the user wants to sync the current repository's YouTube playlist workflow, process videos added on a target date, recover transcripts, retry failed summaries, or handle local YouTube playlist summarization that may require YouTube Data API date matching, Playwright-managed Chrome cookies, yt-dlp subtitle lookup, or MLX Whisper fallback transcription. Do not use this skill for casual YouTube Q&A, generic browser automation, or unrelated video chat.
---

# YouTube AI Digest

Use this skill for the local macOS workflow in this repository.

This skill is for running and reporting the repository's YouTube playlist digest pipeline. It is not a plugin-marketplace skill, and it is not a general browser automation skill.

## What This Skill Is For

- Process the configured `knowledge` playlist into Chinese Markdown outputs.
- Match playlist-added dates in `Asia/Shanghai`, using the YouTube Data API as the primary source of truth.
- Prefer official subtitles, then auto subtitles, then local `mlx-whisper` transcription.
- Keep transcript outputs even when summary generation fails.
- Retry pending summaries without redoing the whole run when possible.

The main outputs are:

- `data/runs/YYYY-MM-DD/daily-overview.zh-CN.md`
- `data/runs/YYYY-MM-DD/manifest.json`
- `data/runs/YYYY-MM-DD/videos/<video-id>/summary.zh-CN.md`
- `data/runs/YYYY-MM-DD/videos/<video-id>/transcript.original.txt`
- `data/runs/YYYY-MM-DD/videos/<video-id>/metadata.json`

## When To Use This Skill

Use this skill when the user is asking for one of these repository-first tasks:

- Sync the `knowledge` playlist for a specific date.
- Generate a Chinese daily digest for newly added playlist videos.
- Recover transcripts for playlist videos, including no-subtitle cases.
- Retry failed or pending summaries from an earlier run.
- Reprocess one known YouTube video inside this repository's local workflow.

This skill can also trigger for closely related local tasks if the user is clearly asking for:

- Local YouTube playlist transcript extraction.
- Subtitle recovery with `yt-dlp`.
- No-subtitle fallback transcription with `mlx-whisper` on macOS.
- Chinese Markdown summaries built from local YouTube transcripts.

## When Not To Use This Skill

Do not use this skill for:

- Casual questions about a YouTube video or channel.
- Generic browser automation not tied to this digest workflow.
- General OpenAI or Playwright setup questions with no playlist-processing goal.
- Cross-platform packaging or Windows instructions.
- Plugin marketplace packaging or distribution work.

## Required Local Setup

Assume these prerequisites before running the workflow:

- macOS on Apple Silicon.
- `uv` has been installed and `uv sync` has been run.
- `yt-dlp`, `ffmpeg`, Google Chrome, and the Python dependencies from `uv.lock` are available.
- `.env.local` contains:
  - `OPENAI_API_KEY`
  - `OPENAI_BASE_URL`
  - `OPENAI_MODEL`
- `data/youtube-oauth-client.json` exists.
- One-time YouTube OAuth has already been completed:
  - `uv run python scripts/run_knowledge_digest.py --youtube-auth`

If the managed Chrome profile is needed, the usual initialization path is:

```bash
uv run python scripts/run_knowledge_digest.py --seed-from-current-profile
```

## Execution Workflow

Use the default run path unless the user explicitly asks for a different one:

```bash
uv run python scripts/run_knowledge_digest.py --target-date YYYY-MM-DD
```

Important execution rules:

- Treat the YouTube Data API as the default source of playlist-added dates.
- Follow transcript priority in this order:
  - official subtitles
  - auto subtitles
  - audio download
  - `mlx-whisper`
- If summary generation fails, keep transcript outputs and use `--retry-summaries` later instead of calling the whole run a total loss.
- Use `--video-id VIDEO_ID --target-date YYYY-MM-DD` only when the user explicitly wants a single-video reprocess.

Useful recovery commands:

```bash
uv run python scripts/run_knowledge_digest.py --target-date YYYY-MM-DD --retry-summaries
uv run python scripts/run_knowledge_digest.py --video-id VIDEO_ID --target-date YYYY-MM-DD
```

## Decision Boundaries

Default behavior:

- Use strict date matching first.
- Keep transcripts even when summaries fail.
- Use the managed Playwright Chrome profile for cookies and page fallback.

Do not default to these paths unless the user explicitly asks for them:

- `--allow-fallback-first-seen`
- `--attach-current-chrome`
- Interactive Google login inside a Playwright-controlled browser

Browser role boundaries:

- Playwright is for cookies, managed profile use, and page fallback.
- It is not the primary source of playlist-added dates.
- It is not the preferred production login path for Google account authentication.

## How To Report Results

After running the workflow, report these items:

- output directory
- processed video count
- failed video count
- pending summary count
- any `needs_review` items
- transcript source for relevant videos
- subtitle detection results or ASR fallback reason when relevant
- timing metrics when they help explain slow runs
- browser diagnostics path if YouTube self-check failed

If the run cannot continue, tell the user the next concrete dependency or credential they need to fix.

## Related Commands

Legacy commands still exist, but they are not the default skill path:

```bash
uv run python scripts/fetch_videos.py --days 7 --keyword AI
uv run python scripts/get_transcript.py --video-id VIDEO_ID
uv run python scripts/generate_report.py --video-id VIDEO_ID --summary "..."
```
