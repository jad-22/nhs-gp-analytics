#!/usr/bin/env python3
"""
Single-chain pipeline:
  download → extract → merge (upsert into base) → output

Folders:
  Base (older):
    ./base/{month}-{year}/
      - GP List Size (All)-Download.csv
      - GP Mapping (England)-Download.csv

  Downloads (new):
    ./downloads/{month}-{year}/
      - downloaded zips
      - totals_extracted/...
      - mapping_extracted/...

  Output (latest):
    ./output/{month}-{year}/
      - GP List Size (All).csv
      - GP Mapping (England).csv

Usage:
  python gp_practice_pipeline.py --month december --year 2025
  python gp_practice_pipeline.py --month 12 --year 2025 --delete-zips
"""

from __future__ import annotations

import argparse
import os
import re
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup


# ----------------------------
# Config
# ----------------------------

BASE_PAGE = (
    "https://digital.nhs.uk/data-and-information/publications/statistical/"
    "patients-registered-at-a-gp-practice/{slug}"
)

# These are stable "resource filename" identifiers used on NHS Digital file host URLs
# Note: NHS Digital may provide these as either .zip or .csv files
TOTALS_STEM = "gp-reg-pat-prac-all"
MAPPING_STEM = "gp-reg-pat-prac-map"

BASE_LIST_FILENAME = "GP List Size (All)-Download.csv"
BASE_MAP_FILENAME = "GP Mapping (England)-Download.csv"

OUT_LIST_FILENAME = "GP List Size (All).csv"
OUT_MAP_FILENAME = "GP Mapping (England).csv"

MONTHS: Dict[str, str] = {
    "1": "january", "01": "january", "jan": "january", "january": "january",
    "2": "february", "02": "february", "feb": "february", "february": "february",
    "3": "march", "03": "march", "mar": "march", "march": "march",
    "4": "april", "04": "april", "apr": "april", "april": "april",
    "5": "may", "05": "may", "may": "may",
    "6": "june", "06": "june", "jun": "june", "june": "june",
    "7": "july", "07": "july", "jul": "july", "july": "july",
    "8": "august", "08": "august", "aug": "august", "august": "august",
    "9": "september", "09": "september", "sep": "september", "sept": "september", "september": "september",
    "10": "october", "oct": "october", "october": "october",
    "11": "november", "nov": "november", "november": "november",
    "12": "december", "dec": "december", "december": "december",
}


# ----------------------------
# Download & extract
# ----------------------------

@dataclass(frozen=True)
class TargetLink:
    name: str
    href: str

def default_month_year() -> tuple[str, int]:
    today = datetime.today()
    # month number -> normalized month slug (january, february, ...)
    month_str = str(today.month)
    return normalize_month(month_str), today.year


def normalize_month(month: str) -> str:
    m = month.strip().lower()
    if m not in MONTHS:
        raise ValueError(f"Unrecognized month '{month}'. Use name (e.g. december) or number (e.g. 12).")
    return MONTHS[m]


def build_page_url(month: str, year: int) -> str:
    slug = f"{normalize_month(month)}-{int(year)}"
    return BASE_PAGE.format(slug=slug)


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; gp-practice-pipeline/1.0; +https://digital.nhs.uk/)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    return s


def fetch_html(session: requests.Session, url: str, timeout: int = 30) -> str:
    r = session.get(url, timeout=timeout)
    r.raise_for_status()
    return r.text


def find_target_links(html: str) -> Dict[str, TargetLink]:
    soup = BeautifulSoup(html, "html.parser")
    anchors = soup.find_all("a", href=True)

    found: Dict[str, TargetLink] = {}

    # Prefer matching by stable filenames in href (supports both .zip and .csv)
    for a in anchors:
        href = a["href"].strip()
        # Check for totals file (zip or csv)
        if TOTALS_STEM in href and (href.endswith(".zip") or href.endswith(".csv")):
            # Prefer exact match over partial
            if href.endswith(f"{TOTALS_STEM}.zip") or href.endswith(f"{TOTALS_STEM}.csv"):
                found["totals"] = TargetLink("totals", href)
        # Check for mapping file (zip or csv)
        if MAPPING_STEM in href and (href.endswith(".zip") or href.endswith(".csv")):
            if href.endswith(f"{MAPPING_STEM}.zip") or href.endswith(f"{MAPPING_STEM}.csv"):
                found["mapping"] = TargetLink("mapping", href)

    # Fallback: infer from visible card text
    if "totals" not in found or "mapping" not in found:
        for a in anchors:
            text = " ".join(a.get_text(" ", strip=True).split()).lower()
            href = a["href"].strip()
            if not href.startswith("https://files.digital.nhs.uk/"):
                continue

            is_data_file = href.endswith(".zip") or href.endswith(".csv")
            if "totals" not in found and ("totals" in text or "list size" in text) and is_data_file:
                found["totals"] = TargetLink("totals", href)
            if "mapping" not in found and "mapping" in text and is_data_file:
                found["mapping"] = TargetLink("mapping", href)

    return found


def filename_from_url(url: str) -> str:
    path = urlparse(url).path
    name = os.path.basename(path)
    return name or "download.bin"


def download_file(
    session: requests.Session,
    url: str,
    out_path: Path,
    timeout: int = 60,
    retries: int = 3,
    backoff_s: float = 1.5,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    for attempt in range(1, retries + 1):
        try:
            with session.get(url, stream=True, timeout=timeout) as r:
                r.raise_for_status()
                with open(out_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            f.write(chunk)
            return
        except requests.RequestException as e:
            if attempt >= retries:
                raise
            sleep_for = backoff_s ** attempt
            print(f"Download failed (attempt {attempt}/{retries}): {e}\nRetrying in {sleep_for:.1f}s...")
            time.sleep(sleep_for)


def safe_extract_zip(zip_path: Path, extract_dir: Path) -> None:
    """
    Extract ZIP with basic Zip Slip protection.
    """
    extract_dir.mkdir(parents=True, exist_ok=True)
    extract_root = extract_dir.resolve()

    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            dest_path = (extract_dir / member.filename).resolve()
            if not str(dest_path).startswith(str(extract_root)):
                raise RuntimeError(f"Unsafe path in zip (possible Zip Slip): {member.filename}")

        zf.extractall(extract_dir)


def find_extracted_dataset(extract_dir: Path, stem_prefix: str) -> Path:
    """
    Find the first matching dataset file in an extracted folder.
    Supports .xlsx/.xls/.csv. Searches recursively.
    """
    if not extract_dir.exists():
        raise FileNotFoundError(str(extract_dir))

    candidates = []
    for ext in ("xlsx", "xls", "csv"):
        # common: exact filename
        candidates += list(extract_dir.rglob(f"{stem_prefix}.{ext}"))
        # sometimes files are suffixed
        candidates += list(extract_dir.rglob(f"{stem_prefix}*.{ext}"))

    # prefer xlsx > xls > csv if multiple exist
    def score(p: Path) -> int:
        suf = p.suffix.lower()
        return {"xlsx": 0, "xls": 1, "csv": 2}.get(suf.lstrip("."), 9)

    candidates = sorted(set(candidates), key=score)
    if not candidates:
        raise FileNotFoundError(f"Could not find extracted dataset starting with '{stem_prefix}' in {extract_dir}")
    return candidates[0]


# ----------------------------
# Merge logic
# ----------------------------

def now_stamp() -> str:
    # Match your base timestamp style: "YYYY-MM-DD h:mmpm"
    dt = datetime.now()
    try:
        s = dt.strftime("%Y-%m-%d %-I:%M%p")
    except ValueError:
        s = dt.strftime("%Y-%m-%d %I:%M%p").lstrip("0").replace(" 0", " ")
    return s.replace("AM", "am").replace("PM", "pm")


def to_ddMonYYYY(value) -> str:
    """Convert '2025-12-01' -> '01Dec2025'. Leave '01Dec2025' as-is."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return value
    s = str(value).strip()
    if not s:
        return s

    if re.fullmatch(r"\d{2}[A-Za-z]{3}\d{4}", s):
        return s[:2] + s[2:5].title() + s[5:]

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        dt = datetime.strptime(s, "%Y-%m-%d")
        return dt.strftime("%d%b%Y")

    s2 = re.sub(r"\s+", "", s)
    if re.fullmatch(r"\d{2}[A-Za-z]{3}\d{4}", s2):
        return s2[:2] + s2[2:5].title() + s2[5:]

    return s


def read_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(str(path))
    suf = path.suffix.lower()
    if suf in (".xlsx", ".xls"):
        return pd.read_excel(path, dtype=str, engine="openpyxl" if suf == ".xlsx" else None)
    return pd.read_csv(path, dtype=str)


def build_list_fields(df_in: pd.DataFrame) -> pd.DataFrame:
    df = df_in.copy()
    if "CODE" in df.columns:
        df["CODE"] = df["CODE"].astype(str).str.strip()
        df["LIST_ID-PRACTICE_ID"] = "LIST-" + df["CODE"]
    if "EXTRACT_DATE" in df.columns:
        df["EXTRACT_DATE"] = df["EXTRACT_DATE"].map(to_ddMonYYYY)
    return df


def build_mapping_fields(df_in: pd.DataFrame) -> pd.DataFrame:
    df = df_in.copy()

    if "PRACTICE_CODE" in df.columns:
        df["PRACTICE_CODE"] = df["PRACTICE_CODE"].astype(str).str.strip()

    # PRACTICE_ID: "{PRACTICE_CODE} - {PRACTICE_NAME}"
    if {"PRACTICE_CODE", "PRACTICE_NAME"} <= set(df.columns):
        df["PRACTICE_ID"] = (
            df["PRACTICE_CODE"].fillna("").astype(str).str.strip()
            + " - "
            + df["PRACTICE_NAME"].fillna("").astype(str).str.strip()
        ).str.strip(" -")

    # formatted region names (as per base)
    if "ICB_NAME" in df.columns:
        df["ICB_NAME_FORMATED"] = df["ICB_NAME"].astype(str).str.upper()
    if "COMM_REGION_NAME" in df.columns:
        df["COMM_REGION_NAME_FORMATED"] = df["COMM_REGION_NAME"].astype(str).str.upper()

    # clinical system derived from supplier (download mapping uses SUPPLIER_NAME)
    if "SUPPLIER_NAME" in df.columns:
        supplier = df["SUPPLIER_NAME"].fillna("").astype(str).str.strip().str.upper()

        df["CLINICAL_SYSTEM"] = supplier.map({
            "TPP": "SystmOne",
            "EMIS": "EMIS Web",
        }).fillna("Others")

    # foreign key to list size
    if "PRACTICE_CODE" in df.columns:
        df["Associated LIST_ID-PRACTICE_ID"] = "LIST-" + df["PRACTICE_CODE"].astype(str).str.strip()

    # composite labels used in base
    if {"PRACTICE_CODE", "PRACTICE_NAME"} <= set(df.columns):
        df["Practice Code & Name"] = (
            df["PRACTICE_NAME"].astype(str).str.strip()
            + " ("
            + df["PRACTICE_CODE"].astype(str).str.strip()
            + ")"
        )
    if {"PCN_CODE", "PCN_NAME"} <= set(df.columns):
        df["PCN Code & Name"] = df["PCN_CODE"].astype(str).str.strip() + " - " + df["PCN_NAME"].astype(str).str.strip()
    if {"ICB_CODE", "ICB_NAME_FORMATED"} <= set(df.columns):
        df["ICB Code & Name"] = df["ICB_CODE"].astype(str).str.strip() + " - " + df["ICB_NAME_FORMATED"].astype(str).str.strip()
    if {"COMM_REGION_CODE", "COMM_REGION_NAME_FORMATED"} <= set(df.columns):
        df["Region Code & Name"] = df["COMM_REGION_CODE"].astype(str).str.strip() + " - " + df["COMM_REGION_NAME_FORMATED"].astype(str).str.strip()

    if "EXTRACT_DATE" in df.columns:
        df["EXTRACT_DATE"] = df["EXTRACT_DATE"].map(to_ddMonYYYY)

    return df


def upsert_by_key(base_df: pd.DataFrame, new_df: pd.DataFrame, key: str, created_col: str, modified_col: str) -> pd.DataFrame:
    """
    Order-preserving UPSERT:
    - Existing base rows keep the same relative order/positions as base_df.
    - Rows with matching key are updated in-place (no reordering).
    - New keys are appended at the bottom in the order they appear in new_df.
    - created_col is preserved for existing rows; set for new rows.
    - modified_col is set for any key present in new_df.
    """

    base = base_df.copy()
    new = new_df.copy()

    if key not in base.columns:
        raise KeyError(f"Base is missing key column '{key}'")
    if key not in new.columns:
        raise KeyError(f"New is missing key column '{key}'")

    # Normalize key
    base[key] = base[key].astype(str).str.strip()
    new[key] = new[key].astype(str).str.strip()

    # If new has duplicate keys, keep the LAST occurrence (most recent in the file),
    # while preserving the overall row order of surviving rows.
    new = new.drop_duplicates(subset=[key], keep="last").copy()

    # Ensure timestamp cols exist
    if created_col not in base.columns:
        base[created_col] = pd.NA
    if modified_col not in base.columns:
        base[modified_col] = pd.NA

    stamp = now_stamp()

    # Build lookup for new values by key
    new_idx = new.set_index(key, drop=False)

    base_keys = set(base[key])
    new_keys_in_order = new[key].tolist()  # preserves file order

    # Keys that already exist in base (update in-place)
    intersect_mask = base[key].isin(new_idx.index)

    # Update base in-place column-by-column (preserves row order)
    for col in new.columns:
        base.loc[intersect_mask, col] = base.loc[intersect_mask, key].map(new_idx[col])

    # Update LAST_MODIFIED for updated/seen keys
    base.loc[intersect_mask, modified_col] = stamp

    # Keys that are new (append at bottom in new-file order)
    to_add_keys = [k for k in new_keys_in_order if k not in base_keys]

    if to_add_keys:
        add_df = new_idx.loc[to_add_keys].copy()

        # Make sure appended rows have base columns too (union of columns)
        for col in base.columns:
            if col not in add_df.columns:
                add_df[col] = pd.NA
        # And base can accept any new-only columns
        for col in add_df.columns:
            if col not in base.columns:
                base[col] = pd.NA

        # Set timestamps for appended rows
        add_df[created_col] = stamp
        add_df[modified_col] = stamp

        # Reorder add_df columns to match base (extras at end)
        add_df = add_df[base.columns.tolist() + [c for c in add_df.columns if c not in base.columns]]

        # Append in order
        base = pd.concat([base, add_df[base.columns]], axis=0, ignore_index=True)

    return base


def merge_base_with_downloads(base_list: pd.DataFrame, base_map: pd.DataFrame,
                             new_list_raw: pd.DataFrame, new_map_raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    # Prepare new list: keep GP + ALL + ALL (matches your base “All persons” slice)
    new_list = new_list_raw.copy()
    for col in ["TYPE", "SEX", "AGE"]:
        if col in new_list.columns:
            new_list[col] = new_list[col].astype(str).str.strip()
    if {"TYPE", "SEX", "AGE"} <= set(new_list.columns):
        new_list = new_list[(new_list["TYPE"] == "GP") & (new_list["SEX"] == "ALL") & (new_list["AGE"] == "ALL")].copy()
    new_list = build_list_fields(new_list)

    # Prepare new mapping
    new_map = build_mapping_fields(new_map_raw)

    # Prep base
    base_list_p = build_list_fields(base_list)
    base_map_p = build_mapping_fields(base_map)

    # Upsert
    merged_map = upsert_by_key(base_map_p, new_map, key="PRACTICE_CODE", created_col="CREATED_ON", modified_col="LAST_MODIFIED")
    merged_list = upsert_by_key(base_list_p, new_list, key="CODE", created_col="CREATED_ON", modified_col="LAST_MODIFIED")

    # Rebuild cross references and patient count sync
    if {"CODE", "NUMBER_OF_PATIENTS"} <= set(merged_list.columns) and "PRACTICE_CODE" in merged_map.columns:
        patients_by_code = merged_list.set_index("CODE")["NUMBER_OF_PATIENTS"]
        merged_map["NUMBER_OF_PATIENTS"] = merged_map["PRACTICE_CODE"].map(patients_by_code)

    if {"PRACTICE_CODE"} <= set(merged_map.columns) and {"CODE", "LIST_ID-PRACTICE_ID"} <= set(merged_list.columns):
        listid_by_code = merged_list.set_index("CODE")["LIST_ID-PRACTICE_ID"]
        merged_map["Associated LIST_ID-PRACTICE_ID"] = merged_map["PRACTICE_CODE"].map(listid_by_code).fillna(
            "LIST-" + merged_map["PRACTICE_CODE"].astype(str).str.strip()
        )

    if {"CODE"} <= set(merged_list.columns) and {"PRACTICE_CODE", "PRACTICE_ID"} <= set(merged_map.columns):
        pracid_by_code = merged_map.set_index("PRACTICE_CODE")["PRACTICE_ID"]
        merged_list["Associated PRACTICE_ID"] = merged_list["CODE"].map(pracid_by_code)

    # Keep base column order first
    base_list_cols = list(base_list.columns)
    base_map_cols = list(base_map.columns)

    extra_list_cols = [c for c in merged_list.columns if c not in base_list_cols]
    extra_map_cols = [c for c in merged_map.columns if c not in base_map_cols]

    merged_list_out = merged_list[base_list_cols + extra_list_cols]
    merged_map_out = merged_map[base_map_cols + extra_map_cols]

    return merged_list_out, merged_map_out


# ----------------------------
# Main pipeline
# ----------------------------

def main() -> None:
    ap = argparse.ArgumentParser()

    # Month/year now optional; default to today's date if not provided
    ap.add_argument(
        "--month",
        help="Month name (e.g. december) or number (e.g. 12). Defaults to today's month.",
    )
    ap.add_argument(
        "--year",
        type=int,
        help="Year, e.g. 2025. Defaults to today's year.",
    )

    ap.add_argument("--base-root", default="./base", help="Root folder containing base/{month}-{year}/...")
    ap.add_argument("--downloads-root", default="./downloads", help="Root folder for downloads/{month}-{year}/...")
    ap.add_argument("--output-root", default="./output", help="Root folder for output/{month}-{year}/...")

    # Default behavior: delete zips. Use --keep-zips to override.
    ap.add_argument(
        "--keep-zips",
        action="store_true",
        help="Keep zip files (default is to delete them).",
    )

    args = ap.parse_args()

    # --- derive month/year defaults ---
    if args.month is not None and args.year is not None:
        month_norm = normalize_month(args.month)
        year = int(args.year)
    elif args.month is None and args.year is None:
        today = datetime.today()
        month_norm = normalize_month(str(today.month))
        year = today.year
    else:
        raise ValueError("Provide both --month and --year together, or neither to use today's date.")

    slug = f"{month_norm}-{year}"
    delete_zips = not args.keep_zips

    base_dir = Path(args.base_root) / slug
    dl_dir = Path(args.downloads_root) / slug
    out_dir = Path(args.output_root) / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    dl_dir.mkdir(parents=True, exist_ok=True)

    # --- 1) download ---
    page_url = build_page_url(month_norm, year)
    print(f"Fetching publication page: {page_url}")

    session = make_session()
    html = fetch_html(session, page_url)
    links = find_target_links(html)

    missing = [k for k in ("totals", "mapping") if k not in links]
    if missing:
        raise RuntimeError(f"Could not find link(s): {missing} on {page_url}. Page layout/filenames may have changed.")

    totals_url = links["totals"].href
    mapping_url = links["mapping"].href

    totals_dl_path = dl_dir / filename_from_url(totals_url)
    mapping_dl_path = dl_dir / filename_from_url(mapping_url)

    print(f"\nDownloading totals:\n  {totals_url}\n  -> {totals_dl_path}")
    download_file(session, totals_url, totals_dl_path)

    print(f"\nDownloading mapping:\n  {mapping_url}\n  -> {mapping_dl_path}")
    download_file(session, mapping_url, mapping_dl_path)

    # --- 2) extract (only if ZIP) or use CSV directly ---
    totals_extract_dir = dl_dir / "totals_extracted"
    mapping_extract_dir = dl_dir / "mapping_extracted"

    # Handle totals file
    if totals_dl_path.suffix.lower() == ".zip":
        print(f"\nExtracting totals -> {totals_extract_dir}")
        safe_extract_zip(totals_dl_path, totals_extract_dir)
        if delete_zips:
            totals_dl_path.unlink(missing_ok=True)
        totals_data_path = find_extracted_dataset(totals_extract_dir, TOTALS_STEM)
    else:
        print(f"\nTotals is a direct CSV (no extraction needed)")
        totals_data_path = totals_dl_path

    # Handle mapping file
    if mapping_dl_path.suffix.lower() == ".zip":
        print(f"Extracting mapping -> {mapping_extract_dir}")
        safe_extract_zip(mapping_dl_path, mapping_extract_dir)
        if delete_zips:
            mapping_dl_path.unlink(missing_ok=True)
        mapping_data_path = find_extracted_dataset(mapping_extract_dir, MAPPING_STEM)
    else:
        print(f"Mapping is a direct CSV (no extraction needed)")
        mapping_data_path = mapping_dl_path

    if delete_zips:
        print("Deleted any zip files (if applicable).")
    else:
        print("Keeping downloaded files (requested via --keep-zips).")

    print(f"\nFound extracted totals dataset:  {totals_data_path}")
    print(f"Found extracted mapping dataset: {mapping_data_path}")

    # --- 4) read base + new ---
    base_list_path = base_dir / BASE_LIST_FILENAME
    base_map_path = base_dir / BASE_MAP_FILENAME

    if not base_list_path.exists():
        raise FileNotFoundError(f"Missing base list file: {base_list_path}")
    if not base_map_path.exists():
        raise FileNotFoundError(f"Missing base mapping file: {base_map_path}")

    print(f"\nReading base list: {base_list_path}")
    base_list = read_table(base_list_path)

    print(f"Reading base mapping: {base_map_path}")
    base_map = read_table(base_map_path)

    print(f"\nReading new totals:  {totals_data_path}")
    new_list_raw = read_table(totals_data_path)

    print(f"Reading new mapping: {mapping_data_path}")
    new_map_raw = read_table(mapping_data_path)

    # --- 5) merge/upsert + rebuild foreign keys ---
    print("\nMerging (upsert base with new)...")
    merged_list, merged_map = merge_base_with_downloads(base_list, base_map, new_list_raw, new_map_raw)

    # --- 6) write outputs (renamed, without “-Download”) ---
    out_list_path = out_dir / OUT_LIST_FILENAME
    out_map_path = out_dir / OUT_MAP_FILENAME

    merged_list.to_csv(out_list_path, index=False)
    merged_map.to_csv(out_map_path, index=False)

    print("\nWrote latest outputs:")
    print(f"- {out_list_path}")
    print(f"- {out_map_path}")
    
    print("\nPractice Data Generation Complete.")
    input("Press Enter to exit...")

if __name__ == "__main__":
    main()
