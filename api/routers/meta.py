"""Vintage, caveats and model accuracy — what a consumer needs to read the numbers."""

from __future__ import annotations

from fastapi import APIRouter

from api import db, repository, serialization
from api.config import ATTRIBUTION, CAVEATS, LICENCE_NAME, LICENCE_URL, SOURCE_URL
from api.deps import source_meta
from api.models import MetaResponse, ModelsResponse

router = APIRouter(prefix="/meta", tags=["meta"])

MODEL_NOTES = [
    "AutoETS is used for practices and PCNs; Holt-Winters for ICBs, regions and national. "
    "The ranking of these two reverses with aggregation level, so neither is used everywhere.",
    "Prophet is not used. It loses to a plain naive baseline at practice and PCN level, "
    "which is where 99.4% of the series are.",
    "ARIMA is excluded despite ranking second at practice level: it diverges on roughly "
    "1.5% of practices, in the worst case by ten orders of magnitude.",
    "`linear` in the model field means the series had under 24 months of history, so no "
    "seasonal model could be fitted and a trend line was used instead.",
    "MASE is scaled by the series' own in-sample seasonal-naive error: below 1 beats "
    "repeating last year's value.",
    "Intervals are nominally 80% but their measured out-of-sample coverage is lower. "
    "`coverage` on a forecast is what its published band achieved on a backtest cutoff it "
    "was not calibrated on; `coverage_native` is the model's own band, shown only for "
    "comparison. Use `measured_coverage` here rather than `interval_level`.",
]


@router.get(
    "",
    response_model=MetaResponse,
    summary="Data vintage, coverage and interpretation caveats",
    description=(
        "Read this before drawing conclusions. It records which month the data runs to, "
        "how many entities are served, what the published intervals actually deliver, "
        "and the known limitations of NHS England's registration data."
    ),
)
def get_meta() -> dict:
    record = db.meta()
    payload = {
        "run_id": str(record["RUN_ID"]),
        "generated_at": serialization.timestamp(record["GENERATED_AT"]),
        "trained_through": serialization.scalar(record["TRAINED_THROUGH"]),
        "earliest_month": serialization.scalar(record["EARLIEST_MONTH"]),
        "latest_month": serialization.scalar(record["LATEST_MONTH"]),
        "practice_count": int(record["PRACTICE_COUNT"]),
        "practice_count_all": int(record["PRACTICE_COUNT_ALL"]),
        "entity_count": int(record["ENTITY_COUNT"]),
        "forecast_count": int(record["FORECAST_COUNT"]),
        "quarantined_count": int(record["QUARANTINED_COUNT"]),
        "interval_level": float(record["INTERVAL_LEVEL"]),
        "measured_coverage": float(record["MEASURED_COVERAGE"]),
        "median_mase": float(record["MEDIAN_MASE"]),
        "caveats": CAVEATS,
        "licence": LICENCE_NAME,
        "licence_url": LICENCE_URL,
        "source": ATTRIBUTION,
        "source_url": SOURCE_URL,
    }
    return payload


@router.get(
    "/models",
    response_model=ModelsResponse,
    summary="Which model serves which level, and how accurate it is",
    description=(
        "Backtest accuracy per aggregation level, measured on the series being served "
        "rather than quoted from a paper. Methodology is in docs/FORECAST_VALIDATION.md."
    ),
)
def get_models() -> dict:
    frame = repository.model_summary()
    return {
        "models": serialization.rows(
            frame,
            [
                "LEVEL",
                "MODEL",
                "ENTITIES",
                "MEDIAN_MASE",
                "MEAN_COVERAGE",
                "MEAN_COVERAGE_NATIVE",
                "UNCALIBRATED",
                "QUARANTINED",
            ],
        ),
        "notes": MODEL_NOTES,
        "meta": source_meta(),
    }
