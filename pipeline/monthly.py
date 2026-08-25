"""Monthly pipeline entry point for scheduled ingestion."""

from __future__ import annotations

import argparse
from datetime import date, timedelta

from .backfill import MonthTarget, run_target
from .utils import append_pipeline_log, normalize_month


def main() -> int:
    """Run ingestion for one monthly publication target."""

    parser = argparse.ArgumentParser(description="NHS GP Analytics monthly pipeline")
    parser.add_argument("--month", default=None)
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--keep-raw", action="store_true")
    args = parser.parse_args()

    if (args.month is None) != (args.year is None):
        raise ValueError("Provide both --month and --year together, or neither.")

    if args.month and args.year:
        target = MonthTarget(month=normalize_month(args.month), year=int(args.year))
    else:
        today = date.today()
        latest_published = today.replace(day=1) - timedelta(days=1)
        target = MonthTarget(month=latest_published.strftime("%B").lower(), year=latest_published.year)

    result = run_target(target, dry_run=args.dry_run, keep_raw=args.keep_raw)
    append_pipeline_log(
        {
            "run_at": result.run_at,
            "month": result.month,
            "year": result.year,
            "status": result.status,
            "totals_url": result.totals_url,
            "mapping_url": result.mapping_url,
            "practices_ingested": result.practices_ingested,
            "error": result.error,
        }
    )

    if result.status in {"failed", "not_published"}:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]