"""Precompute 12-month forecasts for every served entity (DEC-012).

Writes two Parquet artifacts that the public API reads directly, so no model ever
runs inside a request:

    data/processed/forecasts.parquet         12 rows per entity
    data/processed/forecast_metrics.parquet  1 row per entity

Run after the core processed Parquet files are updated:

    python scripts/build_forecast_cache.py

Model choice is per aggregation level and is measured, not assumed — AutoETS for
practices and PCNs, Holt-Winters for ICBs, regions and national. See
``docs/FORECAST_VALIDATION.md`` §7 for the backtest that settled it.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.config import DATA_PROCESSED_DIR, LIST_SIZE_PARQUET_PATH, MAPPING_PARQUET_PATH
from pipeline.entities import LEVELS, build_series, month_start
from science.backtesting import (
    apply_interval_calibration,
    calibrate_intervals,
    rolling_origin_backtest,
    score_backtest,
)
from science.forecasting import _linear_forecast, _prepare_series
from science.stat_forecasting import (
    AutoETS,
    ETSModel,
    SARIMAX,
    arima_forecast,
    autoets_forecast,
    holt_winters_forecast,
    sarima_forecast,
)

FORECASTS_PARQUET_PATH = DATA_PROCESSED_DIR / "forecasts.parquet"
FORECAST_METRICS_PARQUET_PATH = DATA_PROCESSED_DIR / "forecast_metrics.parquet"

# Backtest geometry — identical to the dashboard's calibrated_forecast defaults and to
# the §7 analysis, so precomputed numbers reconcile with the live drill-down.
HORIZON = 12
INITIAL = 36
STEP = 6
INTERVAL_LEVEL = 0.8

# A MASE this far above 1 is a broken series (a merger, a code reassignment), not a
# model that needs tuning: the measured worst case is a practice at ~72 across *every*
# candidate model. Quarantined rather than served as a confident forecast.
MASE_QUARANTINE = 50.0

# Levels whose series are heavily aggregated and smooth. Holt-Winters' damped seasonal
# trend wins here; below roughly 1M patients the ranking flips to AutoETS.
AGGREGATE_LEVELS = frozenset({"national", "region", "icb"})

# Every model the builder can be pointed at, with the library that must be importable
# for it to be real rather than a linear fallback (the DEC-009 guard).
MODEL_REQUIREMENTS: dict[str, tuple[object, str]] = {
    "autoets": (AutoETS, "statsforecast"),
    "holt_winters": (ETSModel, "statsmodels"),
    "arima": (SARIMAX, "statsmodels"),
    "sarima": (SARIMAX, "statsmodels"),
}
MODELS = {
    "autoets": autoets_forecast,
    "holt_winters": holt_winters_forecast,
    "arima": arima_forecast,
    "sarima": sarima_forecast,
}

DEFAULT_PRACTICE_MODEL = "autoets"
DEFAULT_AGGREGATE_MODEL = "holt_winters"

# Each worker is a fresh interpreter that imports numpy, statsmodels and statsforecast
# — roughly half a gigabyte before it forecasts anything. On a 12-core machine that
# runs out of RAM during spawn, so the pool is capped rather than sized to the CPU
# count. Override with --workers on a box with memory to spare.
MAX_WORKERS = 6


def default_workers() -> int:
    return max(1, min(os.cpu_count() or 1, MAX_WORKERS))


# --------------------------------------------------------------------------------------
# Guard 1: never build a cache that silently contains linear-fallback values
# --------------------------------------------------------------------------------------


def require_models(*names: str) -> None:
    """Raise unless every named model's library is importable.

    Without this the forecasters degrade to a straight line and the cache would be
    published with a real model's name on fabricated numbers — the exact failure
    DEC-009 exists to prevent, and one that is invisible downstream.
    """

    for name in names:
        if name not in MODEL_REQUIREMENTS:
            raise ValueError(f"Unknown model {name!r}; choose from {sorted(MODELS)}.")
        library, package = MODEL_REQUIREMENTS[name]
        if library is None:
            raise RuntimeError(
                f"{package} unavailable — refusing to build a forecast cache that would "
                f"silently contain linear-fallback values labelled as {name!r}."
            )


# --------------------------------------------------------------------------------------
# Forecasting
# --------------------------------------------------------------------------------------


def model_for_level(level: str, practice_model: str, aggregate_model: str) -> str:
    return aggregate_model if level in AGGREGATE_LEVELS else practice_model


def _model_actually_used(series: pd.DataFrame, forecast: pd.DataFrame, requested: str) -> str:
    """Guard 3: record the model that ran, never the one that was asked for.

    Every forecaster falls back to a linear trend when the history is under two seasons
    or the fit fails, and it does so silently. The fallback is bit-identical to
    ``_linear_forecast``, so comparing against it is an exact test.
    """

    if forecast.empty:
        return "none"
    fallback = _linear_forecast(series, len(forecast))
    if np.array_equal(forecast["yhat"].to_numpy(dtype=float), fallback["yhat"].to_numpy(dtype=float)):
        return "linear"
    return requested


def _holdout_coverage(results: pd.DataFrame) -> float:
    """What the *calibrated* band would have covered on a cutoff it never saw.

    ``score_backtest`` reports coverage of the model's **native** band, but the API
    publishes the DEC-007 calibrated band — so the native figure describes an interval
    nobody receives. Calibrating on every cutoff and then scoring those same cutoffs is
    no better: it is in-sample, and it flatters itself (0.83 in FORECAST_VALIDATION §5).

    So: calibrate on all cutoffs but the last, score the last. Pure arithmetic on the
    backtest already computed — no refitting.
    """

    if results.empty:
        return float("nan")
    cutoffs = sorted(results["cutoff"].unique())
    if len(cutoffs) < 2:
        return float("nan")

    calibration = calibrate_intervals(results[results["cutoff"] != cutoffs[-1]], level=INTERVAL_LEVEL)
    if calibration.empty:
        return float("nan")

    holdout = results[results["cutoff"] == cutoffs[-1]]
    lookup = calibration.set_index("months_ahead")["half_width"]
    widths = holdout["months_ahead"].map(lookup).fillna(float(lookup.max()))
    inside = (holdout["y"] >= holdout["yhat"] - widths) & (holdout["y"] <= holdout["yhat"] + widths)
    return float(inside.mean())


def forecast_entity(task: tuple[str, str, list, list, str]) -> dict:
    """Backtest, calibrate and fit one series. Runs in a worker process."""

    level, code, dates, values, model_name = task
    series = _prepare_series(pd.DataFrame({"ds": pd.to_datetime(dates), "y": values}))
    forecaster = MODELS[model_name]

    # calibrated_forecast() runs exactly this backtest and throws the scores away.
    # Calling the primitives directly makes per-entity accuracy free.
    results = rolling_origin_backtest(series, forecaster, horizon=HORIZON, initial=INITIAL, step=STEP)
    metrics = score_backtest(results)
    forecast = forecaster(series, HORIZON)
    model_used = _model_actually_used(series, forecast, model_name)

    calibration = calibrate_intervals(results, level=INTERVAL_LEVEL) if not results.empty else pd.DataFrame()
    calibrated = not calibration.empty and not forecast.empty
    if calibrated:
        forecast = apply_interval_calibration(forecast, calibration)

    mase = float(metrics["mase"])
    if forecast.empty:
        reason = "no_forecast"
    elif np.isfinite(mase) and mase > MASE_QUARANTINE:
        reason = "mase_above_threshold"
    else:
        reason = ""

    return {
        "level": level,
        "code": code,
        "model": model_used,
        "calibrated": bool(calibrated),
        "months": int(len(series)),
        "trained_through": series["ds"].iloc[-1] if len(series) else pd.NaT,
        "quarantine_reason": reason,
        "metrics": {
            **{key: float(metrics[key]) for key in ("mae", "rmse", "mape", "mase")},
            # The band the model itself proposed, kept for comparison...
            "coverage_native": float(metrics["coverage"]),
            # ...and the band actually published, scored on unseen data.
            "coverage": _holdout_coverage(results),
        },
        "n_forecasts": int(metrics["n_forecasts"]),
        "forecast": None if forecast.empty else forecast[["ds", "yhat", "yhat_lower", "yhat_upper"]].to_dict("list"),
    }


def _tasks(series: pd.DataFrame, practice_model: str, aggregate_model: str) -> list[tuple]:
    tasks = []
    for (level, code), group in series.groupby(["LEVEL", "ENTITY_CODE"], sort=True):
        ordered = group.sort_values("SNAPSHOT_DATE")
        tasks.append(
            (
                level,
                code,
                ordered["SNAPSHOT_DATE"].tolist(),
                ordered["NUMBER_OF_PATIENTS"].astype(float).tolist(),
                model_for_level(level, practice_model, aggregate_model),
            )
        )
    return tasks


def _run_id(forecasts: pd.DataFrame, vintage: pd.Timestamp) -> str:
    """Content-addressed run id: identical inputs and models produce an identical id.

    The API serves this as the ETag, so it must not churn on a rebuild that changed
    nothing — a timestamp would invalidate every cached client response for free.
    """

    payload = forecasts[["LEVEL", "ENTITY_CODE", "DS", "YHAT", "YHAT_LOWER", "YHAT_UPPER", "MODEL"]]
    digest = hashlib.sha256(pd.util.hash_pandas_object(payload, index=False).values.tobytes()).hexdigest()
    return f"{vintage:%Y-%m}.{digest[:12]}"


def build_forecasts(
    *,
    levels: tuple[str, ...] = LEVELS,
    limit: int | None = None,
    practice_model: str = DEFAULT_PRACTICE_MODEL,
    aggregate_model: str = DEFAULT_AGGREGATE_MODEL,
    workers: int | None = None,
    progress_every: int = 250,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build both cache frames. Returns (forecasts, metrics)."""

    require_models(practice_model, aggregate_model)

    if not LIST_SIZE_PARQUET_PATH.exists():
        raise FileNotFoundError(f"Missing {LIST_SIZE_PARQUET_PATH}")
    if not MAPPING_PARQUET_PATH.exists():
        raise FileNotFoundError(f"Missing {MAPPING_PARQUET_PATH}")

    list_size = pd.read_parquet(LIST_SIZE_PARQUET_PATH)
    mapping = pd.read_parquet(MAPPING_PARQUET_PATH)
    list_size["SNAPSHOT_DATE"] = month_start(list_size["SNAPSHOT_DATE"])
    mapping["SNAPSHOT_DATE"] = month_start(mapping["SNAPSHOT_DATE"])
    mapping = mapping.sort_values("SNAPSHOT_DATE")

    series, register = build_series(list_size, mapping)
    series = series.loc[series["LEVEL"].isin(levels)]
    register = register.loc[register["LEVEL"].isin(levels)]

    if limit is not None:
        keep = register.groupby("LEVEL", group_keys=False).head(limit)
        series = series.merge(keep[["LEVEL", "ENTITY_CODE"]], on=["LEVEL", "ENTITY_CODE"], how="inner")
        register = keep

    names = register.set_index(["LEVEL", "ENTITY_CODE"])["ENTITY_NAME"]
    tasks = _tasks(series, practice_model, aggregate_model)
    print(f"Forecasting {len(tasks):,} series ({', '.join(levels)}) ...", flush=True)

    started = time.perf_counter()
    outputs: list[dict] = []
    with ProcessPoolExecutor(max_workers=workers or default_workers()) as pool:
        for index, result in enumerate(pool.map(forecast_entity, tasks, chunksize=8), start=1):
            outputs.append(result)
            if index % progress_every == 0 or index == len(tasks):
                rate = index / max(time.perf_counter() - started, 1e-9)
                remaining = (len(tasks) - index) / max(rate, 1e-9)
                print(f"  {index:,}/{len(tasks):,}  {rate:.1f} series/s  eta {remaining / 60:.1f} min", flush=True)

    generated_at = datetime.now(timezone.utc).replace(microsecond=0)
    forecast_rows = []
    metric_rows = []
    for result in outputs:
        key = (result["level"], result["code"])
        name = names.get(key, "Unknown")
        metric_rows.append(
            {
                "LEVEL": result["level"],
                "ENTITY_CODE": result["code"],
                "ENTITY_NAME": name,
                "MODEL": result["model"],
                "CALIBRATED": result["calibrated"],
                "N_MONTHS": result["months"],
                "N_FORECASTS": result["n_forecasts"],
                "MAE": result["metrics"]["mae"],
                "RMSE": result["metrics"]["rmse"],
                "MAPE": result["metrics"]["mape"],
                "MASE": result["metrics"]["mase"],
                # COVERAGE is what the published calibrated band achieved on a held-out
                # cutoff; COVERAGE_NATIVE is the model's own band, for comparison only.
                "COVERAGE": result["metrics"]["coverage"],
                "COVERAGE_NATIVE": result["metrics"]["coverage_native"],
                "QUARANTINED": bool(result["quarantine_reason"]),
                "QUARANTINE_REASON": result["quarantine_reason"],
            }
        )
        if result["quarantine_reason"] or result["forecast"] is None:
            continue

        points = pd.DataFrame(result["forecast"])
        forecast_rows.append(
            pd.DataFrame(
                {
                    "LEVEL": result["level"],
                    "ENTITY_CODE": result["code"],
                    "ENTITY_NAME": name,
                    "DS": points["ds"],
                    "HORIZON_MONTH": np.arange(1, len(points) + 1),
                    "YHAT": points["yhat"],
                    "YHAT_LOWER": points["yhat_lower"],
                    "YHAT_UPPER": points["yhat_upper"],
                    "MODEL": result["model"],
                    "CALIBRATED": result["calibrated"],
                    "INTERVAL_LEVEL": INTERVAL_LEVEL,
                    "TRAINED_THROUGH": result["trained_through"],
                }
            )
        )

    metrics = pd.DataFrame(metric_rows).sort_values(["LEVEL", "ENTITY_CODE"]).reset_index(drop=True)
    forecasts = (
        pd.concat(forecast_rows, ignore_index=True).sort_values(["LEVEL", "ENTITY_CODE", "HORIZON_MONTH"]).reset_index(drop=True)
        if forecast_rows
        else pd.DataFrame()
    )

    vintage = series["SNAPSHOT_DATE"].max()
    run_id = _run_id(forecasts, vintage) if not forecasts.empty else f"{vintage:%Y-%m}.empty"
    for frame in (forecasts, metrics):
        if not frame.empty:
            frame["RUN_ID"] = run_id
    if not forecasts.empty:
        forecasts["GENERATED_AT"] = generated_at
    return forecasts, metrics


def write_cache(
    output_dir: Path = DATA_PROCESSED_DIR,
    **kwargs,
) -> dict[str, tuple[int, int]]:
    """Build the forecast caches and write them, returning their shapes."""

    forecasts, metrics = build_forecasts(**kwargs)
    output_dir.mkdir(parents=True, exist_ok=True)
    forecasts.to_parquet(output_dir / FORECASTS_PARQUET_PATH.name, index=False)
    metrics.to_parquet(output_dir / FORECAST_METRICS_PARQUET_PATH.name, index=False)
    return {
        FORECASTS_PARQUET_PATH.name: forecasts.shape,
        FORECAST_METRICS_PARQUET_PATH.name: metrics.shape,
    }


def _summarise(output_dir: Path) -> None:
    forecasts = pd.read_parquet(output_dir / FORECASTS_PARQUET_PATH.name)
    metrics = pd.read_parquet(output_dir / FORECAST_METRICS_PARQUET_PATH.name)
    print(f"\nrun_id: {forecasts['RUN_ID'].iloc[0]}   trained through {forecasts['TRAINED_THROUGH'].max():%Y-%m}")
    summary = metrics.groupby("LEVEL").agg(
        entities=("ENTITY_CODE", "size"),
        median_mase=("MASE", "median"),
        # Mean, not median: per-series coverage is bimodal, so the median flatters it.
        mean_coverage=("COVERAGE", "mean"),
        mean_coverage_native=("COVERAGE_NATIVE", "mean"),
        uncalibrated=("CALIBRATED", lambda flags: int((~flags).sum())),
        quarantined=("QUARANTINED", "sum"),
    )
    print(summary.to_string())
    fallbacks = metrics.loc[metrics["MODEL"].isin({"linear", "none"})]
    if not fallbacks.empty:
        print(f"\n{len(fallbacks)} series fell back below a real model (history too short):")
        print(fallbacks[["LEVEL", "ENTITY_CODE", "MODEL", "N_MONTHS"]].to_string(index=False))
    quarantined = metrics.loc[metrics["QUARANTINED"]]
    if not quarantined.empty:
        print(f"\n{len(quarantined)} series quarantined and not served:")
        print(quarantined[["LEVEL", "ENTITY_CODE", "MASE", "QUARANTINE_REASON"]].to_string(index=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--levels", default=",".join(LEVELS), help="Comma-separated levels to build.")
    parser.add_argument("--limit", type=int, default=None, help="Cap entities per level (local iteration).")
    parser.add_argument("--model-practice", default=DEFAULT_PRACTICE_MODEL, choices=sorted(MODELS))
    parser.add_argument("--model-aggregate", default=DEFAULT_AGGREGATE_MODEL, choices=sorted(MODELS))
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help=f"Worker processes (default: min(CPU count, {MAX_WORKERS}) — each needs ~0.5 GB).",
    )
    parser.add_argument("--output-dir", type=Path, default=DATA_PROCESSED_DIR)
    args = parser.parse_args()

    levels = tuple(level.strip() for level in args.levels.split(",") if level.strip())
    unknown = set(levels) - set(LEVELS)
    if unknown:
        raise SystemExit(f"Unknown level(s): {', '.join(sorted(unknown))}. Choose from {', '.join(LEVELS)}.")

    started = time.perf_counter()
    shapes = write_cache(
        output_dir=args.output_dir,
        levels=levels,
        limit=args.limit,
        practice_model=args.model_practice,
        aggregate_model=args.model_aggregate,
        workers=args.workers,
    )
    for filename, shape in shapes.items():
        print(f"{filename}: {shape[0]:,} rows x {shape[1]} columns")
    _summarise(args.output_dir)
    print(f"\nelapsed {(time.perf_counter() - started) / 60:.1f} min")


if __name__ == "__main__":
    main()
