from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from knowledge_site.config import load_settings  # noqa: E402
from knowledge_site.sync import (  # noqa: E402
    format_sync_failure,
    format_sync_report,
    sync_knowledge_site,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync data/runs into the knowledge site database.")
    parser.add_argument("--runs-dir", type=Path, default=None)
    parser.add_argument(
        "--target-date",
        help="Sync only this date (YYYY-MM-DD). Omit to run a full historical sync.",
    )
    args = parser.parse_args()

    settings = load_settings(require_auth=False)
    try:
        report = sync_knowledge_site(
            settings,
            runs_dir=args.runs_dir,
            target_date=args.target_date,
        )
    except Exception as exc:  # noqa: BLE001
        print(
            format_sync_failure(settings, args.target_date, exc, mode="manual"),
            file=sys.stderr,
        )
        return 1

    print(format_sync_report(settings, report, mode="manual"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
