#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="/Users/administrator/projects/yt-video2knowledge"

fail() {
  echo "NOT_READY: $*" >&2
  exit 1
}

[[ -d "$REPO_ROOT" ]] || fail "Repository root does not exist: $REPO_ROOT"
[[ -f "$REPO_ROOT/pyproject.toml" ]] || fail "Missing pyproject.toml in $REPO_ROOT"
[[ -f "$REPO_ROOT/uv.lock" ]] || fail "Missing uv.lock in $REPO_ROOT"
[[ -f "$REPO_ROOT/.env.local" ]] || fail "Missing .env.local in $REPO_ROOT"
[[ -f "$REPO_ROOT/data/youtube-oauth-client.json" ]] || fail "Missing data/youtube-oauth-client.json"
[[ -f "$REPO_ROOT/data/youtube-oauth-token.json" ]] || fail "Missing data/youtube-oauth-token.json; run --youtube-auth first"
[[ -d "$REPO_ROOT/data/chrome-automation-profile" ]] || fail "Missing managed Chrome profile; run --seed-from-current-profile first"

command -v uv >/dev/null 2>&1 || fail "uv is not installed"
command -v yt-dlp >/dev/null 2>&1 || fail "yt-dlp is not installed"
command -v ffmpeg >/dev/null 2>&1 || fail "ffmpeg is not installed"

echo "READY: $REPO_ROOT"
