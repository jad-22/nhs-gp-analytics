#!/usr/bin/env python3
"""
NHS GP Practice Data — Historical Backfill Script
==================================================

Downloads all available monthly publications from NHS Digital and builds
the longitudinal Parquet dataset from scratch.

Usage:
    # Full backfill from Jan 2019 to present
    python -m pipeline.backfill

    # Backfill a specific range
    python -m pipeline.backfill --from-month january --from-year 2020 \
                                --to-month december --to-year 2025

    # Dry run (check which months are missing without downloading)
    python -m pipeline.backfill --dry-run

    # Retry only previously failed months
    python -m pipeline.backfill --retry-failed

    # Force re-download even if month already exists in Parquet
    python -m pipeline.backfill --force

    # Control concurrency and politeness delay
    python -m pipeline.backfill --delay 3.0 --max-retries 5
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import zipfile
from dataclasses import dataclass, field, asdict
from datetime import datetime, date
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW = REPO_ROOT / "data" / "raw"
DATA_PROCESSED = REPO_ROOT / "data" / "processed"
PIPELINE_LOG = REPO_ROOT / "data" / "pipeline_log.json"

DATA_RAW.mkdir(parents=True, exist_ok=True)
DATA_PROCESSED.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_PAGE = (
    "https://digital.nhs.uk/data-and-information/publications/statistical/"
    "patients-registered-at-a-gp-practice/{slug}"
)
FILES_HOST = "https://files.digital.nhs.uk/"

TOTALS_STEM = "gp-reg-pat-prac-all"
MAPPING_STEM = "gp-reg-pat-prac-map"

# Source system changed ~Jan 2023 from NHAIS to PDS
PDS_START = date(2023, 1, 1)

# NHS Digital publishes data back to ~Jan 2015
DEFAULT_FROM = date(2019, 1, 1)   # 2019 = ~6 years; go earlier if desired

MONTHS: dict[str, str] = {
    "1": "january",  "01": "january",  "jan": "january",  "january": "january",
    "2": "february", "02": "february", "feb": "february", "february": "february",
    "3": "march",    "03": "march",    "mar": "march",    "march": "march",
    "4": "april",    "04": "april",    "apr": "april",    "april": "april",
    "5": "may",      "05": "may",      "may": "may",
    "6": "june",     "06": "june",     "jun": "june",     "june": "june",
    "7": "july",     "07": "july",     "jul": "july",     "july": "july",
    "8": "august",   "08": "august",   "aug": "august",   "august": "august",
    "9": "september","09": "september","sep": "september","sept": "september","september": "september",
    "10": "october", "oct": "october", "october": "october",
    "11": "november","nov": "november","november": "november",
    "12": "december","dec": "december","december": "december",
}

MONTH_TO_INT: dict[str, int] = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(REPO_ROOT / "backfill.log", mode="a", encoding="utf-8"),
    ],
)
log = logging.getLogger("backfill")

# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class BackfillError(Exception):
    """Base class for backfill errors."""


class PageNotFoundError(BackfillError):
    """Publication page does not exist (404 or month not yet published)."""


class LinksNotFoundError(BackfillError):
    """Publication page exists but expected download links are missing.
    
    This typically means NHS Digital changed the page layout or file naming.
    Action required: inspect the page and update TOTALS_STEM / MAPPING_STEM.
    """


class DownloadError(BackfillError):
    """File download failed after all retries."""


class ExtractionError(BackfillError):
    """ZIP extraction or CSV discovery failed."""


class TransformError(BackfillError):
    """Data transformation / validation failed."""


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class MonthTarget:
    month: str    # normalised lowercase e.g. "december"
    year: int

    @property
    def slug(self) -> str:
        return f"{self.month}-{self.year}"

    @property
    def snapshot_date(self) -> date:
        return date(self.year, MONTH_TO_INT[self.month], 1)

    @property
    def label(self) -> str:
        return f"{self.month.capitalize()} {self.year}"


@dataclass
class RunResult:
    month: str
    year: int
    status: str                    # "success" | "skipped" | "failed" | "not_published"
    run_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    totals_url: Optional[str] = None
    mapping_url: Optional[str] = None
    practices_ingested: Optional[int] = None
    error: Optional[str] = None
    error_type: Optional[str] = None


# ---------------------------------------------------------------------------
# Pipeline log helpers
# ---------------------------------------------------------------------------


def load_pipeline_log() -> list[dict]:
    if PIPELINE_LOG.exists():
        try:
            with open(PIPELINE_LOG, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Could not read pipeline log ({e}), starting fresh.")
    return []


def save_pipeline_log(records: list[dict]) -> None:
    with open(PIPELINE_LOG, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)


def log_run(result: RunResult) -> None:
    """Append or update a run result in the pipeline log."""
    records = load_pipeline_log()
    key = (result.month, result.year)
    updated = False
    for i, rec in enumerate(records):
        if (rec.get("month"), rec.get("year")) == key:
            records[i] = asdict(result)
            updated = True
            break
    if not updated:
        records.append(asdict(result))
    save_pipeline_log(records)


def get_failed_months(log_records: list[dict]) -> list[tuple[str, int]]:
    return [
        (r["month"], r["year"])
        for r in log_records
        if r.get("status") == "failed"
    ]


def get_ingested_snapshot_dates(parquet_path: Path) -> set[date]:
    """Return set of SNAPSHOT_DATE values already in the Parquet file."""
    if not parquet_path.exists():
        return set()
    try:
        df = pd.read_parquet(parquet_path, columns=["SNAPSHOT_DATE"])
        return set(pd.to_datetime(df["SNAPSHOT_DATE"]).dt.date.unique())
    except Exception as e:
        log.warning(f"Could not read existing Parquet ({e}), treating as empty.")
        return set()


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (compatible; nhs-gp-analytics-backfill/1.0; "
            "open-source portfolio project; +https://github.com)"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.9",
    })
    return s


def fetch_with_retry(
    session: requests.Session,
    url: str,
    stream: bool = False,
    timeout: int = 30,
    max_retries: int = 3,
    backoff_base: float = 2.0,
    expected_404_ok: bool = False,
) -> requests.Response:
    """
    GET with exponential backoff retry.

    Args:
        expected_404_ok: If True, 404 raises PageNotFoundError instead of DownloadError.
    """
    last_exc: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            r = session.get(url, stream=stream, timeout=timeout)

            if r.status_code == 404:
                if expected_404_ok:
                    raise PageNotFoundError(f"404 — publication not found: {url}")
                # Don't retry 404s — they won't change
                raise PageNotFoundError(f"404 — publication not found: {url}")

            if r.status_code == 429:
                retry_after = int(r.headers.get("Retry-After", 60))
                log.warning(f"Rate limited (429). Waiting {retry_after}s before retry {attempt}/{max_retries}.")
                time.sleep(retry_after)
                continue

            if r.status_code >= 500:
                log.warning(
                    f"Server error {r.status_code} on attempt {attempt}/{max_retries}: {url}"
                )
                last_exc = DownloadError(f"HTTP {r.status_code}: {url}")
                time.sleep(backoff_base ** attempt)
                continue

            r.raise_for_status()
            return r

        except PageNotFoundError:
            raise  # Never retry 404s

        except requests.exceptions.ConnectionError as e:
            log.warning(f"Connection error on attempt {attempt}/{max_retries}: {e}")
            last_exc = e
            time.sleep(backoff_base ** attempt)

        except requests.exceptions.Timeout as e:
            log.warning(f"Timeout on attempt {attempt}/{max_retries}: {url}")
            last_exc = e
            time.sleep(backoff_base ** attempt)

        except requests.exceptions.RequestException as e:
            log.warning(f"Request error on attempt {attempt}/{max_retries}: {e}")
            last_exc = e
            time.sleep(backoff_base ** attempt)

    raise DownloadError(
        f"Failed to download {url} after {max_retries} attempts. Last error: {last_exc}"
    )


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------


def build_page_url(target: MonthTarget) -> str:
    return BASE_PAGE.format(slug=target.slug)


def find_download_links(
    html: str,
    page_url: str,
) -> dict[str, str]:
    """
    Parse publication page HTML and return {'totals': url, 'mapping': url}.

    Strategy:
      1. Primary: match href containing stable stem with .zip or .csv extension,
         hosted on files.digital.nhs.uk.
      2. Fallback A: match by anchor visible text ("totals", "list size", "mapping").
      3. Fallback B: log a structured warning so the caller can escalate.

    Raises:
        LinksNotFoundError: if neither strategy finds both files.
    """
    soup = BeautifulSoup(html, "lxml")
    anchors = soup.find_all("a", href=True)
    found: dict[str, str] = {}

    # --- Primary: stem-based href matching ---
    for a in anchors:
        href = a["href"].strip()
        if not href.startswith(FILES_HOST):
            continue
        lhref = href.lower()
        ext_ok = lhref.endswith(".zip") or lhref.endswith(".csv")
        if not ext_ok:
            continue

        if "totals" not in found and TOTALS_STEM in lhref:
            found["totals"] = href
        if "mapping" not in found and MAPPING_STEM in lhref:
            found["mapping"] = href

    # --- Fallback A: visible text matching ---
    if len(found) < 2:
        for a in anchors:
            href = a["href"].strip()
            if not href.startswith(FILES_HOST):
                continue
            text = " ".join(a.get_text(" ", strip=True).split()).lower()
            lhref = href.lower()
            ext_ok = lhref.endswith(".zip") or lhref.endswith(".csv")
            if not ext_ok:
                continue

            if "totals" not in found and ("totals" in text or "list size" in text or "all persons" in text):
                log.info(f"  [Fallback A] Matched totals by link text: '{text[:60]}'")
                found["totals"] = href
            if "mapping" not in found and "mapping" in text:
                log.info(f"  [Fallback A] Matched mapping by link text: '{text[:60]}'")
                found["mapping"] = href

    missing = [k for k in ("totals", "mapping") if k not in found]
    if missing:
        # Log all hrefs from files.digital.nhs.uk to help diagnose
        all_file_links = [
            a["href"] for a in anchors
            if a["href"].strip().startswith(FILES_HOST)
        ]
        log.error(
            f"  Could not find link(s): {missing}\n"
            f"  Page: {page_url}\n"
            f"  All files.digital.nhs.uk links on page:\n"
            + "\n".join(f"    {u}" for u in all_file_links)
            + "\n  ACTION: Check if NHS Digital changed file stems or page layout."
        )
        raise LinksNotFoundError(
            f"Could not find {missing} on {page_url}. "
            "Page layout may have changed — update TOTALS_STEM / MAPPING_STEM."
        )

    return found


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


def download_file(
    session: requests.Session,
    url: str,
    out_path: Path,
    max_retries: int = 3,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    log.info(f"  Downloading: {url}")

    try:
        r = fetch_with_retry(session, url, stream=True, timeout=90, max_retries=max_retries)
        total = int(r.headers.get("Content-Length", 0))
        downloaded = 0

        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=256 * 1024):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)

        if total and downloaded < total * 0.95:
            raise DownloadError(
                f"Incomplete download: got {downloaded}/{total} bytes from {url}"
            )

        log.info(f"  Saved {downloaded:,} bytes → {out_path.name}")

    except DownloadError:
        if out_path.exists():
            out_path.unlink()
        raise


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def safe_extract_zip(zip_path: Path, extract_dir: Path) -> None:
    """Extract ZIP with Zip Slip protection."""
    extract_dir.mkdir(parents=True, exist_ok=True)
    extract_root = extract_dir.resolve()

    try:
        with zipfile.ZipFile(zip_path) as zf:
            for member in zf.infolist():
                dest = (extract_dir / member.filename).resolve()
                if not str(dest).startswith(str(extract_root)):
                    raise ExtractionError(
                        f"Unsafe path in ZIP (Zip Slip attempt?): {member.filename}"
                    )
            zf.extractall(extract_dir)
    except zipfile.BadZipFile as e:
        raise ExtractionError(f"Bad ZIP file {zip_path}: {e}") from e


def find_extracted_csv(extract_dir: Path, stem_prefix: str) -> Path:
    """Find the best matching data file (prefer xlsx > xls > csv)."""
    candidates = []
    for ext in ("xlsx", "xls", "csv"):
        candidates += list(extract_dir.rglob(f"{stem_prefix}*.{ext}"))

    def score(p: Path) -> int:
        return {"xlsx": 0, "xls": 1, "csv": 2}.get(p.suffix.lower().lstrip("."), 9)

    candidates = sorted(set(candidates), key=score)
    if not candidates:
        raise ExtractionError(
            f"No file matching '{stem_prefix}*' found in {extract_dir}\n"
            f"  Files present: {[p.name for p in extract_dir.rglob('*') if p.is_file()]}"
        )
    return candidates[0]


def get_data_path(
    session: requests.Session,
    url: str,
    dl_dir: Path,
    stem: str,
    max_retries: int,
) -> Path:
    """Download (if needed) and return the path to the CSV/XLSX data file."""
    filename = os.path.basename(urlparse(url).path) or "download.bin"
    dl_path = dl_dir / filename

    # Skip download if already exists (idempotent)
    if dl_path.exists() and dl_path.stat().st_size > 0:
        log.info(f"  Already downloaded: {dl_path.name}")
    else:
        download_file(session, url, dl_path, max_retries=max_retries)

    if dl_path.suffix.lower() == ".zip":
        extract_dir = dl_dir / f"{stem}_extracted"
        if not extract_dir.exists() or not any(extract_dir.iterdir()):
            log.info(f"  Extracting ZIP → {extract_dir.name}/")
            safe_extract_zip(dl_path, extract_dir)
        data_path = find_extracted_csv(extract_dir, stem)
    else:
        data_path = dl_path

    return data_path


# ---------------------------------------------------------------------------
# Transform
# ---------------------------------------------------------------------------


def read_data_file(path: Path) -> pd.DataFrame:
    suf = path.suffix.lower()
    try:
        if suf in (".xlsx", ".xls"):
            return pd.read_excel(path, dtype=str, engine="openpyxl" if suf == ".xlsx" else None)
        return pd.read_csv(path, dtype=str, low_memory=False)
    except Exception as e:
        raise TransformError(f"Could not read {path}: {e}") from e


def transform_list_size(df_raw: pd.DataFrame, snapshot_date: date, data_source: str) -> pd.DataFrame:
    """
    Normalise the raw list size CSV into a clean, typed DataFrame
    ready for appending to the longitudinal Parquet.
    """
    df = df_raw.copy()

    # Normalise column names
    df.columns = [c.strip().upper() for c in df.columns]

    # Filter to practice-level totals: GP / ALL sex / ALL age
    for col in ("TYPE", "SEX", "AGE"):
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip().str.upper()

    if {"TYPE", "SEX", "AGE"} <= set(df.columns):
        mask = (df["TYPE"] == "GP") & (df["SEX"] == "ALL") & (df["AGE"] == "ALL")
        df = df[mask].copy()

    if df.empty:
        raise TransformError(
            "No GP/ALL/ALL rows found in list size file. "
            "Check TYPE/SEX/AGE column values."
        )

    # Require CODE and NUMBER_OF_PATIENTS
    if "CODE" not in df.columns:
        raise TransformError(f"Missing 'CODE' column. Available: {list(df.columns)}")
    if "NUMBER_OF_PATIENTS" not in df.columns:
        raise TransformError(
            f"Missing 'NUMBER_OF_PATIENTS' column. Available: {list(df.columns)}"
        )

    df["CODE"] = df["CODE"].astype(str).str.strip()

    # Cast patient count to int — coerce non-numeric to NaN, then warn
    df["NUMBER_OF_PATIENTS"] = pd.to_numeric(
        df["NUMBER_OF_PATIENTS"].str.replace(",", ""), errors="coerce"
    )
    n_nulls = df["NUMBER_OF_PATIENTS"].isna().sum()
    if n_nulls > 0:
        log.warning(f"  {n_nulls} rows with non-numeric NUMBER_OF_PATIENTS — set to NaN.")
    df["NUMBER_OF_PATIENTS"] = df["NUMBER_OF_PATIENTS"].astype("Int64")

    # Add derived columns
    df["SNAPSHOT_DATE"] = pd.Timestamp(snapshot_date)
    df["DATA_SOURCE"] = data_source

    return df[["SNAPSHOT_DATE", "CODE", "NUMBER_OF_PATIENTS", "DATA_SOURCE"]].reset_index(drop=True)


def transform_mapping(df_raw: pd.DataFrame, snapshot_date: date, data_source: str) -> pd.DataFrame:
    """
    Normalise the raw mapping CSV into a clean DataFrame
    ready for appending to the longitudinal Parquet.
    """
    df = df_raw.copy()
    df.columns = [c.strip().upper() for c in df.columns]

    if "PRACTICE_CODE" not in df.columns:
        raise TransformError(
            f"Missing 'PRACTICE_CODE' column. Available: {list(df.columns)}"
        )

    df["PRACTICE_CODE"] = df["PRACTICE_CODE"].astype(str).str.strip()

    # Derive CLINICAL_SYSTEM from SUPPLIER_NAME
    if "SUPPLIER_NAME" in df.columns:
        supplier = df["SUPPLIER_NAME"].fillna("").astype(str).str.strip().str.upper()
        df["CLINICAL_SYSTEM"] = supplier.map({"EMIS": "EMIS Web", "TPP": "SystmOne"}).fillna("Others")
    else:
        log.warning("  SUPPLIER_NAME column not found — CLINICAL_SYSTEM will be null.")
        df["CLINICAL_SYSTEM"] = None

    df["SNAPSHOT_DATE"] = pd.Timestamp(snapshot_date)
    df["DATA_SOURCE"] = data_source

    keep_cols = [
        "SNAPSHOT_DATE", "PRACTICE_CODE", "PRACTICE_NAME", "POSTCODE",
        "PCN_CODE", "PCN_NAME", "ICB_CODE", "ICB_NAME",
        "COMM_REGION_CODE", "COMM_REGION_NAME",
        "SUPPLIER_NAME", "CLINICAL_SYSTEM", "DATA_SOURCE",
    ]
    present = [c for c in keep_cols if c in df.columns]
    missing_cols = set(keep_cols) - set(present)
    if missing_cols:
        log.warning(f"  Mapping columns not found (will be null): {missing_cols}")
        for c in missing_cols:
            df[c] = None

    return df[keep_cols].reset_index(drop=True)


def validate_practice_count(
    df: pd.DataFrame,
    snapshot_date: date,
    existing_parquet: Path,
    tolerance: float = 0.08,
) -> None:
    """Warn if practice count deviates by more than `tolerance` from previous month."""
    n_new = len(df)
    if not existing_parquet.exists():
        return
    try:
        existing = pd.read_parquet(existing_parquet, columns=["SNAPSHOT_DATE", "CODE"])
        existing["SNAPSHOT_DATE"] = pd.to_datetime(existing["SNAPSHOT_DATE"]).dt.date
        prev_dates = sorted(d for d in existing["SNAPSHOT_DATE"].unique() if d < snapshot_date)
        if not prev_dates:
            return
        prev_date = prev_dates[-1]
        n_prev = len(existing[existing["SNAPSHOT_DATE"] == prev_date])
        if n_prev > 0:
            pct_change = abs(n_new - n_prev) / n_prev
            if pct_change > tolerance:
                log.warning(
                    f"  Practice count changed significantly: {n_prev} → {n_new} "
                    f"({pct_change:.1%} vs {tolerance:.0%} tolerance). "
                    "Review for unexpected data issues."
                )
    except Exception as e:
        log.warning(f"  Could not validate practice count: {e}")


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def upsert_parquet(new_df: pd.DataFrame, parquet_path: Path, key_cols: list[str]) -> int:
    """
    Append new_df to parquet_path, replacing any rows with matching key_cols.
    Returns the number of new rows written.
    """
    if parquet_path.exists():
        try:
            existing = pd.read_parquet(parquet_path)
            # Drop rows from existing that are being replaced
            mask = existing[key_cols].apply(tuple, axis=1).isin(
                new_df[key_cols].apply(tuple, axis=1)
            )
            n_replaced = mask.sum()
            if n_replaced > 0:
                log.info(f"  Replacing {n_replaced:,} existing rows (NHS retroactive correction).")
            existing = existing[~mask]
            combined = pd.concat([existing, new_df], ignore_index=True)
        except Exception as e:
            log.warning(f"  Could not read existing Parquet ({e}). Creating new file.")
            combined = new_df
    else:
        combined = new_df

    combined = combined.sort_values(
        ["SNAPSHOT_DATE"] + [c for c in key_cols if c != "SNAPSHOT_DATE"]
    ).reset_index(drop=True)

    combined.to_parquet(parquet_path, index=False, engine="pyarrow")
    return len(new_df)


# ---------------------------------------------------------------------------
# Per-month orchestration
# ---------------------------------------------------------------------------


def process_month(
    target: MonthTarget,
    session: requests.Session,
    max_retries: int = 3,
    keep_raw: bool = False,
) -> RunResult:
    """
    Full pipeline for a single month:
      scrape → download → extract → transform → upsert Parquet

    Returns a RunResult regardless of success/failure.
    """
    result = RunResult(month=target.month, year=target.year, status="failed")
    dl_dir = DATA_RAW / target.slug
    dl_dir.mkdir(parents=True, exist_ok=True)

    page_url = build_page_url(target)
    log.info(f"Processing {target.label} → {page_url}")

    try:
        # 1. Fetch publication page
        try:
            r = fetch_with_retry(
                session, page_url,
                max_retries=max_retries,
                expected_404_ok=True,
            )
            html = r.text
        except PageNotFoundError:
            log.info(f"  → Not published yet (404): {target.label}")
            result.status = "not_published"
            return result

        # 2. Find download links
        links = find_download_links(html, page_url)
        result.totals_url = links["totals"]
        result.mapping_url = links["mapping"]

        # 3. Download both files
        totals_path = get_data_path(
            session, links["totals"], dl_dir, TOTALS_STEM, max_retries
        )
        mapping_path = get_data_path(
            session, links["mapping"], dl_dir, MAPPING_STEM, max_retries
        )

        # 4. Transform
        snapshot_date = target.snapshot_date
        data_source = "PDS" if snapshot_date >= PDS_START else "NHAIS"

        totals_raw = read_data_file(totals_path)
        mapping_raw = read_data_file(mapping_path)

        list_size_df = transform_list_size(totals_raw, snapshot_date, data_source)
        mapping_df = transform_mapping(mapping_raw, snapshot_date, data_source)

        # 5. Validate
        validate_practice_count(
            list_size_df,
            snapshot_date,
            DATA_PROCESSED / "list_size.parquet",
        )

        # 6. Upsert to Parquet
        n_list = upsert_parquet(
            list_size_df,
            DATA_PROCESSED / "list_size.parquet",
            key_cols=["SNAPSHOT_DATE", "CODE"],
        )
        n_map = upsert_parquet(
            mapping_df,
            DATA_PROCESSED / "mapping.parquet",
            key_cols=["SNAPSHOT_DATE", "PRACTICE_CODE"],
        )
        log.info(f"  ✓ Ingested {n_list:,} list size rows, {n_map:,} mapping rows.")

        # 7. Optionally clean up raw files
        if not keep_raw:
            for p in dl_dir.rglob("*"):
                if p.is_file() and p.suffix.lower() in (".zip",):
                    p.unlink()

        result.status = "success"
        result.practices_ingested = n_list

    except PageNotFoundError as e:
        result.status = "not_published"
        result.error = str(e)
        result.error_type = "PageNotFoundError"
        log.info(f"  → Skipping {target.label}: page not found.")

    except LinksNotFoundError as e:
        result.status = "failed"
        result.error = str(e)
        result.error_type = "LinksNotFoundError"
        log.error(f"  ✗ {target.label}: download links not found — NHS layout may have changed.")
        log.error("    Review TOTALS_STEM / MAPPING_STEM constants or page HTML.")

    except DownloadError as e:
        result.status = "failed"
        result.error = str(e)
        result.error_type = "DownloadError"
        log.error(f"  ✗ {target.label}: download failed — {e}")

    except ExtractionError as e:
        result.status = "failed"
        result.error = str(e)
        result.error_type = "ExtractionError"
        log.error(f"  ✗ {target.label}: extraction failed — {e}")

    except TransformError as e:
        result.status = "failed"
        result.error = str(e)
        result.error_type = "TransformError"
        log.error(f"  ✗ {target.label}: transform failed — {e}")

    except Exception as e:
        result.status = "failed"
        result.error = str(e)
        result.error_type = type(e).__name__
        log.error(f"  ✗ {target.label}: unexpected error — {type(e).__name__}: {e}")
        log.debug("  Full traceback:", exc_info=True)

    return result


# ---------------------------------------------------------------------------
# Month range generator
# ---------------------------------------------------------------------------


def month_range(from_date: date, to_date: date) -> list[MonthTarget]:
    """Generate all MonthTarget objects between from_date and to_date (inclusive)."""
    targets = []
    year = from_date.year
    month = from_date.month
    while date(year, month, 1) <= to_date:
        month_name = list(MONTHS.values())[
            [list(MONTHS.keys()).index(str(month).zfill(0))
             for k in MONTHS if k == str(month)][0]
        ]
        # Simpler: use a direct mapping
        m_name = {
            1: "january", 2: "february", 3: "march", 4: "april",
            5: "may", 6: "june", 7: "july", 8: "august",
            9: "september", 10: "october", 11: "november", 12: "december",
        }[month]
        targets.append(MonthTarget(month=m_name, year=year))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return targets


def normalize_month(m: str) -> str:
    k = m.strip().lower()
    if k not in MONTHS:
        raise ValueError(f"Unrecognised month '{m}'. Use name or number.")
    return MONTHS[k]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(
        description="NHS GP Practice Data — Historical Backfill",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--from-month", default=None,
                    help=f"Start month (name or number). Default: {DEFAULT_FROM.strftime('%B')}")
    ap.add_argument("--from-year", type=int, default=None,
                    help=f"Start year. Default: {DEFAULT_FROM.year}")
    ap.add_argument("--to-month", default=None,
                    help="End month. Default: current month")
    ap.add_argument("--to-year", type=int, default=None,
                    help="End year. Default: current year")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show which months would be processed without downloading")
    ap.add_argument("--force", action="store_true",
                    help="Re-download even if month already exists in Parquet")
    ap.add_argument("--retry-failed", action="store_true",
                    help="Only process months that previously failed")
    ap.add_argument("--keep-raw", action="store_true",
                    help="Keep ZIP files after extraction")
    ap.add_argument("--delay", type=float, default=2.0,
                    help="Seconds to wait between months (default: 2.0)")
    ap.add_argument("--max-retries", type=int, default=3,
                    help="HTTP retry attempts per file (default: 3)")

    args = ap.parse_args()

    today = date.today()

    from_date = date(
        args.from_year or DEFAULT_FROM.year,
        MONTH_TO_INT[normalize_month(args.from_month)] if args.from_month else DEFAULT_FROM.month,
        1,
    )
    to_date = date(
        args.to_year or today.year,
        MONTH_TO_INT[normalize_month(args.to_month)] if args.to_month else today.month,
        1,
    )

    if from_date > to_date:
        ap.error(f"--from ({from_date}) is after --to ({to_date})")

    all_targets = month_range(from_date, to_date)

    # Determine which months to skip
    existing_log = load_pipeline_log()

    if args.retry_failed:
        failed = set(get_failed_months(existing_log))
        targets = [t for t in all_targets if (t.month, t.year) in failed]
        log.info(f"Retry mode: {len(targets)} previously failed months to retry.")
    elif not args.force:
        already_ingested = get_ingested_snapshot_dates(DATA_PROCESSED / "list_size.parquet")
        targets = [t for t in all_targets if t.snapshot_date not in already_ingested]
        skipped = len(all_targets) - len(targets)
        if skipped:
            log.info(f"Skipping {skipped} months already in Parquet (use --force to override).")
    else:
        targets = all_targets

    log.info(f"Backfill range: {from_date} → {to_date}")
    log.info(f"Months to process: {len(targets)}")

    if args.dry_run:
        log.info("DRY RUN — no files will be downloaded.")
        for t in targets:
            log.info(f"  Would process: {t.label}")
        return

    if not targets:
        log.info("Nothing to do. All months already ingested.")
        return

    session = make_session()
    results = {"success": 0, "failed": 0, "skipped": 0, "not_published": 0}

    for i, target in enumerate(targets):
        result = process_month(
            target,
            session,
            max_retries=args.max_retries,
            keep_raw=args.keep_raw,
        )
        log_run(result)
        results[result.status] = results.get(result.status, 0) + 1

        # Be polite between requests; longer pause after errors
        if i < len(targets) - 1:
            delay = args.delay if result.status != "failed" else args.delay * 2
            time.sleep(delay)

    # Summary
    log.info("\n" + "=" * 60)
    log.info("BACKFILL COMPLETE")
    log.info(f"  ✓ Success:       {results['success']}")
    log.info(f"  ✗ Failed:        {results['failed']}")
    log.info(f"  ~ Not published: {results.get('not_published', 0)}")
    log.info(f"  → Skipped:       {results.get('skipped', 0)}")
    log.info("=" * 60)

    if results["failed"] > 0:
        log.warning(
            f"{results['failed']} month(s) failed. "
            "Run with --retry-failed to retry, or check backfill.log for details."
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
