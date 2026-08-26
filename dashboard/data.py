"""Cached data loaders and lightweight dashboard transformations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

try:
    import streamlit as st
except ModuleNotFoundError:  # pragma: no cover - test environments may omit Streamlit.
    class _StreamlitShim:
        @staticmethod
        def cache_data(*_args: object, **_kwargs: object):
            def decorator(func):
                return func

            return decorator

    st = _StreamlitShim()

from science.backtesting import (
    Forecaster,
    calibrated_forecast,
    linear_forecast,
    naive_forecast,
    seasonal_naive_forecast,
)
from science.forecasting import Prophet, forecast_list_size
from science.stat_forecasting import (
    AutoETS,
    ETSModel,
    SARIMAX,
    arima_forecast,
    autoets_forecast,
    holt_winters_forecast,
    sarima_forecast,
)

# Drill-down forecast models (DEC-009/DEC-010/DEC-011). AutoETS is the default: it
# wins the practice-level backtest, which is the level this drill-down serves
# (docs/FORECAST_VALIDATION.md §7). Prophet, the former default, ranks 5th here and
# loses to the naive baseline on individual practices. The other statistical models
# and the harness baselines are offered for comparison. Keys are UI labels.
FORECAST_MODELS: dict[str, Forecaster] = {
    "AutoETS (recommended)": autoets_forecast,
    "Holt-Winters": holt_winters_forecast,
    "Prophet": forecast_list_size,
    "SARIMA": sarima_forecast,
    "ARIMA": arima_forecast,
    "Linear trend": linear_forecast,
    "Seasonal naive": seasonal_naive_forecast,
    "Naive (last value)": naive_forecast,
}

# Selected when the caller does not name a model. Kept as a constant so the default
# lives in one place rather than being implied by dict ordering.
DEFAULT_FORECAST_MODEL = "AutoETS (recommended)"

# The default for national, regional and ICB series. DEC-011 found the ranking reverses
# with aggregation level: AutoETS wins practice and PCN series, Holt-Winters wins the
# aggregates, so one dashboard-wide default would be wrong at one end or the other.
# `scripts/build_forecast_cache.py` encodes the same split as DEFAULT_PRACTICE_MODEL /
# DEFAULT_AGGREGATE_MODEL; the two must agree or the dashboard and the API will serve
# different numbers for the same series.
AGGREGATE_FORECAST_MODEL = "Holt-Winters"

# The library symbol each optional model needs; None means not installed and the
# label is hidden so it never silently serves the linear fallback (DEC-009 guard).
_MODEL_REQUIREMENTS: dict[str, object] = {
    "AutoETS (recommended)": AutoETS,
    "Holt-Winters": ETSModel,
    "Prophet": Prophet,
    "SARIMA": SARIMAX,
    "ARIMA": SARIMAX,
}


def forecast_model_options() -> list[str]:
    """UI labels for the forecast model selector, hiding models whose library is missing."""

    return [
        label
        for label in FORECAST_MODELS
        if _MODEL_REQUIREMENTS.get(label, True) is not None
    ]


def _available_or_fallback(preferred: str) -> str:
    """``preferred`` if its library is installed, else the first model that is.

    Falls back rather than returning a model whose library is absent, because every
    forecaster degrades to a linear trend when it cannot import — which would serve a
    straight line under a real model's name (the DEC-009 guard).
    """

    options = forecast_model_options()
    if preferred in options:
        return preferred
    return options[0] if options else preferred


def default_forecast_model() -> str:
    """The model used for practice-level series when no model is named."""

    return _available_or_fallback(DEFAULT_FORECAST_MODEL)


def default_aggregate_forecast_model() -> str:
    """The model used for national, regional and ICB series when no model is named."""

    return _available_or_fallback(AGGREGATE_FORECAST_MODEL)

REPO_ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
CACHE_DIR = PROCESSED_DIR / "dashboard"

LIST_SIZE_PATH = PROCESSED_DIR / "list_size.parquet"

LATEST_SNAPSHOT_PATH = CACHE_DIR / "latest_snapshot.parquet"
LIST_SIZE_GEO_PATH = CACHE_DIR / "list_size_geo.parquet"
MARKET_SHARE_PATH = CACHE_DIR / "market_share.parquet"
MIGRATIONS_PATH = CACHE_DIR / "migrations.parquet"
ANOMALIES_PATH = CACHE_DIR / "anomalies.parquet"
DEPRIVATION_LATEST_PATH = CACHE_DIR / "deprivation_latest.parquet"
CLUSTER_K_PATH = CACHE_DIR / "cluster_k.parquet"
INEQUALITY_PATH = CACHE_DIR / "inequality.parquet"
CORRELATIONS_PATH = CACHE_DIR / "correlations.parquet"


@dataclass(frozen=True)
class PageFilters:
    """Subset of sidebar filter state used by data helpers."""

    date_from: object
    date_to: object
    regions: tuple[str, ...] = ()
    icbs: tuple[str, ...] = ()


def _empty() -> pd.DataFrame:
    return pd.DataFrame()


def _read_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        return _empty()
    return pd.read_parquet(path)


@st.cache_data(ttl=3600)
def load_latest_snapshot() -> pd.DataFrame:
    """Load the cached latest practice snapshot."""

    return _read_parquet(LATEST_SNAPSHOT_PATH)


@st.cache_data(ttl=3600)
def load_list_size_geo() -> pd.DataFrame:
    """Load monthly list-size totals grouped by region and ICB."""

    return _read_parquet(LIST_SIZE_GEO_PATH)


@st.cache_data(ttl=3600)
def load_market_share() -> pd.DataFrame:
    """Load monthly clinical-system counts grouped by geography."""

    return _read_parquet(MARKET_SHARE_PATH)


@st.cache_data(ttl=3600)
def load_migrations() -> pd.DataFrame:
    """Load cached supplier migration signals."""

    return _read_parquet(MIGRATIONS_PATH)


@st.cache_data(ttl=3600)
def load_anomalies() -> pd.DataFrame:
    """Load cached anomaly rows."""

    return _read_parquet(ANOMALIES_PATH)


@st.cache_data(ttl=3600)
def load_deprivation_latest() -> pd.DataFrame:
    """Load the latest deprivation and cluster cache."""

    return _read_parquet(DEPRIVATION_LATEST_PATH)


@st.cache_data(ttl=3600)
def load_cluster_k() -> pd.DataFrame:
    """Load precomputed cluster assignments for k = 2..10 (DEC-008)."""

    return _read_parquet(CLUSTER_K_PATH)


@st.cache_data(ttl=3600)
def load_inequality() -> pd.DataFrame:
    """Load cached inequality time series."""

    return _read_parquet(INEQUALITY_PATH)


@st.cache_data(ttl=3600)
def load_correlations() -> pd.DataFrame:
    """Load latest size-vs-IMD correlations by region."""

    return _read_parquet(CORRELATIONS_PATH)


@st.cache_data(ttl=3600)
def load_list_size() -> pd.DataFrame:
    """Load raw list-size history for practice drill-downs."""

    return _read_parquet(LIST_SIZE_PATH)


def cache_health() -> tuple[bool, list[str]]:
    """Return whether all dashboard cache files exist and which are missing."""

    expected = [
        LATEST_SNAPSHOT_PATH,
        LIST_SIZE_GEO_PATH,
        MARKET_SHARE_PATH,
        MIGRATIONS_PATH,
        ANOMALIES_PATH,
        DEPRIVATION_LATEST_PATH,
        CLUSTER_K_PATH,
        INEQUALITY_PATH,
        CORRELATIONS_PATH,
    ]
    missing = [str(path.relative_to(REPO_ROOT)) for path in expected if not path.exists()]
    return not missing, missing


def as_page_filters(filter_state: object) -> PageFilters:
    """Convert the sidebar FilterState into an immutable cache key."""

    return PageFilters(
        date_from=getattr(filter_state, "date_from"),
        date_to=getattr(filter_state, "date_to"),
        regions=tuple(getattr(filter_state, "regions", []) or []),
        icbs=tuple(getattr(filter_state, "icbs", []) or []),
    )


def filter_frame(
    frame: pd.DataFrame,
    filters: PageFilters,
    *,
    date_column: str = "SNAPSHOT_DATE",
) -> pd.DataFrame:
    """Apply common date, region, and ICB filters to a cached frame."""

    if frame.empty:
        return frame.copy()

    out = frame.copy()
    if date_column in out.columns:
        dates = pd.to_datetime(out[date_column], errors="coerce")
        start = pd.Timestamp(filters.date_from)
        end = pd.Timestamp(filters.date_to)
        out = out.loc[(dates >= start) & (dates <= end)].copy()

    if filters.regions and "REGION_NAME" in out.columns:
        out = out.loc[out["REGION_NAME"].isin(filters.regions)].copy()

    if filters.icbs and "ICB_NAME" in out.columns:
        out = out.loc[out["ICB_NAME"].isin(filters.icbs)].copy()

    return out


def aggregate_list_size(frame: pd.DataFrame) -> pd.DataFrame:
    """Aggregate grouped list-size rows into a monthly total."""

    if frame.empty:
        return pd.DataFrame(columns=["SNAPSHOT_DATE", "PATIENT_COUNT", "PRACTICE_COUNT"])

    return (
        frame.groupby("SNAPSHOT_DATE", as_index=False)
        .agg(PATIENT_COUNT=("PATIENT_COUNT", "sum"), PRACTICE_COUNT=("PRACTICE_COUNT", "sum"))
        .sort_values("SNAPSHOT_DATE")
        .reset_index(drop=True)
    )


def aggregate_market_share(frame: pd.DataFrame) -> pd.DataFrame:
    """Aggregate market-share counts after filters and recompute shares."""

    if frame.empty:
        return pd.DataFrame(
            columns=[
                "SNAPSHOT_DATE",
                "CLINICAL_SYSTEM",
                "PRACTICE_COUNT",
                "PATIENT_COUNT",
                "PRACTICE_SHARE",
                "PATIENT_SHARE",
            ]
        )

    grouped = (
        frame.groupby(["SNAPSHOT_DATE", "CLINICAL_SYSTEM"], as_index=False)
        .agg(PRACTICE_COUNT=("PRACTICE_COUNT", "sum"), PATIENT_COUNT=("PATIENT_COUNT", "sum"))
        .sort_values(["SNAPSHOT_DATE", "CLINICAL_SYSTEM"])
        .reset_index(drop=True)
    )
    totals = grouped.groupby("SNAPSHOT_DATE")[["PRACTICE_COUNT", "PATIENT_COUNT"]].transform("sum")
    grouped["PRACTICE_SHARE"] = grouped["PRACTICE_COUNT"] / totals["PRACTICE_COUNT"].replace(0, pd.NA)
    grouped["PATIENT_SHARE"] = grouped["PATIENT_COUNT"] / totals["PATIENT_COUNT"].replace(0, pd.NA)
    return grouped


def latest_market_heatmap(frame: pd.DataFrame) -> pd.DataFrame:
    """Return latest regional clinical-system practice share rows."""

    if frame.empty:
        return pd.DataFrame(columns=["REGION_NAME", "CLINICAL_SYSTEM", "PRACTICE_SHARE"])

    latest_date = pd.to_datetime(frame["SNAPSHOT_DATE"]).max()
    latest = frame.loc[pd.to_datetime(frame["SNAPSHOT_DATE"]) == latest_date].copy()
    grouped = (
        latest.groupby(["REGION_NAME", "CLINICAL_SYSTEM"], as_index=False)
        .agg(PRACTICE_COUNT=("PRACTICE_COUNT", "sum"))
        .sort_values(["REGION_NAME", "CLINICAL_SYSTEM"])
    )
    totals = grouped.groupby("REGION_NAME")["PRACTICE_COUNT"].transform("sum")
    grouped["PRACTICE_SHARE"] = grouped["PRACTICE_COUNT"] / totals.replace(0, pd.NA)
    return grouped


def practice_options(latest: pd.DataFrame, filters: PageFilters, query: str) -> list[str]:
    """Return formatted practice options matching a user query."""

    scoped = filter_frame(latest, filters, date_column="SNAPSHOT_DATE")
    if scoped.empty or not query.strip():
        return []

    text = query.strip().casefold()
    names = scoped["PRACTICE_NAME"].fillna("").astype(str)
    codes = scoped["CODE"].fillna("").astype(str)
    mask = names.str.casefold().str.contains(text, regex=False) | codes.str.casefold().str.contains(text, regex=False)
    matches = scoped.loc[mask, ["CODE", "PRACTICE_NAME", "REGION_NAME"]].drop_duplicates("CODE").head(50)
    return [
        f"{row.PRACTICE_NAME or 'Unknown practice'} ({row.CODE}) - {row.REGION_NAME or 'Unknown region'}"
        for row in matches.itertuples()
    ]


def code_from_option(option: str) -> str | None:
    """Extract an ODS practice code from a formatted practice option."""

    if "(" not in option or ")" not in option:
        return None
    return option.split("(", 1)[1].split(")", 1)[0].strip() or None


@st.cache_data(ttl=3600)
def practice_history_with_forecast(
    practice_code: str,
    periods: int = 12,
    model: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, bool]:
    """Return one practice history, its forecast, and whether the band is calibrated.

    The interval is calibrated from the practice's own rolling-origin backtest when
    the history is long enough (DEC-007/DEC-009); ``calibrated=False`` means the
    model's native band survived and should be presented as indicative only.
    """

    list_size = load_list_size()
    if list_size.empty:
        return _empty(), _empty(), False

    history = list_size.loc[list_size["CODE"] == practice_code, ["SNAPSHOT_DATE", "CODE", "NUMBER_OF_PATIENTS"]].copy()
    history = history.sort_values("SNAPSHOT_DATE").reset_index(drop=True)
    if history.empty:
        return history, _empty(), False

    resolved = model or default_forecast_model()
    forecaster = FORECAST_MODELS.get(resolved, autoets_forecast)
    forecast, calibrated = calibrated_forecast(history, forecaster, periods=periods)
    return history, forecast, calibrated


@st.cache_data(ttl=3600)
def aggregate_history_with_forecast(
    monthly: pd.DataFrame,
    periods: int = 12,
    model: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, bool]:
    """Forecast an aggregated monthly total, and say whether the band is calibrated.

    ``monthly`` must be the output of ``aggregate_list_size`` — one summed row per
    month. An unaggregated frame would be silently wrong rather than an error:
    ``science.forecasting._prepare_series`` collapses duplicate months with
    ``groupby("ds").mean()``, so a multi-practice frame yields a mean per practice, an
    order-of-magnitude error that still looks like a plausible number (DEC-012 guard 2).
    The duplicate-month check below turns that into a loud failure.

    Defaults to Holt-Winters, which wins the aggregate backtests, rather than the
    practice-level AutoETS default (DEC-011).
    """

    if monthly.empty:
        return _empty(), _empty(), False

    history = (
        monthly[["SNAPSHOT_DATE", "PATIENT_COUNT"]]
        .rename(columns={"PATIENT_COUNT": "NUMBER_OF_PATIENTS"})
        .sort_values("SNAPSHOT_DATE")
        .reset_index(drop=True)
    )
    if history["SNAPSHOT_DATE"].duplicated().any():
        raise ValueError(
            "aggregate_history_with_forecast expects one summed row per month; "
            "pass the output of aggregate_list_size, not a per-practice frame."
        )

    resolved = model or default_aggregate_forecast_model()
    forecaster = FORECAST_MODELS.get(resolved, holt_winters_forecast)
    forecast, calibrated = calibrated_forecast(history, forecaster, periods=periods)
    return history, forecast, calibrated


def format_int(value: object) -> str:
    """Format a numeric value for compact dashboard text."""

    try:
        return f"{int(round(float(value))):,}"
    except (TypeError, ValueError):
        return "-"


def format_pct(value: object) -> str:
    """Format a share as a percentage."""

    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "-"


__all__ = [
    "AGGREGATE_FORECAST_MODEL",
    "DEFAULT_FORECAST_MODEL",
    "FORECAST_MODELS",
    "PageFilters",
    "default_aggregate_forecast_model",
    "default_forecast_model",
    "forecast_model_options",
    "aggregate_history_with_forecast",
    "aggregate_list_size",
    "aggregate_market_share",
    "as_page_filters",
    "cache_health",
    "code_from_option",
    "filter_frame",
    "format_int",
    "format_pct",
    "latest_market_heatmap",
    "load_anomalies",
    "load_cluster_k",
    "load_correlations",
    "load_deprivation_latest",
    "load_inequality",
    "load_latest_snapshot",
    "load_list_size_geo",
    "load_market_share",
    "load_migrations",
    "practice_history_with_forecast",
    "practice_options",
]
