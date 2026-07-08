"""Rolling-origin backtesting for the NHS GP Analytics forecasting models.

Methodology and model-selection protocol are documented in
``docs/FORECAST_VALIDATION.md`` (decision record DEC-004).
"""

from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

from science.forecasting import Prophet, _linear_forecast, _prepare_series, forecast_list_size

# A forecaster takes a training frame with ds/y columns and a number of future
# monthly periods, and returns a frame with ds/yhat (optionally yhat_lower/yhat_upper).
Forecaster = Callable[[pd.DataFrame, int], pd.DataFrame]

SEASON_LENGTH = 12
INTERVAL_Z = 1.96


def _future_months(last_date: pd.Timestamp, periods: int) -> list[pd.Timestamp]:
    return [
        (last_date + pd.offsets.MonthBegin(step)).to_period("M").to_timestamp(how="start")
        for step in range(1, periods + 1)
    ]


def naive_forecast(df: pd.DataFrame, periods: int) -> pd.DataFrame:
    """Repeat the last observed value, with Gaussian random-walk intervals."""

    series = _prepare_series(df)
    if series.empty or periods <= 0:
        return pd.DataFrame(columns=["ds", "yhat", "yhat_lower", "yhat_upper"])

    last_value = float(series.iloc[-1]["y"])
    diffs = series["y"].diff().dropna()
    sigma = float(diffs.std(ddof=1)) if len(diffs) > 1 else 0.0

    rows = []
    for step, future_date in enumerate(_future_months(series.iloc[-1]["ds"], periods), start=1):
        width = INTERVAL_Z * sigma * np.sqrt(step)
        rows.append(
            {
                "ds": future_date,
                "yhat": max(0.0, last_value),
                "yhat_lower": max(0.0, last_value - width),
                "yhat_upper": max(0.0, last_value + width),
            }
        )
    return pd.DataFrame(rows)


def seasonal_naive_forecast(df: pd.DataFrame, periods: int) -> pd.DataFrame:
    """Repeat the value from the same month one season earlier."""

    series = _prepare_series(df)
    if series.empty or periods <= 0:
        return pd.DataFrame(columns=["ds", "yhat", "yhat_lower", "yhat_upper"])
    if len(series) < SEASON_LENGTH:
        return naive_forecast(series, periods)

    last_season = series["y"].tail(SEASON_LENGTH).to_numpy(dtype=float)
    seasonal_diffs = series["y"].diff(SEASON_LENGTH).dropna()
    sigma = float(seasonal_diffs.std(ddof=1)) if len(seasonal_diffs) > 1 else 0.0

    rows = []
    for step, future_date in enumerate(_future_months(series.iloc[-1]["ds"], periods), start=1):
        prediction = float(last_season[(step - 1) % SEASON_LENGTH])
        seasons_ahead = (step - 1) // SEASON_LENGTH + 1
        width = INTERVAL_Z * sigma * np.sqrt(seasons_ahead)
        rows.append(
            {
                "ds": future_date,
                "yhat": max(0.0, prediction),
                "yhat_lower": max(0.0, prediction - width),
                "yhat_upper": max(0.0, prediction + width),
            }
        )
    return pd.DataFrame(rows)


def linear_forecast(df: pd.DataFrame, periods: int) -> pd.DataFrame:
    """Ordinary least-squares trend line — the Prophet fallback in forecasting.py."""

    series = _prepare_series(df)
    if series.empty or periods <= 0:
        return pd.DataFrame(columns=["ds", "yhat", "yhat_lower", "yhat_upper"])
    return _linear_forecast(series, periods)


def default_forecasters() -> dict[str, Forecaster]:
    """Candidate models for compare_models, keyed by display name.

    The production Prophet model is only included when Prophet is importable, so a
    lean environment never silently scores the linear fallback under Prophet's name.
    """

    forecasters: dict[str, Forecaster] = {
        "naive": naive_forecast,
        "seasonal_naive": seasonal_naive_forecast,
        "linear": linear_forecast,
    }
    if Prophet is not None:
        forecasters["prophet"] = forecast_list_size
    return forecasters


def generate_cutoffs(
    series: pd.DataFrame,
    horizon: int = 12,
    initial: int = 36,
    step: int = 6,
) -> list[pd.Timestamp]:
    """Training cutoff dates for rolling-origin evaluation.

    Cutoffs are spaced ``step`` months apart working backwards from the latest month
    that still leaves a full ``horizon`` of actuals, and each keeps at least
    ``initial`` months of training history. Returned in ascending order.
    """

    if horizon <= 0 or initial <= 0 or step <= 0:
        raise ValueError("generate_cutoffs expects positive horizon, initial, and step.")
    if series.empty:
        return []

    months = series["ds"].sort_values().reset_index(drop=True)
    latest_cutoff_position = len(months) - 1 - horizon
    earliest_cutoff_position = initial - 1
    positions = range(latest_cutoff_position, earliest_cutoff_position - 1, -step)
    return sorted(months.iloc[position] for position in positions)


def _mase_scale(train: pd.DataFrame) -> float:
    """In-sample naive error used as the MASE denominator (seasonal when possible)."""

    values = train["y"].to_numpy(dtype=float)
    if len(values) > SEASON_LENGTH:
        errors = np.abs(values[SEASON_LENGTH:] - values[:-SEASON_LENGTH])
    elif len(values) > 1:
        errors = np.abs(np.diff(values))
    else:
        return float("nan")
    scale = float(np.mean(errors))
    return scale if scale > 0 else float("nan")


def rolling_origin_backtest(
    df: pd.DataFrame,
    forecaster: Forecaster,
    horizon: int = 12,
    initial: int = 36,
    step: int = 6,
) -> pd.DataFrame:
    """Backtest one forecaster over rolling cutoffs; one row per forecast month.

    Output columns: cutoff, ds, y, yhat, yhat_lower, yhat_upper, months_ahead,
    mase_scale. Returns an empty frame when the series is too short for any cutoff.
    """

    series = _prepare_series(df)
    columns = ["cutoff", "ds", "y", "yhat", "yhat_lower", "yhat_upper", "months_ahead", "mase_scale"]
    results = []

    for cutoff in generate_cutoffs(series, horizon=horizon, initial=initial, step=step):
        train = series[series["ds"] <= cutoff]
        forecast = forecaster(train, horizon)
        if forecast.empty:
            continue

        forecast = forecast.copy()
        forecast["ds"] = pd.to_datetime(forecast["ds"]).dt.to_period("M").dt.to_timestamp(how="start")
        for column in ("yhat_lower", "yhat_upper"):
            if column not in forecast.columns:
                forecast[column] = np.nan

        merged = forecast.merge(series, on="ds", how="inner")
        merged["cutoff"] = cutoff
        merged["months_ahead"] = (
            (merged["ds"].dt.year - cutoff.year) * 12 + (merged["ds"].dt.month - cutoff.month)
        )
        merged["mase_scale"] = _mase_scale(train)
        results.append(merged[columns])

    if not results:
        return pd.DataFrame(columns=columns)
    return pd.concat(results, ignore_index=True)


def score_backtest(results: pd.DataFrame) -> pd.Series:
    """Summarise backtest rows into accuracy metrics.

    MASE is the primary metric: mean absolute error scaled by the training series'
    in-sample seasonal-naive error, so below 1.0 beats seasonal naive. Coverage is
    the fraction of actuals inside [yhat_lower, yhat_upper] — compare it against the
    interval's nominal level (Prophet defaults to 80%).
    """

    index = ["n_forecasts", "mae", "rmse", "mape", "mase", "coverage"]
    if results.empty:
        return pd.Series([0, *([float("nan")] * 5)], index=index)

    error = results["yhat"] - results["y"]
    absolute_error = error.abs()

    nonzero = results["y"] != 0
    mape = float((absolute_error[nonzero] / results["y"][nonzero].abs()).mean()) if nonzero.any() else float("nan")

    scaled = absolute_error / results["mase_scale"]
    scaled = scaled.replace([np.inf, -np.inf], np.nan).dropna()
    mase = float(scaled.mean()) if len(scaled) else float("nan")

    has_bounds = results["yhat_lower"].notna() & results["yhat_upper"].notna()
    if has_bounds.any():
        inside = results["y"].between(results["yhat_lower"], results["yhat_upper"]) & has_bounds
        coverage = float(inside.sum() / has_bounds.sum())
    else:
        coverage = float("nan")

    return pd.Series(
        [
            int(len(results)),
            float(absolute_error.mean()),
            float(np.sqrt((error**2).mean())),
            mape,
            mase,
            coverage,
        ],
        index=index,
    )


def score_by_horizon(results: pd.DataFrame) -> pd.DataFrame:
    """Accuracy metrics per months-ahead step, to see how error grows with horizon."""

    if results.empty:
        return pd.DataFrame()
    return results.groupby("months_ahead").apply(score_backtest)


def compare_models(
    df: pd.DataFrame,
    forecasters: dict[str, Forecaster] | None = None,
    horizon: int = 12,
    initial: int = 36,
    step: int = 6,
) -> pd.DataFrame:
    """Backtest several forecasters on identical cutoffs; one scored row per model.

    Sorted by MASE ascending, so the first row is the model to beat.
    """

    candidates = default_forecasters() if forecasters is None else forecasters
    rows = {
        name: score_backtest(
            rolling_origin_backtest(df, forecaster, horizon=horizon, initial=initial, step=step)
        )
        for name, forecaster in candidates.items()
    }
    summary = pd.DataFrame.from_dict(rows, orient="index")
    summary.index.name = "model"
    return summary.sort_values("mase", na_position="last")
