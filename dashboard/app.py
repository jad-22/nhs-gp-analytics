"""NHS GP Analytics home page."""

from __future__ import annotations

import streamlit as st

from dashboard.components.filters import load_filter_options, render_sidebar
from dashboard.components.theme import BORDER, CORAL, MUTED, inject_global_css
from dashboard.data import cache_health

st.set_page_config(page_title="NHS GP Analytics", layout="wide", initial_sidebar_state="expanded")
inject_global_css()
render_sidebar()

_MONO = "'JetBrains Mono', 'Fira Code', monospace"

st.markdown(
    f"""<div style="padding-bottom:2rem;">
        <h1 style="margin-bottom:0.375rem;">NHS GP Analytics</h1>
        <p style="color:{MUTED}; max-width:68ch; line-height:1.65; margin:0;">
            An automated analytics platform built on NHS England GP registration data.
            Monthly pipeline - practice-level trends, supplier share, and deprivation signals.
        </p>
    </div>""",
    unsafe_allow_html=True,
)

_num = (
    f"font-family:{_MONO}; color:{CORAL}; "
    "font-size:0.8125rem; font-weight:500; letter-spacing:0.02em;"
)
_desc = f"color:{MUTED}; font-size:0.9375rem; line-height:1.65; margin:0.5rem 0 1.25rem;"
_rule = f"border-top:2px solid {BORDER}; padding-top:1.25rem;"

col1, col2, col3 = st.columns(3, gap="large")

with col1:
    st.markdown(
        f"""<div style="{_rule}">
            <h3><span style="{_num}">1 -</span> List Size Trends</h3>
            <p style="{_desc}">Monthly patient registration counts from the processed backfill.
            National trajectory, regional breakdown, and practice-level time series
            with 12-month forecasting.</p>
        </div>""",
        unsafe_allow_html=True,
    )
    st.page_link("pages/1_List_Size_Trends.py", label="Explore trends")

with col2:
    st.markdown(
        f"""<div style="{_rule}">
            <h3><span style="{_num}">2 -</span> Clinical System Market Share</h3>
            <p style="{_desc}">EMIS Web vs SystmOne market share over time by patient count
            and practice count. Regional concentration and migration signals across
            England's commissioner regions.</p>
        </div>""",
        unsafe_allow_html=True,
    )
    st.page_link("pages/2_Clinical_System_Market_Share.py", label="Explore market share")

with col3:
    st.markdown(
        f"""<div style="{_rule}">
            <h3><span style="{_num}">3 -</span> Deprivation Analysis</h3>
            <p style="{_desc}">IMD decile distribution across England's GP practices, with
            practice marker mapping and clustering. Boundary choropleths are deferred
            until a later GeoJSON phase.</p>
        </div>""",
        unsafe_allow_html=True,
    )
    st.page_link("pages/3_Deprivation_Analysis.py", label="Explore deprivation")

opts = load_filter_options()
date_from_str = opts["date_min"].strftime("%b %Y")
date_to_str = opts["date_max"].strftime("%b %Y")
practices = opts["total_practices"]
practices_str = f"{practices:,} practices - " if practices else ""
healthy, missing = cache_health()
cache_label = "Dashboard cache ready" if healthy else f"Dashboard cache missing {len(missing)} file(s)"

st.markdown(
    f"""<div style="margin-top:3rem; padding-top:1.5rem; border-top:1px solid {BORDER};">
        <span style="font-family:{_MONO}; font-size:0.75rem; color:{MUTED};">
            Data: {date_from_str} - {date_to_str} - {practices_str}NHS England GP Registration Statistics
            <br>{cache_label}
        </span>
    </div>""",
    unsafe_allow_html=True,
)
