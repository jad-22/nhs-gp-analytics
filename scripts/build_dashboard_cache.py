"""Build dashboard-ready Parquet caches for Streamlit.

Run after the core processed Parquet files are updated:

    python scripts/build_dashboard_cache.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.config import DATA_PROCESSED_DIR, LIST_SIZE_PARQUET_PATH, MAPPING_PARQUET_PATH
from science.anomaly import flag_anomalies
from science.clustering import cluster_practices
from science.deprivation import flag_underserved, regional_inequality, size_imd_correlation

CACHE_DIR = DATA_PROCESSED_DIR / "dashboard"


def _clean_name(value: object) -> str | None:
    if pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    return " ".join(part.capitalize() if part.lower() not in {"and", "of", "the"} else part.lower() for part in text.split())


def _normalise_mapping(mapping: pd.DataFrame) -> pd.DataFrame:
    frame = mapping.copy()
    frame["SNAPSHOT_DATE"] = pd.to_datetime(frame["SNAPSHOT_DATE"], errors="coerce").dt.to_period("M").dt.to_timestamp()
    frame["REGION_NAME"] = frame.get("COMM_REGION_NAME", pd.Series(index=frame.index, dtype=object)).map(_clean_name)
    frame["ICB_NAME"] = frame.get("ICB_NAME", pd.Series(index=frame.index, dtype=object)).map(_clean_name)
    frame["PRACTICE_NAME"] = frame.get("PRACTICE_NAME", pd.Series(index=frame.index, dtype=object)).fillna("Unknown practice")
    frame["CLINICAL_SYSTEM"] = frame.get("CLINICAL_SYSTEM", pd.Series(index=frame.index, dtype=object)).fillna("Others")
    frame["SUPPLIER_NAME"] = frame.get("SUPPLIER_NAME", pd.Series(index=frame.index, dtype=object)).fillna("Unknown")
    return frame


def _read_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    if not LIST_SIZE_PARQUET_PATH.exists():
        raise FileNotFoundError(f"Missing {LIST_SIZE_PARQUET_PATH}")
    if not MAPPING_PARQUET_PATH.exists():
        raise FileNotFoundError(f"Missing {MAPPING_PARQUET_PATH}")

    list_size = pd.read_parquet(LIST_SIZE_PARQUET_PATH)
    mapping = pd.read_parquet(MAPPING_PARQUET_PATH)
    list_size["SNAPSHOT_DATE"] = pd.to_datetime(list_size["SNAPSHOT_DATE"], errors="coerce").dt.to_period("M").dt.to_timestamp()
    return list_size, _normalise_mapping(mapping)


def _joined_history(list_size: pd.DataFrame, mapping: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "SNAPSHOT_DATE",
        "PRACTICE_CODE",
        "PRACTICE_NAME",
        "REGION_NAME",
        "ICB_NAME",
        "SUPPLIER_NAME",
        "CLINICAL_SYSTEM",
        "IMD_SCORE",
        "IMD_DECILE",
        "LATITUDE",
        "LONGITUDE",
    ]
    available = [column for column in columns if column in mapping.columns]
    joined = list_size.merge(
        mapping[available],
        left_on=["SNAPSHOT_DATE", "CODE"],
        right_on=["SNAPSHOT_DATE", "PRACTICE_CODE"],
        how="left",
    )
    joined["REGION_NAME"] = joined["REGION_NAME"].fillna("Unknown region")
    joined["ICB_NAME"] = joined["ICB_NAME"].fillna("Unknown ICB")
    joined["CLINICAL_SYSTEM"] = joined["CLINICAL_SYSTEM"].fillna("Others")
    joined["PRACTICE_NAME"] = joined["PRACTICE_NAME"].fillna("Unknown practice")
    return joined


def build_latest_snapshot(joined: pd.DataFrame) -> pd.DataFrame:
    latest_date = joined["SNAPSHOT_DATE"].max()
    return joined.loc[joined["SNAPSHOT_DATE"] == latest_date].sort_values("CODE").reset_index(drop=True)


def build_list_size_geo(joined: pd.DataFrame) -> pd.DataFrame:
    return (
        joined.groupby(["SNAPSHOT_DATE", "REGION_NAME", "ICB_NAME"], dropna=False, as_index=False)
        .agg(PATIENT_COUNT=("NUMBER_OF_PATIENTS", "sum"), PRACTICE_COUNT=("CODE", "nunique"))
        .sort_values(["SNAPSHOT_DATE", "REGION_NAME", "ICB_NAME"])
        .reset_index(drop=True)
    )


def build_market_share(joined: pd.DataFrame) -> pd.DataFrame:
    return (
        joined.groupby(["SNAPSHOT_DATE", "REGION_NAME", "ICB_NAME", "CLINICAL_SYSTEM"], dropna=False, as_index=False)
        .agg(PRACTICE_COUNT=("CODE", "nunique"), PATIENT_COUNT=("NUMBER_OF_PATIENTS", "sum"))
        .sort_values(["SNAPSHOT_DATE", "REGION_NAME", "ICB_NAME", "CLINICAL_SYSTEM"])
        .reset_index(drop=True)
    )


def build_migrations(joined: pd.DataFrame) -> pd.DataFrame:
    base = (
        joined[
            [
                "SNAPSHOT_DATE",
                "CODE",
                "PRACTICE_NAME",
                "REGION_NAME",
                "ICB_NAME",
                "SUPPLIER_NAME",
                "CLINICAL_SYSTEM",
            ]
        ]
        .drop_duplicates(["SNAPSHOT_DATE", "CODE"])
        .sort_values(["CODE", "SNAPSHOT_DATE"])
        .reset_index(drop=True)
    )
    base["PREVIOUS_SUPPLIER_NAME"] = base.groupby("CODE")["SUPPLIER_NAME"].shift(1)
    base["PREVIOUS_CLINICAL_SYSTEM"] = base.groupby("CODE")["CLINICAL_SYSTEM"].shift(1)
    changed = base.loc[
        base["PREVIOUS_SUPPLIER_NAME"].notna()
        & (base["SUPPLIER_NAME"] != base["PREVIOUS_SUPPLIER_NAME"])
        & (base["SUPPLIER_NAME"] != "Unknown")
    ].copy()
    return changed.rename(
        columns={
            "SNAPSHOT_DATE": "CHANGE_DATE",
            "SUPPLIER_NAME": "NEW_SUPPLIER_NAME",
            "CLINICAL_SYSTEM": "NEW_CLINICAL_SYSTEM",
        }
    ).reset_index(drop=True)


def build_anomalies(joined: pd.DataFrame) -> pd.DataFrame:
    flagged = flag_anomalies(joined)
    anomalies = flagged.loc[flagged["ANOMALY_FLAG"]].copy()
    keep = [
        "SNAPSHOT_DATE",
        "CODE",
        "PRACTICE_NAME",
        "REGION_NAME",
        "ICB_NAME",
        "NUMBER_OF_PATIENTS",
        "MOM_CHANGE_ABS",
        "MOM_CHANGE_PCT",
        "ANOMALY_TYPE",
        "ANOMALY_SCORE",
        "ISOLATION_FLAG",
    ]
    available = [column for column in keep if column in anomalies.columns]
    return anomalies[available].sort_values(["SNAPSHOT_DATE", "ANOMALY_SCORE"], ascending=[False, False]).reset_index(drop=True)


def build_deprivation_latest(latest: pd.DataFrame) -> pd.DataFrame:
    flagged = flag_underserved(latest)
    clustered = cluster_practices(flagged, n_clusters=6)
    return clustered.reset_index(drop=True)


def build_inequality(joined: pd.DataFrame) -> pd.DataFrame:
    required = joined.dropna(subset=["IMD_DECILE"]).copy()
    if required.empty:
        return pd.DataFrame()
    return regional_inequality(required)


def build_correlations(latest: pd.DataFrame) -> pd.DataFrame:
    required = latest.dropna(subset=["IMD_DECILE"]).copy()
    if required.empty:
        return pd.DataFrame()
    return size_imd_correlation(required)


def write_cache(output_dir: Path = CACHE_DIR, *, skip_anomalies: bool = False) -> dict[str, tuple[int, int]]:
    """Build all dashboard cache files and return their shapes."""

    output_dir.mkdir(parents=True, exist_ok=True)
    list_size, mapping = _read_inputs()
    joined = _joined_history(list_size, mapping)
    latest = build_latest_snapshot(joined)

    outputs: dict[str, pd.DataFrame] = {
        "latest_snapshot.parquet": latest,
        "list_size_geo.parquet": build_list_size_geo(joined),
        "market_share.parquet": build_market_share(joined),
        "migrations.parquet": build_migrations(joined),
        "deprivation_latest.parquet": build_deprivation_latest(latest),
        "inequality.parquet": build_inequality(joined),
        "correlations.parquet": build_correlations(latest),
    }
    if not skip_anomalies:
        outputs["anomalies.parquet"] = build_anomalies(joined)

    shapes: dict[str, tuple[int, int]] = {}
    for filename, frame in outputs.items():
        frame.to_parquet(output_dir / filename, index=False)
        shapes[filename] = frame.shape
    return shapes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-anomalies", action="store_true", help="Skip the slow anomaly cache rebuild.")
    args = parser.parse_args()

    shapes = write_cache(skip_anomalies=args.skip_anomalies)
    for filename, shape in shapes.items():
        print(f"{filename}: {shape[0]:,} rows x {shape[1]} columns")


if __name__ == "__main__":
    main()
