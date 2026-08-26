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
    statistical_labels = {"AutoETS (recommended)", "Holt-Winters", "SARIMA", "ARIMA"}
    if HAS_STATSMODELS:
        assert {"Holt-Winters", "SARIMA", "ARIMA"}.issubset(options)
    if HAS_STATSFORECAST:
        assert "AutoETS (recommended)" in options
    if not HAS_STATSMODELS and not HAS_STATSFORECAST:
        assert not statistical_labels & set(options)


def test_autoets_is_the_practice_drilldown_default() -> None:
    """DEC-011: AutoETS wins the practice-level backtest, so it is the drill-down default."""

    from dashboard.data import (
        DEFAULT_FORECAST_MODEL,
        FORECAST_MODELS,
        default_forecast_model,
        forecast_model_options,
    )
    from science.stat_forecasting import autoets_forecast

    assert DEFAULT_FORECAST_MODEL == "AutoETS (recommended)"
    assert FORECAST_MODELS[DEFAULT_FORECAST_MODEL] is autoets_forecast
    # The selector indexes off default_forecast_model(), but AutoETS also leads the
    # dict so the recommendation reads first in the dropdown.
    assert forecast_model_options()[0] == DEFAULT_FORECAST_MODEL if HAS_STATSFORECAST else True

    if HAS_STATSFORECAST:
        assert default_forecast_model() == DEFAULT_FORECAST_MODEL


def test_holt_winters_is_the_aggregate_default() -> None:
    """DEC-011: the ranking reverses with aggregation level, so aggregates get Holt-Winters."""

    from dashboard.data import (
        AGGREGATE_FORECAST_MODEL,
        DEFAULT_FORECAST_MODEL,
        FORECAST_MODELS,
        default_aggregate_forecast_model,
    )
    from science.stat_forecasting import holt_winters_forecast

    assert AGGREGATE_FORECAST_MODEL == "Holt-Winters"
    assert FORECAST_MODELS[AGGREGATE_FORECAST_MODEL] is holt_winters_forecast
    # The whole point of the split: the two levels must not resolve to one model.
    assert AGGREGATE_FORECAST_MODEL != DEFAULT_FORECAST_MODEL

    if HAS_STATSMODELS:
        assert default_aggregate_forecast_model() == AGGREGATE_FORECAST_MODEL


def test_dashboard_aggregate_default_matches_the_cache_builder() -> None:
    """The dashboard and the precomputed API must not serve different models per level."""

    from dashboard.data import AGGREGATE_FORECAST_MODEL, DEFAULT_FORECAST_MODEL, FORECAST_MODELS
    from scripts.build_forecast_cache import (
        DEFAULT_AGGREGATE_MODEL,
        DEFAULT_PRACTICE_MODEL,
        MODELS,
    )

    assert FORECAST_MODELS[AGGREGATE_FORECAST_MODEL] is MODELS[DEFAULT_AGGREGATE_MODEL]
    assert FORECAST_MODELS[DEFAULT_FORECAST_MODEL] is MODELS[DEFAULT_PRACTICE_MODEL]


def test_default_aggregate_forecast_model_falls_back_when_library_missing(monkeypatch) -> None:
    """Same DEC-009 guard as the practice default: never name a model that cannot run."""

    import dashboard.data as data

    monkeypatch.setitem(data._MODEL_REQUIREMENTS, data.AGGREGATE_FORECAST_MODEL, None)
    resolved = data.default_aggregate_forecast_model()

    assert resolved != data.AGGREGATE_FORECAST_MODEL
    assert resolved in data.forecast_model_options()


def test_default_forecast_model_falls_back_when_library_missing(monkeypatch) -> None:
    """Never default to a model whose library is absent — that serves a silent linear fallback."""

    import dashboard.data as data

    monkeypatch.setitem(data._MODEL_REQUIREMENTS, data.DEFAULT_FORECAST_MODEL, None)
    resolved = data.default_forecast_model()

    assert resolved != data.DEFAULT_FORECAST_MODEL
    assert resolved in data.forecast_model_options()


def _monthly_aggregate(months: int = 60) -> pd.DataFrame:
    """A summed monthly total in aggregate_list_size's output shape."""

    dates = pd.date_range("2019-01-01", periods=months, freq="MS")
    values = np.linspace(1_000_000, 1_060_000, months) + np.tile([0, 900, -700, 400, -200, 100], months // 6)[:months]
    return pd.DataFrame(
        {"SNAPSHOT_DATE": dates, "PATIENT_COUNT": values, "PRACTICE_COUNT": 120}
    )


@pytest.mark.skipif(not HAS_STATSMODELS, reason="statsmodels not installed")
def test_aggregate_history_with_forecast_projects_the_summed_total() -> None:
    """The aggregate forecast runs on the summed series and stays on its scale."""

    from dashboard.data import aggregate_history_with_forecast

    monthly = _monthly_aggregate()
    history, forecast, calibrated = aggregate_history_with_forecast(monthly, periods=12)

    assert len(history) == len(monthly)
    assert history["NUMBER_OF_PATIENTS"].tolist() == monthly["PATIENT_COUNT"].tolist()
    assert len(forecast) == 12
    assert {"ds", "yhat", "yhat_lower", "yhat_upper"}.issubset(forecast.columns)
    assert calibrated is True
    # Forecasting the sum, not a per-practice mean: an averaged series would land
    # near 8,000 rather than the million-scale total.
    assert forecast["yhat"].min() > monthly["PATIENT_COUNT"].min() * 0.5
    assert (forecast["yhat_lower"] <= forecast["yhat"]).all()
    assert (forecast["yhat"] <= forecast["yhat_upper"]).all()


def test_aggregate_history_with_forecast_rejects_an_unaggregated_frame() -> None:
    """DEC-012 guard 2: duplicate months would be averaged, not summed, and look plausible."""

    from dashboard.data import aggregate_history_with_forecast

    monthly = _monthly_aggregate(48)
    per_practice = pd.concat([monthly, monthly], ignore_index=True)

    with pytest.raises(ValueError, match="one summed row per month"):
        aggregate_history_with_forecast(per_practice, periods=12)


def test_aggregate_history_with_forecast_handles_an_empty_selection() -> None:
    """Filters can exclude everything; that is an empty chart, not a crash."""

    from dashboard.data import aggregate_history_with_forecast

    history, forecast, calibrated = aggregate_history_with_forecast(pd.DataFrame(), periods=12)

    assert history.empty
    assert forecast.empty
    assert calibrated is False
