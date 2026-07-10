import numpy as np
import pandas as pd
import pytest

from science.backtesting import (
    apply_interval_calibration,
    calibrate_intervals,
    calibrated_forecast,
    compare_models,
    generate_cutoffs,
    linear_forecast,
    naive_forecast,
    rolling_origin_backtest,
    score_backtest,
    score_by_horizon,
    seasonal_naive_forecast,
)


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


def test_naive_forecast_repeats_last_value() -> None:
    forecast = naive_forecast(_monthly_frame([100, 110, 120]), periods=3)

    assert list(forecast.columns) == ["ds", "yhat", "yhat_lower", "yhat_upper"]
    assert forecast["yhat"].eq(120).all()
    assert forecast.iloc[0]["ds"] == pd.Timestamp("2020-04-01")
    assert (forecast["yhat_upper"] - forecast["yhat_lower"]).is_monotonic_increasing


def test_seasonal_naive_repeats_last_season() -> None:
    values = list(range(100, 124))  # 24 months
    forecast = seasonal_naive_forecast(_monthly_frame(values), periods=13)

    # First forecast month (2022-01) should repeat 2021-01's value, and the
    # 13th month wraps around to repeat the first forecast value.
    assert forecast.iloc[0]["yhat"] == values[12]
    assert forecast.iloc[11]["yhat"] == values[23]
    assert forecast.iloc[12]["yhat"] == values[12]


def test_seasonal_naive_falls_back_with_short_history() -> None:
    forecast = seasonal_naive_forecast(_monthly_frame([100, 110, 120]), periods=2)

    assert forecast["yhat"].eq(120).all()


def test_generate_cutoffs_respects_initial_and_horizon() -> None:
    series = _trend_with_seasonality(60).rename(
        columns={"SNAPSHOT_DATE": "ds", "NUMBER_OF_PATIENTS": "y"}
    )

    cutoffs = generate_cutoffs(series, horizon=12, initial=36, step=6)

    # 60 months (2020-01..2024-12): latest cutoff leaves 12 actuals (2023-12),
    # stepping back 6 months until only 36 training months remain (2022-12).
    assert cutoffs == [pd.Timestamp("2022-12-01"), pd.Timestamp("2023-06-01"), pd.Timestamp("2023-12-01")]
    assert generate_cutoffs(series, horizon=48, initial=36, step=6) == []
    with pytest.raises(ValueError):
        generate_cutoffs(series, horizon=0)


def test_rolling_origin_backtest_scores_linear_series_well() -> None:
    frame = _monthly_frame([1000.0 + 10 * i for i in range(60)])

    results = rolling_origin_backtest(frame, naive_forecast, horizon=12, initial=36, step=6)

    assert set(results.columns) == {
        "cutoff",
        "ds",
        "y",
        "yhat",
        "yhat_lower",
        "yhat_upper",
        "months_ahead",
        "mase_scale",
    }
    assert results["cutoff"].nunique() == 3
    assert results["months_ahead"].between(1, 12).all()
    # Every forecast month must only use data from before it happened.
    assert (results["ds"] > results["cutoff"]).all()

    scores = score_backtest(results)
    # Naive forecast of a +10/month trend is wrong by 10 * months_ahead.
    assert scores["mae"] == pytest.approx(65.0)
    # Seasonal-naive in-sample error is 120/month, so MASE well below 1.
    assert scores["mase"] < 1.0


def test_score_backtest_empty_and_coverage() -> None:
    empty = score_backtest(pd.DataFrame(columns=["y", "yhat", "yhat_lower", "yhat_upper", "mase_scale"]))
    assert empty["n_forecasts"] == 0
    assert np.isnan(empty["mae"])

    results = pd.DataFrame(
        {
            "y": [100.0, 100.0],
            "yhat": [110.0, 90.0],
            "yhat_lower": [105.0, 80.0],
            "yhat_upper": [115.0, 100.0],
            "mase_scale": [10.0, 10.0],
            "months_ahead": [1, 2],
        }
    )
    scores = score_backtest(results)
    assert scores["coverage"] == pytest.approx(0.5)
    assert scores["mase"] == pytest.approx(1.0)
    assert scores["mape"] == pytest.approx(0.1)


def test_score_by_horizon_groups_by_months_ahead() -> None:
    frame = _monthly_frame([1000.0 + 10 * i for i in range(60)])
    results = rolling_origin_backtest(frame, naive_forecast, horizon=12, initial=36, step=6)

    by_horizon = score_by_horizon(results)

    assert list(by_horizon.index) == list(range(1, 13))
    # Naive error grows linearly with horizon on a trending series.
    assert by_horizon.loc[12, "mae"] > by_horizon.loc[1, "mae"]


def test_calibrate_intervals_takes_per_horizon_quantiles() -> None:
    results = pd.DataFrame(
        {
            "y": [100.0] * 10 + [100.0] * 10,
            "yhat": [101.0] * 10 + [105.0] * 10,
            "months_ahead": [1] * 10 + [2] * 10,
        }
    )

    calibration = calibrate_intervals(results, level=0.8)

    assert list(calibration.columns) == ["months_ahead", "half_width"]
    assert calibration.set_index("months_ahead").loc[1, "half_width"] == pytest.approx(1.0)
    assert calibration.set_index("months_ahead").loc[2, "half_width"] == pytest.approx(5.0)
    with pytest.raises(ValueError):
        calibrate_intervals(results, level=1.5)


def test_apply_interval_calibration_widens_band_and_clips() -> None:
    forecast = pd.DataFrame(
        {
            "ds": pd.date_range("2025-01-01", periods=3, freq="MS"),
            "yhat": [10.0, 20.0, 30.0],
            "yhat_lower": [10.0, 20.0, 30.0],
            "yhat_upper": [10.0, 20.0, 30.0],
        }
    )
    calibration = pd.DataFrame({"months_ahead": [1, 2], "half_width": [15.0, 5.0]})

    calibrated = apply_interval_calibration(forecast, calibration)

    assert calibrated.iloc[0]["yhat_lower"] == 0.0  # clipped, 10 - 15
    assert calibrated.iloc[0]["yhat_upper"] == 25.0
    assert calibrated.iloc[1]["yhat_lower"] == 15.0
    # Horizon 3 exceeds the calibrated range and reuses the widest known width.
    assert calibrated.iloc[2]["yhat_upper"] == 30.0 + 15.0


def test_calibration_restores_backtest_coverage() -> None:
    # The linear model on a noisy series produces some band; calibrating from the
    # backtest's own errors must bring coverage to at least the requested level.
    rng = np.random.default_rng(7)
    values = 1000 + 10 * np.arange(72, dtype=float) + rng.normal(0, 40, size=72)
    frame = _monthly_frame(list(values))

    results = rolling_origin_backtest(frame, linear_forecast, horizon=12, initial=36, step=6)
    calibration = calibrate_intervals(results, level=0.8)
    recalibrated = apply_interval_calibration(results, calibration)

    coverage = score_backtest(recalibrated)["coverage"]
    assert coverage >= 0.8


def test_calibrated_forecast_replaces_band_when_history_allows() -> None:
    rng = np.random.default_rng(3)
    values = 1000 + 10 * np.arange(60, dtype=float) + rng.normal(0, 30, size=60)
    frame = _monthly_frame(list(values))

    forecast, calibrated = calibrated_forecast(frame, linear_forecast, periods=12)
    native = linear_forecast(frame, 12)

    assert calibrated is True
    assert len(forecast) == 12
    # Point forecast is untouched; only the band changes.
    assert np.allclose(forecast["yhat"], native["yhat"])
    assert (forecast["yhat_lower"] <= forecast["yhat"]).all()
    assert (forecast["yhat_upper"] >= forecast["yhat"]).all()


def test_calibrated_forecast_keeps_native_band_on_short_history() -> None:
    frame = _monthly_frame([1000.0 + 10 * i for i in range(20)])  # < initial + periods

    forecast, calibrated = calibrated_forecast(frame, linear_forecast, periods=12)
    native = linear_forecast(frame, 12)

    assert calibrated is False
    assert np.allclose(forecast["yhat_upper"], native["yhat_upper"])


def test_dashboard_forecast_model_registry() -> None:
    from dashboard.data import FORECAST_MODELS, forecast_model_options

    options = forecast_model_options()
    assert set(options).issubset(FORECAST_MODELS)
    assert {"Linear trend", "Seasonal naive", "Naive (last value)"}.issubset(options)

    frame = _monthly_frame([100.0 + i for i in range(30)])
    for label in options:
        if label.startswith("Prophet"):
            continue  # Prophet fit is exercised by the science tests when installed.
        forecast = FORECAST_MODELS[label](frame, 3)
        assert list(forecast.columns) == ["ds", "yhat", "yhat_lower", "yhat_upper"]
        assert len(forecast) == 3


def test_compare_models_ranks_linear_first_on_trending_series() -> None:
    frame = _trend_with_seasonality(60)
    # Pin the candidate set: the default registry adds Prophet when installed,
    # which would make the ranking environment-dependent.
    baselines = {
        "naive": naive_forecast,
        "seasonal_naive": seasonal_naive_forecast,
        "linear": linear_forecast,
    }

    summary = compare_models(frame, forecasters=baselines, horizon=12, initial=36, step=6)

    assert {"naive", "seasonal_naive", "linear"} == set(summary.index)
    assert list(summary.columns) == ["n_forecasts", "mae", "rmse", "mape", "mase", "coverage"]
    # On a clean linear trend with mild seasonality the trend model must win.
    assert summary.index[0] == "linear"
    assert summary.loc["linear", "mase"] < summary.loc["naive", "mase"]
