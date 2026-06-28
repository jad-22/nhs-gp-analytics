"""List Size Trends page scaffold."""

from __future__ import annotations

import streamlit as st

from dashboard.components.charts import empty_figure
from dashboard.components.filters import render_global_filters


st.title("List Size Trends")
render_global_filters()
st.plotly_chart(empty_figure("National Headline (Scaffold)"), use_container_width=True)
st.info("Detailed trend and anomaly views will be implemented in Phase 3.")
