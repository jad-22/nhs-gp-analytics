"""Deprivation Analysis - IMD distribution across GP practices."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

REPO_ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / "dashboard").is_dir())
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dashboard.components.charts import cluster_scatter, deprivation_scatter, inequality_line
from dashboard.components.filters import render_sidebar
from dashboard.components.maps import practice_marker_map
from dashboard.components.theme import BORDER, CORAL, FONT_MONO, MUTED, inject_global_css
from dashboard.data import (
    as_page_filters,
    cache_health,
    filter_frame,
    format_int,
    format_pct,
    load_cluster_k,
    load_correlations,
    load_deprivation_latest,
    load_inequality,
)

st.set_page_config(page_title="Deprivation Analysis - NHS GP Analytics", layout="wide", initial_sidebar_state="expanded")
inject_global_css()
filters = as_page_filters(render_sidebar())

healthy, missing = cache_health()
if not healthy:
    st.warning(f"Dashboard cache is incomplete. Run `python scripts/build_dashboard_cache.py`. Missing: {', '.join(missing)}")

st.markdown("<h1>Deprivation Analysis</h1>", unsafe_allow_html=True)
st.markdown(
    f"""<p style="color:{MUTED}; max-width:72ch; line-height:1.65; margin-bottom:1.5rem;">
        IMD-linked practice records, under-served flags, and practice segmentation.
        Boundary GeoJSON choropleths are intentionally deferred; this phase uses
        lightweight practice marker maps from the postcode enrichment.
    </p>""",
    unsafe_allow_html=True,
)

latest = filter_frame(load_deprivation_latest(), filters)
if not latest.empty:
    underserved = latest.loc[latest.get("UNDER_SERVED", False) == True]  # noqa: E712
    scored = latest.dropna(subset=["IMD_DECILE"])
    underserved_share = len(underserved) / len(scored) if len(scored) else 0
    st.markdown(
        f"""<div style="border:1px solid {BORDER}; border-radius:4px; padding:0.85rem 1rem; margin-bottom:1.25rem;">
            <span style="font-family:{FONT_MONO}; color:{CORAL}; font-size:1rem;">{format_int(len(scored))}</span>
            <span style="color:{MUTED}; margin-left:0.4rem;">IMD-scored practices</span>
            <span style="color:{MUTED}; margin:0 0.7rem;">/</span>
            <span style="font-family:{FONT_MONO}; color:{CORAL};">{format_int(len(underserved))}</span>
            <span style="color:{MUTED}; margin-left:0.4rem;">under-served flags</span>
            <span style="color:{MUTED}; margin:0 0.7rem;">/</span>
            <span style="font-family:{FONT_MONO}; color:{CORAL};">{format_pct(underserved_share)}</span>
            <span style="color:{MUTED}; margin-left:0.4rem;">of scored practices</span>
        </div>""",
        unsafe_allow_html=True,
    )

st.plotly_chart(practice_marker_map(latest, "Practice locations by IMD decile"), use_container_width=True)

left, right = st.columns(2, gap="large")
with left:
    st.plotly_chart(deprivation_scatter(latest, "Practice size vs IMD score"), use_container_width=True)
with right:
    cluster_k = filter_frame(load_cluster_k(), filters)
    if cluster_k.empty or "K" not in cluster_k.columns:
        # Stale cache without cluster_k.parquet - fall back to the single cached partition.
        st.plotly_chart(cluster_scatter(latest, "Cluster explorer"), use_container_width=True)
    else:
        silhouettes = cluster_k.drop_duplicates("K").set_index("K")["SILHOUETTE_SCORE"].sort_index()
        best_k = int(silhouettes.idxmax())
        chosen_k = st.select_slider(
            "Cluster count (k)",
            options=[int(k) for k in silhouettes.index],
            value=best_k,
            help="Segments are precomputed for each k during the cache build; the default is the k with the best silhouette score.",
        )
        st.plotly_chart(
            cluster_scatter(cluster_k.loc[cluster_k["K"] == chosen_k], f"Cluster explorer - k = {chosen_k}"),
            use_container_width=True,
        )
        st.caption(
            f"Silhouette at k = {chosen_k}: {silhouettes[chosen_k]:.2f}"
            f" - best k = {best_k} ({silhouettes[best_k]:.2f})."
            " Scores are computed on all practices, before sidebar filters."
        )

st.markdown("---")
st.markdown("<h2>Inequality trends</h2>", unsafe_allow_html=True)
inequality = filter_frame(load_inequality(), filters)
st.plotly_chart(inequality_line(inequality, "List-size inequality by deprivation band"), use_container_width=True)

left, right = st.columns(2, gap="large")
with left:
    st.markdown("<h2>Under-served practices</h2>", unsafe_allow_html=True)
    if latest.empty or "UNDER_SERVED" not in latest.columns:
        st.info("No under-served flags for the selected filters.")
    else:
        table = latest.loc[latest["UNDER_SERVED"]].copy()
        table = table.sort_values(["IMD_DECILE", "NUMBER_OF_PATIENTS"], ascending=[True, True]).head(200)
        table["IMD_DECILE"] = pd.to_numeric(table["IMD_DECILE"], errors="coerce").map(lambda value: f"{value:.0f}")
        st.dataframe(
            table[["CODE", "PRACTICE_NAME", "REGION_NAME", "ICB_NAME", "NUMBER_OF_PATIENTS", "IMD_DECILE"]],
            width="stretch",
            hide_index=True,
        )

with right:
    st.markdown("<h2>Regional correlation</h2>", unsafe_allow_html=True)
    correlations = filter_frame(load_correlations(), filters, date_column="SNAPSHOT_DATE")
    if correlations.empty:
        st.info("No correlation rows for the selected filters.")
    else:
        display = correlations.copy()
        for column in ("PEARSON_R", "P_VALUE"):
            if column in display.columns:
                display[column] = pd.to_numeric(display[column], errors="coerce").map(lambda value: f"{value:.3f}")
        st.dataframe(display, width="stretch", hide_index=True)
