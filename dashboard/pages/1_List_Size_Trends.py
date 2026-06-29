"""List Size Trends — monthly patient registration time series."""

from __future__ import annotations

import streamlit as st

from dashboard.components.filters import render_sidebar
from dashboard.components.theme import BORDER, MUTED, inject_global_css

st.set_page_config(
    page_title="List Size Trends · NHS GP Analytics",
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_global_css()
filters = render_sidebar()

_MONO = "'JetBrains Mono', 'Fira Code', monospace"

st.markdown("<h1>List Size Trends</h1>", unsafe_allow_html=True)
st.markdown(
    f"""<p style="color:{MUTED}; max-width:72ch; line-height:1.65; margin-bottom:2rem;">
        Monthly patient registration counts for NHS England GP practices, 2015 to present.
        National trajectory, regional breakdown, and practice-level time series with
        12-month ARIMA forecasting.
    </p>""",
    unsafe_allow_html=True,
)

st.markdown(
    f"""<div style="border:1px solid {BORDER}; border-radius:4px; padding:3rem 2rem;
        text-align:center; margin-bottom:1rem;">
        <p style="font-family:{_MONO}; font-size:0.8125rem; color:{MUTED}; margin:0;">
            Chart: National headline · {filters.date_from.strftime('%b %Y')} –
            {filters.date_to.strftime('%b %Y')} · coming in module build
        </p>
    </div>""",
    unsafe_allow_html=True,
)
