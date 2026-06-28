"""Streamlit entry point scaffold for NHS GP Analytics."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st


@st.cache_data(ttl=3600)
def load_pipeline_log(log_path: Path) -> list[dict]:
    """Load pipeline log records if present."""

    if not log_path.exists():
        return []
    try:
        frame = pd.read_json(log_path)
    except ValueError:
        return []
    return frame.to_dict(orient="records")


def main() -> None:
    """Render the dashboard home scaffold."""

    st.set_page_config(page_title="NHS GP Analytics", layout="wide")
    st.title("NHS GP Analytics")
    st.caption("Phase 1 scaffold: data foundation and module placeholders")

    repo_root = Path(__file__).resolve().parent.parent
    records = load_pipeline_log(repo_root / "data" / "pipeline_log.json")
    last_run = records[-1]["run_at"] if records else "No runs recorded"

    st.sidebar.header("Pipeline Status")
    st.sidebar.write(f"Last run: {last_run}")

    st.markdown(
        """
        This app scaffold is in place for later phases.

        - Page 1: List Size Trends
        - Page 2: Clinical System Market Share
        - Page 3: Deprivation Analysis
        """
    )


if __name__ == "__main__":
    main()
