"""Prepare IMD source data into a typed parquet file."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import duckdb
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = REPO_ROOT / "data" / "enrichment" / "imd_2025.csv"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "enrichment" / "imd_2025.parquet"


def to_snake_case(name: str) -> str:
    name = name.strip()
    name = name.replace("&", "and")
    name = name.replace("/", " ")
    name = name.replace("-", " ")
    name = name.replace("(", " ")
    name = name.replace(")", " ")
    name = re.sub(r"[^0-9a-zA-Z]+", "_", name)
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    name = name.lower()
    name = re.sub(r"_+", "_", name)
    return name.strip("_")


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare IMD source CSV to parquet")
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="Path to IMD source CSV")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output parquet path")
    args = parser.parse_args()

    input_file = Path(args.input)
    output_file = Path(args.output)

    if not input_file.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")

    print(f"Reading: {input_file}")
    df = pd.read_csv(
        input_file,
        sep=None,
        engine="python",
        dtype=str,
        encoding="utf-8-sig",
    )

    print(f"Rows read: {len(df):,}")
    print(f"Columns read: {len(df.columns):,}")

    df.columns = [to_snake_case(col) for col in df.columns]

    rename_map = {
        "lsoa_code": "lsoa11cd",
        "lsoa_name": "lsoa11_name",
        "local_authority_district_code": "lad_code",
        "local_authority_district_name": "lad_name",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    for col in df.columns:
        df[col] = df[col].astype("string").str.strip()

    string_columns = {"lsoa11cd", "lsoa11_name", "lad_code", "lad_name"}
    for col in df.columns:
        if col not in string_columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "lsoa11cd" not in df.columns:
        raise ValueError("Missing required column after cleaning: lsoa11cd")

    duplicate_lsoas = df["lsoa11cd"].duplicated().sum()
    if duplicate_lsoas:
        print(f"Warning: found {duplicate_lsoas:,} duplicated LSOA codes.")

    output_file.parent.mkdir(parents=True, exist_ok=True)
    print(f"Writing Parquet: {output_file}")
    df.to_parquet(output_file, engine="pyarrow", index=False, compression="zstd")

    con = duckdb.connect()
    escaped = str(output_file).replace("'", "''")
    result = con.execute(
        f"SELECT COUNT(*) AS row_count, COUNT(DISTINCT lsoa11cd) AS distinct_lsoa_count FROM read_parquet('{escaped}')"
    ).fetchdf()
    print(result)


if __name__ == "__main__":
    main()
