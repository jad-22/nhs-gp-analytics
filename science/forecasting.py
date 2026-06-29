"""Forecasting helpers for the NHS GP Analytics project scaffold."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from pipeline.config import PDS_START

try:  # pragma: no cover - Prophet is validated through notebook smoke tests.
    from prophet import Prophet
except Exception:  # pragma: no cover - keep the helper usable in lean environments.
    Prophet = None


def _month_start(value: object) -> pd.Timestamp:
    timestamp = pd.to_datetime(value, errors="coerce")
    if pd.isna(timestamp):
        raise ValueError("Unable to parse a monthly timestamp for forecasting.")
    return timestamp.to_period("M").to_timestamp(how="start")


def _prepare_series(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["ds", "y"])

    frame = df.copy()
    if {"ds", "y"}.issubset(frame.columns):
        series = frame[["ds", "y"]].copy()
    elif {"SNAPSHOT_DATE", "NUMBER_OF_PATIENTS"}.issubset(frame.columns):
        series = frame.rename(columns={"SNAPSHOT_DATE": "ds", "NUMBER_OF_PATIENTS": "y"})[["ds", "y"]].copy()
    else:
        raise ValueError("forecast_list_size expects ds/y or SNAPSHOT_DATE/NUMBER_OF_PATIENTS columns.")

    series["ds"] = pd.to_datetime(series["ds"], errors="coerce").dt.to_period("M").dt.to_timestamp(how="start")
    series["y"] = pd.to_numeric(series["y"], errors="coerce")
    series = series.dropna(subset=["ds", "y"])
    series = series.groupby("ds", as_index=False)["y"].mean().sort_values("ds").reset_index(drop=True)
    return series


def _default_changepoints(series: pd.DataFrame, changepoints: list[str] | None) -> list[pd.Timestamp]:
    if series.empty:
        return []

    start = series["ds"].min().to_period("M").to_timestamp(how="start")
    end = series["ds"].max().to_period("M").to_timestamp(how="start")
    points: list[pd.Timestamp] = []

    if changepoints:
        for value in changepoints:
            timestamp = _month_start(value)
            if start <= timestamp <= end:
                points.append(timestamp)

    pds_transition = pd.Timestamp(PDS_START).to_period("M").to_timestamp(how="start")
    if start <= pds_transition <= end:
        points.append(pds_transition)

    for year in range(start.year, end.year + 1):
        april = pd.Timestamp(date(year, 4, 1))
        if start <= april <= end:
            points.append(april)

    return sorted(dict.fromkeys(points))


def _linear_forecast(series: pd.DataFrame, periods: int) -> pd.DataFrame:
    history = series.copy()
    history["row_index"] = np.arange(len(history), dtype=float)

    if len(history) >= 2:
        slope, intercept = np.polyfit(history["row_index"], history["y"], 1)
        fitted = slope * history["row_index"] + intercept
        residual_std = float(np.std(history["y"] - fitted, ddof=1)) if len(history) > 2 else 0.0
    elif len(history) == 1:
        slope = 0.0
        intercept = float(history.iloc[0]["y"])
        residual_std = 0.0
    else:
        return pd.DataFrame(columns=["ds", "yhat", "yhat_lower", "yhat_upper"])

    future_rows = []
    last_date = history.iloc[-1]["ds"]
    for step in range(1, periods + 1):
        future_date = (last_date + pd.offsets.MonthBegin(step)).to_period("M").to_timestamp(how="start")
        row_index = len(history) + step - 1
        prediction = slope * row_index + intercept
        uncertainty = 1.96 * residual_std
        future_rows.append(
            {
                "ds": future_date,
                "yhat": max(0.0, float(prediction)),
                "yhat_lower": max(0.0, float(prediction - uncertainty)),
                "yhat_upper": max(0.0, float(prediction + uncertainty)),
            }
        )
    return pd.DataFrame(future_rows)


def forecast_list_size(
    df: pd.DataFrame,
    periods: int = 12,
    changepoints: list[str] | None = None,
) -> pd.DataFrame:
    """Forecast monthly list size with Prophet when available, otherwise a linear fallback."""

    series = _prepare_series(df)
    if series.empty or periods <= 0:
        return pd.DataFrame(columns=["ds", "yhat", "yhat_lower", "yhat_upper"])

    if Prophet is None or len(series) < 24:
        return _linear_forecast(series, periods)

    model = Prophet(
        changepoints=[point.to_pydatetime() for point in _default_changepoints(series, changepoints)],
        yearly_seasonality=True,
        weekly_seasonality=False,
        daily_seasonality=False,
    )
    model.fit(series)

    future = model.make_future_dataframe(periods=periods, freq="MS", include_history=False)
    forecast = model.predict(future)
    output = forecast[["ds", "yhat", "yhat_lower", "yhat_upper"]].copy()
    output["ds"] = pd.to_datetime(output["ds"]).dt.to_period("M").dt.to_timestamp(how="start")
    return output.reset_index(drop=True)