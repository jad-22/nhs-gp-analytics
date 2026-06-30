"""Design system: brand tokens, CSS injection, and Plotly factory for NHS GP Analytics."""

from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st
import streamlit.components.v1 as components

# ── Brand tokens ──────────────────────────────────────────────────────────────
# Source of truth for all colour and typography values used across the dashboard.
# Every page imports from here; never hard-code these values elsewhere.

CORAL      = "#D1461D"  # Primary — active elements, chart series 1, interactive accents
CORAL_DEEP = "#8F3518"  # Hover and pressed state on coral-filled elements
CORAL_TINT = "#FDF0EC"  # Selected panel backgrounds, active sidebar item highlight
INK        = "#1E1816"  # Body text and headings — ≥14:1 contrast on white
MUTED      = "#5C5552"  # Secondary labels, axis text, captions — ~5:1 on white
SURFACE    = "#F6F4F3"  # Sidebar and secondary panel background
BG         = "#FFFFFF"  # Main content canvas
BORDER     = "#E0DEDD"  # Dividers, grid lines, input stroke at rest

CHART_COLORS: list[str] = [
    CORAL,      # Series 1 — always coral (brand thread in every chart)
    "#3B61A8",  # Series 2 — slate blue
    "#1A7A78",  # Series 3 — teal
    "#6B52A8",  # Series 4 — muted plum
    "#B07B1B",  # Series 5 — warm amber
    MUTED,      # Series 6 — neutral fallback
]

FONT_SANS = "'DM Sans', system-ui, -apple-system, sans-serif"
FONT_MONO = "'JetBrains Mono', 'Fira Code', monospace"


# ── Plotly brand template ─────────────────────────────────────────────────────
# Registered once at import time. Reference as template="simple_white+nhs_gp_brand"
# to layer brand styles on top of Plotly's clean simple_white baseline.

_brand_tpl = go.layout.Template(
    layout=go.Layout(
        colorway=CHART_COLORS,
        font=dict(family=FONT_SANS, color=INK, size=13),
        plot_bgcolor=BG,
        paper_bgcolor=BG,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0,
            font=dict(size=12, color=MUTED),
            bgcolor="rgba(0,0,0,0)",
            borderwidth=0,
        ),
        xaxis=dict(
            showgrid=False,
            zeroline=False,
            showline=True,
            linecolor=BORDER,
            tickfont=dict(family=FONT_MONO, size=11, color=MUTED),
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor=BORDER,
            gridwidth=1,
            zeroline=False,
            showline=False,
            tickfont=dict(family=FONT_MONO, size=11, color=MUTED),
        ),
        hoverlabel=dict(
            bgcolor=INK,
            font=dict(color=BG, family=FONT_SANS, size=13),
            bordercolor=INK,
        ),
    )
)
pio.templates["nhs_gp_brand"] = _brand_tpl


# ── CSS injection ─────────────────────────────────────────────────────────────

_FONT_URL = (
    "https://fonts.googleapis.com/css2?"
    "family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,500;0,9..40,600;1,9..40,400"
    "&family=JetBrains+Mono:wght@400;500"
    "&display=swap"
)

_CSS = f"""<style>
@import url('{_FONT_URL}');

/* ── Token layer ─────────────────────────────────────────────── */
:root {{
    --c-coral:      {CORAL};
    --c-coral-deep: {CORAL_DEEP};
    --c-coral-tint: {CORAL_TINT};
    --c-ink:        {INK};
    --c-muted:      {MUTED};
    --c-surface:    {SURFACE};
    --c-bg:         {BG};
    --c-border:     {BORDER};
    --f-sans:       {FONT_SANS};
    --f-mono:       {FONT_MONO};
    --ease-out:     cubic-bezier(0.25, 1, 0.5, 1);
}}

/* ── Global font ─────────────────────────────────────────────── */
html, body, [class*="css"], p, div,
h1, h2, h3, h4, h5, h6,
label, button, input, select, textarea, th, td, a {{
    font-family: var(--f-sans) !important;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
}}

/* Preserve Streamlit's Material Symbols ligatures for sidebar controls. */
.material-symbols-rounded,
.material-symbols-outlined,
.material-symbols-sharp,
.material-icons,
.material-icons-outlined,
[class*="material-symbols"],
[class*="material-icons"] {{
    font-family:
        "Material Symbols Rounded",
        "Material Symbols Outlined",
        "Material Icons" !important;
    font-weight: normal !important;
    font-style: normal !important;
    font-size: 1.25rem !important;
    line-height: 1 !important;
    letter-spacing: normal !important;
    text-transform: none !important;
    display: inline-block !important;
    white-space: nowrap !important;
    word-wrap: normal !important;
    direction: ltr !important;
    -webkit-font-feature-settings: "liga" !important;
    font-feature-settings: "liga" !important;
    -webkit-font-smoothing: antialiased;
}}

/* Mono reserved for data values and metric figures */
code, pre,
[data-testid="stMetricValue"],
[data-testid="stMetricLabel"] {{
    font-family: var(--f-mono) !important;
}}

/* ── Sidebar ─────────────────────────────────────────────────── */
section[data-testid="stSidebar"] {{
    background-color: {SURFACE} !important;
    border-right: 1px solid {BORDER};
}}
/* Streamlit collapses via transform (not width:0), so the sidebar always
   occupies its 256px in the flex layout even when visually hidden.
   Override to zero width on collapse so stMain can reflow to full viewport. */
section[data-testid="stSidebar"][aria-expanded="false"] {{
    width: 0px !important;
    min-width: 0px !important;
    border-right: none !important;
}}
section[data-testid="stSidebar"] > div:first-child {{
    background-color: {SURFACE} !important;
    padding-top: 0 !important;
}}
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] .stMarkdown p,
section[data-testid="stSidebar"] p {{
    font-size: 0.8125rem !important;
    color: {MUTED};
    line-height: 1.5;
}}

/* ── Main content ────────────────────────────────────────────── */
.main .block-container {{
    max-width: 1440px;
    padding-top: 2rem;
    padding-bottom: 3rem;
}}

/* ── Heading scale (fixed rem — product register) ────────────── */
h1 {{
    font-size: 2rem !important;
    font-weight: 600 !important;
    line-height: 1.2 !important;
    color: {INK} !important;
    letter-spacing: -0.02em;
    margin-bottom: 0.25rem !important;
}}
h2 {{
    font-size: 1.5rem !important;
    font-weight: 600 !important;
    line-height: 1.3 !important;
    color: {INK} !important;
    letter-spacing: -0.01em;
}}
h3 {{
    font-size: 1.125rem !important;
    font-weight: 600 !important;
    line-height: 1.4 !important;
    color: {INK} !important;
}}
h4 {{
    font-size: 1rem !important;
    font-weight: 600 !important;
    color: {INK} !important;
}}
p, li {{
    color: {INK};
    line-height: 1.65;
}}

/* ── Dividers ────────────────────────────────────────────────── */
hr {{
    border: none !important;
    border-top: 1px solid {BORDER} !important;
    margin: 1.5rem 0 !important;
}}

/* ── Interactive transitions ─────────────────────────────────── */
button, input, select, textarea,
[data-testid="stSelectbox"],
[data-testid="stMultiSelect"],
[data-testid="stDateInput"] {{
    transition:
        border-color 150ms var(--ease-out),
        box-shadow   150ms var(--ease-out),
        background   150ms var(--ease-out) !important;
}}

/* ── Hide Streamlit chrome ───────────────────────────────────── */
#MainMenu                           {{ visibility: hidden; }}
footer                              {{ visibility: hidden; height: 0 !important; overflow: hidden; }}
.stDeployButton                     {{ display: none !important; }}

/* Keep stToolbar in layout flow (display:none collapses stHeader to 0 height,
   which clips stExpandSidebarButton and makes it invisible). Hide only the
   specific chrome we don't want instead. */
[data-testid="stToolbar"]           {{ background: transparent !important; border: 0 !important; box-shadow: none !important; }}
[data-testid="stToolbarActions"]    {{ display: none !important; }}
[data-testid="stAppDeployButton"]   {{ display: none !important; }}

/* Streamlit moves the sidebar expand button into the header when collapsed.
   Keep the header layer available; hide only the nonessential chrome. */
[data-testid="stHeader"] {{
    background: transparent !important;
    border: 0 !important;
    box-shadow: none !important;
}}

/* Collapse button (inside expanded sidebar) — CSS only, no layout issues here */
[data-testid="stSidebarCollapseButton"],
[data-testid="collapsedControl"],
[data-testid="stSidebarCollapsedControl"] {{
    align-items: center !important;
    background: {BG} !important;
    border: 1px solid {BORDER} !important;
    border-radius: 6px !important;
    box-shadow: 0 1px 2px rgba(30, 24, 22, 0.08) !important;
    display: inline-flex !important;
    height: 2.25rem !important;
    justify-content: center !important;
    margin: 0.5rem 0 0 0.5rem !important;
    opacity: 1 !important;
    pointer-events: auto !important;
    position: relative !important;
    visibility: visible !important;
    width: 2.25rem !important;
    z-index: 1000000 !important;
}}
[data-testid="stSidebarCollapseButton"] button,
[data-testid="collapsedControl"] button,
[data-testid="stSidebarCollapsedControl"] button {{
    color: {INK} !important;
    display: inline-flex !important;
    opacity: 1 !important;
    pointer-events: auto !important;
    visibility: visible !important;
}}

/* Expand button: CSS-best-effort (JS in _SIDEBAR_COLLAPSE_JS is authoritative —
   Emotion CSS beats stylesheet !important by source order, JS inline !important wins) */
[data-testid="stExpandSidebarButton"] {{
    align-items: center !important;
    background: {BG} !important;
    border: 1px solid {BORDER} !important;
    border-radius: 6px !important;
    box-shadow: 0 1px 2px rgba(30, 24, 22, 0.08) !important;
    color: {INK} !important;
    cursor: pointer !important;
    display: inline-flex !important;
    height: 2.25rem !important;
    justify-content: center !important;
    left: 0.5rem !important;
    opacity: 1 !important;
    pointer-events: auto !important;
    position: fixed !important;
    top: 0.5rem !important;
    visibility: visible !important;
    width: 2.25rem !important;
    z-index: 1000000 !important;
}}

/* ── Reduced motion ──────────────────────────────────────────── */
@media (prefers-reduced-motion: reduce) {{
    *, *::before, *::after {{
        animation: none !important;
        transition: none !important;
    }}
}}
</style>"""


_SIDEBAR_COLLAPSE_JS = """
<script>
(function() {
  function updateLayout() {
    try {
      var doc = window.parent.document;
      var sidebar = doc.querySelector('[data-testid="stSidebar"]');
      if (!sidebar) return;
      var collapsed = sidebar.getAttribute('aria-expanded') === 'false';
      if (collapsed) {
        sidebar.style.setProperty('width', '0px', 'important');
        sidebar.style.setProperty('min-width', '0px', 'important');
        sidebar.style.setProperty('overflow', 'hidden', 'important');
        sidebar.style.setProperty('border-right', 'none', 'important');
      } else {
        sidebar.style.removeProperty('width');
        sidebar.style.removeProperty('min-width');
        sidebar.style.removeProperty('overflow');
        sidebar.style.removeProperty('border-right');
      }
      var btn = doc.querySelector('[data-testid="stExpandSidebarButton"]');
      if (btn) {
        btn.style.setProperty('position', 'fixed', 'important');
        btn.style.setProperty('top', '0.5rem', 'important');
        btn.style.setProperty('left', '0.5rem', 'important');
        btn.style.setProperty('width', '2.25rem', 'important');
        btn.style.setProperty('height', '2.25rem', 'important');
        btn.style.setProperty('display', 'inline-flex', 'important');
        btn.style.setProperty('align-items', 'center', 'important');
        btn.style.setProperty('justify-content', 'center', 'important');
        btn.style.setProperty('background', '#FFFFFF', 'important');
        btn.style.setProperty('border', '1px solid #E0DEDD', 'important');
        btn.style.setProperty('border-radius', '6px', 'important');
        btn.style.setProperty('box-shadow', '0 1px 2px rgba(30,24,22,0.08)', 'important');
        btn.style.setProperty('opacity', '1', 'important');
        btn.style.setProperty('visibility', 'visible', 'important');
        btn.style.setProperty('pointer-events', 'auto', 'important');
        btn.style.setProperty('cursor', 'pointer', 'important');
        btn.style.setProperty('z-index', '1000000', 'important');
        btn.style.setProperty('color', '#1E1816', 'important');
      }
    } catch(e) {}
  }
  if (window.parent._nhsSidebarFix) clearInterval(window.parent._nhsSidebarFix);
  window.parent._nhsSidebarFix = setInterval(updateLayout, 50);
  updateLayout();
})();
</script>
"""


def inject_global_css() -> None:
    """Inject brand fonts, CSS tokens, and Streamlit overrides.

    Call on every page immediately after st.set_page_config(). Safe to call
    multiple times per page run; duplicate <style> blocks are harmless.
    """
    st.markdown(_CSS, unsafe_allow_html=True)
    components.html(_SIDEBAR_COLLAPSE_JS, height=1, scrolling=False)


def apply_brand_theme(
    fig: go.Figure,
    title: str = "",
    *,
    height: int = 440,
    show_legend: bool = True,
) -> go.Figure:
    """Apply the brand Plotly layout to a figure. Mutates and returns it.

    Layers 'simple_white+nhs_gp_brand': Plotly's clean baseline overridden
    by the project's coral colorway, DM Sans type, JetBrains Mono tick labels,
    and dark tooltip. Sets per-figure title, height, and margin.

    Usage::

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=dates, y=totals, name="All practices"))
        fig.add_trace(go.Scatter(x=dates, y=emis, name="EMIS Web"))
        fig = apply_brand_theme(fig, title="National patient registrations", height=480)
        st.plotly_chart(fig, use_container_width=True)
    """
    fig.update_layout(
        template="simple_white+nhs_gp_brand",
        title=dict(
            text=title,
            font=dict(size=18, color=INK, family=FONT_SANS),
            x=0,
            xanchor="left",
            pad=dict(l=0, b=14),
        ),
        height=height,
        margin=dict(l=0, r=8, t=54 if title else 16, b=16),
        showlegend=show_legend,
    )
    return fig
