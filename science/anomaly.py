"""Anomaly detection helpers for the NHS GP Analytics project scaffold."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest


def _practice_column(frame: pd.DataFrame) -> str:
    if "CODE" in frame.columns:
        return "CODE"
    if "PRACTICE_CODE" in frame.columns:
        return "PRACTICE_CODE"
    raise ValueError("flag_anomalies expects a practice code column named CODE or PRACTICE_CODE.")


def _region_column(frame: pd.DataFrame) -> str | None:
    for column in ("COMM_REGION_NAME", "REGION_NAME", "ICB_NAME"):
        if column in frame.columns:
            return column
    return None


def _prepare_frame(df: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    if df.empty:
        return pd.DataFrame(), "CODE"

    frame = df.copy()
    code_column = _practice_column(frame)

    if "SNAPSHOT_DATE" not in frame.columns:
        raise ValueError("flag_anomalies expects a SNAPSHOT_DATE column.")
    if "NUMBER_OF_PATIENTS" not in frame.columns:
        raise ValueError("flag_anomalies expects a NUMBER_OF_PATIENTS column.")

    frame["SNAPSHOT_DATE"] = pd.to_datetime(frame["SNAPSHOT_DATE"], errors="coerce").dt.to_period("M").dt.to_timestamp(how="start")
    frame["NUMBER_OF_PATIENTS"] = pd.to_numeric(frame["NUMBER_OF_PATIENTS"], errors="coerce")
    frame = frame.dropna(subset=["SNAPSHOT_DATE", code_column, "NUMBER_OF_PATIENTS"])
    frame = frame.sort_values([code_column, "SNAPSHOT_DATE"]).reset_index(drop=True)

    previous = frame.groupby(code_column)["NUMBER_OF_PATIENTS"].shift(1)
    has_previous = previous.notna()
    frame["MOM_CHANGE_ABS"] = frame["NUMBER_OF_PATIENTS"] - previous
    frame["MOM_CHANGE_PCT"] = np.where(
        has_previous & (previous > 0),
        frame["MOM_CHANGE_ABS"] / previous,
        np.where(has_previous & (frame["NUMBER_OF_PATIENTS"] > 0), 1.0, 0.0),
    )
    frame["MOM_CHANGE_PCT"] = frame["MOM_CHANGE_PCT"].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    frame["MOM_CHANGE_ABS"] = frame["MOM_CHANGE_ABS"].fillna(0.0)
    return frame, code_column


def _rolling_decline(frame: pd.DataFrame, code_column: str) -> pd.Series:
    decline = pd.Series(False, index=frame.index)
    for _, practice_frame in frame.groupby(code_column, sort=False):
        decreasing = practice_frame["MOM_CHANGE_ABS"] < 0
        rolling_decline = decreasing.rolling(window=6, min_periods=6).sum() == 6
        decline.loc[practice_frame.index] = rolling_decline.fillna(False)
    return decline


def _merger_suspects(frame: pd.DataFrame, code_column: str) -> pd.Series:
    region_column = _region_column(frame)
    if region_column is None:
        grouping_columns = ["SNAPSHOT_DATE"]
    else:
        grouping_columns = ["SNAPSHOT_DATE", region_column]

    merger = pd.Series(False, index=frame.index)
    for _, month_frame in frame.groupby(grouping_columns, dropna=False, sort=False):
        positive_peak = month_frame["MOM_CHANGE_ABS"].clip(lower=0).max()
        if positive_peak <= 0:
            continue
        candidate_mask = month_frame["MOM_CHANGE_PCT"] <= -0.8
        if not candidate_mask.any():
            continue
        merger.loc[month_frame.index[candidate_mask & (month_frame["MOM_CHANGE_ABS"].abs() <= positive_peak * 2)]] = True
    return merger


def flag_anomalies(df: pd.DataFrame) -> pd.DataFrame:
    """Label practice-level anomalies using momentum, Z-scores, and Isolation Forest."""

    frame, code_column = _prepare_frame(df)
    if frame.empty:
        empty = frame.copy()
        empty["ANOMALY_TYPE"] = pd.Series(dtype="object")
        return empty

    z_source = frame["MOM_CHANGE_PCT"]
    std = float(z_source.std(ddof=0))
    mean = float(z_source.mean())
    frame["Z_SCORE"] = 0.0 if std == 0 else (z_source - mean) / std

    features = frame[["NUMBER_OF_PATIENTS", "MOM_CHANGE_PCT", "MOM_CHANGE_ABS"]].fillna(0.0)
    if len(frame) > 5 and features.nunique().sum() > 3:
        model = IsolationForest(n_estimators=200, contamination=0.05, random_state=42)
        model.fit(features)
        frame["ISOLATION_SCORE"] = -model.decision_function(features)
        frame["ISOLATION_FLAG"] = model.predict(features) == -1
    else:
        frame["ISOLATION_SCORE"] = 0.0
        frame["ISOLATION_FLAG"] = False

    closure = frame["MOM_CHANGE_PCT"] <= -0.8
    spike = (frame["MOM_CHANGE_PCT"] >= 0.4) | (frame["Z_SCORE"].abs() >= 3.0)
    gradual_decline = _rolling_decline(frame, code_column)
    merger = _merger_suspects(frame, code_column)

    anomaly_type = pd.Series("", index=frame.index, dtype="object")
    anomaly_type = anomaly_type.mask(gradual_decline, "GRADUAL_DECLINE")
    anomaly_type = anomaly_type.mask(spike, "SPIKE")
    anomaly_type = anomaly_type.mask(merger, "MERGER_SUSPECTED")
    anomaly_type = anomaly_type.mask(closure, "CLOSURE_SUSPECTED")

    anomaly_type = anomaly_type.where(anomaly_type != "", None)
    frame["ANOMALY_TYPE"] = anomaly_type
    frame["ANOMALY_FLAG"] = frame["ANOMALY_TYPE"].notna() | frame["ISOLATION_FLAG"]
    frame["ANOMALY_SCORE"] = frame["Z_SCORE"].abs().fillna(0.0) + frame["ISOLATION_SCORE"].fillna(0.0)
    return frame.reset_index(drop=True)