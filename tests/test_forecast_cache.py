"""Tests for the precomputed forecast cache (scripts/build_forecast_cache.py).

The cache is what the public API serves, so the tests here concentrate on the ways it
could be wrong *and still look plausible*: aggregates silently averaged instead of
summed, a missing library turning every forecast into a straight line under a real
model's name, and pathological series being published as confident forecasts.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pipeline import entities
from scripts import build_forecast_cache as cache

HAS_STATSMODELS = cache.ETSModel is not None
HAS_STATSFORECAST = cache.AutoETS is not None


def _months(count: int, start: str = "2020-01-01") -> pd.DatetimeIndex:
    return pd.date_range(start, periods=count, freq="MS")


def _list_size(codes: dict[str, list[float]], start: str = "2020-01-01") -> pd.DataFrame:
    rows = []
    for code, values in codes.items():
        for date, value in zip(_months(len(values), start), values):
            rows.append({"SNAPSHOT_DATE": date, "CODE": code, "NUMBER_OF_PATIENTS": value})
    return pd.DataFrame(rows)


def _mapping(assignments: dict[str, dict[str, str]], months: int, start: str = "2020-01-01") -> pd.DataFrame:
    rows = []
    for date in _months(months, start):
        for code, attributes in assignments.items():
            rows.append({"SNAPSHOT_DATE": date, "PRACTICE_CODE": code, **attributes})
    return pd.DataFrame(rows)


ASSIGNMENTS = {
    "A00001": {
        "PRACTICE_NAME": "Alpha Surgery",
        "PCN_CODE": "U00001",
        "PCN_NAME": "Alpha PCN",
        "ICB_CODE": "QAA",
        "ICB_NAME": "Alpha ICB",
        "COMM_REGION_CODE": "Y01",
        "COMM_REGION_NAME": "ALPHA REGION",
        "CCG_CODE": "00A",
    },
    "A00002": {
        "PRACTICE_NAME": "Beta Surgery",
        "PCN_CODE": "U00001",
        "PCN_NAME": "Alpha PCN",
        "ICB_CODE": "QAA",
        "ICB_NAME": "Alpha ICB",
        "COMM_REGION_CODE": "Y01",
        "COMM_REGION_NAME": "ALPHA REGION",
        "CCG_CODE": "00A",
    },
}


@pytest.fixture
def cache_inputs(tmp_path, monkeypatch):
    """Two practices with 60 months of clean trend + seasonality, written as Parquet."""

    index = np.arange(60, dtype=float)
    seasonal = 200 * np.sin(2 * np.pi * index / 12)
    list_size = _list_size(
        {
            "A00001": list(10_000 + 25 * index + seasonal),
            "A00002": list(4_000 + 10 * index + seasonal / 2),
        }
    )
    mapping = _mapping(ASSIGNMENTS, months=60)

    list_path = tmp_path / "list_size.parquet"
    mapping_path = tmp_path / "mapping.parquet"
    list_size.to_parquet(list_path, index=False)
    mapping.to_parquet(mapping_path, index=False)
    monkeypatch.setattr(cache, "LIST_SIZE_PARQUET_PATH", list_path)
    monkeypatch.setattr(cache, "MAPPING_PARQUET_PATH", mapping_path)
    return list_size, mapping


# --------------------------------------------------------------------------------------
# Guard 1: a missing library must fail the build, not quietly linearise it
# --------------------------------------------------------------------------------------


def test_require_models_raises_when_library_missing(monkeypatch):
    monkeypatch.setitem(cache.MODEL_REQUIREMENTS, "autoets", (None, "statsforecast"))

    with pytest.raises(RuntimeError, match="statsforecast unavailable"):
        cache.require_models("autoets")


def test_require_models_rejects_unknown_model():
    with pytest.raises(ValueError, match="Unknown model"):
        cache.require_models("magic")


def test_build_refuses_to_run_without_the_library(cache_inputs, monkeypatch):
    monkeypatch.setitem(cache.MODEL_REQUIREMENTS, "holt_winters", (None, "statsmodels"))

    with pytest.raises(RuntimeError, match="refusing to build a forecast cache"):
        cache.build_forecasts(levels=("national",))


# --------------------------------------------------------------------------------------
# Guard 2: aggregates are summed, not averaged
# --------------------------------------------------------------------------------------


def test_aggregates_sum_practices_rather_than_averaging(cache_inputs):
    list_size, mapping = cache_inputs
    series, register = entities.build_series(list_size, mapping)

    latest = list_size["SNAPSHOT_DATE"].max()
    expected = list_size.loc[list_size["SNAPSHOT_DATE"] == latest, "NUMBER_OF_PATIENTS"].sum()

    for level in ("national", "region", "icb", "pcn"):
        block = series.loc[(series["LEVEL"] == level) & (series["SNAPSHOT_DATE"] == latest)]
        assert block["NUMBER_OF_PATIENTS"].sum() == pytest.approx(expected)
        # The mean of the two practices is ~7k; the sum is ~14k. Averaging would pass a
        # naive "is it a number" check, so assert the totals reconcile exactly.
        assert block["NUMBER_OF_PATIENTS"].sum() > list_size["NUMBER_OF_PATIENTS"].max()

    assert set(register["LEVEL"]) == set(cache.LEVELS)
    assert register.loc[register["LEVEL"] == "practice", "ENTITY_CODE"].tolist() == ["A00001", "A00002"]


def test_only_entities_active_in_the_latest_snapshot_are_forecast(cache_inputs):
    list_size, mapping = cache_inputs
    closed = list_size.loc[list_size["CODE"] == "A00002"].copy()
    closed["CODE"] = "A00003"
    closed = closed.loc[closed["SNAPSHOT_DATE"] < closed["SNAPSHOT_DATE"].max()]
    extended_mapping = pd.concat(
        [mapping, mapping.loc[mapping["PRACTICE_CODE"] == "A00002"].assign(PRACTICE_CODE="A00003")],
        ignore_index=True,
    )

    series, register = entities.build_series(pd.concat([list_size, closed], ignore_index=True), extended_mapping)

    practices = set(register.loc[register["LEVEL"] == "practice", "ENTITY_CODE"])
    assert "A00003" not in practices, "a practice absent from the latest snapshot must not be forecast"
    # Its history still counts towards the aggregates it belonged to.
    national = series.loc[(series["LEVEL"] == "national")].set_index("SNAPSHOT_DATE")["NUMBER_OF_PATIENTS"]
    assert national.iloc[0] > series.loc[series["LEVEL"] == "practice"].groupby("SNAPSHOT_DATE")["NUMBER_OF_PATIENTS"].sum().iloc[0]


def test_ccg_bridge_recovers_practices_that_closed_before_icbs_existed():
    """ICB_CODE starts 2022-07 and CCG_CODE stops 2022-06; the bridge must span the gap."""

    months = pd.date_range("2022-05-01", periods=3, freq="MS")
    rows = []
    for date in months:
        icb = "QAA" if date >= pd.Timestamp("2022-07-01") else None
        ccg = None if date >= pd.Timestamp("2022-07-01") else "00A"
        rows.append({"SNAPSHOT_DATE": date, "PRACTICE_CODE": "A00001", "ICB_CODE": icb, "CCG_CODE": ccg})
    # A00009 closed in June 2022, so it never carries an ICB code of its own.
    rows.append({"SNAPSHOT_DATE": months[0], "PRACTICE_CODE": "A00009", "ICB_CODE": None, "CCG_CODE": "00A"})
    mapping = pd.DataFrame(rows)
    for column in ("PRACTICE_NAME", "PCN_CODE", "COMM_REGION_CODE"):
        mapping[column] = None

    resolved = entities.practice_entities(mapping)

    assert resolved.loc["A00009", "ICB_CODE"] == "QAA"


# --------------------------------------------------------------------------------------
# Guard 3: the recorded model is the one that ran
# --------------------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_STATSMODELS, reason="statsmodels not installed")
def test_short_history_is_recorded_as_linear_not_as_the_requested_model():
    dates = pd.date_range("2024-01-01", periods=18, freq="MS")  # < MIN_SEASONAL_HISTORY
    values = [1000.0 + 10 * step for step in range(18)]

    result = cache.forecast_entity(("practice", "A00001", list(dates), values, "holt_winters"))

    assert result["model"] == "linear", "a silent fallback must never be labelled holt_winters"
    assert result["calibrated"] is False


@pytest.mark.skipif(not HAS_STATSMODELS, reason="statsmodels not installed")
def test_full_history_records_the_real_model_and_calibrates():
    index = np.arange(78, dtype=float)
    dates = pd.date_range("2020-01-01", periods=78, freq="MS")
    values = list(10_000 + 25 * index + 200 * np.sin(2 * np.pi * index / 12))

    result = cache.forecast_entity(("national", "ENG", list(dates), values, "holt_winters"))

    assert result["model"] == "holt_winters"
    assert result["calibrated"] is True
    assert result["n_forecasts"] > 0
    assert result["metrics"]["mase"] < 1.0
    assert result["trained_through"] == pd.Timestamp("2026-06-01")
    assert len(result["forecast"]["yhat"]) == cache.HORIZON


# --------------------------------------------------------------------------------------
# Quarantine
# --------------------------------------------------------------------------------------


def test_pathological_series_is_quarantined_and_not_served(monkeypatch):
    """A series no model can track must not be published as a confident forecast."""

    monkeypatch.setattr(cache, "MASE_QUARANTINE", 0.0)  # force the branch deterministically
    index = np.arange(78, dtype=float)
    dates = pd.date_range("2020-01-01", periods=78, freq="MS")
    values = list(10_000 + 25 * index)

    model = "holt_winters" if HAS_STATSMODELS else "autoets"
    if cache.MODEL_REQUIREMENTS[model][0] is None:
        pytest.skip("no statistical model available")

    result = cache.forecast_entity(("practice", "A00001", list(dates), values, model))

    assert result["quarantine_reason"] == "mase_above_threshold"


# --------------------------------------------------------------------------------------
# End-to-end shape and content
# --------------------------------------------------------------------------------------


@pytest.mark.skipif(not (HAS_STATSMODELS and HAS_STATSFORECAST), reason="forecasting libraries not installed")
def test_end_to_end_cache_contract(cache_inputs):
    forecasts, metrics = cache.build_forecasts(workers=1, progress_every=10_000)

    assert list(forecasts.columns) == [
        "LEVEL",
        "ENTITY_CODE",
        "ENTITY_NAME",
        "DS",
        "HORIZON_MONTH",
        "YHAT",
        "YHAT_LOWER",
        "YHAT_UPPER",
        "MODEL",
        "CALIBRATED",
        "INTERVAL_LEVEL",
        "TRAINED_THROUGH",
        "RUN_ID",
        "GENERATED_AT",
    ]
    assert set(metrics["LEVEL"]) == set(cache.LEVELS)

    # 5 levels x (1 national + 1 region + 1 icb + 1 pcn + 2 practices) = 6 entities.
    assert len(metrics) == 6
    assert len(forecasts) == 6 * cache.HORIZON

    per_entity = forecasts.groupby(["LEVEL", "ENTITY_CODE"])["HORIZON_MONTH"]
    assert (per_entity.count() == cache.HORIZON).all()
    assert (per_entity.min() == 1).all()
    assert (forecasts["YHAT_LOWER"] <= forecasts["YHAT"]).all()
    assert (forecasts["YHAT_UPPER"] >= forecasts["YHAT"]).all()
    assert (forecasts["YHAT_LOWER"] >= 0).all()
    assert forecasts["RUN_ID"].nunique() == 1
    assert forecasts["INTERVAL_LEVEL"].eq(cache.INTERVAL_LEVEL).all()

    # The measured per-level split: statistical model per level, never Prophet.
    models = metrics.set_index("LEVEL")["MODEL"].to_dict()
    assert models["practice"] == "autoets"
    assert models["pcn"] == "autoets"
    assert models["national"] == "holt_winters"
    assert models["icb"] == "holt_winters"
    assert "prophet" not in set(metrics["MODEL"])


@pytest.mark.skipif(not (HAS_STATSMODELS and HAS_STATSFORECAST), reason="forecasting libraries not installed")
def test_run_id_is_content_addressed(cache_inputs):
    first, _ = cache.build_forecasts(workers=1, progress_every=10_000)
    second, _ = cache.build_forecasts(workers=1, progress_every=10_000)

    # GENERATED_AT moves; RUN_ID must not, or every client's cached response is
    # invalidated by a rebuild that changed nothing.
    assert first["RUN_ID"].iloc[0] == second["RUN_ID"].iloc[0]
    assert first["RUN_ID"].iloc[0].startswith("2024-12.")


def test_model_for_level_matches_the_measured_split():
    for level in ("national", "region", "icb"):
        assert cache.model_for_level(level, "autoets", "holt_winters") == "holt_winters"
    for level in ("pcn", "practice"):
        assert cache.model_for_level(level, "autoets", "holt_winters") == "autoets"
