"""Branded Plotly chart factories for the Streamlit dashboard."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from dashboard.components.theme import BORDER, CHART_COLORS, CORAL, CORAL_TINT, INK, MUTED, apply_brand_theme


def empty_figure(title: str, message: str = "No data available for the selected filters.") -> go.Figure:
    """Return a branded empty-state figure."""

    fig = go.Figure()
    fig.add_annotation(
        text=message,
        x=0.5,
        y=0.5,
        xref="paper",
        yref="paper",
        showarrow=False,
        font=dict(color=MUTED, size=14),
    )
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return apply_brand_theme(fig, title=title, height=320, show_legend=False)


def patient_total_line(frame: pd.DataFrame, title: str) -> go.Figure:
    """Line chart for total registered patients over time."""

    if frame.empty:
        return empty_figure(title)

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=frame["SNAPSHOT_DATE"],
            y=frame["PATIENT_COUNT"],
            name="Registered patients",
            mode="lines",
            line=dict(color=CORAL, width=2.5),
            hovertemplate="%{x|%b %Y}<br>%{y:,.0f} patients<extra></extra>",
        )
    )
    fig.update_yaxes(title_text="Registered patients", tickformat=",.0f")
    return apply_brand_theme(fig, title=title, height=420, show_legend=False)


def regional_patient_lines(frame: pd.DataFrame, title: str, max_regions: int = 8) -> go.Figure:
    """Multi-line patient-count chart by region or selected ICB."""

    if frame.empty:
        return empty_figure(title)

    group_column = "ICB_NAME" if frame["ICB_NAME"].nunique(dropna=True) <= max_regions and frame["ICB_NAME"].nunique(dropna=True) > 1 else "REGION_NAME"
    grouped = (
        frame.groupby(["SNAPSHOT_DATE", group_column], as_index=False)
        .agg(PATIENT_COUNT=("PATIENT_COUNT", "sum"))
        .sort_values(["SNAPSHOT_DATE", group_column])
    )

    latest_totals = (
        grouped.sort_values("SNAPSHOT_DATE")
        .groupby(group_column, as_index=False)
        .tail(1)
        .sort_values("PATIENT_COUNT", ascending=False)
        .head(max_regions)
    )
    keep = set(latest_totals[group_column])
    grouped = grouped.loc[grouped[group_column].isin(keep)]

    fig = go.Figure()
    for idx, (name, part) in enumerate(grouped.groupby(group_column, sort=False)):
        fig.add_trace(
            go.Scatter(
                x=part["SNAPSHOT_DATE"],
                y=part["PATIENT_COUNT"],
                name=str(name),
                mode="lines",
                line=dict(color=CHART_COLORS[idx % len(CHART_COLORS)], width=2),
                hovertemplate="%{x|%b %Y}<br>%{y:,.0f} patients<extra></extra>",
            )
        )

    fig.update_yaxes(title_text="Registered patients", tickformat=",.0f")
    return apply_brand_theme(fig, title=title, height=440, show_legend=True)


def practice_forecast_chart(history: pd.DataFrame, forecast: pd.DataFrame, title: str) -> go.Figure:
    """Practice history with forecast confidence band."""

    if history.empty:
        return empty_figure(title, "Search for a practice to view its time series.")

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=history["SNAPSHOT_DATE"],
            y=history["NUMBER_OF_PATIENTS"],
            name="Observed",
            mode="lines",
            line=dict(color=CORAL, width=2.5),
            hovertemplate="%{x|%b %Y}<br>%{y:,.0f} patients<extra></extra>",
        )
    )
    if not forecast.empty:
        fig.add_trace(
            go.Scatter(
                x=forecast["ds"],
                y=forecast["yhat_upper"],
                name="Upper interval",
                mode="lines",
                line=dict(width=0, color=BORDER),
                hoverinfo="skip",
                showlegend=False,
            )
        )
        fig.add_trace(
            go.Scatter(
                x=forecast["ds"],
                y=forecast["yhat_lower"],
                name="Forecast interval",
                mode="lines",
                line=dict(width=0, color=BORDER),
                fill="tonexty",
                fillcolor=CORAL_TINT,
                hoverinfo="skip",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=forecast["ds"],
                y=forecast["yhat"],
                name="Forecast",
                mode="lines",
                line=dict(color="#3B61A8", width=2, dash="dash"),
                hovertemplate="%{x|%b %Y}<br>%{y:,.0f} forecast patients<extra></extra>",
            )
        )

    fig.update_yaxes(title_text="Registered patients", tickformat=",.0f")
    return apply_brand_theme(fig, title=title, height=420, show_legend=True)


def market_share_area(frame: pd.DataFrame, share_column: str, title: str) -> go.Figure:
    """Stacked area chart for clinical-system share."""

    if frame.empty:
        return empty_figure(title)

    systems = ["EMIS Web", "SystmOne", "Others"]
    fig = go.Figure()
    for idx, system in enumerate(systems):
        part = frame.loc[frame["CLINICAL_SYSTEM"] == system].sort_values("SNAPSHOT_DATE")
        if part.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=part["SNAPSHOT_DATE"],
                y=part[share_column],
                name=system,
                mode="lines",
                stackgroup="one",
                line=dict(width=1.5, color=CHART_COLORS[idx % len(CHART_COLORS)]),
                hovertemplate="%{x|%b %Y}<br>%{y:.1%}<extra></extra>",
            )
        )
    fig.update_yaxes(title_text="Share", tickformat=".0%")
    return apply_brand_theme(fig, title=title, height=430, show_legend=True)


def market_heatmap(frame: pd.DataFrame, title: str) -> go.Figure:
    """Regional heatmap for latest practice share by clinical system."""

    if frame.empty:
        return empty_figure(title)

    pivot = frame.pivot_table(
        index="REGION_NAME",
        columns="CLINICAL_SYSTEM",
        values="PRACTICE_SHARE",
        aggfunc="sum",
        fill_value=0,
    ).sort_index()

    fig = go.Figure(
        data=go.Heatmap(
            z=pivot.values,
            x=list(pivot.columns),
            y=list(pivot.index),
            colorscale=[
                [0.0, "#FFFFFF"],
                [0.5, CORAL_TINT],
                [1.0, CORAL],
            ],
            zmin=0,
            zmax=max(0.01, float(pivot.values.max())),
            colorbar=dict(tickformat=".0%", title="Share"),
            hovertemplate="%{y}<br>%{x}: %{z:.1%}<extra></extra>",
        )
    )
    return apply_brand_theme(fig, title=title, height=420, show_legend=False)


def system_size_distribution(frame: pd.DataFrame, title: str) -> go.Figure:
    """Violin plot of current practice list size by clinical system."""

    if frame.empty:
        return empty_figure(title)

    fig = go.Figure()
    for idx, (system, part) in enumerate(frame.groupby("CLINICAL_SYSTEM", sort=False)):
        fig.add_trace(
            go.Violin(
                x=[system] * len(part),
                y=part["NUMBER_OF_PATIENTS"],
                name=str(system),
                line_color=CHART_COLORS[idx % len(CHART_COLORS)],
                fillcolor="rgba(209,70,29,0.12)" if idx == 0 else None,
                box_visible=True,
                meanline_visible=True,
                hovertemplate="%{x}<br>%{y:,.0f} patients<extra></extra>",
            )
        )
    fig.update_yaxes(title_text="Registered patients", tickformat=",.0f")
    return apply_brand_theme(fig, title=title, height=420, show_legend=False)


def deprivation_scatter(frame: pd.DataFrame, title: str) -> go.Figure:
    """Scatter plot of list size against IMD score."""

    if frame.empty:
        return empty_figure(title)

    frame = frame.dropna(subset=["IMD_SCORE", "NUMBER_OF_PATIENTS"])
    if frame.empty:
        return empty_figure(title, "No IMD-scored practices for the selected filters.")

    fig = go.Figure()
    for idx, (region, part) in enumerate(frame.groupby("REGION_NAME", sort=False)):
        fig.add_trace(
            go.Scattergl(
                x=part["IMD_SCORE"],
                y=part["NUMBER_OF_PATIENTS"],
                name=str(region),
                mode="markers",
                marker=dict(size=7, color=CHART_COLORS[idx % len(CHART_COLORS)], opacity=0.68),
                customdata=part[["PRACTICE_NAME", "CODE", "IMD_DECILE"]],
                hovertemplate="%{customdata[0]} (%{customdata[1]})<br>IMD score %{x:.1f}<br>Decile %{customdata[2]:.0f}<br>%{y:,.0f} patients<extra></extra>",
            )
        )
    fig.update_xaxes(title_text="IMD score")
    fig.update_yaxes(title_text="Registered patients", tickformat=",.0f")
    return apply_brand_theme(fig, title=title, height=470, show_legend=True)


def cluster_scatter(frame: pd.DataFrame, title: str) -> go.Figure:
    """UMAP cluster explorer scatter plot."""

    required = {"UMAP_X", "UMAP_Y", "CLUSTER"}
    if frame.empty or not required.issubset(frame.columns):
        return empty_figure(title)

    fig = go.Figure()
    for idx, (cluster, part) in enumerate(frame.groupby("CLUSTER", sort=True)):
        fig.add_trace(
            go.Scattergl(
                x=part["UMAP_X"],
                y=part["UMAP_Y"],
                name=f"Cluster {cluster}",
                mode="markers",
                marker=dict(size=7, color=CHART_COLORS[idx % len(CHART_COLORS)], opacity=0.72),
                customdata=part[["PRACTICE_NAME", "CODE", "NUMBER_OF_PATIENTS", "IMD_DECILE"]],
                hovertemplate="%{customdata[0]} (%{customdata[1]})<br>%{customdata[2]:,.0f} patients<br>IMD decile %{customdata[3]:.0f}<extra></extra>",
            )
        )
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return apply_brand_theme(fig, title=title, height=430, show_legend=True)


def inequality_line(frame: pd.DataFrame, title: str) -> go.Figure:
    """Gini coefficient trend by deprivation band."""

    if frame.empty:
        return empty_figure(title)

    work = frame.copy()
    work["IMD_BAND"] = pd.cut(
        pd.to_numeric(work["IMD_DECILE"], errors="coerce"),
        bins=[0, 3, 7, 10],
        labels=["Most deprived (1-3)", "Middle (4-7)", "Least deprived (8-10)"],
    )
    grouped = (
        work.groupby(["SNAPSHOT_DATE", "IMD_BAND"], observed=False, as_index=False)
        .agg(GINI_COEFFICIENT=("GINI_COEFFICIENT", "mean"))
        .dropna(subset=["IMD_BAND"])
    )

    fig = go.Figure()
    for idx, (band, part) in enumerate(grouped.groupby("IMD_BAND", observed=False)):
        fig.add_trace(
            go.Scatter(
                x=part["SNAPSHOT_DATE"],
                y=part["GINI_COEFFICIENT"],
                name=str(band),
                mode="lines",
                line=dict(color=CHART_COLORS[idx % len(CHART_COLORS)], width=2),
                hovertemplate="%{x|%b %Y}<br>Gini %{y:.3f}<extra></extra>",
            )
        )
    fig.update_yaxes(title_text="Gini coefficient", tickformat=".2f")
    return apply_brand_theme(fig, title=title, height=390, show_legend=True)


__all__ = [
    "cluster_scatter",
    "deprivation_scatter",
    "empty_figure",
    "inequality_line",
    "market_heatmap",
    "market_share_area",
    "patient_total_line",
    "practice_forecast_chart",
    "regional_patient_lines",
    "system_size_distribution",
]
