import numpy as np
import pandas as pd
import pytest

from science import stat_forecasting
from science.backtesting import (
    default_forecasters,
    linear_forecast,
    rolling_origin_backtest,
    score_backtest,
)
from science.stat_forecasting import (
    arima_forecast,
    autoets_forecast,
    holt_winters_forecast,
    sarima_forecast,
    statistical_forecasters,
)

HAS_STATSMODELS = stat_forecasting.SARIMAX is not None
HAS_STATSFORECAST = stat_forecasting.AutoETS is not None

ALL_MODELS = [
    pytest.param(holt_winters_forecast, id="holt_winters", marks=pytest.mark.skipif(not HAS_STATSMODELS, reason="statsmodels not installed")),
    pytest.param(arima_forecast, id="arima", marks=pytest.mark.skipif(not HAS_STATSMODELS, reason="statsmodels not installed")),
    pytest.param(sarima_forecast, id="sarima", marks=pytest.mark.skipif(not HAS_STATSMODELS, reason="statsmodels not installed")),
    pytest.param(autoets_forecast, id="autoets", marks=pytest.mark.skipif(not HAS_STATSFORECAST, reason="statsforecast not installed")),
]


def _monthly_frame(values: list[float], start: str = "2020-01-01") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "SNAPSHOT_DATE": pd.date_range(start, periods=len(values), freq="MS"),
            "NUMBER_OF_PATIENTS": values,
        }
    )


def _trend_with_seasonality(months: int) -> pd.DataFrame:
    index = np.arange(months, dtype=float)
    values = 10_000 + 25 * index + 200 * np.sin(2 * np.pi * index / 12)
    return _monthly_frame(list(values))


@pytest.mark.parametrize("forecaster", ALL_MODELS)
def test_contract_columns_dates_and_band(forecaster) -> None:
    frame = _trend_with_seasonality(48)

    forecast = forecaster(frame, 12)

    assert list(forecast.columns) == ["ds", "yhat", "yhat_lower", "yhat_upper"]
    assert len(forecast) == 12
    assert forecast.iloc[0]["ds"] == pd.Timestamp("2024-01-01")
    assert forecast["ds"].is_monotonic_increasing
    assert (forecast["yhat_lower"] <= forecast["yhat"]).all()
    assert (forecast["yhat_upper"] >= forecast["yhat"]).all()
    assert (forecast["yhat_lower"] >= 0).all()


@pytest.mark.parametrize("forecaster", ALL_MODELS)
def test_empty_input_and_zero_periods(forecaster) -> None:
    assert forecaster(pd.DataFrame(), 12).empty
    assert forecaster(_trend_with_seasonality(48), 0).empty


@pytest.mark.parametrize("forecaster", ALL_MODELS)
def test_short_history_falls_back_to_linear(forecaster) -> None:
    frame = _monthly_frame([1000.0 + 10 * i for i in range(18)])  # < MIN_SEASONAL_HISTORY

    forecast = forecaster(frame, 6)
    fallback = linear_forecast(frame, 6)

    assert np.allclose(forecast["yhat"], fallback["yhat"])


SEASONAL_MODELS = [param for param in ALL_MODELS if param.id != "arima"]


@pytest.mark.parametrize("forecaster", SEASONAL_MODELS)
def test_seasonal_models_do_not_silently_fall_back(forecaster) -> None:
    # Guards against a fit path that raises and quietly serves the linear fallback:
    # on a strongly seasonal series a real seasonal model cannot produce the
    # straight line the fallback does.
    frame = _trend_with_seasonality(48)

    forecast = forecaster(frame, 12)
    fallback = linear_forecast(frame, 12)

    assert not np.allclose(forecast["yhat"], fallback["yhat"])


@pytest.mark.parametrize("forecaster", SEASONAL_MODELS)
def test_beats_seasonal_naive_on_clean_seasonal_trend(forecaster) -> None:
    # A clean trend + seasonality series is exactly what these models exist for:
    # each must backtest well below MASE 1 (the seasonal-naive yardstick). ARIMA is
    # excluded — it deliberately ignores seasonality, so it cannot win here.
    frame = _trend_with_seasonality(72)

    results = rolling_origin_backtest(frame, forecaster, horizon=12, initial=36, step=6)
    scores = score_backtest(results)

    assert scores["n_forecasts"] > 0
    assert scores["mase"] < 1.0


@pytest.mark.skipif(not HAS_STATSMODELS, reason="statsmodels not installed")
def test_arima_tracks_noisy_trend() -> None:
    rng = np.random.default_rng(11)
    values = 10_000 + 25 * np.arange(72, dtype=float) + rng.normal(0, 50, size=72)
    frame = _monthly_frame(list(values))

    results = rolling_origin_backtest(frame, arima_forecast, horizon=12, initial=36, step=6)
    scores = score_backtest(results)

    assert scores["n_forecasts"] > 0
    # The drift term must keep pace with the trend: on a non-seasonal series the
    # MASE scale is the seasonal step (12 * 25 = 300/month), so well below 1.
    assert scores["mase"] < 0.5


def test_missing_library_falls_back_to_linear(monkeypatch) -> None:
    frame = _trend_with_seasonality(48)
    fallback = linear_forecast(frame, 6)

    monkeypatch.setattr(stat_forecasting, "ETSModel", None)
    monkeypatch.setattr(stat_forecasting, "SARIMAX", None)
    monkeypatch.setattr(stat_forecasting, "AutoETS", None)

    for forecaster in (holt_winters_forecast, arima_forecast, sarima_forecast, autoets_forecast):
        assert np.allclose(forecaster(frame, 6)["yhat"], fallback["yhat"])
    assert statistical_forecasters() == {}


def test_registries_only_expose_available_models() -> None:
    stats = statistical_forecasters()
    defaults = default_forecasters()

    if HAS_STATSMODELS:
        assert {"holt_winters", "arima", "sarima"}.issubset(stats)
    else:
        assert not {"holt_winters", "arima", "sarima"} & set(stats)
    if HAS_STATSFORECAST:
        assert "autoets" in stats
    else:
        assert "autoets" not in stats

    assert set(stats).issubset(defaults)
    assert {"naive", "seasonal_naive", "linear"}.issubset(defaults)


def test_dashboard_options_hide_missing_libraries() -> None:
    from dashboard.data import FORECAST_MODELS, forecast_model_options

    options = forecast_model_options()
    assert set(options).issubset(FORECAST_MODELS)
    statistical_labels = {"AutoETS", "Holt-Winters", "SARIMA", "ARIMA"}
    if HAS_STATSMODELS:
        assert {"Holt-Winters", "SARIMA", "ARIMA"}.issubset(options)
    if HAS_STATSFORECAST:
        assert "AutoETS" in options
    if not HAS_STATSMODELS and not HAS_STATSFORECAST:
        assert not statistical_labels & set(options)
