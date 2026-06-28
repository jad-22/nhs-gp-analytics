"""Parquet persistence and DuckDB query helpers."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from .config import LIST_SIZE_PARQUET_PATH, MAPPING_PARQUET_PATH, ensure_data_directories


def _read_parquet_if_exists(path: Path) -> pd.DataFrame:
    if path.exists():
        return pd.read_parquet(path)
    return pd.DataFrame()


def _coerce_schema(existing: pd.DataFrame, incoming: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if existing.empty:
        return existing.copy(), incoming.copy()

    existing_columns = list(existing.columns)
    all_columns = existing_columns + [column for column in incoming.columns if column not in existing_columns]
    existing_out = existing.reindex(columns=all_columns)
    incoming_out = incoming.reindex(columns=all_columns)
    return existing_out, incoming_out


def _upsert_dataframe(path: Path, incoming: pd.DataFrame, key_columns: list[str]) -> pd.DataFrame:
    ensure_data_directories()

    if incoming.empty:
        existing = _read_parquet_if_exists(path)
        if not existing.empty:
            return existing
        return incoming

    existing = _read_parquet_if_exists(path)
    existing, incoming_aligned = _coerce_schema(existing, incoming)

    combined = pd.concat([existing, incoming_aligned], ignore_index=True)
    combined = combined.drop_duplicates(subset=key_columns, keep="last")

    sort_columns = [column for column in ["SNAPSHOT_DATE", *key_columns] if column in combined.columns]
    if sort_columns:
        combined = combined.sort_values(sort_columns).reset_index(drop=True)

    path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(path, index=False)
    return combined


def upsert_list_size(df: pd.DataFrame) -> pd.DataFrame:
    """Upsert list-size monthly data by SNAPSHOT_DATE and CODE."""

    return _upsert_dataframe(LIST_SIZE_PARQUET_PATH, df, key_columns=["SNAPSHOT_DATE", "CODE"])


def upsert_mapping(df: pd.DataFrame) -> pd.DataFrame:
    """Upsert mapping monthly data by SNAPSHOT_DATE and PRACTICE_CODE."""

    return _upsert_dataframe(
        MAPPING_PARQUET_PATH,
        df,
        key_columns=["SNAPSHOT_DATE", "PRACTICE_CODE"],
    )


def upsert_month(list_size_df: pd.DataFrame, mapping_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Persist one month of list-size and mapping data."""

    return upsert_list_size(list_size_df), upsert_mapping(mapping_df)


def _connect() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(database=":memory:")

    if LIST_SIZE_PARQUET_PATH.exists():
        list_path = str(LIST_SIZE_PARQUET_PATH).replace("'", "''")
        connection.execute(f"CREATE VIEW list_size AS SELECT * FROM read_parquet('{list_path}')")
    else:
        connection.register(
            "list_size_empty",
            pd.DataFrame(columns=["SNAPSHOT_DATE", "CODE", "NUMBER_OF_PATIENTS", "DATA_SOURCE"]),
        )
        connection.execute("CREATE VIEW list_size AS SELECT * FROM list_size_empty")

    if MAPPING_PARQUET_PATH.exists():
        mapping_path = str(MAPPING_PARQUET_PATH).replace("'", "''")
        connection.execute(f"CREATE VIEW mapping AS SELECT * FROM read_parquet('{mapping_path}')")
    else:
        connection.register(
            "mapping_empty",
            pd.DataFrame(columns=["SNAPSHOT_DATE", "PRACTICE_CODE", "CLINICAL_SYSTEM", "COMM_REGION_NAME"]),
        )
        connection.execute("CREATE VIEW mapping AS SELECT * FROM mapping_empty")

    return connection


def query(sql: str) -> pd.DataFrame:
    """Run a SQL query against list_size and mapping parquet views."""

    with _connect() as connection:
        return connection.execute(sql).fetchdf()


def get_list_size_ts(practice_code: str | None = None) -> pd.DataFrame:
    """Return list-size time series for all practices or one practice code."""

    base_sql = "SELECT SNAPSHOT_DATE, CODE, NUMBER_OF_PATIENTS, DATA_SOURCE FROM list_size"
    with _connect() as connection:
        if practice_code:
            return connection.execute(
                base_sql + " WHERE CODE = ? ORDER BY SNAPSHOT_DATE, CODE",
                [practice_code],
            ).fetchdf()
        return connection.execute(base_sql + " ORDER BY SNAPSHOT_DATE, CODE").fetchdf()


def get_market_share_ts(region: str | None = None) -> pd.DataFrame:
    """Return monthly market share by clinical system."""

    region_clause = "AND UPPER(COALESCE(m.COMM_REGION_NAME, '')) = UPPER(?)" if region else ""
    sql = f"""
    WITH joined AS (
        SELECT
            l.SNAPSHOT_DATE,
            COALESCE(m.CLINICAL_SYSTEM, 'Others') AS CLINICAL_SYSTEM,
            COALESCE(m.COMM_REGION_NAME, '') AS COMM_REGION_NAME,
            l.CODE,
            l.NUMBER_OF_PATIENTS
        FROM list_size l
        LEFT JOIN mapping m
            ON l.SNAPSHOT_DATE = m.SNAPSHOT_DATE
            AND l.CODE = m.PRACTICE_CODE
        WHERE 1 = 1
        {region_clause}
    ),
    by_system AS (
        SELECT
            SNAPSHOT_DATE,
            CLINICAL_SYSTEM,
            COUNT(DISTINCT CODE) AS PRACTICE_COUNT,
            SUM(NUMBER_OF_PATIENTS) AS PATIENT_COUNT
        FROM joined
        GROUP BY SNAPSHOT_DATE, CLINICAL_SYSTEM
    ),
    totals AS (
        SELECT
            SNAPSHOT_DATE,
            SUM(PRACTICE_COUNT) AS TOTAL_PRACTICE_COUNT,
            SUM(PATIENT_COUNT) AS TOTAL_PATIENT_COUNT
        FROM by_system
        GROUP BY SNAPSHOT_DATE
    )
    SELECT
        b.SNAPSHOT_DATE,
        b.CLINICAL_SYSTEM,
        b.PRACTICE_COUNT,
        b.PATIENT_COUNT,
        CASE WHEN t.TOTAL_PRACTICE_COUNT = 0 THEN NULL ELSE b.PRACTICE_COUNT::DOUBLE / t.TOTAL_PRACTICE_COUNT END AS PRACTICE_SHARE,
        CASE WHEN t.TOTAL_PATIENT_COUNT = 0 THEN NULL ELSE b.PATIENT_COUNT::DOUBLE / t.TOTAL_PATIENT_COUNT END AS PATIENT_SHARE
    FROM by_system b
    JOIN totals t USING (SNAPSHOT_DATE)
    ORDER BY b.SNAPSHOT_DATE, b.CLINICAL_SYSTEM
    """

    with _connect() as connection:
        if region:
            return connection.execute(sql, [region]).fetchdf()
        return connection.execute(sql).fetchdf()


def get_latest_snapshot() -> pd.DataFrame:
    """Return latest snapshot by joining list_size and mapping tables."""

    mapping_columns_df = _read_parquet_if_exists(MAPPING_PARQUET_PATH)
    optional_mapping_columns = [
        "PRACTICE_NAME",
        "PCN_CODE",
        "PCN_NAME",
        "ICB_CODE",
        "ICB_NAME",
        "COMM_REGION_CODE",
        "COMM_REGION_NAME",
        "SUPPLIER_NAME",
        "CLINICAL_SYSTEM",
        "POSTCODE",
        "IMD_SCORE",
        "IMD_DECILE",
        "LATITUDE",
        "LONGITUDE",
    ]
    available = set(mapping_columns_df.columns)
    mapping_selects = [
        f"m.{column}" if column in available else f"NULL AS {column}"
        for column in optional_mapping_columns
    ]

    sql = f"""
    WITH latest AS (
        SELECT MAX(SNAPSHOT_DATE) AS SNAPSHOT_DATE
        FROM list_size
    )
    SELECT
        l.SNAPSHOT_DATE,
        l.CODE,
        l.NUMBER_OF_PATIENTS,
        l.DATA_SOURCE,
        m.PRACTICE_CODE,
        {", ".join(mapping_selects)}
    FROM list_size l
    JOIN latest x ON l.SNAPSHOT_DATE = x.SNAPSHOT_DATE
    LEFT JOIN mapping m
        ON l.SNAPSHOT_DATE = m.SNAPSHOT_DATE
        AND l.CODE = m.PRACTICE_CODE
    ORDER BY l.CODE
    """
    return query(sql)


__all__ = [
    "get_latest_snapshot",
    "get_list_size_ts",
    "get_market_share_ts",
    "query",
    "upsert_list_size",
    "upsert_mapping",
    "upsert_month",
]