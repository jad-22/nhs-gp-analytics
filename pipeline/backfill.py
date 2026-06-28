"""Historical and targeted monthly backfill entry point."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Iterable

from .config import (
    DATA_RAW_DIR,
    DEFAULT_BACKFILL_START,
    MAPPING_STEM,
    MONTH_TO_INT,
    TOTALS_STEM,
    ensure_data_directories,
)
from .extractor import find_extracted_dataset, safe_extract_zip
from .loader import upsert_month
from .scraper import (
    DownloadError,
    LinksNotFoundError,
    PageNotFoundError,
    download_file,
    fetch_html,
    filename_from_url,
    find_target_links,
    make_session,
    publication_url,
)
from .transformer import TransformError, transform_list_size, transform_mapping
from .utils import append_pipeline_log, normalize_month, setup_logging


log = setup_logging(__name__)


@dataclass(frozen=True)
class MonthTarget:
    """A single publication month to ingest."""

    month: str
    year: int

    @property
    def slug(self) -> str:
        month_num = MONTH_TO_INT[self.month]
        return f"{self.year}-{month_num:02d}-{self.month}"

    @property
    def snapshot_date(self) -> date:
        return date(self.year, MONTH_TO_INT[self.month], 1)


@dataclass
class RunResult:
    """Summary of a pipeline run."""

    month: str
    year: int
    status: str
    run_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    totals_url: str | None = None
    mapping_url: str | None = None
    practices_ingested: int | None = None
    error: str | None = None


def _month_start(value: date) -> date:
    return date(value.year, value.month, 1)


def _iter_months(start_date: date, end_date: date) -> Iterable[MonthTarget]:
    cursor = _month_start(start_date)
    limit = _month_start(end_date)

    while cursor <= limit:
        month_name = datetime(cursor.year, cursor.month, 1).strftime("%B").lower()
        yield MonthTarget(month=month_name, year=cursor.year)
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)


def _resolve_input_path(download_path: Path, extract_dir: Path, stem: str, keep_raw: bool) -> Path:
    if download_path.suffix.lower() == ".zip":
        safe_extract_zip(download_path, extract_dir)
        if not keep_raw:
            download_path.unlink(missing_ok=True)
        return find_extracted_dataset(extract_dir, stem)
    return download_path


def run_target(target: MonthTarget, dry_run: bool = False, keep_raw: bool = False) -> RunResult:
    """Run pipeline ingestion for one publication month target."""

    ensure_data_directories()
    page_url = publication_url(target.month, target.year)
    session = make_session()

    try:
        html = fetch_html(session, page_url)
        links = find_target_links(html)
        totals_url = links["totals"].href
        mapping_url = links["mapping"].href

        if dry_run:
            return RunResult(
                month=target.month,
                year=target.year,
                status="dry-run",
                totals_url=totals_url,
                mapping_url=mapping_url,
                practices_ingested=None,
            )

        month_raw_dir = DATA_RAW_DIR / target.slug
        totals_download_path = month_raw_dir / filename_from_url(totals_url)
        mapping_download_path = month_raw_dir / filename_from_url(mapping_url)

        download_file(session, totals_url, totals_download_path)
        download_file(session, mapping_url, mapping_download_path)

        totals_input_path = _resolve_input_path(
            totals_download_path,
            month_raw_dir / "totals_extracted",
            TOTALS_STEM,
            keep_raw,
        )
        mapping_input_path = _resolve_input_path(
            mapping_download_path,
            month_raw_dir / "mapping_extracted",
            MAPPING_STEM,
            keep_raw,
        )

        list_size_df = transform_list_size(totals_input_path, target.snapshot_date)
        mapping_df = transform_mapping(mapping_input_path, target.snapshot_date)
        upsert_month(list_size_df, mapping_df)

        return RunResult(
            month=target.month,
            year=target.year,
            status="success",
            totals_url=totals_url,
            mapping_url=mapping_url,
            practices_ingested=int(list_size_df["CODE"].nunique()),
        )
    except PageNotFoundError as exc:
        return RunResult(month=target.month, year=target.year, status="not_published", error=str(exc))
    except (LinksNotFoundError, DownloadError, TransformError, RuntimeError, ValueError) as exc:
        return RunResult(month=target.month, year=target.year, status="failed", error=str(exc))


def main() -> int:
    """CLI entry point for historical or targeted backfill runs."""

    parser = argparse.ArgumentParser(description="NHS GP Analytics backfill pipeline")
    parser.add_argument("--month", default=None)
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--from-month", default=None)
    parser.add_argument("--from-year", type=int, default=None)
    parser.add_argument("--to-month", default=None)
    parser.add_argument("--to-year", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--keep-raw", action="store_true")
    args = parser.parse_args()

    ensure_data_directories()

    if (args.month is None) != (args.year is None):
        raise ValueError("Provide both --month and --year together, or neither.")

    targets: list[MonthTarget]
    if args.month and args.year:
        targets = [MonthTarget(month=normalize_month(args.month), year=int(args.year))]
    else:
        start_month = normalize_month(args.from_month) if args.from_month else DEFAULT_BACKFILL_START.strftime("%B").lower()
        start_year = int(args.from_year) if args.from_year else DEFAULT_BACKFILL_START.year
        end_default = date.today()
        end_month = normalize_month(args.to_month) if args.to_month else end_default.strftime("%B").lower()
        end_year = int(args.to_year) if args.to_year else end_default.year

        start_date = date(start_year, MONTH_TO_INT[start_month], 1)
        end_date = date(end_year, MONTH_TO_INT[end_month], 1)
        if start_date > end_date:
            raise ValueError("Backfill start date must be on or before end date.")
        targets = list(_iter_months(start_date, end_date))

    mode = "dry-run" if args.dry_run else "ingest"
    log.info("Starting backfill in %s mode for %s month target(s)", mode, len(targets))

    failures = 0
    for target in targets:
        log.info("Processing %s", target.slug)
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
            failures += 1
            log.warning("%s failed with status=%s error=%s", target.slug, result.status, result.error)
        else:
            log.info("%s complete with status=%s", target.slug, result.status)

    if failures:
        log.warning("Backfill finished with %s unsuccessful month(s)", failures)
        return 1

    log.info("Backfill finished successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["MonthTarget", "RunResult", "main", "run_target"]