#!/usr/bin/env python3
"""CLI entrypoint for the local knowledge playlist digest."""
from __future__ import annotations

import argparse
import json
import sys

from knowledge_digest import (
    ConfigurationError,
    DigestError,
    _json_default,
    parse_target_date,
    run_knowledge_digest,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Process the local knowledge playlist digest workflow.")
    parser.add_argument("--target-date", help="Target date in YYYY-MM-DD, interpreted in Asia/Shanghai.")
    parser.add_argument("--playlist-url", help="Override the configured playlist URL.")
    parser.add_argument("--youtube-auth", action="store_true", help="Run the one-time local OAuth flow for YouTube Data API.")
    parser.add_argument("--seed-from-current-profile", action="store_true", help="Clone the current Chrome Default profile into the automation profile. Chrome must be fully closed first.")
    parser.add_argument("--bootstrap-login", action="store_true", help="Open the managed Chrome profile for a one-time YouTube login.")
    parser.add_argument("--attach-current-chrome", action="store_true", help="Debug-only mode: attach to the current Chrome CDP session.")
    parser.add_argument("--force-login", action="store_true", help="Deprecated alias for --bootstrap-login.")
    parser.add_argument("--retry-summaries", action="store_true", help="Retry pending summaries from an existing run directory.")
    parser.add_argument("--allow-fallback-first-seen", action="store_true", help="Allow first-seen fallback when the YouTube API cannot verify playlist added dates.")
    parser.add_argument("--full-reprocess", action="store_true", help="Force a full rerun for the target date instead of default same-day incremental processing.")
    parser.add_argument("--video-id", help="Process a single video directly.")
    args = parser.parse_args()

    try:
        manifest = run_knowledge_digest(
            target_date=parse_target_date(args.target_date),
            playlist_url=args.playlist_url,
            youtube_auth=args.youtube_auth,
            seed_from_current_profile=args.seed_from_current_profile,
            bootstrap_login=args.bootstrap_login or args.force_login,
            attach_current_chrome=args.attach_current_chrome,
            retry_summaries=args.retry_summaries,
            allow_fallback_first_seen=args.allow_fallback_first_seen,
            full_reprocess=args.full_reprocess,
            video_id=args.video_id,
        )
    except (ConfigurationError, DigestError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(manifest, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
