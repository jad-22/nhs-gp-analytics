"""Extract an England-only ONSPD lookup parquet using DuckDB."""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_GLOB = REPO_ROOT / "data" / "enrichment" / "onspd" / "*.csv"
DEFAULT_OUTPUT = REPO_ROOT / "data" / "enrichment" / "onspd_postcode_lookup.parquet"


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract England-only ONSPD parquet")
    parser.add_argument(
        "--input-glob",
        default=str(DEFAULT_INPUT_GLOB),
        help="Glob pattern for ONSPD CSV files",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="Output parquet path",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=8,
        help="DuckDB worker threads",
    )
    parser.add_argument(
        "--memory-limit",
        default="8GB",
        help="DuckDB memory limit, e.g. 8GB",
    )
    parser.add_argument(
        "--temp-directory",
        default=str(REPO_ROOT / "data" / "tmp" / "duckdb_temp"),
        help="DuckDB temp directory",
    )
    args = parser.parse_args()

    input_glob = args.input_glob.replace("\\", "/")
    output_file = Path(args.output)
    output_path = str(output_file).replace("\\", "/")
    temp_dir = Path(args.temp_directory)

    temp_dir.mkdir(parents=True, exist_ok=True)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    if output_file.exists():
        output_file.unlink()

    con = duckdb.connect()
    con.execute(f"SET threads TO {max(1, args.threads)};")
    con.execute(f"SET memory_limit = '{args.memory_limit}';")
    escaped_temp_dir = str(temp_dir).replace("'", "''")
    con.execute(f"SET temp_directory = '{escaped_temp_dir}';")

    query = f"""
COPY (
    SELECT
        pcd7 AS postcode,
        lsoa11cd,
        lsoa21cd,
        TRY_CAST(lat AS DOUBLE) AS latitude,
        TRY_CAST(long AS DOUBLE) AS longitude
    FROM read_csv(
        '{input_glob}',
        header = true,
        delim = ',',
        quote = '"',
        escape = '"',
        union_by_name = true,
        all_varchar = true,
        ignore_errors = true,
        strict_mode = false,
        null_padding = true,
        sample_size = 20480
    )
    WHERE ctry25cd = 'E92000001'
      AND lsoa21cd IS NOT NULL
      AND lsoa21cd <> ''
) TO '{output_path}'
WITH (
    FORMAT PARQUET,
    COMPRESSION ZSTD
);
"""

    con.execute(query)

    print(f"Done. Output written to: {output_file}")


if __name__ == "__main__":
    main()
