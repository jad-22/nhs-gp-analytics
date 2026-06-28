"""Map helper scaffolds for dashboard pages."""

from __future__ import annotations

import plotly.graph_objects as go


def empty_map(title: str) -> go.Figure:
    """Return a placeholder map figure for scaffold pages."""

    fig = go.Figure()
    fig.update_layout(title=title, template="plotly_white")
    return fig
