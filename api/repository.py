"""Every SQL statement the API runs, in one place.

Routers call these functions and never write SQL, so the parameterised-query boundary is
a single reviewable file. Nothing here interpolates user input into a statement; the one
place a value reaches the text (the ``level`` filter) is validated against a fixed set
first.
"""

from __future__ import annotations

import pandas as pd

from api import db

AGGREGATE_LEVELS = ("national", "region", "icb", "pcn")
ALL_LEVELS = AGGREGATE_LEVELS + ("practice",)

PRACTICE_COLUMNS = [
    "ODS_CODE",
    "PRACTICE_NAME",
    "PRACTICE_POSTCODE",
    "PCN_CODE",
    "PCN_NAME",
    "ICB_CODE",
    "ICB_NAME",
    "REGION_CODE",
    "REGION_NAME",
    "CLINICAL_SYSTEM",
    "SUPPLIER_NAME",
    "IMD_SCORE",
    "IMD_DECILE",
    "LATITUDE",
    "LONGITUDE",
    "NUMBER_OF_PATIENTS",
    "ACTIVE",
    "FIRST_MONTH",
    "LAST_MONTH",
    "AS_OF",
]


def normalise_code(code: str) -> str:
    return code.strip().upper()


# --------------------------------------------------------------------------------------
# Practices
# --------------------------------------------------------------------------------------


def get_practice(ods_code: str) -> dict | None:
    return db.query_one(
        f"SELECT {', '.join(PRACTICE_COLUMNS)} FROM practices WHERE ODS_CODE = ?",
        [normalise_code(ods_code)],
    )


def search_practices(
    *,
    search: str | None,
    icb: str | None,
    pcn: str | None,
    region: str | None,
    active: bool | None,
    limit: int,
    offset: int,
) -> tuple[pd.DataFrame, int]:
    clauses: list[str] = []
    params: list = []
    if search:
        clauses.append("(ODS_CODE ILIKE ? OR PRACTICE_NAME ILIKE ?)")
        pattern = f"%{search.strip()}%"
        params.extend([pattern, pattern])
    for column, value in (("ICB_CODE", icb), ("PCN_CODE", pcn), ("REGION_CODE", region)):
        if value:
            clauses.append(f"{column} = ?")
            params.append(normalise_code(value))
    if active is not None:
        clauses.append("ACTIVE = ?")
        params.append(active)

    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    total = int(db.query(f"SELECT COUNT(*) AS n FROM practices{where}", params).iloc[0]["n"])
    page = db.query(
        f"SELECT {', '.join(PRACTICE_COLUMNS)} FROM practices{where} ORDER BY ODS_CODE LIMIT ? OFFSET ?",
        [*params, limit, offset],
    )
    return page, total


def practice_history(ods_code: str) -> pd.DataFrame:
    return db.query(
        "SELECT SNAPSHOT_DATE, NUMBER_OF_PATIENTS, DATA_SOURCE FROM list_size "
        "WHERE CODE = ? ORDER BY SNAPSHOT_DATE",
        [normalise_code(ods_code)],
    )


# --------------------------------------------------------------------------------------
# Aggregate entities
# --------------------------------------------------------------------------------------


def _check_level(level: str) -> str:
    if level not in ALL_LEVELS:
        raise ValueError(f"Unknown level {level!r}")
    return level


def get_entity(level: str, entity_code: str) -> dict | None:
    return db.query_one(
        "SELECT LEVEL, ENTITY_CODE, ENTITY_NAME, PRACTICE_COUNT, LATEST_PATIENTS, AS_OF "
        "FROM entities WHERE LEVEL = ? AND ENTITY_CODE = ?",
        [_check_level(level), normalise_code(entity_code)],
    )


def list_entities(level: str, *, search: str | None = None) -> pd.DataFrame:
    clause = ""
    params: list = [_check_level(level)]
    if search:
        clause = " AND (ENTITY_CODE ILIKE ? OR ENTITY_NAME ILIKE ?)"
        pattern = f"%{search.strip()}%"
        params.extend([pattern, pattern])
    return db.query(
        "SELECT LEVEL, ENTITY_CODE, ENTITY_NAME, PRACTICE_COUNT, LATEST_PATIENTS, AS_OF "
        f"FROM entities WHERE LEVEL = ?{clause} ORDER BY ENTITY_NAME",
        params,
    )


def aggregate_history(level: str, entity_code: str) -> pd.DataFrame:
    return db.query(
        "SELECT SNAPSHOT_DATE, NUMBER_OF_PATIENTS FROM aggregate_list_size "
        "WHERE LEVEL = ? AND ENTITY_CODE = ? ORDER BY SNAPSHOT_DATE",
        [_check_level(level), normalise_code(entity_code)],
    )


# --------------------------------------------------------------------------------------
# Forecasts
# --------------------------------------------------------------------------------------


def get_forecast(level: str, entity_code: str) -> pd.DataFrame:
    return db.query(
        "SELECT DS, HORIZON_MONTH, YHAT, YHAT_LOWER, YHAT_UPPER, MODEL, CALIBRATED, "
        "INTERVAL_LEVEL, TRAINED_THROUGH, GENERATED_AT, ENTITY_NAME "
        "FROM forecasts WHERE LEVEL = ? AND ENTITY_CODE = ? ORDER BY HORIZON_MONTH",
        [_check_level(level), normalise_code(entity_code)],
    )


def get_metrics(level: str, entity_code: str) -> dict | None:
    return db.query_one(
        "SELECT MODEL, N_FORECASTS, MAE, RMSE, MAPE, MASE, COVERAGE, COVERAGE_NATIVE, "
        "CALIBRATED, QUARANTINED, QUARANTINE_REASON FROM forecast_metrics "
        "WHERE LEVEL = ? AND ENTITY_CODE = ?",
        [_check_level(level), normalise_code(entity_code)],
    )


def model_summary() -> pd.DataFrame:
    return db.query(
        """
        SELECT LEVEL,
               MODEL,
               COUNT(*)                                   AS ENTITIES,
               MEDIAN(MASE)                               AS MEDIAN_MASE,
               AVG(COVERAGE)                              AS MEAN_COVERAGE,
               AVG(COVERAGE_NATIVE)                       AS MEAN_COVERAGE_NATIVE,
               SUM(CASE WHEN NOT CALIBRATED THEN 1 ELSE 0 END) AS UNCALIBRATED,
               SUM(CASE WHEN QUARANTINED THEN 1 ELSE 0 END)    AS QUARANTINED
        FROM forecast_metrics
        GROUP BY LEVEL, MODEL
        ORDER BY LEVEL, MODEL
        """
    )
