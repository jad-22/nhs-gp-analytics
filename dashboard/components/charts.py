"""Chart factory scaffolds for dashboard pages."""

from __future__ import annotations

import plotly.graph_objects as go


def empty_figure(title: str) -> go.Figure:
    """Return a small placeholder figure used during scaffold phase."""

    fig = go.Figure()
    fig.update_layout(title=title, template="plotly_white")
    return fig
