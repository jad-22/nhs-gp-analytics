"""List Size Trends - monthly patient registration time series."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

REPO_ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / "dashboard").is_dir())
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dashboard.components.charts import patient_total_line, practice_forecast_chart, regional_patient_lines
from dashboard.components.filters import render_sidebar
from dashboard.components.theme import BORDER, CORAL, FONT_MONO, MUTED, inject_global_css
from dashboard.data import (
    aggregate_list_size,
    as_page_filters,
    cache_health,
    code_from_option,
    filter_frame,
    forecast_model_options,
    format_int,
    load_anomalies,
    load_latest_snapshot,
    load_list_size_geo,
    practice_history_with_forecast,
    practice_options,
)

st.set_page_config(page_title="List Size Trends - NHS GP Analytics", layout="wide", initial_sidebar_state="expanded")
inject_global_css()
filters = as_page_filters(render_sidebar())

healthy, missing = cache_health()
if not healthy:
    st.warning(f"Dashboard cache is incomplete. Run `python scripts/build_dashboard_cache.py`. Missing: {', '.join(missing)}")

st.markdown("<h1>List Size Trends</h1>", unsafe_allow_html=True)
st.markdown(
    f"""<p style="color:{MUTED}; max-width:72ch; line-height:1.65; margin-bottom:1.5rem;">
        Monthly GP practice registration counts. Start with the national shape,
        then narrow by region or ICB and drill into individual practice histories.
    </p>""",
    unsafe_allow_html=True,
)

geo = filter_frame(load_list_size_geo(), filters)
monthly = aggregate_list_size(geo)

if not monthly.empty:
    latest = monthly.sort_values("SNAPSHOT_DATE").tail(1).iloc[0]
    earliest = monthly.sort_values("SNAPSHOT_DATE").head(1).iloc[0]
    change = latest["PATIENT_COUNT"] - earliest["PATIENT_COUNT"]
    st.markdown(
        f"""<div style="border:1px solid {BORDER}; border-radius:4px; padding:0.85rem 1rem; margin-bottom:1.25rem;">
            <span style="font-family:{FONT_MONO}; color:{CORAL}; font-size:1rem;">{format_int(latest['PATIENT_COUNT'])}</span>
            <span style="color:{MUTED}; margin-left:0.4rem;">registered patients in scope</span>
            <span style="color:{MUTED}; margin:0 0.7rem;">/</span>
            <span style="font-family:{FONT_MONO}; color:{CORAL};">{format_int(latest['PRACTICE_COUNT'])}</span>
            <span style="color:{MUTED}; margin-left:0.4rem;">practices</span>
            <span style="color:{MUTED}; margin:0 0.7rem;">/</span>
            <span style="font-family:{FONT_MONO}; color:{CORAL};">{format_int(change)}</span>
            <span style="color:{MUTED}; margin-left:0.4rem;">patient change since first selected month</span>
        </div>""",
        unsafe_allow_html=True,
    )

st.plotly_chart(patient_total_line(monthly, "Registered patients over time"), use_container_width=True)
st.plotly_chart(regional_patient_lines(geo, "Regional breakdown"), use_container_width=True)

st.markdown("---")
st.markdown("<h2>Practice drill-down</h2>", unsafe_allow_html=True)
st.markdown(
    f"""<p style="color:{MUTED}; max-width:72ch;">
        Search by practice name or ODS code. Forecasts are computed on demand and cached
        per practice and model. AutoETS is the default: it won the practice-level
        backtest across 999 practices (DEC-011), which is the level this drill-down
        serves. Prophet, Holt-Winters, SARIMA, ARIMA and the harness baselines are
        available for comparison. Where the history is long enough, the 80% band is
        calibrated from the practice's own backtest errors — which delivers about 74%
        coverage out of sample, not the nominal 80%.
    </p>""",
    unsafe_allow_html=True,
)

latest_snapshot = load_latest_snapshot()
query = st.text_input("Practice search", placeholder="Type a practice name or ODS code")
options = practice_options(latest_snapshot, filters, query)
if options:
    selected = st.selectbox("Matching practice", options=options)
    code = code_from_option(selected)
else:
    selected = ""
    code = None
    if query:
        st.info("No matching practices in the selected filters.")

if code:
    model = st.selectbox(
        "Forecast model",
        options=forecast_model_options(),
        help="AutoETS ranked best at practice level in rolling-origin backtesting (median MASE 0.525 across 999 practices; see docs/FORECAST_VALIDATION.md §7). Holt-Winters wins on aggregated series, and Prophet ranks 5th here — the ranking depends on aggregation level.",
    )
    history, forecast, calibrated = practice_history_with_forecast(code, model=model)
    st.plotly_chart(practice_forecast_chart(history, forecast, f"{code} list size forecast - {model}"), use_container_width=True)
    if calibrated:
        st.caption("80% band calibrated from this practice's rolling-origin backtest errors (DEC-007).")
    elif not forecast.empty:
        st.caption("Native model band - history too short to calibrate (needs ~4 years); treat as indicative.")
else:
    st.plotly_chart(practice_forecast_chart(pd.DataFrame(), pd.DataFrame(), "Practice list size forecast"), use_container_width=True)

st.markdown("---")
st.markdown("<h2>Anomaly signals</h2>", unsafe_allow_html=True)
anomalies = filter_frame(load_anomalies(), filters)
if anomalies.empty:
    st.info("No cached anomalies for the selected filters.")
else:
    anomaly_types = sorted(anomalies["ANOMALY_TYPE"].dropna().unique().tolist())
    selected_types = st.multiselect("Anomaly type", options=anomaly_types, default=anomaly_types)
    if selected_types:
        anomalies = anomalies.loc[anomalies["ANOMALY_TYPE"].isin(selected_types)].copy()
    display = anomalies.head(250).copy()
    display["SNAPSHOT_DATE"] = pd.to_datetime(display["SNAPSHOT_DATE"]).dt.strftime("%b %Y")
    display["MOM_CHANGE_PCT"] = pd.to_numeric(display["MOM_CHANGE_PCT"], errors="coerce").map(lambda value: f"{value:.1%}")
    display["MOM_CHANGE_ABS"] = pd.to_numeric(display["MOM_CHANGE_ABS"], errors="coerce").map(lambda value: f"{value:,.0f}")
    st.dataframe(
        display[
            [
                "SNAPSHOT_DATE",
                "CODE",
                "PRACTICE_NAME",
                "REGION_NAME",
                "NUMBER_OF_PATIENTS",
                "MOM_CHANGE_ABS",
                "MOM_CHANGE_PCT",
                "ANOMALY_TYPE",
            ]
        ],
        width="stretch",
        hide_index=True,
    )
