"""Forecasting helpers for the NHS GP Analytics project scaffold."""

from __future__ import annotations

import pandas as pd


def forecast_list_size(
    df: pd.DataFrame,
    periods: int = 12,
    changepoints: list[str] | None = None,
) -> pd.DataFrame:
    """Placeholder for the Prophet-based forecasting implementation."""

    raise NotImplementedError("Forecasting will be implemented in the next pass.")