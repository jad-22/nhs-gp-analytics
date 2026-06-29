"""Deprivation analysis helpers for the NHS GP Analytics project scaffold."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import pearsonr


def _region_column(frame: pd.DataFrame) -> str | None:
    for column in ("COMM_REGION_NAME", "REGION_NAME", "ICB_NAME"):
        if column in frame.columns:
            return column
    return None


def _gini(values: pd.Series) -> float:
    cleaned = pd.to_numeric(values, errors="coerce").dropna()
    cleaned = cleaned[cleaned >= 0]
    if cleaned.empty:
        return float("nan")

    sorted_values = np.sort(cleaned.to_numpy())
    total = sorted_values.sum()
    if total == 0:
        return 0.0

    n = sorted_values.size
    index = np.arange(1, n + 1)
    return float((2 * np.sum(index * sorted_values) / (n * total)) - (n + 1) / n)


def _prepare_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()

    frame = df.copy()
    if "NUMBER_OF_PATIENTS" not in frame.columns:
        raise ValueError("Deprivation helpers expect NUMBER_OF_PATIENTS.")
    if "IMD_DECILE" not in frame.columns:
        raise ValueError("Deprivation helpers expect IMD_DECILE.")

    frame["NUMBER_OF_PATIENTS"] = pd.to_numeric(frame["NUMBER_OF_PATIENTS"], errors="coerce")
    frame["IMD_DECILE"] = pd.to_numeric(frame["IMD_DECILE"], errors="coerce")
    if "SNAPSHOT_DATE" in frame.columns:
        frame["SNAPSHOT_DATE"] = pd.to_datetime(frame["SNAPSHOT_DATE"], errors="coerce").dt.to_period("M").dt.to_timestamp(how="start")
    return frame


def flag_underserved(df: pd.DataFrame) -> pd.DataFrame:
    """Flag practices in deprived areas with below-median list sizes."""

    frame = _prepare_frame(df)
    if frame.empty:
        return frame.assign(UNDER_SERVED=pd.Series(dtype=bool))

    if "SNAPSHOT_DATE" in frame.columns:
        frame["NATIONAL_MEDIAN_PATIENTS"] = frame.groupby("SNAPSHOT_DATE")["NUMBER_OF_PATIENTS"].transform("median")
    else:
        frame["NATIONAL_MEDIAN_PATIENTS"] = float(frame["NUMBER_OF_PATIENTS"].median())

    frame["DEPRIVED_AREA"] = frame["IMD_DECILE"].le(3)
    frame["SMALL_PRACTICE"] = frame["NUMBER_OF_PATIENTS"] < frame["NATIONAL_MEDIAN_PATIENTS"]
    frame["UNDER_SERVED"] = frame["DEPRIVED_AREA"] & frame["SMALL_PRACTICE"]
    return frame


def regional_inequality(df: pd.DataFrame) -> pd.DataFrame:
    """Compute Gini coefficients for list sizes by IMD decile and region over time."""

    frame = _prepare_frame(df)
    if frame.empty:
        return pd.DataFrame(columns=["GINI_COEFFICIENT"])

    grouping_columns = [column for column in ("SNAPSHOT_DATE", _region_column(frame), "IMD_DECILE") if column is not None]
    summary = (
        frame.groupby(grouping_columns, dropna=False)
        .agg(
            GINI_COEFFICIENT=("NUMBER_OF_PATIENTS", _gini),
            PRACTICE_COUNT=("NUMBER_OF_PATIENTS", "size"),
            MEAN_PATIENTS=("NUMBER_OF_PATIENTS", "mean"),
            MEDIAN_PATIENTS=("NUMBER_OF_PATIENTS", "median"),
        )
        .reset_index()
    )
    return summary.sort_values(grouping_columns).reset_index(drop=True)


def size_imd_correlation(df: pd.DataFrame) -> pd.DataFrame:
    """Return Pearson correlations between list size and IMD decile by region."""

    frame = _prepare_frame(df)
    if frame.empty:
        return pd.DataFrame(columns=["PEARSON_R", "P_VALUE"])

    region_column = _region_column(frame)
    grouping_columns = [column for column in (region_column,) if column is not None]
    if not grouping_columns:
        grouping_columns = ["ALL"]
        frame = frame.assign(ALL="All regions")

    records = []
    for group_name, group in frame.groupby(grouping_columns, dropna=False):
        cleaned = group[["NUMBER_OF_PATIENTS", "IMD_DECILE"]].dropna()
        if len(cleaned) < 2 or cleaned["IMD_DECILE"].nunique() < 2:
            r_value = float("nan")
            p_value = float("nan")
        else:
            r_value, p_value = pearsonr(cleaned["NUMBER_OF_PATIENTS"], cleaned["IMD_DECILE"])

        if isinstance(group_name, tuple):
            group_name = group_name[0]
        records.append({
            grouping_columns[0]: group_name,
            "PEARSON_R": float(r_value),
            "P_VALUE": float(p_value),
            "N": int(len(cleaned)),
        })

    return pd.DataFrame(records).sort_values(grouping_columns).reset_index(drop=True)