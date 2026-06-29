"""Clinical System Market Share — EMIS vs SystmOne over time."""

from __future__ import annotations

import streamlit as st

from dashboard.components.filters import render_sidebar
from dashboard.components.theme import BORDER, MUTED, inject_global_css

st.set_page_config(
    page_title="Market Share · NHS GP Analytics",
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_global_css()
filters = render_sidebar()

_MONO = "'JetBrains Mono', 'Fira Code', monospace"

st.markdown("<h1>Clinical System Market Share</h1>", unsafe_allow_html=True)
st.markdown(
    f"""<p style="color:{MUTED}; max-width:72ch; line-height:1.65; margin-bottom:2rem;">
        EMIS Web vs SystmOne share of NHS England GP practices by patient count and
        practice count, 2015 to present. Regional concentration and migration signals
        across commissioner regions.
    </p>""",
    unsafe_allow_html=True,
)

st.markdown(
    f"""<div style="border:1px solid {BORDER}; border-radius:4px; padding:3rem 2rem;
        text-align:center; margin-bottom:1rem;">
        <p style="font-family:{_MONO}; font-size:0.8125rem; color:{MUTED}; margin:0;">
            Chart: National share over time · {filters.date_from.strftime('%b %Y')} –
            {filters.date_to.strftime('%b %Y')} · coming in module build
        </p>
    </div>""",
    unsafe_allow_html=True,
)
