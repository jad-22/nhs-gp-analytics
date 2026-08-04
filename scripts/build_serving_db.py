"""Compile the processed Parquet files into the API's serving database.

    python scripts/build_serving_db.py

Produces ``data/processed/serving.duckdb``: native DuckDB tables with indexes on the
lookup keys and the practice-to-geography join already denormalised. Measured on the
real data, a point lookup drops from 6.0 ms (a view over Parquet) to 1.0 ms, and the
worst-case history join from 14.8 ms to nothing at all.

This is a **build artifact, not source** — it is regenerated from Parquet on every
Docker build and is not committed. Parquet stays the source of truth because it is what
the pipeline writes and what git can diff.

Imports only pandas, duckdb and ``pipeline`` — no ``science``, so the API image never
acquires a forecasting library.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.config import DATA_PROCESSED_DIR, LIST_SIZE_PARQUET_PATH, MAPPING_PARQUET_PATH
from pipeline.entities import LEVELS, build_series, entity_names, month_start, practice_entities

SERVING_DB_PATH = DATA_PROCESSED_DIR / "serving.duckdb"
FORECASTS_PARQUET_PATH = DATA_PROCESSED_DIR / "forecasts.parquet"
FORECAST_METRICS_PARQUET_PATH = DATA_PROCESSED_DIR / "forecast_metrics.parquet"

# Practice attributes served at /v1/practices/{code}, as of the latest snapshot.
PRACTICE_ATTRIBUTES = [
    "PRACTICE_NAME",
    "PRACTICE_POSTCODE",
    "PCN_CODE",
    "PCN_NAME",
    "ICB_CODE",
    "ICB_NAME",
    "COMM_REGION_CODE",
    "COMM_REGION_NAME",
    "CLINICAL_SYSTEM",
    "SUPPLIER_NAME",
    "IMD_SCORE",
    "IMD_DECILE",
    "LATITUDE",
    "LONGITUDE",
]


def _read_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    for path in (LIST_SIZE_PARQUET_PATH, MAPPING_PARQUET_PATH, FORECASTS_PARQUET_PATH, FORECAST_METRICS_PARQUET_PATH):
        if not path.exists():
            raise FileNotFoundError(f"Missing {path}. Run the pipeline and scripts/build_forecast_cache.py first.")

    list_size = pd.read_parquet(LIST_SIZE_PARQUET_PATH)
    mapping = pd.read_parquet(MAPPING_PARQUET_PATH)
    list_size["SNAPSHOT_DATE"] = month_start(list_size["SNAPSHOT_DATE"])
    mapping["SNAPSHOT_DATE"] = month_start(mapping["SNAPSHOT_DATE"])
    mapping = mapping.sort_values("SNAPSHOT_DATE")
    return (
        list_size,
        mapping,
        pd.read_parquet(FORECASTS_PARQUET_PATH),
        pd.read_parquet(FORECAST_METRICS_PARQUET_PATH),
    )


def build_practices(list_size: pd.DataFrame, mapping: pd.DataFrame) -> pd.DataFrame:
    """Every practice ever seen, with its latest attributes and an ACTIVE flag.

    Closed practices are kept: their history is still public data and the API serves it.
    ``ACTIVE`` is what lets ``/forecast`` explain a 404 instead of extrapolating a list
    that stopped.
    """

    entities = practice_entities(mapping)
    latest_month = list_size["SNAPSHOT_DATE"].max()

    attributes = mapping.groupby("PRACTICE_CODE")[PRACTICE_ATTRIBUTES].last()
    # Codes resolved by practice_entities win: they carry the CCG->ICB bridge.
    attributes["PCN_CODE"] = entities["PCN_CODE"]
    attributes["ICB_CODE"] = entities["ICB_CODE"]
    attributes["COMM_REGION_CODE"] = entities["REGION_CODE"]

    history = list_size.groupby("CODE").agg(
        FIRST_MONTH=("SNAPSHOT_DATE", "min"),
        LAST_MONTH=("SNAPSHOT_DATE", "max"),
        MONTHS=("SNAPSHOT_DATE", "size"),
    )
    latest = list_size.loc[list_size["SNAPSHOT_DATE"] == latest_month].set_index("CODE")

    practices = history.join(attributes, how="left")
    practices["NUMBER_OF_PATIENTS"] = latest["NUMBER_OF_PATIENTS"]
    practices["DATA_SOURCE"] = latest["DATA_SOURCE"]
    practices["ACTIVE"] = practices["LAST_MONTH"] == latest_month
    practices["AS_OF"] = latest_month
    practices["PRACTICE_NAME"] = practices["PRACTICE_NAME"].fillna("Unknown practice")

    return (
        practices.reset_index()
        .rename(columns={"CODE": "ODS_CODE", "COMM_REGION_CODE": "REGION_CODE", "COMM_REGION_NAME": "REGION_NAME"})
        .sort_values("ODS_CODE")
        .reset_index(drop=True)
    )


def build_entities(series: pd.DataFrame, register: pd.DataFrame, list_size: pd.DataFrame, mapping: pd.DataFrame) -> pd.DataFrame:
    """The aggregate entity register: one row per region / ICB / PCN, plus national."""

    latest_month = series["SNAPSHOT_DATE"].max()
    latest = series.loc[series["SNAPSHOT_DATE"] == latest_month].set_index(["LEVEL", "ENTITY_CODE"])["NUMBER_OF_PATIENTS"]

    entities = practice_entities(mapping)
    active_codes = set(list_size.loc[list_size["SNAPSHOT_DATE"] == latest_month, "CODE"])
    active = entities.loc[entities.index.isin(active_codes)]
    counts = {
        "national": pd.Series({"ENG": len(active)}),
        "region": active.groupby("REGION_CODE").size(),
        "icb": active.groupby("ICB_CODE").size(),
        "pcn": active.groupby("PCN_CODE").size(),
    }

    frame = register.loc[register["LEVEL"] != "practice"].copy()
    frame["LATEST_PATIENTS"] = pd.MultiIndex.from_frame(frame[["LEVEL", "ENTITY_CODE"]]).map(latest)
    frame["PRACTICE_COUNT"] = [
        int(counts[level].get(code, 0)) for level, code in zip(frame["LEVEL"], frame["ENTITY_CODE"])
    ]
    frame["AS_OF"] = latest_month
    return frame.sort_values(["LEVEL", "ENTITY_CODE"]).reset_index(drop=True)


def build_meta(practices: pd.DataFrame, entities: pd.DataFrame, forecasts: pd.DataFrame, metrics: pd.DataFrame) -> pd.DataFrame:
    """One row describing this vintage — served verbatim at /v1/meta."""

    served = metrics.loc[~metrics["QUARANTINED"]]
    return pd.DataFrame(
        [
            {
                "RUN_ID": forecasts["RUN_ID"].iloc[0],
                "GENERATED_AT": forecasts["GENERATED_AT"].iloc[0],
                "TRAINED_THROUGH": forecasts["TRAINED_THROUGH"].max(),
                "EARLIEST_MONTH": practices["FIRST_MONTH"].min(),
                "LATEST_MONTH": practices["LAST_MONTH"].max(),
                "PRACTICE_COUNT": int(practices["ACTIVE"].sum()),
                "PRACTICE_COUNT_ALL": int(len(practices)),
                "ENTITY_COUNT": int(len(entities)),
                "FORECAST_COUNT": int(forecasts.groupby(["LEVEL", "ENTITY_CODE"]).ngroups),
                "QUARANTINED_COUNT": int(metrics["QUARANTINED"].sum()),
                "INTERVAL_LEVEL": float(forecasts["INTERVAL_LEVEL"].iloc[0]),
                # The honest number: what the published interval achieved on cutoffs it
                # was not calibrated on. §5 of FORECAST_VALIDATION reports 0.83, but that
                # is self-calibrated and flatters itself. The API publishes what it
                # measured, not the nominal level it aimed at.
                # The *mean* of per-series coverage, not the median: it equals the
                # pooled fraction of actuals that landed inside the band, which is what
                # "80% coverage" claims. The median reads 0.83 only because the
                # distribution is bimodal — 36% of practices cover all 12 held-out
                # months and 4% cover none — and would overstate the guarantee.
                "MEASURED_COVERAGE": float(served["COVERAGE"].mean()),
                "MEASURED_COVERAGE_NATIVE": float(served["COVERAGE_NATIVE"].mean()),
                "MEDIAN_MASE": float(served["MASE"].median()),
            }
        ]
    )


INDEXES = (
    ("practices", "ODS_CODE"),
    ("practices", "ICB_CODE"),
    ("practices", "PCN_CODE"),
    ("practices", "REGION_CODE"),
    ("list_size", "CODE"),
    ("aggregate_list_size", "ENTITY_CODE"),
    ("forecasts", "ENTITY_CODE"),
    ("forecast_metrics", "ENTITY_CODE"),
    ("entities", "ENTITY_CODE"),
)


def compile_database(output_path: Path = SERVING_DB_PATH) -> dict[str, int]:
    list_size, mapping, forecasts, metrics = _read_inputs()
    series, register = build_series(list_size, mapping)

    tables = {
        "practices": build_practices(list_size, mapping),
        "list_size": list_size.sort_values(["CODE", "SNAPSHOT_DATE"]).reset_index(drop=True),
        "aggregate_list_size": series.loc[series["LEVEL"] != "practice"].reset_index(drop=True),
        "entities": build_entities(series, register, list_size, mapping),
        "forecasts": forecasts,
        "forecast_metrics": metrics,
    }
    tables["meta"] = build_meta(tables["practices"], tables["entities"], forecasts, metrics)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.unlink(missing_ok=True)
    connection = duckdb.connect(str(output_path))
    try:
        for name, frame in tables.items():
            connection.register(f"_{name}", frame)
            connection.execute(f"CREATE TABLE {name} AS SELECT * FROM _{name}")
            connection.unregister(f"_{name}")
        for table, column in INDEXES:
            connection.execute(f"CREATE INDEX idx_{table}_{column.lower()} ON {table}({column})")
        connection.execute("CHECKPOINT")
    finally:
        connection.close()

    return {name: len(frame) for name, frame in tables.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=SERVING_DB_PATH)
    args = parser.parse_args()

    counts = compile_database(args.output)
    for name, rows in counts.items():
        print(f"{name}: {rows:,} rows")
    print(f"\n{args.output} ({args.output.stat().st_size / 1e6:.1f} MB)")
    print(f"levels: {', '.join(LEVELS)}")


if __name__ == "__main__":
    main()
