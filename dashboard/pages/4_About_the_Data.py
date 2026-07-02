"""About the data page: sources, caveats, and interpretation guidance."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

REPO_ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / "dashboard").is_dir())
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dashboard.components.filters import load_pipeline_log, render_sidebar
from dashboard.components.theme import BORDER, FONT_MONO, MUTED, inject_global_css

st.set_page_config(page_title="About the Data - NHS GP Analytics", layout="wide", initial_sidebar_state="expanded")
inject_global_css()
render_sidebar()

st.markdown("<h1>About the Data</h1>", unsafe_allow_html=True)
st.markdown(
    f"""<p style="color:{MUTED}; max-width:72ch; line-height:1.65; margin-bottom:1.5rem;">
        Data comes from NHS England GP registration publications and is enriched with
        IMD and ONS postcode lookup assets. This page summarizes source provenance,
        caveats, and how to interpret dashboard outputs.
    </p>""",
    unsafe_allow_html=True,
)

left, right = st.columns(2, gap="large")

with left:
    st.markdown("<h2>Primary Sources</h2>", unsafe_allow_html=True)
    st.markdown(
        f"""<div style="border:1px solid {BORDER}; border-radius:4px; padding:0.9rem 1rem;">
            <ul style="margin:0; padding-left:1.1rem;">
                <li>NHS England monthly GP registrations (practice totals and mapping)</li>
                <li>DLUHC IMD 2025 deprivation metrics</li>
                <li>ONS Postcode Directory (England-only extract)</li>
            </ul>
        </div>""",
        unsafe_allow_html=True,
    )

with right:
    st.markdown("<h2>Coverage</h2>", unsafe_allow_html=True)
    st.markdown(
        f"""<div style="border:1px solid {BORDER}; border-radius:4px; padding:0.9rem 1rem;">
            <ul style="margin:0; padding-left:1.1rem;">
                <li>Monthly practice-level time series snapshots</li>
                <li>Geography filters by region and ICB</li>
                <li>Practice-level supplier and deprivation joins</li>
            </ul>
        </div>""",
        unsafe_allow_html=True,
    )

st.markdown("---")
st.markdown("<h2>Known Caveats</h2>", unsafe_allow_html=True)

caveats = pd.DataFrame(
    [
        {
            "Caveat": "NHAIS to PDS source change",
            "Detail": "Data source changed around early 2023, which can introduce discontinuities.",
            "How handled": "Annotated as a known break; trends should be interpreted with this transition in mind.",
        },
        {
            "Caveat": "April ICB restructures",
            "Detail": "Commissioner geographies can change around April each year.",
            "How handled": "Historical mapping is retained and April points should be interpreted with caution.",
        },
        {
            "Caveat": "Registered list inflation",
            "Detail": "Registered patient totals may exceed resident population due to ghost registrations.",
            "How handled": "Figures are shown as published by NHS data; no correction is applied.",
        },
        {
            "Caveat": "Retroactive file corrections",
            "Detail": "Upstream files may be corrected after publication.",
            "How handled": "Pipeline supports re-ingestion and upsert of historical months.",
        },
        {
            "Caveat": "Practice closures vs data gaps",
            "Detail": "Disappearance from monthly data can indicate closure, merger, or a data issue.",
            "How handled": "Anomaly outputs are flagged as suspected signals rather than confirmed events.",
        },
    ]
)

st.dataframe(caveats, width="stretch", hide_index=True)

st.markdown("---")
st.markdown("<h2>Pipeline Transparency</h2>", unsafe_allow_html=True)
log = load_pipeline_log()
if not log:
    st.info("No pipeline run records available in data/pipeline_log.json.")
else:
    recent = pd.DataFrame(log).tail(12).copy()
    if "run_at" in recent.columns:
        recent["run_at"] = pd.to_datetime(recent["run_at"], errors="coerce")
        recent = recent.sort_values("run_at", ascending=False)
        recent["run_at"] = recent["run_at"].dt.strftime("%Y-%m-%d %H:%M")

    columns = [
        col
        for col in ["run_at", "month", "year", "status", "practices_ingested", "error"]
        if col in recent.columns
    ]
    st.dataframe(recent[columns], width="stretch", hide_index=True)

st.markdown(
    f"""<p style="font-family:{FONT_MONO}; font-size:0.75rem; color:{MUTED}; margin-top:1rem;">
        For full implementation details, see docs/PROJECT_SPEC.md and docs/PIPELINE_IMPLEMENTATION_PLAN.md.
    </p>""",
    unsafe_allow_html=True,
)
