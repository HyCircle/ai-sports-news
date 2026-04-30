"""CLI entry point for spnews."""

from __future__ import annotations

import argparse
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import DEFAULT_TIMEZONE, DB_PATH
from .db import mark_articles_done, save_events
from .indexer import update_report_indexes
from .report import build_full_report


def _prepare_test_db(source_db_path: Path) -> tuple[Path, tempfile.TemporaryDirectory]:
    """Create a temporary database path, seeded from the real DB when present."""
    temp_dir = tempfile.TemporaryDirectory(prefix="spnews-test-")
    temp_db_path = Path(temp_dir.name) / source_db_path.name
    if source_db_path.exists():
        shutil.copy2(source_db_path, temp_db_path)
    return temp_db_path, temp_dir


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
        help=(
            "Output file path "
            "(default: output/<date>_sports_daily.md; in --test mode only saved when set)"
        ),
    )
    parser.add_argument(
        "--db",
        type=str,
        default=None,
        help=f"Database file path (default: {DB_PATH})",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help=(
            "Run in isolated test mode: use a temporary DB copy, skip homepage/archive "
            "updates, and only save the report when --output is explicitly provided"
        ),
    )
    args = parser.parse_args()

    db_path = Path(args.db) if args.db else DB_PATH
    run_db_path = db_path
    temp_db_dir = None

    if args.test:
        run_db_path, temp_db_dir = _prepare_test_db(db_path)
        print(f"Test mode: using temporary database {run_db_path}")

    try:
        # Build report (fetch → pending → cluster → summarize)
        report, events_by_sport, used_links, ignored_links = build_full_report(
            sports=args.sports, db_path=run_db_path,
        )

        # Determine output path
        out_path = None
        if args.output:
            out_path = Path(args.output)
        elif not args.test:
            date_str = datetime.now(ZoneInfo(DEFAULT_TIMEZONE)).strftime("%Y-%m-%d")
            out_path = Path("output") / f"{date_str}_sports_daily.md"

        if out_path:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(report, encoding="utf-8")
            print(f"\nReport saved to: {out_path}")
        elif args.test:
            print("\nTest mode: report generated in memory and not saved. Pass -o/--output to save it.")

        # --- Closing DB update (only after successful file write) ---
        if args.test:
            print("Test mode: database updates skipped.")
        elif used_links or ignored_links:
            date_str = datetime.now(ZoneInfo(DEFAULT_TIMEZONE)).strftime("%Y-%m-%d")
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

        if args.test:
            print("Test mode: homepage and archive indexes skipped.")
        else:
            # Keep homepage report lists in sync with output/ directory.
            update_report_indexes(Path.cwd())
            print("Homepage and archive indexes updated.")
    finally:
        if temp_db_dir is not None:
            temp_db_dir.cleanup()


if __name__ == "__main__":
    main()
