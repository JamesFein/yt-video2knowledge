from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from knowledge_site.config import load_settings  # noqa: E402
from knowledge_site.sync import sync_knowledge_site  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync data/runs into the knowledge site database.")
    parser.add_argument("--runs-dir", type=Path, default=None)
    args = parser.parse_args()

    settings = load_settings(require_auth=False)
    report = sync_knowledge_site(settings, runs_dir=args.runs_dir)
    print(
        "Synced "
        f"{len(report.days)} day(s), "
        f"{report.imported_video_count} imported video(s)."
    )
    for day in report.days:
        print(
            f"- {day.day_date}: imported={day.imported_video_count}, "
            f"pending={day.skipped_pending_count}, failed={day.skipped_failed_count}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

