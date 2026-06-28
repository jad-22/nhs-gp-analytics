"""Transformation entry points for monthly NHS extracts."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from .config import PDS_START


class TransformError(RuntimeError):
    """Raised when a raw extract cannot be normalised."""


def _read_table(raw_path: Path) -> pd.DataFrame:
    if not raw_path.exists():
        raise TransformError(f"Raw file does not exist: {raw_path}")

    suffix = raw_path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(raw_path)
    if suffix == ".csv":
        return pd.read_csv(raw_path)
    raise TransformError(f"Unsupported raw file type: {raw_path.suffix}")


def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    normalised = df.copy()
    normalised.columns = [
        "_".join(str(column).strip().upper().replace("-", " ").split())
        for column in normalised.columns
    ]
    return normalised


def transform_list_size(raw_path: Path, snapshot_date: date) -> pd.DataFrame:
    """Transform list-size raw data into the canonical schema."""

    frame = _normalise_columns(_read_table(raw_path))

    code_column = next(
        (column for column in ("CODE", "GP_PRACTICE_CODE", "PRACTICE_CODE") if column in frame.columns),
        None,
    )
    if code_column is None:
        raise TransformError("List-size file is missing a practice code column")

    patients_column = next(
        (column for column in ("NUMBER_OF_PATIENTS", "TOTAL_ALL") if column in frame.columns),
        None,
    )
    if patients_column is None:
        raise TransformError("List-size file is missing a patient count column")

    for column in ("TYPE", "SEX", "AGE"):
        if column in frame.columns:
            frame[column] = frame[column].astype(str).str.strip().str.upper()

    if {"TYPE", "SEX", "AGE"} <= set(frame.columns):
        frame = frame[
            (frame["TYPE"] == "GP")
            & (frame["SEX"] == "ALL")
            & (frame["AGE"] == "ALL")
        ].copy()

    frame["CODE"] = frame[code_column].astype(str).str.strip()
    frame["NUMBER_OF_PATIENTS"] = pd.to_numeric(frame[patients_column], errors="coerce")
    if frame["NUMBER_OF_PATIENTS"].isna().any():
        raise TransformError("NUMBER_OF_PATIENTS contains non-numeric values")

    frame["NUMBER_OF_PATIENTS"] = frame["NUMBER_OF_PATIENTS"].astype(int)
    frame["SNAPSHOT_DATE"] = pd.Timestamp(snapshot_date)
    frame["DATA_SOURCE"] = "PDS" if snapshot_date >= PDS_START else "NHAIS"

    return frame[["SNAPSHOT_DATE", "CODE", "NUMBER_OF_PATIENTS", "DATA_SOURCE"]].dropna(
        subset=["CODE"]
    )


def transform_mapping(raw_path: Path, snapshot_date: date) -> pd.DataFrame:
    """Transform mapping raw data and derive clinical system labels."""

    frame = _normalise_columns(_read_table(raw_path))
    code_column = next(
        (column for column in ("PRACTICE_CODE", "CODE", "GP_PRACTICE_CODE") if column in frame.columns),
        None,
    )
    if code_column is None:
        raise TransformError("Mapping file is missing a practice code column")

    frame["PRACTICE_CODE"] = frame[code_column].astype(str).str.strip()

    if "POSTCODE" not in frame.columns and "PRACTICE_POSTCODE" in frame.columns:
        frame["POSTCODE"] = frame["PRACTICE_POSTCODE"]

    supplier = frame.get("SUPPLIER_NAME", pd.Series(index=frame.index, dtype=str)).fillna("")
    supplier = supplier.astype(str).str.strip().str.upper()
    frame["CLINICAL_SYSTEM"] = supplier.map({"TPP": "SystmOne", "EMIS": "EMIS Web"}).fillna("Others")

    frame["SNAPSHOT_DATE"] = pd.Timestamp(snapshot_date)

    ordered_columns = ["SNAPSHOT_DATE", "PRACTICE_CODE"] + [
        column for column in frame.columns if column not in {"SNAPSHOT_DATE", "PRACTICE_CODE"}
    ]
    return frame[ordered_columns]


__all__ = ["TransformError", "transform_list_size", "transform_mapping"]