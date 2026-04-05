"""CLI entry point for spnews."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import DEFAULT_TIMEZONE, DB_PATH
from .db import mark_articles_done, save_events
from .indexer import update_report_indexes
from .report import build_full_report


def main():
    parser = argparse.ArgumentParser(description="Sports News Daily Report Generator")
    parser.add_argument(
        "-s", "--sports",
        nargs="+",
        choices=["baseball", "football", "formula1", "soccer", "basketball"],
        default=None,
        help="Sports to include (default: all)",
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help="Output file path (default: output/<date>_sports_daily.md)",
    )
    parser.add_argument(
        "--db",
        type=str,
        default=None,
        help=f"Database file path (default: {DB_PATH})",
    )
    args = parser.parse_args()

    db_path = Path(args.db) if args.db else DB_PATH

    # Build report (fetch → pending → cluster → summarize)
    report, events_by_sport, used_links, ignored_links = build_full_report(
        sports=args.sports, db_path=db_path,
    )

    # Determine output path
    date_str = datetime.now(ZoneInfo(DEFAULT_TIMEZONE)).strftime("%Y-%m-%d")
    if args.output:
        out_path = Path(args.output)
    else:
        out_path = Path("output") / f"{date_str}_sports_daily.md"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(f"\nReport saved to: {out_path}")

    # --- Closing DB update (only after successful file write) ---
    if used_links or ignored_links:
        try:
            mark_articles_done(db_path, date_str, used_links, ignored_links)
            for sport, evts in events_by_sport.items():
                save_events(db_path, date_str, sport, evts)
            print(
                f"Database updated: {len(used_links)} articles used, "
                f"{len(ignored_links)} ignored, "
                f"{sum(len(e) for e in events_by_sport.values())} events saved."
            )
        except Exception as exc:
            print(
                f"WARNING: DB update failed ({exc}). "
                "Affected articles will be reprocessed on next run."
            )

    # Keep homepage report lists in sync with output/ directory.
    update_report_indexes(Path.cwd())
    print("Homepage and archive indexes updated.")


if __name__ == "__main__":
    main()
