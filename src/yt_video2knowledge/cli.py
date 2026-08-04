"""Command-line interface for the local knowledge workflow."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from yt_video2knowledge.digest.config import _json_default, parse_target_date
from yt_video2knowledge.digest.errors import ConfigurationError, DigestError
from yt_video2knowledge.digest.manifest import is_manifest_complete, recover_run
from yt_video2knowledge.digest.run import run_knowledge_digest
from yt_video2knowledge.site.config import load_settings
from yt_video2knowledge.site.sync import format_sync_failure, format_sync_report, sync_knowledge_site


NON_CONTENT_FLAGS = (
    "youtube_auth",
    "seed_from_current_profile",
    "bootstrap_login",
    "force_login",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="yt-video2knowledge")
    commands = parser.add_subparsers(dest="command", required=True)

    digest = commands.add_parser("digest", help="Process the Knowledge Playlist for a Target Date.")
    digest.add_argument("--target-date", help="Target Date in YYYY-MM-DD, interpreted in Asia/Shanghai.")
    digest.add_argument("--playlist-url", help="Override the configured Knowledge Playlist URL.")
    digest.add_argument("--youtube-auth", action="store_true", help="Run the one-time local YouTube OAuth flow.")
    digest.add_argument("--seed-from-current-profile", action="store_true", help="Clone the current Chrome profile into the automation profile.")
    digest.add_argument("--bootstrap-login", action="store_true", help="Open the managed Chrome profile for one-time login.")
    digest.add_argument("--attach-current-chrome", action="store_true", help="Debug-only: attach to the current Chrome CDP session.")
    digest.add_argument("--force-login", action="store_true", help="Deprecated alias for --bootstrap-login.")
    summary_mode = digest.add_mutually_exclusive_group()
    summary_mode.add_argument("--retry-summaries", action="store_true", help="Retry Pending-summary Videos in an existing Digest Run.")
    summary_mode.add_argument("--regenerate-summaries", action="store_true", help="Regenerate summaries from saved Transcripts.")
    digest.add_argument("--allow-fallback-first-seen", action="store_true", help="Allow first-seen fallback when Playlist-added Date is unavailable.")
    digest.add_argument("--full-reprocess", action="store_true", help="Force a full rerun instead of incremental processing.")
    digest.add_argument("--video-id", help="Process one video directly.")
    digest.add_argument("--force-summary-retry", action="store_true", help="Force one extra bounded summary retry.")
    digest.add_argument("--adopt-summary-file", help="Adopt a prepared Markdown summary for --video-id.")
    digest.set_defaults(handler=_run_digest)

    sync = commands.add_parser("sync-site", help="Sync Summary-ready Videos into the Knowledge Site.")
    sync.add_argument("--runs-dir", type=Path, default=None)
    sync.add_argument("--target-date", help="Sync only this Target Date; omit for full historical sync.")
    sync.set_defaults(handler=_run_site_sync)

    recover = commands.add_parser("recover-manifest", help="Rebuild a Digest Run manifest from existing artifacts.")
    recover.add_argument("--target-date", required=True, help="Target Date in YYYY-MM-DD.")
    recover.set_defaults(handler=_run_manifest_recovery)
    return parser


def _sync_target_date(target_date: str, *, mode: str) -> int:
    settings = load_settings(require_auth=False)
    try:
        report = sync_knowledge_site(settings, target_date=target_date)
    except Exception as exc:  # noqa: BLE001
        print(format_sync_failure(settings, target_date, exc, mode=mode), file=sys.stderr)
        return 1
    print(format_sync_report(settings, report, mode=mode), file=sys.stderr)
    return 0


def _run_digest(args: argparse.Namespace) -> int:
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
    if any(getattr(args, flag) for flag in NON_CONTENT_FLAGS):
        return 0
    if _sync_target_date(target_date.isoformat(), mode="auto") != 0:
        return 1
    if not is_manifest_complete(manifest):
        print("Digest finished partially; manifest still has failed or pending summaries.", file=sys.stderr)
        return 2
    return 0


def _run_site_sync(args: argparse.Namespace) -> int:
    settings = load_settings(require_auth=False)
    try:
        report = sync_knowledge_site(settings, runs_dir=args.runs_dir, target_date=args.target_date)
    except Exception as exc:  # noqa: BLE001
        print(format_sync_failure(settings, args.target_date, exc, mode="manual"), file=sys.stderr)
        return 1
    print(format_sync_report(settings, report, mode="manual"))
    return 0


def _run_manifest_recovery(args: argparse.Namespace) -> int:
    try:
        manifest = recover_run(args.target_date)
    except DigestError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(manifest, ensure_ascii=False, indent=2, default=_json_default))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
