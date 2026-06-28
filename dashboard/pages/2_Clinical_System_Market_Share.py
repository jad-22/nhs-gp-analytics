"""Clinical System Market Share page scaffold."""

from __future__ import annotations

import streamlit as st

from dashboard.components.charts import empty_figure
from dashboard.components.filters import render_global_filters


st.title("Clinical System Market Share")
render_global_filters()
st.plotly_chart(empty_figure("National Share Over Time (Scaffold)"), use_container_width=True)
st.info("Market-share charts and migration signals will be implemented in Phase 3.")
