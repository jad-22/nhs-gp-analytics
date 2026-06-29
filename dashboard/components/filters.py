"""Sidebar brand mark, date range, and geographic filter for all dashboard pages."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from dashboard.components.theme import BORDER, CORAL, INK, MUTED

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_LIST_SIZE_PATH = _REPO_ROOT / "data" / "processed" / "list_size.parquet"
_MAPPING_PATH = _REPO_ROOT / "data" / "processed" / "mapping.parquet"
_LOG_PATH = _REPO_ROOT / "data" / "pipeline_log.json"

_AMBER = "#B07B1B"
_MONO = "'JetBrains Mono', 'Fira Code', monospace"


@dataclass
class FilterState:
    date_from: date
    date_to: date
    regions: list[str] = field(default_factory=list)
    icbs: list[str] = field(default_factory=list)

    @property
    def has_region_filter(self) -> bool:
        return bool(self.regions)

    @property
    def has_icb_filter(self) -> bool:
        return bool(self.icbs)


@st.cache_data(ttl=3600)
def load_filter_options() -> dict[str, Any]:
    """Load date range, region list, ICB-by-region map, and practice count from parquet."""
    date_min: date = date(2015, 1, 1)
    date_max: date = date.today()
    regions: list[str] = []
    icb_by_region: dict[str, list[str]] = {}
    total_practices: int = 0

    if _LIST_SIZE_PATH.exists():
        try:
            df_ls = pd.read_parquet(_LIST_SIZE_PATH, columns=["SNAPSHOT_DATE"])
            if not df_ls.empty:
                parsed = pd.to_datetime(df_ls["SNAPSHOT_DATE"], errors="coerce")
                date_min = parsed.min().date()
                date_max = parsed.max().date()
        except Exception:
            pass

    if _MAPPING_PATH.exists():
        try:
            df_map = pd.read_parquet(_MAPPING_PATH)
            if "PRACTICE_CODE" in df_map.columns:
                total_practices = int(df_map["PRACTICE_CODE"].nunique())
            if "COMM_REGION_NAME" in df_map.columns:
                regions = sorted(df_map["COMM_REGION_NAME"].dropna().unique().tolist())
            if "COMM_REGION_NAME" in df_map.columns and "ICB_NAME" in df_map.columns:
                for region in regions:
                    mask = df_map["COMM_REGION_NAME"] == region
                    icbs = sorted(df_map.loc[mask, "ICB_NAME"].dropna().unique().tolist())
                    if icbs:
                        icb_by_region[region] = icbs
        except Exception:
            pass

    return {
        "date_min": date_min,
        "date_max": date_max,
        "regions": regions,
        "icb_by_region": icb_by_region,
        "total_practices": total_practices,
    }


@st.cache_data(ttl=3600)
def load_pipeline_log() -> list[dict]:
    """Load pipeline run records from the JSON log file."""
    if not _LOG_PATH.exists():
        return []
    try:
        data = json.loads(_LOG_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _label(text: str) -> str:
    return (
        f'<div style="font-size:0.6875rem; font-weight:600; color:{MUTED}; '
        f'text-transform:uppercase; letter-spacing:0.07em; '
        f'margin:1rem 0 0.3rem;">{text}</div>'
    )


def render_sidebar() -> FilterState:
    """Render brand mark, date range, geographic filters, and pipeline status.

    Call on every page immediately after inject_global_css(). Returns the
    current filter selections so each page can scope its queries.
    """
    opts = load_filter_options()

    with st.sidebar:
        # ── Brand mark ──────────────────────────────────────────────────────
        st.markdown(
            f"""<div style="padding:1.25rem 0 0.5rem;">
                <div style="font-size:1rem; font-weight:600; color:{INK};
                    letter-spacing:-0.01em; line-height:1.2;">
                    NHS GP Analytics
                </div>
                <div style="font-size:0.6875rem; color:{MUTED}; margin-top:0.2rem;
                    font-family:{_MONO};">
                    England · {opts['date_min'].year}–{opts['date_max'].year}
                </div>
                <div style="height:2px; background:{CORAL}; border-radius:1px;
                    margin-top:0.875rem;"></div>
            </div>""",
            unsafe_allow_html=True,
        )

        # ── Period ──────────────────────────────────────────────────────────
        st.markdown(_label("Period"), unsafe_allow_html=True)
        date_range = st.date_input(
            "Period",
            value=(opts["date_min"], opts["date_max"]),
            min_value=opts["date_min"],
            max_value=opts["date_max"],
            format="DD/MM/YYYY",
            label_visibility="collapsed",
        )
        if isinstance(date_range, (tuple, list)) and len(date_range) == 2:
            date_from: date = date_range[0]
            date_to: date = date_range[1]
        elif isinstance(date_range, (tuple, list)) and len(date_range) == 1:
            date_from = date_range[0]
            date_to = opts["date_max"]
        else:
            date_from = opts["date_min"]
            date_to = opts["date_max"]

        # ── Region ──────────────────────────────────────────────────────────
        st.markdown(_label("Region"), unsafe_allow_html=True)
        selected_regions: list[str] = st.multiselect(
            "Region",
            options=opts["regions"],
            default=[],
            placeholder="All regions",
            label_visibility="collapsed",
        )

        # ── ICB (scoped to selected regions) ────────────────────────────────
        if selected_regions:
            icb_options: list[str] = sorted(
                {icb for r in selected_regions for icb in opts["icb_by_region"].get(r, [])}
            )
        else:
            icb_options = sorted(
                {icb for icbs in opts["icb_by_region"].values() for icb in icbs}
            )

        st.markdown(_label("ICB"), unsafe_allow_html=True)
        selected_icbs: list[str] = st.multiselect(
            "ICB",
            options=icb_options,
            default=[],
            placeholder="All ICBs",
            label_visibility="collapsed",
        )

        # ── Pipeline status ─────────────────────────────────────────────────
        st.markdown(
            f'<div style="height:1px; background:{BORDER}; margin:1.25rem 0 1rem;"></div>',
            unsafe_allow_html=True,
        )
        log = load_pipeline_log()
        if log:
            last = log[-1]
            run_at: str = last.get("run_at", "")
            status: str = last.get("status", "ok")
            practices: int = last.get("practices_ingested", opts["total_practices"]) or 0
            is_ok = status in ("ok", "success", "complete")
            dot_color = CORAL if is_ok else _AMBER
            status_label = "Pipeline up to date" if is_ok else f"Pipeline: {status}"
            run_date = run_at[:10] if run_at else "—"
            practices_str = f"{practices:,}" if practices else "—"
            st.markdown(
                f"""<div style="display:flex; align-items:flex-start; gap:0.5rem;">
                    <div style="width:6px; height:6px; border-radius:50%;
                        background:{dot_color}; margin-top:0.35rem; flex-shrink:0;"></div>
                    <div>
                        <div style="font-size:0.75rem; color:{MUTED}; line-height:1.5;">
                            {status_label}
                        </div>
                        <div style="font-size:0.6875rem; font-family:{_MONO};
                            color:{MUTED}; margin-top:0.1rem;">
                            {run_date} · {practices_str} practices
                        </div>
                    </div>
                </div>""",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f"""<div style="display:flex; align-items:flex-start; gap:0.5rem;">
                    <div style="width:6px; height:6px; border-radius:50%;
                        background:{MUTED}; margin-top:0.35rem; flex-shrink:0;"></div>
                    <div style="font-size:0.75rem; color:{MUTED}; line-height:1.5;">
                        No pipeline runs recorded
                    </div>
                </div>""",
                unsafe_allow_html=True,
            )

    return FilterState(
        date_from=date_from,
        date_to=date_to,
        regions=list(selected_regions),
        icbs=list(selected_icbs),
    )


__all__ = ["FilterState", "load_filter_options", "load_pipeline_log", "render_sidebar"]
