"""Map helpers for geography-light dashboard views."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from dashboard.components.theme import CORAL, CORAL_TINT, INK, MUTED, apply_brand_theme


def practice_marker_map(frame: pd.DataFrame, title: str) -> go.Figure:
    """Render practice markers coloured by IMD decile.

    Boundary GeoJSON choropleths are intentionally deferred to a later phase.
    This map uses cached practice latitude/longitude so it remains lightweight.
    """

    if frame.empty:
        fig = go.Figure()
        fig.add_annotation(
            text="No mapped practices for the selected filters.",
            x=0.5,
            y=0.5,
            xref="paper",
            yref="paper",
            showarrow=False,
            font=dict(color=MUTED, size=14),
        )
        fig.update_xaxes(visible=False)
        fig.update_yaxes(visible=False)
        return apply_brand_theme(fig, title=title, height=430, show_legend=False)

    mapped = frame.dropna(subset=["LATITUDE", "LONGITUDE"]).copy()
    if mapped.empty:
        return practice_marker_map(pd.DataFrame(), title)

    fig = go.Figure(
        go.Scattermap(
            lat=mapped["LATITUDE"],
            lon=mapped["LONGITUDE"],
            mode="markers",
            marker=dict(
                size=7,
                color=mapped["IMD_DECILE"],
                colorscale=[
                    [0.0, CORAL],
                    [0.5, CORAL_TINT],
                    [1.0, "#3B61A8"],
                ],
                cmin=1,
                cmax=10,
                colorbar=dict(title="IMD decile"),
                opacity=0.72,
            ),
            customdata=mapped[["PRACTICE_NAME", "CODE", "NUMBER_OF_PATIENTS", "REGION_NAME"]],
            hovertemplate="%{customdata[0]} (%{customdata[1]})<br>%{customdata[3]}<br>%{customdata[2]:,.0f} patients<extra></extra>",
        )
    )
    fig.update_layout(
        map=dict(
            style="open-street-map",
            center=dict(lat=52.7, lon=-1.7),
            zoom=5,
        ),
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        font=dict(color=INK),
    )
    return apply_brand_theme(fig, title=title, height=520, show_legend=False)


__all__ = ["practice_marker_map"]
