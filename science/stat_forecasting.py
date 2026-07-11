"""Classical statistical forecasters for the NHS GP Analytics project (DEC-010).

Implements the candidate families from ``docs/FORECAST_VALIDATION.md`` §2 —
Holt-Winters, ARIMA, SARIMA (statsmodels) and AutoETS (statsforecast) — behind the
same ``Forecaster`` contract as the Prophet model and the harness baselines: take a
frame with ds/y (or SNAPSHOT_DATE/NUMBER_OF_PATIENTS), return ds/yhat with a native
80% interval.

Each model degrades the same way ``forecast_list_size`` does: the linear fallback
when its library is missing, the history is shorter than two full seasons, or the
fit fails to converge. The registries (``default_forecasters`` in backtesting,
``FORECAST_MODELS`` in the dashboard) only expose a model when its library is
importable, so a lean environment never scores the fallback under the model's name.
"""

from __future__ import annotations

import warnings
from typing import Callable

import numpy as np
import pandas as pd

from science.forecasting import _linear_forecast, _prepare_series

try:  # pragma: no cover - exercised only when statsmodels is installed.
    from statsmodels.tsa.exponential_smoothing.ets import ETSModel
    from statsmodels.tsa.statespace.sarimax import SARIMAX
except Exception:  # pragma: no cover - keep the module importable in lean environments.
    ETSModel = None
    SARIMAX = None

try:  # pragma: no cover - exercised only when statsforecast is installed.
    from statsforecast.models import AutoETS
except Exception:  # pragma: no cover - keep the module importable in lean environments.
    AutoETS = None

SEASON_LENGTH = 12
# Match forecast_list_size's Prophet gate: below two full seasons, seasonal models
# cannot estimate their seasonal component and the linear fallback is more honest.
MIN_SEASONAL_HISTORY = 24
INTERVAL_LEVEL = 0.8


def _empty_forecast() -> pd.DataFrame:
    return pd.DataFrame(columns=["ds", "yhat", "yhat_lower", "yhat_upper"])


def _assemble(series: pd.DataFrame, periods: int, mean, lower, upper) -> pd.DataFrame:
    """Standardise raw model output into the ds/yhat/yhat_lower/yhat_upper contract."""

    last_date = series.iloc[-1]["ds"]
    future = [
        (last_date + pd.offsets.MonthBegin(step)).to_period("M").to_timestamp(how="start")
        for step in range(1, periods + 1)
    ]
    frame = pd.DataFrame(
        {
            "ds": future,
            "yhat": np.asarray(mean, dtype=float),
            "yhat_lower": np.asarray(lower, dtype=float),
            "yhat_upper": np.asarray(upper, dtype=float),
        }
    )
    for column in ("yhat", "yhat_lower", "yhat_upper"):
        frame[column] = frame[column].clip(lower=0.0)
    return frame


def holt_winters_forecast(df: pd.DataFrame, periods: int) -> pd.DataFrame:
    """Classic additive Holt-Winters (level + trend + 12-month seasonality).

    Uses statsmodels' state-space ``ETSModel`` rather than the legacy
    ``ExponentialSmoothing`` because only the former produces prediction intervals.
    """

    series = _prepare_series(df)
    if series.empty or periods <= 0:
        return _empty_forecast()
    if ETSModel is None or len(series) < MIN_SEASONAL_HISTORY:
        return _linear_forecast(series, periods)

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            # get_prediction needs a pandas endog (it reads the index for row labels).
            model = ETSModel(
                series["y"].astype(float).reset_index(drop=True),
                error="add",
                trend="add",
                seasonal="add",
                seasonal_periods=SEASON_LENGTH,
            )
            fitted = model.fit(disp=False)
            prediction = fitted.get_prediction(start=len(series), end=len(series) + periods - 1)
            summary = prediction.summary_frame(alpha=1 - INTERVAL_LEVEL)
    except Exception:
        return _linear_forecast(series, periods)
    return _assemble(series, periods, summary["mean"], summary["pi_lower"], summary["pi_upper"])


def _sarimax_forecast(
    series: pd.DataFrame,
    periods: int,
    order: tuple[int, int, int],
    seasonal_order: tuple[int, int, int, int],
    trend: str | None,
) -> pd.DataFrame:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = SARIMAX(
                series["y"].to_numpy(dtype=float),
                order=order,
                seasonal_order=seasonal_order,
                trend=trend,
                enforce_stationarity=False,
                enforce_invertibility=False,
            )
            fitted = model.fit(disp=False)
            summary = fitted.get_forecast(steps=periods).summary_frame(alpha=1 - INTERVAL_LEVEL)
    except Exception:
        return _linear_forecast(series, periods)
    return _assemble(series, periods, summary["mean"], summary["mean_ci_lower"], summary["mean_ci_upper"])


def arima_forecast(df: pd.DataFrame, periods: int, order: tuple[int, int, int] = (1, 1, 1)) -> pd.DataFrame:
    """Classic non-seasonal ARIMA(1,1,1) with drift.

    The constant on the differenced series gives linear drift in levels, which the
    steadily growing list sizes need; seasonality is deliberately ignored so the
    model isolates what autocorrelation alone buys.
    """

    series = _prepare_series(df)
    if series.empty or periods <= 0:
        return _empty_forecast()
    if SARIMAX is None or len(series) < MIN_SEASONAL_HISTORY:
        return _linear_forecast(series, periods)
    return _sarimax_forecast(series, periods, order=order, seasonal_order=(0, 0, 0, 0), trend="c")


def sarima_forecast(
    df: pd.DataFrame,
    periods: int,
    order: tuple[int, int, int] = (0, 1, 1),
    seasonal_order: tuple[int, int, int, int] = (0, 1, 1, SEASON_LENGTH),
) -> pd.DataFrame:
    """The classic "airline" SARIMA (0,1,1)(0,1,1)12.

    Box & Jenkins' benchmark for trended, seasonal monthly data: regular plus
    seasonal differencing removes trend and seasonality, one MA term each mops up
    the remaining autocorrelation. No trend constant — the double differencing
    already absorbs it.
    """

    series = _prepare_series(df)
    if series.empty or periods <= 0:
        return _empty_forecast()
    if SARIMAX is None or len(series) < MIN_SEASONAL_HISTORY:
        return _linear_forecast(series, periods)
    return _sarimax_forecast(series, periods, order=order, seasonal_order=seasonal_order, trend=None)


def autoets_forecast(df: pd.DataFrame, periods: int) -> pd.DataFrame:
    """AutoETS: exponential smoothing with the ETS variant auto-selected by AICc.

    statsforecast searches error/trend/seasonality combinations (additive,
    multiplicative, damped, none) and keeps the best-scoring one — the strongest
    statistical competitor to Prophet in published monthly benchmarks.
    """

    series = _prepare_series(df)
    if series.empty or periods <= 0:
        return _empty_forecast()
    if AutoETS is None or len(series) < MIN_SEASONAL_HISTORY:
        return _linear_forecast(series, periods)

    level = int(round(INTERVAL_LEVEL * 100))
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = AutoETS(season_length=SEASON_LENGTH)
            result = model.forecast(y=series["y"].to_numpy(dtype=float), h=periods, level=[level])
    except Exception:
        return _linear_forecast(series, periods)
    return _assemble(series, periods, result["mean"], result[f"lo-{level}"], result[f"hi-{level}"])


def statistical_forecasters() -> dict[str, Callable[[pd.DataFrame, int], pd.DataFrame]]:
    """The classical models whose libraries are importable, keyed like default_forecasters."""

    forecasters: dict[str, Callable[[pd.DataFrame, int], pd.DataFrame]] = {}
    if ETSModel is not None:
        forecasters["holt_winters"] = holt_winters_forecast
    if SARIMAX is not None:
        forecasters["arima"] = arima_forecast
        forecasters["sarima"] = sarima_forecast
    if AutoETS is not None:
        forecasters["autoets"] = autoets_forecast
    return forecasters
