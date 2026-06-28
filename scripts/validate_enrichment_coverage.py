"""Validate enrichment coverage (IMD + geo) in mapping parquet outputs."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MAPPING_PATH = REPO_ROOT / "data" / "processed" / "mapping.parquet"


def _pct(series: pd.Series) -> float:
    if len(series) == 0:
        return 0.0
    return float(series.notna().mean())


def _render_pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate IMD and geo enrichment coverage")
    parser.add_argument("--mapping", default=str(DEFAULT_MAPPING_PATH), help="Path to mapping parquet")
    parser.add_argument(
        "--min-imd-coverage",
        type=float,
        default=None,
        help="Optional minimum IMD coverage (0-1) for latest snapshot",
    )
    parser.add_argument(
        "--min-geo-coverage",
        type=float,
        default=None,
        help="Optional minimum geo coverage (0-1) for latest snapshot",
    )
    parser.add_argument(
        "--top-n-regions",
        type=int,
        default=10,
        help="How many regions to show in latest-snapshot regional coverage summary",
    )
    args = parser.parse_args()

    mapping_path = Path(args.mapping)
    if not mapping_path.exists():
        print(f"FAIL: mapping parquet not found: {mapping_path}")
        return 1

    df = pd.read_parquet(mapping_path)
    required_columns = ["SNAPSHOT_DATE", "IMD_SCORE", "IMD_DECILE", "LATITUDE", "LONGITUDE"]
    missing = [column for column in required_columns if column not in df.columns]
    if missing:
        print(f"FAIL: missing enrichment columns in mapping parquet: {missing}")
        return 1

    if len(df) == 0:
        print("FAIL: mapping parquet is empty")
        return 1

    df = df.copy()
    df["SNAPSHOT_DATE"] = pd.to_datetime(df["SNAPSHOT_DATE"], errors="coerce")
    df = df[df["SNAPSHOT_DATE"].notna()]

    if len(df) == 0:
        print("FAIL: SNAPSHOT_DATE could not be parsed for any rows")
        return 1

    latest_snapshot = df["SNAPSHOT_DATE"].max()
    latest_df = df[df["SNAPSHOT_DATE"] == latest_snapshot].copy()

    imd_complete = df["IMD_SCORE"].notna() & df["IMD_DECILE"].notna()
    geo_complete = df["LATITUDE"].notna() & df["LONGITUDE"].notna()

    latest_imd_complete = latest_df["IMD_SCORE"].notna() & latest_df["IMD_DECILE"].notna()
    latest_geo_complete = latest_df["LATITUDE"].notna() & latest_df["LONGITUDE"].notna()

    overall_imd = _pct(imd_complete)
    overall_geo = _pct(geo_complete)
    latest_imd = _pct(latest_imd_complete)
    latest_geo = _pct(latest_geo_complete)

    print("Enrichment Coverage Summary")
    print(f"- Mapping rows: {len(df):,}")
    print(f"- Snapshot range: {df['SNAPSHOT_DATE'].min().date()} -> {latest_snapshot.date()}")
    print(f"- Overall IMD coverage: {_render_pct(overall_imd)}")
    print(f"- Overall Geo coverage: {_render_pct(overall_geo)}")
    print(f"- Latest snapshot IMD coverage ({latest_snapshot.date()}): {_render_pct(latest_imd)}")
    print(f"- Latest snapshot Geo coverage ({latest_snapshot.date()}): {_render_pct(latest_geo)}")

    # Per snapshot summary
    by_snapshot = (
        df.groupby("SNAPSHOT_DATE", dropna=False)
        .apply(
            lambda g: pd.Series(
                {
                    "ROWS": len(g),
                    "IMD_COVERAGE": _pct(g["IMD_SCORE"].notna() & g["IMD_DECILE"].notna()),
                    "GEO_COVERAGE": _pct(g["LATITUDE"].notna() & g["LONGITUDE"].notna()),
                }
            )
        )
        .reset_index()
        .sort_values("SNAPSHOT_DATE")
    )

    print("\nPer-snapshot coverage (last 12)")
    tail = by_snapshot.tail(12)
    for _, row in tail.iterrows():
        snapshot = row["SNAPSHOT_DATE"].date()
        print(
            f"- {snapshot}: rows={int(row['ROWS']):,}, "
            f"imd={_render_pct(float(row['IMD_COVERAGE']))}, "
            f"geo={_render_pct(float(row['GEO_COVERAGE']))}"
        )

    # Regional summary for latest snapshot if region exists
    if "COMM_REGION_NAME" in latest_df.columns:
        latest_df["COMM_REGION_NAME"] = latest_df["COMM_REGION_NAME"].fillna("Unknown")
        by_region = (
            latest_df.groupby("COMM_REGION_NAME", dropna=False)
            .apply(
                lambda g: pd.Series(
                    {
                        "ROWS": len(g),
                        "IMD_COVERAGE": _pct(g["IMD_SCORE"].notna() & g["IMD_DECILE"].notna()),
                        "GEO_COVERAGE": _pct(g["LATITUDE"].notna() & g["LONGITUDE"].notna()),
                    }
                )
            )
            .reset_index()
            .sort_values(["ROWS", "COMM_REGION_NAME"], ascending=[False, True])
            .head(max(args.top_n_regions, 1))
        )

        print(f"\nLatest snapshot regional coverage (top {max(args.top_n_regions, 1)} by row count)")
        for _, row in by_region.iterrows():
            print(
                f"- {row['COMM_REGION_NAME']}: rows={int(row['ROWS']):,}, "
                f"imd={_render_pct(float(row['IMD_COVERAGE']))}, "
                f"geo={_render_pct(float(row['GEO_COVERAGE']))}"
            )

    failures: list[str] = []
    if args.min_imd_coverage is not None and latest_imd < args.min_imd_coverage:
        failures.append(
            f"Latest IMD coverage {_render_pct(latest_imd)} is below threshold {_render_pct(args.min_imd_coverage)}"
        )
    if args.min_geo_coverage is not None and latest_geo < args.min_geo_coverage:
        failures.append(
            f"Latest Geo coverage {_render_pct(latest_geo)} is below threshold {_render_pct(args.min_geo_coverage)}"
        )

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1

    print("\nPASS: Enrichment coverage validation completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
