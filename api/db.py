"""Read-only access to the compiled serving database.

One connection is opened at import and shared. ``pipeline/loader.py`` connects per call,
which is fine for Streamlit but wasteful once it is per HTTP request. DuckDB read-only
connections are safe to share across threads.

Every query here is parameterised. ``pipeline.loader.query()`` takes raw SQL and must
never be reachable from a request handler — that is why this module exists rather than
reusing it.
"""

from __future__ import annotations

import threading
from functools import lru_cache

import duckdb
import pandas as pd

from api.config import SERVING_DB_PATH

_lock = threading.Lock()
_connection: duckdb.DuckDBPyConnection | None = None


def connection() -> duckdb.DuckDBPyConnection:
    global _connection
    if _connection is None:
        with _lock:
            if _connection is None:
                if not SERVING_DB_PATH.exists():
                    raise RuntimeError(
                        f"Serving database missing at {SERVING_DB_PATH}. "
                        "Run scripts/build_serving_db.py."
                    )
                _connection = duckdb.connect(str(SERVING_DB_PATH), read_only=True)
    return _connection


def query(sql: str, params: list | tuple = ()) -> pd.DataFrame:
    """Run a parameterised query. ``sql`` is always a literal in this package."""

    # cursor() gives each request its own result stream over the shared connection.
    return connection().cursor().execute(sql, list(params)).fetch_df()


def query_one(sql: str, params: list | tuple = ()) -> dict | None:
    frame = query(sql, params)
    return None if frame.empty else frame.iloc[0].to_dict()


@lru_cache(maxsize=1)
def meta() -> dict:
    """The vintage row. Cached — it is one row that never changes while the app runs."""

    row = query_one("SELECT * FROM meta")
    if row is None:
        raise RuntimeError("Serving database has no meta row; rebuild it.")
    return row


@lru_cache(maxsize=1)
def run_id() -> str:
    return str(meta()["RUN_ID"])
