import numpy as np
import pandas as pd
import pytest

from science.backtesting import (
    compare_models,
    generate_cutoffs,
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


def test_compare_models_ranks_linear_first_on_trending_series() -> None:
    frame = _trend_with_seasonality(60)

    summary = compare_models(frame, horizon=12, initial=36, step=6)

    assert {"naive", "seasonal_naive", "linear"}.issubset(summary.index)
    assert list(summary.columns) == ["n_forecasts", "mae", "rmse", "mape", "mase", "coverage"]
    # On a clean linear trend with mild seasonality the trend model must win.
    assert summary.index[0] == "linear"
    assert summary.loc["linear", "mase"] < summary.loc["naive", "mase"]
