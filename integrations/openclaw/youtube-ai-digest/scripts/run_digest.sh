#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="/Users/administrator/projects/yt-video2knowledge"
THIS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

"$THIS_DIR/check_repo_ready.sh" >/dev/null

cd "$REPO_ROOT"
exec uv run yt-video2knowledge digest "$@"
