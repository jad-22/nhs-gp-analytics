"""Filter widget scaffolds for Streamlit pages."""

from __future__ import annotations

import streamlit as st


def render_global_filters() -> dict[str, str | None]:
    """Render placeholder global filters and return selected values."""

    st.sidebar.subheader("Global Filters")
    region = st.sidebar.selectbox("Region", options=["All"], index=0)
    icb = st.sidebar.selectbox("ICB", options=["All"], index=0)
    return {
        "region": None if region == "All" else region,
        "icb": None if icb == "All" else icb,
    }
