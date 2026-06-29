<!-- SEED: re-run /impeccable document once there's code to capture the actual tokens and components. -->

---
name: NHS GP Analytics
description: Automated analytics platform on NHS England GP registration data — evidence-first dashboard with committed coral accent.
---

# Design System: NHS GP Analytics

## 1. Overview

**Creative North Star: "The Evidence Report"**

This dashboard is a serious data instrument that also has to impress. The aesthetic reads as data journalism — the kind of work published by the FT Data team or Observable's notebooks: pure white ground, disciplined typographic hierarchy, a confident primary colour that signals intentionality without shouting. The coral is the apothecary bottle, not the shelf it sits on: warm, considered, and unmistakeable as a brand signature rather than a mood.

The interface disappears when the data is loaded. Charts carry the visual weight; UI chrome exists to navigate and filter, never to perform. A portfolio reviewer who has already sat through ten Tableau dashboards today should pause at this one — not because it's loud, but because every spacing decision and colour choice looks like it was made by someone who cared about the answer.

Streamlit provides the scaffolding; CSS injection provides the character. Font stack, spacing rhythm, sidebar treatment, and chart colour sequences all override the Streamlit defaults. Nothing here reads as "built with Streamlit" — it reads as "built by someone who knows design and chose Streamlit for the right reasons."

**Key Characteristics:**
- Committed coral threading every screen — never absent, never competing with the data
- Pure white content canvas; coral is the accent, not the atmosphere
- Sans for all UI; mono for all data values, codes, and metrics — the pairing is information, not decoration
- Responsive micro-transitions: state changes are smooth, loads acknowledged, nothing jerks
- No decorative chrome — every element earns its place by serving the analysis
- References: Observable, Datawrapper, FT Visual Journalism. Anti-references: default Streamlit, GOV.UK / NHS.uk, Tableau / Power BI.

## 2. Colors: The Coral and Ink Palette

**Strategy: Committed.** The coral carries 30–60% of the interface identity. It appears on active navigation, filter pills, chart primary series, heading accents, and CTA elements — present on every screen, never used decoratively on empty space.

### Primary
- **Coral Anchor** (`oklch(0.590 0.188 35.8)` / `#D1461D`): The brand's visual signature. Active nav items, selected filter chips, primary chart series (always series 1), primary action buttons. White text on any filled coral element — mid-luminance saturation makes dark text muddy, not legible.
- **Deep Coral** (`oklch(0.400 0.160 35.8)` / `#8F3518`): Hover and pressed state for coral-filled elements. Signals direct response to interaction. Same hue, not a different colour.
- **Coral Tint** (`oklch(0.950 0.025 35.8)` / `#FDF0EC`): Active panel highlight, selected sidebar item background, filter pill selected state background. Barely visible as a brand tint; functions as a selection affordance without reading as decoration.

### Neutral
- **Pure White** (`oklch(1.000 0.000 0)` / `#FFFFFF`): Main content canvas. All charts and data tables sit on this surface.
- **Surface** (`oklch(0.972 0.005 36)` / `#F6F4F3`): Sidebar and secondary panel background. Barely perceptible from white without them side by side. Overrides Streamlit's default grey sidebar (`#F0F2F6`) via `config.toml`.
- **Ink** (`oklch(0.140 0.012 36)` / `#1E1816`): All body text, headings, labels, axis text. Near-black with the faintest coral tint — monochromatic-looking but characterful. ≥14:1 contrast on white ✓
- **Muted** (`oklch(0.420 0.010 36)` / `#5C5552`): Secondary labels, axis tick labels, sidebar captions, data source annotations, timestamps. ~5:1 contrast on white ✓
- **Border** (`oklch(0.880 0.006 36)` / `#E0DEDD`): Table grid lines, panel separators, input stroke at rest. Structure without noise.

### Chart Data Series Palette
`[to be finalised at implementation — anchor from coral + cool complements]`
- Series 1: Coral `#D1461D` (always)
- Series 2: Slate blue `oklch(0.420 0.120 240)` / approx. `#3B61A8`
- Series 3: Teal `oklch(0.520 0.100 185)` / approx. `#1A7A78`
- Series 4: Muted plum `oklch(0.480 0.090 295)` / approx. `#6B52A8`
- Diverging (deprivation maps): Coral → neutral grey → slate blue

### Streamlit Theme Configuration
Write `.streamlit/config.toml` with these values before building any page:
```toml
[theme]
primaryColor             = "#D1461D"   # Coral Anchor
backgroundColor          = "#FFFFFF"   # Pure White
secondaryBackgroundColor = "#F6F4F3"   # Surface (sidebar + secondary panels)
textColor                = "#1E1816"   # Ink
font                     = "sans serif"
```

Then load fonts and refine via CSS injection in `dashboard/app.py`:
```python
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,500;0,9..40,600&family=JetBrains+Mono:wght@400;500&display=swap');

html, body, [class*="css"] {
    font-family: 'DM Sans', system-ui, -apple-system, sans-serif;
}
/* Data values, codes, and metric figures get mono */
code, .stCode, [data-testid="stMetricValue"],
[data-testid="stMetricLabel"] { font-family: 'JetBrains Mono', 'Fira Code', monospace; }
</style>
""", unsafe_allow_html=True)
```

**The Committed Thread Rule.** The coral must appear on every screen. If you're designing a page and the coral is absent, something is wrong — find the right element to carry it (active filter, selected nav, chart series 1, section heading accent). Coral's rarity is not the point; its consistency is.

**The Data Colour Rule.** Never use Plotly's default colour sequence. `#636EFA`, `#EF553B`, and `#00CC96` are legible as "default Plotly" at a glance. Set `color_discrete_sequence` or `color_continuous_scale` explicitly on every chart, anchored to the palette above. Start Plotly chart templates from `"simple_white"` — closest to this system's flat, clean baseline.

## 3. Typography: DM Sans + JetBrains Mono

**UI font:** DM Sans — geometric humanist, authoritative without being corporate `[recommended; confirm at implementation]`
**Data / mono font:** JetBrains Mono — clean at 14px, widely available, unmistakeable as "data" `[recommended; confirm at implementation]`

**Character:** A single-family sans handles the full UI hierarchy through weight variation. Mono is reserved exclusively for data — codes, metric values, timestamps, and numeric table cells. The contrast between reading insight prose in DM Sans and encountering an ODS practice code in JetBrains Mono is intentional: it signals "this is a data object, not a label."

### Hierarchy
Per the product register, use a **fixed rem scale** — not fluid/clamped. Streamlit renders at consistent DPI; fluid type makes headings shrink awkwardly in sidebar context.

- **Page Title** (600, 2rem / 32px, lh 1.2): The `st.title()` / `h1` on each dashboard page. Ink. `text-wrap: balance`.
- **Section Heading** (600, 1.5rem / 24px, lh 1.3): Major analytical section headers. May carry a thin 2px full-width coral rule beneath — never a left-stripe.
- **Chart / Panel Heading** (600, 1.125rem / 18px, lh 1.4): Individual chart titles, panel labels.
- **Body / Insight** (400, 1rem / 16px, lh 1.6): Methodology notes, data caveats, analytical commentary. Max 72ch line length.
- **Label / Caption** (500, 0.875rem / 14px): Axis labels, filter labels, sidebar footers, table column headers.
- **Mono — Data cell** (400, 0.875rem / 14px): ODS practice codes, numeric cells, dates in tables. JetBrains Mono.
- **Mono — Featured figure** (500, 1.5rem / 24px): Standalone metric callouts (if used; see Do's and Don'ts).

**The Mono Discipline Rule.** Mono is only for data — codes, numbers, timestamps. Never use it for headings, navigation, prose labels, or any UI copy. The sans/mono contrast is information-carrying. Diluting it with decorative mono use destroys the signal.

## 4. Elevation

The surface is flat by default. Depth is not decoration here; it is functional information. Most UI elements — panels, sidebar, charts, filter bars — sit at the same visual plane as the content canvas, distinguished by `--surface` vs `--bg` background colour and `--border` dividers.

Shadow appears in exactly two contexts: floating UI that genuinely floats above the layer (tooltips, dropdown menus). Even then, the shadow is ambient and minimal.

### Shadow Vocabulary
- **Floating / tooltip** (`box-shadow: 0 2px 8px oklch(0.140 0.012 36 / 0.10), 0 0 1px oklch(0.140 0.012 36 / 0.06)`): The only elevated element. Appears on chart tooltips and any popover. Signals "above the layer," not "important."
- **All panels, cards, sidebar**: no shadow. Background colour distinction and `border: 1px solid #E0DEDD` handle separation.

**The Flat-by-Default Rule.** If an element is not floating above the content layer, it has no shadow. Surface separation is achieved by background colour and borders only. Shadow is a functional signal, not an aesthetic one.

## 5. Components

`[Omitted — seed mode. No components built yet. Re-run /impeccable document once dashboard/app.py and pages are implemented to capture the real component vocabulary.]`

## 6. Do's and Don'ts

### Do:
- **Do** write `.streamlit/config.toml` with `primaryColor = "#D1461D"` and `textColor = "#1E1816"` before building any page — this is the foundation.
- **Do** set Plotly's `color_discrete_sequence` to start with `["#D1461D", "#3B61A8", "#1A7A78", "#6B52A8"]` on every chart. The coral leads every data series.
- **Do** start every Plotly chart from `template="simple_white"` — it removes the default grey gridlines and gives the cleanest baseline.
- **Do** use white text on any filled coral element (buttons, active pills, badge chips). The coral is mid-luminance-saturated; dark text reads as muddy.
- **Do** use JetBrains Mono for ODS practice codes, metric values, and any numeric table cell. The mono font is the signal that says "this is data."
- **Do** add `@media (prefers-reduced-motion: reduce) { * { transition: none !important; animation: none !important; } }` in the CSS injection block.

### Don't:
- **Don't** leave Streamlit defaults in place. The default sidebar colour (`#F0F2F6`), default primary (`#FF4B4B`), and default system font are the "generic Streamlit" anti-reference by name. Every default is overridden.
- **Don't** use GOV.UK / NHS.uk aesthetics — no GDS Transport or Noto Sans font, no `#005EA5` NHS blue, no green NHS header bar. This is a portfolio piece, not an official NHS product, and the difference should be immediately apparent.
- **Don't** use Tableau / Power BI BI-tool patterns — no navy header bars, no KPI card grids with drop-shadow panels and coloured top-stripe borders, no logo watermarks, no "dashboard of dashboards" landing screen.
- **Don't** use Plotly's default colour sequence. `#636EFA` and `#EF553B` are legible at a glance as "no one changed the defaults." Every chart sets its own sequence.
- **Don't** use `border-left: 4px solid #D1461D` on any card, callout, alert, or list item. This is the BI-tool side-stripe anti-pattern in its most recognisable form. Use background tints (`#FDF0EC`), full borders, or nothing.
- **Don't** build the hero-metric template: big number, small label, coloured tile background, four stats in a grid. This is the SaaS cliché and it says nothing. Let the time-series chart and choropleth map carry the analytical weight.
- **Don't** use mono font for headings, navigation labels, sidebar copy, or any prose. The sans/mono contrast is a functional signal; decorative mono use erases it.
- **Don't** use a warm-tinted background (cream, sand, parchment). The warmth of this system lives entirely in the coral. The background is pure `#FFFFFF`, not a warm-neutral approximation of it.
