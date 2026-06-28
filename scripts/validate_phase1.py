"""Phase 1 validation checks for processed parquet outputs."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
LIST_PATH = REPO_ROOT / "data" / "processed" / "list_size.parquet"
MAPPING_PATH = REPO_ROOT / "data" / "processed" / "mapping.parquet"


def _check_required_columns(df: pd.DataFrame, required: list[str], label: str) -> list[str]:
    missing = [column for column in required if column not in df.columns]
    if missing:
        return [f"{label}: missing required columns {missing}"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Phase 1 data outputs")
    parser.add_argument("--list", default=str(LIST_PATH))
    parser.add_argument("--mapping", default=str(MAPPING_PATH))
    args = parser.parse_args()

    list_path = Path(args.list)
    mapping_path = Path(args.mapping)

    failures: list[str] = []

    if not list_path.exists():
        failures.append(f"list_size parquet not found: {list_path}")
    if not mapping_path.exists():
        failures.append(f"mapping parquet not found: {mapping_path}")
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1

    list_df = pd.read_parquet(list_path)
    mapping_df = pd.read_parquet(mapping_path)

    failures.extend(
        _check_required_columns(
            list_df,
            ["SNAPSHOT_DATE", "CODE", "NUMBER_OF_PATIENTS", "DATA_SOURCE"],
            "list_size",
        )
    )
    failures.extend(
        _check_required_columns(
            mapping_df,
            ["SNAPSHOT_DATE", "PRACTICE_CODE", "CLINICAL_SYSTEM"],
            "mapping",
        )
    )

    if not failures:
        list_dupes = list_df.duplicated(subset=["SNAPSHOT_DATE", "CODE"]).sum()
        map_dupes = mapping_df.duplicated(subset=["SNAPSHOT_DATE", "PRACTICE_CODE"]).sum()
        if list_dupes:
            failures.append(f"list_size has {list_dupes} duplicate SNAPSHOT_DATE+CODE rows")
        if map_dupes:
            failures.append(f"mapping has {map_dupes} duplicate SNAPSHOT_DATE+PRACTICE_CODE rows")

    if "SNAPSHOT_DATE" in list_df.columns and len(list_df):
        list_dates = pd.to_datetime(list_df["SNAPSHOT_DATE"], errors="coerce")
        print(f"list_size rows: {len(list_df):,}")
        print(f"list_size snapshots: {list_dates.min().date()} -> {list_dates.max().date()}")
    if "SNAPSHOT_DATE" in mapping_df.columns and len(mapping_df):
        map_dates = pd.to_datetime(mapping_df["SNAPSHOT_DATE"], errors="coerce")
        print(f"mapping rows: {len(mapping_df):,}")
        print(f"mapping snapshots: {map_dates.min().date()} -> {map_dates.max().date()}")

    if len(list_df) == 0:
        failures.append("list_size parquet is empty")
    if len(mapping_df) == 0:
        failures.append("mapping parquet is empty")

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1

    print("PASS: Phase 1 validation checks completed successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
