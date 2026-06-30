"""Clinical System Market Share - EMIS vs SystmOne over time."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

REPO_ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / "dashboard").is_dir())
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dashboard.components.charts import market_heatmap, market_share_area, system_size_distribution
from dashboard.components.filters import render_sidebar
from dashboard.components.theme import BORDER, CORAL, FONT_MONO, MUTED, inject_global_css
from dashboard.data import (
    aggregate_market_share,
    as_page_filters,
    cache_health,
    filter_frame,
    format_int,
    format_pct,
    latest_market_heatmap,
    load_latest_snapshot,
    load_market_share,
    load_migrations,
)

st.set_page_config(page_title="Market Share - NHS GP Analytics", layout="wide", initial_sidebar_state="expanded")
inject_global_css()
filters = as_page_filters(render_sidebar())

healthy, missing = cache_health()
if not healthy:
    st.warning(f"Dashboard cache is incomplete. Run `python scripts/build_dashboard_cache.py`. Missing: {', '.join(missing)}")

st.markdown("<h1>Clinical System Market Share</h1>", unsafe_allow_html=True)
st.markdown(
    f"""<p style="color:{MUTED}; max-width:72ch; line-height:1.65; margin-bottom:1.5rem;">
        EMIS Web, SystmOne, and other supplier systems viewed by practice count and
        by registered patient count. Migration rows flag practices where supplier
        attribution changed between monthly snapshots.
    </p>""",
    unsafe_allow_html=True,
)

market = filter_frame(load_market_share(), filters)
share = aggregate_market_share(market)
latest_snapshot = filter_frame(load_latest_snapshot(), filters)

if not share.empty:
    latest_date = pd.to_datetime(share["SNAPSHOT_DATE"]).max()
    latest = share.loc[pd.to_datetime(share["SNAPSHOT_DATE"]) == latest_date].copy()
    leading = latest.sort_values("PATIENT_SHARE", ascending=False).head(1)
    if not leading.empty:
        row = leading.iloc[0]
        st.markdown(
            f"""<div style="border:1px solid {BORDER}; border-radius:4px; padding:0.85rem 1rem; margin-bottom:1.25rem;">
                <span style="font-family:{FONT_MONO}; color:{CORAL}; font-size:1rem;">{row['CLINICAL_SYSTEM']}</span>
                <span style="color:{MUTED}; margin-left:0.4rem;">largest by patient coverage</span>
                <span style="color:{MUTED}; margin:0 0.7rem;">/</span>
                <span style="font-family:{FONT_MONO}; color:{CORAL};">{format_pct(row['PATIENT_SHARE'])}</span>
                <span style="color:{MUTED}; margin-left:0.4rem;">patient share</span>
                <span style="color:{MUTED}; margin:0 0.7rem;">/</span>
                <span style="font-family:{FONT_MONO}; color:{CORAL};">{format_int(row['PRACTICE_COUNT'])}</span>
                <span style="color:{MUTED}; margin-left:0.4rem;">practices</span>
            </div>""",
            unsafe_allow_html=True,
        )

left, right = st.columns(2, gap="large")
with left:
    st.plotly_chart(market_share_area(share, "PRACTICE_SHARE", "Share of practices"), use_container_width=True)
with right:
    st.plotly_chart(market_share_area(share, "PATIENT_SHARE", "Share of registered patients"), use_container_width=True)

left, right = st.columns(2, gap="large")
with left:
    st.plotly_chart(market_heatmap(latest_market_heatmap(market), "Latest regional practice share"), use_container_width=True)
with right:
    st.plotly_chart(system_size_distribution(latest_snapshot, "Current practice size distribution"), use_container_width=True)

st.markdown("---")
st.markdown("<h2>Migration signals</h2>", unsafe_allow_html=True)
migrations = filter_frame(load_migrations(), filters, date_column="CHANGE_DATE")
if migrations.empty:
    st.info("No supplier migrations for the selected filters.")
else:
    display = migrations.sort_values("CHANGE_DATE", ascending=False).head(250).copy()
    display["CHANGE_DATE"] = pd.to_datetime(display["CHANGE_DATE"]).dt.strftime("%b %Y")
    st.dataframe(
        display[
            [
                "CHANGE_DATE",
                "CODE",
                "PRACTICE_NAME",
                "REGION_NAME",
                "PREVIOUS_SUPPLIER_NAME",
                "NEW_SUPPLIER_NAME",
                "PREVIOUS_CLINICAL_SYSTEM",
                "NEW_CLINICAL_SYSTEM",
            ]
        ],
        width="stretch",
        hide_index=True,
    )
