#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_DIR="$REPO_ROOT/openclaw-skill/youtube-ai-digest"
TARGET_ROOT="${HOME}/.openclaw/skills"
TARGET_DIR="$TARGET_ROOT/youtube-ai-digest"

if [[ ! -d "$SOURCE_DIR" ]]; then
  echo "Missing OpenClaw skill source directory: $SOURCE_DIR" >&2
  exit 1
fi

mkdir -p "$TARGET_ROOT"
rm -rf "$TARGET_DIR"
mkdir -p "$TARGET_DIR"
cp -R "$SOURCE_DIR"/. "$TARGET_DIR"/
chmod +x "$TARGET_DIR"/scripts/*.sh

echo "Installed OpenClaw skill to: $TARGET_DIR"
echo "Validate with:"
echo "  openclaw skills list --json"
echo "  openclaw skills check --json"
echo "  openclaw skills info youtube-ai-digest"
