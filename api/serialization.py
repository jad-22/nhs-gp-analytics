"""Convert stored rows into the API's JSON vocabulary.

Parquet is ``UPPER_SNAKE``, JSON is ``snake_case``; the core Parquet uses
``timestamp[ms]`` and the dashboard caches ``timestamp[us]``. Both conversions happen
here and nowhere else, so a route handler never has to remember which is which.
"""

from __future__ import annotations

import math
from datetime import date, datetime

import pandas as pd

# Stored names that do not simply lower-case into the published name.
RENAMES = {
    "ODS_CODE": "ods_code",
    "SNAPSHOT_DATE": "date",
    "DS": "date",
    "NUMBER_OF_PATIENTS": "patients",
    "COMM_REGION_CODE": "region_code",
    "COMM_REGION_NAME": "region_name",
    "PRACTICE_POSTCODE": "postcode",
    "YHAT": "yhat",
    "YHAT_LOWER": "yhat_lower",
    "YHAT_UPPER": "yhat_upper",
}


def field_name(column: str) -> str:
    return RENAMES.get(column, column.lower())


def scalar(value):
    """Normalise one stored value into something JSON can carry."""

    if value is None or value is pd.NaT:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.date().isoformat() if value.tzinfo is None else value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (pd.Series, pd.Index)):
        raise TypeError("scalar() expects a single value")
    if hasattr(value, "item"):  # numpy scalars
        value = value.item()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def row(record: dict, columns: list[str] | None = None) -> dict:
    """Rename and normalise one row, keeping ``columns`` in the order given."""

    keys = columns if columns is not None else list(record)
    return {field_name(key): scalar(record.get(key)) for key in keys}


def rows(frame: pd.DataFrame, columns: list[str] | None = None) -> list[dict]:
    keys = columns if columns is not None else list(frame.columns)
    return [row(record, keys) for record in frame.to_dict("records")]


def timestamp(value) -> str | None:
    """ISO-8601 for a moment in time, as opposed to a calendar month."""

    if value is None or value is pd.NaT:
        return None
    moment = pd.Timestamp(value)
    if moment.tzinfo is None:
        moment = moment.tz_localize("UTC")
    return moment.isoformat().replace("+00:00", "Z")
