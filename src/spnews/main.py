"""CLI entry point for spnews."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from .report import build_full_report


def main():
    parser = argparse.ArgumentParser(description="Sports News Daily Report Generator")
    parser.add_argument(
        "-s", "--sports",
        nargs="+",
        choices=["baseball", "football", "formula1"],
        default=None,
        help="Sports to include (default: all)",
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=24,
        help="Look back N hours (default: 24)",
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help="Output file path (default: output/<date>_sports_daily.md)",
    )
    args = parser.parse_args()

    report = build_full_report(sports=args.sports, hours=args.hours)

    # Determine output path
    if args.output:
        out_path = Path(args.output)
    else:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        out_path = Path("output") / f"{date_str}_sports_daily.md"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(f"\nReport saved to: {out_path}")


if __name__ == "__main__":
    main()
