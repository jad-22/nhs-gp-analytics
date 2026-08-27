"""Assemble stored rows into response payloads.

The list-size and forecast shapes are identical for a practice and for an ICB, so they
are built once here and the routers only differ in how they resolve the entity.
"""

from __future__ import annotations

import pandas as pd

from api import repository, serialization
from api.deps import not_found, source_meta

UNCALIBRATED_WARNING = (
    "History too short to calibrate; the interval is the model's native band and is "
    "indicative only."
)

LIST_SIZE_COLUMNS = ["SNAPSHOT_DATE", "NUMBER_OF_PATIENTS", "DATA_SOURCE"]
FORECAST_POINT_COLUMNS = ["DS", "HORIZON_MONTH", "YHAT", "YHAT_LOWER", "YHAT_UPPER"]
ACCURACY_FIELDS = ("MASE", "MAE", "RMSE", "MAPE", "COVERAGE", "COVERAGE_NATIVE", "N_FORECASTS")


def list_size_response(level: str, entity_code: str, entity_name: str | None, history: pd.DataFrame) -> dict:
    columns = [column for column in LIST_SIZE_COLUMNS if column in history.columns]
    return {
        "level": level,
        "entity_code": entity_code,
        "entity_name": entity_name,
        "points": serialization.rows(history, columns),
        "meta": source_meta(),
    }


def forecast_response(level: str, entity_code: str, entity_name: str | None, *, closed: bool = False) -> dict:
    """Build a forecast payload, or raise the 404 that explains why there isn't one."""

    if closed:
        raise not_found(
            f"{entity_code} is not in the latest snapshot, so it has no forecast. Its "
            "history is still available at the list-size endpoint.",
            "entity_closed",
        )

    points = repository.get_forecast(level, entity_code)
    metrics = repository.get_metrics(level, entity_code)

    if points.empty:
        if metrics and metrics.get("QUARANTINED"):
            raise not_found(
                f"No forecast is published for {entity_code}: its history is too "
                "irregular for any model to track, so serving one would be misleading "
                f"(reason: {metrics.get('QUARANTINE_REASON')}).",
                "forecast_withheld",
            )
        raise not_found(f"No forecast found for {entity_code} at {level} level.", "forecast_not_found")

    first = points.iloc[0]
    calibrated = bool(first["CALIBRATED"])
    block = {
        "model": str(first["MODEL"]),
        "calibrated": calibrated,
        "interval_level": float(first["INTERVAL_LEVEL"]),
        "trained_through": serialization.scalar(first["TRAINED_THROUGH"]),
        "generated_at": serialization.timestamp(first["GENERATED_AT"]),
        "interval_warning": None if calibrated else UNCALIBRATED_WARNING,
        "points": serialization.rows(points, FORECAST_POINT_COLUMNS),
    }

    accuracy = {field.lower(): None for field in ACCURACY_FIELDS}
    if metrics:
        accuracy = {field.lower(): serialization.scalar(metrics[field]) for field in ACCURACY_FIELDS}

    return {
        "level": level,
        "entity_code": entity_code,
        "entity_name": entity_name or serialization.scalar(first.get("ENTITY_NAME")),
        "forecast": block,
        "accuracy": accuracy,
        "meta": source_meta(),
    }
