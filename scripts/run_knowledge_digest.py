#!/usr/bin/env python3
"""CLI entrypoint for the local knowledge playlist digest."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from knowledge_digest import (  # noqa: E402
    ConfigurationError,
    DigestError,
    _json_default,
    is_manifest_complete,
    parse_target_date,
    run_knowledge_digest,
)
from knowledge_site.config import load_settings  # noqa: E402
from knowledge_site.sync import (  # noqa: E402
    format_sync_failure,
    format_sync_report,
    sync_knowledge_site,
)


NON_CONTENT_FLAGS = (
    "youtube_auth",
    "seed_from_current_profile",
    "bootstrap_login",
    "force_login",
)


def _auto_sync_knowledge_site(target_date: str) -> int:
    settings = load_settings(require_auth=False)
    try:
        report = sync_knowledge_site(settings, target_date=target_date)
    except Exception as exc:  # noqa: BLE001
        print(
            format_sync_failure(settings, target_date, exc, mode="auto"),
            file=sys.stderr,
        )
        return 1
    print(format_sync_report(settings, report, mode="auto"), file=sys.stderr)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Process the local knowledge playlist digest workflow.")
    parser.add_argument("--target-date", help="Target date in YYYY-MM-DD, interpreted in Asia/Shanghai.")
    parser.add_argument("--playlist-url", help="Override the configured playlist URL.")
    parser.add_argument("--youtube-auth", action="store_true", help="Run the one-time local OAuth flow for YouTube Data API.")
    parser.add_argument("--seed-from-current-profile", action="store_true", help="Clone the current Chrome Default profile into the automation profile. Chrome must be fully closed first.")
    parser.add_argument("--bootstrap-login", action="store_true", help="Open the managed Chrome profile for a one-time YouTube login.")
    parser.add_argument("--attach-current-chrome", action="store_true", help="Debug-only mode: attach to the current Chrome CDP session.")
    parser.add_argument("--force-login", action="store_true", help="Deprecated alias for --bootstrap-login.")
    summary_mode = parser.add_mutually_exclusive_group()
    summary_mode.add_argument("--retry-summaries", action="store_true", help="Retry pending summaries from an existing run directory.")
    summary_mode.add_argument(
        "--regenerate-summaries",
        action="store_true",
        help="Regenerate existing summaries from saved transcripts without downloading or transcribing again.",
    )
    parser.add_argument("--allow-fallback-first-seen", action="store_true", help="Allow first-seen fallback when the YouTube API cannot verify playlist added dates.")
    parser.add_argument("--full-reprocess", action="store_true", help="Force a full rerun for the target date instead of default same-day incremental processing.")
    parser.add_argument("--video-id", help="Process a single video directly.")
    parser.add_argument("--force-summary-retry", action="store_true", help="Force one more pending-summary retry even after the bounded retry stop condition.")
    parser.add_argument("--adopt-summary-file", help="Adopt a manually prepared Markdown summary for --video-id and rebuild the run manifest.")
    args = parser.parse_args()

    target_date = parse_target_date(args.target_date)
    try:
        manifest = run_knowledge_digest(
            target_date=target_date,
            playlist_url=args.playlist_url,
            youtube_auth=args.youtube_auth,
            seed_from_current_profile=args.seed_from_current_profile,
            bootstrap_login=args.bootstrap_login or args.force_login,
            attach_current_chrome=args.attach_current_chrome,
            retry_summaries=args.retry_summaries,
            regenerate_summaries=args.regenerate_summaries,
            allow_fallback_first_seen=args.allow_fallback_first_seen,
            full_reprocess=args.full_reprocess,
            video_id=args.video_id,
            force_summary_retry=args.force_summary_retry,
            adopt_summary_file=Path(args.adopt_summary_file) if args.adopt_summary_file else None,
        )
    except (ConfigurationError, DigestError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(manifest, ensure_ascii=False, indent=2, default=_json_default))

    is_content_run = not any(getattr(args, flag) for flag in NON_CONTENT_FLAGS)
    if is_content_run:
        sync_status = _auto_sync_knowledge_site(target_date.isoformat())
        if sync_status != 0:
            return sync_status
        if not is_manifest_complete(manifest):
            print(
                "Digest finished partially; manifest still has failed or pending summaries.",
                file=sys.stderr,
            )
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
