"""Deprivation Analysis page scaffold."""

from __future__ import annotations

import streamlit as st

from dashboard.components.filters import render_global_filters
from dashboard.components.maps import empty_map


st.title("Deprivation Analysis")
render_global_filters()
st.plotly_chart(empty_map("Deprivation Map (Scaffold)"), use_container_width=True)
st.info("Spatial analysis and cluster explorer will be implemented in Phase 3.")
