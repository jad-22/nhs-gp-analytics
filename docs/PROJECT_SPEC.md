# NHS GP Analytics Platform — Project Specification

> **Portfolio project.** End-to-end data engineering + data science + visualisation platform built on open NHS England data. Designed to be publicly hosted, fully automated, and production-quality.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Repo Scaffold](#2-repo-scaffold)
3. [Data Sources](#3-data-sources)
4. [Data Engineering Specification](#4-data-engineering-specification)
5. [Data Model](#5-data-model)
6. [Data Science Modules](#6-data-science-modules)
7. [Dashboard Specification](#7-dashboard-specification)
8. [Pipeline Automation](#8-pipeline-automation)
9. [Stack & Dependencies](#9-stack--dependencies)
10. [Hosting & Deployment](#10-hosting--deployment)
11. [Known Data Caveats](#11-known-data-caveats)
12. [Development Phases](#12-development-phases)

---

## 1. Project Overview

### Purpose

A publicly hosted analytics platform that ingests, processes, and visualises NHS England GP practice registration data. The platform tracks list size trends, clinical system (EMIS vs SystmOne) market share, and deprivation inequality across England's ~6,300 GP practices, with automated monthly data refresh.

### Analytical Modules

| Module | Centrepiece Analysis | DS Technique |
|--------|----------------------|--------------|
| 1 — List Size Trends | Practice growth/decline over time; closure/merger detection | Time series (Prophet), anomaly detection (Z-score / Isolation Forest) |
| 2 — Clinical System Market Share | EMIS Web vs SystmOne vs Others over time by region/ICB | Share-of-market time series, migration signal detection |
| 3 — Deprivation Analysis | Practice size vs IMD deprivation index; under-served area identification | Clustering (K-Means / UMAP), choropleth mapping |

### Key Portfolio Signals

- Automated data pipeline (scraping → transform → Parquet → DuckDB) running on GitHub Actions
- Multi-year time series with Prophet forecasting
- Spatial analysis with choropleth maps (Plotly / Folium)
- Clean Streamlit dashboard hosted on Streamlit Cloud (free tier)
- Annotated data quality handling (NHAIS→PDS source discontinuity, ICB restructures)

---

## 2. Repo Scaffold

### Directory Structure

```
nhs-gp-analytics/
│
├── .github/
│   └── workflows/
│       ├── monthly_pipeline.yml       # Scheduled monthly data ingestion
│       └── backfill.yml               # Manual trigger for historical backfill
│
├── data/
│   ├── raw/                           # Downloaded + extracted CSVs (gitignored if large)
│   │   └── {YYYY}-{MM}-{month-name}/  # e.g. 2026-04-april
│   │       ├── gp-reg-pat-prac-all.csv
│   │       └── gp-reg-pat-prac-map.csv
│   ├── processed/                     # Parquet files committed to repo
│   │   ├── list_size.parquet          # Longitudinal list size (all months)
│   │   └── mapping.parquet            # Longitudinal mapping (all months)
│   ├── enrichment/                    # Static enrichment data (committed)
│   │   ├── imd_2025.parquet           # IMD 2025 deprivation metrics by LSOA
│   │   └── onspd_postcode_lookup.parquet  # ONS postcode → LSOA + lat/lng (trimmed)
│   └── pipeline_log.json              # JSON log of all pipeline runs
│
├── pipeline/
│   ├── __init__.py
│   ├── config.py                      # Constants, stems, month map, paths
│   ├── scraper.py                     # NHS Digital page scraping + download
│   ├── extractor.py                   # ZIP extraction + file discovery
│   ├── transformer.py                 # Clean, normalise, add SNAPSHOT_DATE
│   ├── loader.py                      # Append to Parquet; DuckDB query helpers
│   ├── backfill.py                    # Historical backfill orchestrator
│   ├── monthly.py                     # Entry point for scheduled monthly run
│   └── utils.py                       # Logging, retry decorators, path helpers
│
├── science/
│   ├── __init__.py
│   ├── forecasting.py                 # Prophet time series per practice/region
│   ├── anomaly.py                     # Z-score + Isolation Forest anomaly flags
│   ├── clustering.py                  # K-Means + UMAP practice segmentation
│   └── deprivation.py                 # IMD merge + regression / scatter logic
│
├── dashboard/
│   ├── app.py                         # Streamlit entry point
│   ├── pages/
│   │   ├── 1_List_Size_Trends.py
│   │   ├── 2_Clinical_System_Market_Share.py
│   │   └── 3_Deprivation_Analysis.py
│   └── components/
│       ├── filters.py                 # Shared sidebar filter widgets
│       ├── charts.py                  # Plotly chart factory functions
│       └── maps.py                    # Choropleth / scatter map helpers
│
├── tests/
│   ├── test_scraper.py
│   ├── test_transformer.py
│   └── test_loader.py
│
├── notebooks/
│   └── exploration.ipynb              # EDA scratch space (not deployed)
│
├── scripts/
│   ├── download_enrichment.py         # Stage/download enrichment source files
│   ├── prepare_imd_parquet.py         # Build IMD 2025 parquet
│   ├── extract_onspd_england.py       # Build England-only ONSPD parquet (DuckDB)
│   └── join_enrichment.py             # Join enrichment into mapping parquet
│
├── .gitignore
├── requirements.txt
├── requirements-dev.txt
├── README.md
└── PROJECT_SPEC.md                    # This file
```

### `.gitignore`

```gitignore
# Raw downloaded files (can be large)
data/raw/

# Python
__pycache__/
*.pyc
.env
.venv/
*.egg-info/

# Jupyter
.ipynb_checkpoints/

# OS
.DS_Store
Thumbs.db
```

> **Note:** `data/processed/*.parquet` and `data/enrichment/` **are committed** to the repo. Streamlit Cloud reads them directly. Raw CSVs in `data/raw/` are gitignored to keep repo size manageable — they are only produced transiently during pipeline runs.

---

## 3. Data Sources

### Primary — NHS England Digital

| File | Stem | Format | Frequency |
|------|------|--------|-----------|
| GP List Size (All persons, practice level) | `gp-reg-pat-prac-all` | ZIP → CSV | Monthly |
| GP Organisational Mapping | `gp-reg-pat-prac-map` | ZIP → CSV | Monthly |

**Publication page pattern:**
```
https://digital.nhs.uk/data-and-information/publications/statistical/
patients-registered-at-a-gp-practice/{month}-{year}
```

**Download URL pattern (scraped — hash prefix changes every month):**
```
https://files.digital.nhs.uk/{HASH}/{HASH}/gp-reg-pat-prac-all.zip
https://files.digital.nhs.uk/{HASH}/{HASH}/gp-reg-pat-prac-map.zip
```

> The `files.digital.nhs.uk` hash is not predictable — links must be resolved by scraping the publication page. File stems are stable. Files may be served as `.zip` or `.csv` directly — the pipeline handles both.

**Historical coverage:** Data is available monthly from approximately January 2015. Source system changed from NHAIS to PDS; see Section 11 for handling.

### Enrichment — IMD Deprivation

| Source | File | Description |
|--------|------|-------------|
| DLUHC | `imd_2025.parquet` | English Indices of Multiple Deprivation 2025 — LSOA metrics |
| ONS | `onspd_postcode_lookup.parquet` | Postcode → LSOA11/LSOA21 + lat/lng lookup |

**IMD download:** https://opendatacommunities.org/resource?uri=http://opendatacommunities.org/data/societal-wellbeing/deprivation/indices

**ONSPD download:** https://geoportal.statistics.gov.uk/datasets/ons-postcode-directory

Both are free and open. Source files are staged/downloaded with `scripts/download_enrichment.py`, then preprocessed to Parquet using `scripts/prepare_imd_parquet.py` and `scripts/extract_onspd_england.py`.

**Enrichment preprocessing policy (lean extracts):**
- ONSPD source extracts are large (~1.5GB), so preprocess into a compact England-only lookup before joining.
- ONSPD preprocessing uses DuckDB to scan CSV files via glob and select/filter required columns efficiently.
- Keep only rows where `CTRY25CD=E92000001` i.e. England, where the `LSOA21CD` values are in the range `E01XXXXXX`.
- Keep only these ONSPD columns and rename to canonical names:
  - `pcd7` -> `POSTCODE`
  - `lsoa11cd` -> `LSOA11CD`
  - `lsoa21cd` -> `LSOA21CD`
  - `lat` -> `LATITUDE`
  - `long` -> `LONGITUDE`

**Storage format policy:**
- Persist enrichment assets as Parquet (`imd_2025.parquet`, `onspd_postcode_lookup.parquet`) for typed columns and faster repeated reads.

**IMD retained columns for exploration/visualisation:**
- `LSOA code`
- `LSOA name`
- `Local Authority District code`
- `Local Authority District name`
- `Index of Multiple Deprivation Score`
- `Index of Multiple Deprivation Rank`
- `Index of Multiple Deprivation Decile`
- `Income Score`
- `Income Rank`
- `Income Decile`
- `Employment Score`
- `Employment Rank`
- `Employment Decile`
- `Education Skills and Training Score`
- `Education Skills and Training Rank`
- `Education Skills and Training Decile`
- `Health Deprivation and Disability Score`
- `Health Deprivation and Disability Rank`
- `Health Deprivation and Disability Decile`
- `Crime Score`
- `Crime Rank`
- `Crime Decile`
- `Barriers to Housing and Services Score`
- `Barriers to Housing and Services Rank`
- `Barriers to Housing and Services Decile`
- `Living Environment Score`
- `Living Environment Rank`
- `Living Environment Decile`
- `IDACI Score`
- `IDACI Rank`
- `IDACI Decile`
- `IDAOPI Score`
- `IDAOPI Rank`
- `IDAOPI Decile`

---

## 4. Data Engineering Specification

### 4.1 Scraper (`pipeline/scraper.py`)

**Responsibilities:**
- Build the publication page URL from month + year
- Fetch and parse page HTML with BeautifulSoup
- Locate download links by matching stable file stem in `href` (primary) or anchor link text (fallback)
- Support both `.zip` and `.csv` direct links
- Download with streaming, retries (3x with exponential backoff), and progress logging
- Validate HTTP response codes; raise descriptive errors on failure

**Error handling requirements:**
- `PageNotFoundError` (404): publication not yet released for that month
- `LinksNotFoundError`: page exists but stem-matching links are absent (layout change)
- `DownloadError`: network failure after all retries exhausted
- All errors must be caught and logged to `pipeline_log.json` with timestamp and full URL

### 4.2 Extractor (`pipeline/extractor.py`)

**Responsibilities:**
- Extract ZIP with Zip Slip protection (already in existing script — carry forward)
- Find extracted CSV/XLSX by stem prefix, preferring XLSX > XLS > CSV
- Handle case where NHS serves CSV directly (no ZIP)
- Clean up raw ZIPs post-extraction (default behaviour; `--keep-raw` flag to override)

### 4.3 Transformer (`pipeline/transformer.py`)

**Responsibilities:**
- Read extracted CSV/XLSX into pandas DataFrame
- Normalise column names (strip whitespace, uppercase)
- For list size file: filter to `TYPE=GP`, `SEX=ALL`, `AGE=ALL` (practice-level totals)
- Cast `NUMBER_OF_PATIENTS` to integer
- Add `SNAPSHOT_DATE` column: first day of the month being processed (e.g. `2025-12-01`) as `datetime64`
- Add `DATA_SOURCE` column: `"PDS"` for data from Jan 2023 onwards, `"NHAIS"` for earlier (see Section 11)
- Add `CLINICAL_SYSTEM` column (from `SUPPLIER_NAME` in mapping: `TPP → SystmOne`, `EMIS → EMIS Web`, else `Others`)
- Validate: warn (do not fail) if practice count deviates >5% from previous month

### 4.4 Loader (`pipeline/loader.py`)

**Responsibilities:**
- Append new month's transformed data to existing `data/processed/list_size.parquet` and `data/processed/mapping.parquet`
- Deduplication: if `SNAPSHOT_DATE` + `CODE` already exists in Parquet, overwrite (handles NHS retroactive corrections)
- Expose DuckDB query helpers for the dashboard (returns DataFrames)
- Keep Parquet schema stable across months; add nullable columns if schema evolves

**DuckDB helpers to expose:**
```python
def query(sql: str) -> pd.DataFrame
def get_list_size_ts(practice_code: str | None = None) -> pd.DataFrame
def get_market_share_ts(region: str | None = None) -> pd.DataFrame
def get_latest_snapshot() -> pd.DataFrame  # most recent month, merged list+map
```

### 4.5 Pipeline Log (`data/pipeline_log.json`)

Each run appends a record:
```json
{
  "run_at": "2026-01-15T09:00:00Z",
  "month": "december",
  "year": 2025,
  "status": "success",
  "totals_url": "https://files.digital.nhs.uk/40/58F467/gp-reg-pat-prac-all.zip",
  "mapping_url": "https://files.digital.nhs.uk/F5/3E6C88/gp-reg-pat-prac-map.zip",
  "practices_ingested": 6324,
  "error": null
}
```

---

## 5. Data Model

### `list_size.parquet`

| Column | Type | Source | Notes |
|--------|------|--------|-------|
| `SNAPSHOT_DATE` | `date` | Derived | First day of publication month |
| `CODE` | `str` | Raw | Practice ODS code (primary key per snapshot) |
| `NUMBER_OF_PATIENTS` | `int` | Raw | Total registered patients |
| `DATA_SOURCE` | `str` | Derived | `PDS` or `NHAIS` |

### `mapping.parquet`

| Column | Type | Source | Notes |
|--------|------|--------|-------|
| `SNAPSHOT_DATE` | `date` | Derived | First day of publication month |
| `PRACTICE_CODE` | `str` | Raw | ODS code — joins to `list_size.CODE` |
| `PRACTICE_NAME` | `str` | Raw | |
| `POSTCODE` | `str` | Raw | Used for IMD + geo enrichment |
| `PCN_CODE` | `str` | Raw | |
| `PCN_NAME` | `str` | Raw | |
| `ICB_CODE` | `str` | Raw | |
| `ICB_NAME` | `str` | Raw | |
| `COMM_REGION_CODE` | `str` | Raw | |
| `COMM_REGION_NAME` | `str` | Raw | |
| `SUPPLIER_NAME` | `str` | Raw | `EMIS`, `TPP`, or other |
| `CLINICAL_SYSTEM` | `str` | Derived | `EMIS Web`, `SystmOne`, `Others` |
| `LSOA_CODE` | `str` | Enrichment (ONSPD) | England-only postcode to LSOA lookup key |
| `IMD_SCORE` | `float` | Enrichment | Joined from IMD via LSOA lookup |
| `IMD_RANK` | `int` | Enrichment | National IMD rank |
| `IMD_DECILE` | `int` | Enrichment | 1 = most deprived, 10 = least |
| `LSOA_NAME` | `str` | Enrichment | IMD LSOA name |
| `LAD_CODE` | `str` | Enrichment | Local Authority District code |
| `LAD_NAME` | `str` | Enrichment | Local Authority District name |
| `INCOME_SCORE` | `float` | Enrichment | IMD domain metric |
| `INCOME_RANK` | `int` | Enrichment | IMD domain metric |
| `INCOME_DECILE` | `int` | Enrichment | IMD domain metric |
| `EMPLOYMENT_SCORE` | `float` | Enrichment | IMD domain metric |
| `EMPLOYMENT_RANK` | `int` | Enrichment | IMD domain metric |
| `EMPLOYMENT_DECILE` | `int` | Enrichment | IMD domain metric |
| `EDUCATION_SKILLS_TRAINING_SCORE` | `float` | Enrichment | IMD domain metric |
| `EDUCATION_SKILLS_TRAINING_RANK` | `int` | Enrichment | IMD domain metric |
| `EDUCATION_SKILLS_TRAINING_DECILE` | `int` | Enrichment | IMD domain metric |
| `HEALTH_DEPRIVATION_DISABILITY_SCORE` | `float` | Enrichment | IMD domain metric |
| `HEALTH_DEPRIVATION_DISABILITY_RANK` | `int` | Enrichment | IMD domain metric |
| `HEALTH_DEPRIVATION_DISABILITY_DECILE` | `int` | Enrichment | IMD domain metric |
| `CRIME_SCORE` | `float` | Enrichment | IMD domain metric |
| `CRIME_RANK` | `int` | Enrichment | IMD domain metric |
| `CRIME_DECILE` | `int` | Enrichment | IMD domain metric |
| `BARRIERS_HOUSING_SERVICES_SCORE` | `float` | Enrichment | IMD domain metric |
| `BARRIERS_HOUSING_SERVICES_RANK` | `int` | Enrichment | IMD domain metric |
| `BARRIERS_HOUSING_SERVICES_DECILE` | `int` | Enrichment | IMD domain metric |
| `LIVING_ENVIRONMENT_SCORE` | `float` | Enrichment | IMD domain metric |
| `LIVING_ENVIRONMENT_RANK` | `int` | Enrichment | IMD domain metric |
| `LIVING_ENVIRONMENT_DECILE` | `int` | Enrichment | IMD domain metric |
| `IDACI_SCORE` | `float` | Enrichment | IMD supplementary indicator |
| `IDACI_RANK` | `int` | Enrichment | IMD supplementary indicator |
| `IDACI_DECILE` | `int` | Enrichment | IMD supplementary indicator |
| `IDAOPI_SCORE` | `float` | Enrichment | IMD supplementary indicator |
| `IDAOPI_RANK` | `int` | Enrichment | IMD supplementary indicator |
| `IDAOPI_DECILE` | `int` | Enrichment | IMD supplementary indicator |
| `LATITUDE` | `float` | Enrichment | From ONSPD postcode lookup |
| `LONGITUDE` | `float` | Enrichment | From ONSPD postcode lookup |

---

## 6. Data Science Modules

### 6.1 Time Series Forecasting (`science/forecasting.py`)

**Input:** `list_size.parquet` filtered to a practice or region  
**Method:** Facebook Prophet — handles seasonality and NHS structural breaks (April ICB restructures)  
**Output:** 12-month forecast with confidence intervals as DataFrame  
**Change points:** Mark NHAIS→PDS transition and known April restructure dates as Prophet change points  
**Scope:** Run at region level by default (practice-level too slow for real-time dashboard — pre-compute for top practices)

```python
def forecast_list_size(
    df: pd.DataFrame,       # time series for one entity
    periods: int = 12,      # months ahead
    changepoints: list[str] | None = None
) -> pd.DataFrame           # columns: ds, yhat, yhat_lower, yhat_upper
```

### 6.2 Anomaly Detection (`science/anomaly.py`)

**Input:** `list_size.parquet` — month-over-month change per practice  
**Methods:**
- Z-score on `MOM_CHANGE_PCT`: flag practices where `|z| > 3` as anomalous
- Isolation Forest on `[NUMBER_OF_PATIENTS, MOM_CHANGE_PCT, MOM_CHANGE_ABS]` for multivariate detection

**Anomaly categories to label:**
- `CLOSURE_SUSPECTED`: list size drops >80% in one month
- `MERGER_SUSPECTED`: practice disappears while a nearby practice grows proportionally
- `SPIKE`: unexplained large increase (possible data correction)
- `GRADUAL_DECLINE`: consistent downward trend over 6+ months

```python
def flag_anomalies(df: pd.DataFrame) -> pd.DataFrame  # adds ANOMALY_TYPE column
```

### 6.3 Clustering (`science/clustering.py`)

**Input:** Latest snapshot merged list + mapping  
**Features:** `NUMBER_OF_PATIENTS`, `IMD_DECILE`, `COMM_REGION_NAME`, `CLINICAL_SYSTEM`, practice age (derived from first appearance in time series)  
**Method:** K-Means (k=5–7, silhouette-optimised) with UMAP for 2D visualisation  
**Output:** Cluster label + cluster profile summary per practice

```python
def cluster_practices(df: pd.DataFrame, n_clusters: int = 6) -> pd.DataFrame
def umap_embed(df: pd.DataFrame) -> pd.DataFrame  # adds UMAP_X, UMAP_Y
```

### 6.4 Deprivation Analysis (`science/deprivation.py`)

**Input:** `mapping.parquet` latest snapshot (with IMD joined)  
**Analyses:**
- Scatter: list size vs IMD score, colour by region
- Under-served flag: `IMD_DECILE <= 3` AND `NUMBER_OF_PATIENTS < national_median`
- Pearson correlation: list size vs IMD decile by region
- Regional inequality index: Gini coefficient of list sizes within each IMD decile band

```python
def flag_underserved(df: pd.DataFrame) -> pd.DataFrame
def regional_inequality(df: pd.DataFrame) -> pd.DataFrame
```

---

## 7. Dashboard Specification

### Entry Point (`dashboard/app.py`)

- Streamlit multi-page app
- Global sidebar: date range selector (min: earliest snapshot, max: latest), region filter, ICB filter
- Cache data loads with `@st.cache_data(ttl=3600)`
- Show last pipeline run date + practices in current dataset in sidebar footer

### Page 1 — List Size Trends

**Sections:**

1. **National headline** — total registered patients over time (line chart)
2. **Regional breakdown** — multi-line chart, one line per NHS region
3. **Practice drill-down** — search by practice name or ODS code → show practice time series + 12-month Prophet forecast with confidence band
4. **Anomaly table** — filterable table of flagged practices (closures, mergers, spikes) with export to CSV
5. **EMIS vs SystmOne overlay** — toggle to colour time series lines by clinical system

**Charts:** Plotly `go.Scatter` with rangeslider; Plotly `go.Table` for anomaly list

### Page 2 — Clinical System Market Share

**Sections:**

1. **National share over time** — stacked area chart (EMIS Web / SystmOne / Others) as % of practices
2. **Share by patient count** — same but weighted by `NUMBER_OF_PATIENTS`
3. **Regional heatmap** — Plotly heatmap: regions × clinical system → current share %
4. **Practice size distribution by system** — violin plot: list size distribution per clinical system
5. **Migration signals** — table of practices that changed `SUPPLIER_NAME` between snapshots

### Page 3 — Deprivation Analysis

**Sections:**

1. **Practice marker map** — England practice locations coloured by `IMD_DECILE`; boundary choropleths deferred to a later GeoJSON phase
2. **Scatter plot** — `NUMBER_OF_PATIENTS` (y) vs `IMD_SCORE` (x), colour by region, size by list size
3. **Under-served practices** — filterable table: deprived area + small practice flag
4. **Cluster explorer** — UMAP 2D plot with cluster labels; cluster profile cards (avg size, avg IMD, dominant system, region)
5. **Inequality trends** — Gini coefficient of list sizes within each IMD decile, over time (line chart)

**Maps:** Phase 3 uses lightweight Plotly practice marker maps from cached latitude/longitude enrichment. Boundary GeoJSON choropleths are deferred to a later phase so Phase 3 can ship without adding a large boundary asset or network-dependent GeoJSON fetch path. Later choropleth work should source ICB boundaries from the ONS Open Geography Portal and commit a trimmed, dashboard-ready boundary asset.

### Phase 3 Implementation Status

Phase 3 is complete as of 2026-06-30. The delivered dashboard includes:

- Streamlit multi-page entry point in `dashboard/app.py`
- Shared dashboard components in `dashboard/components/`
- Cached data loading and lightweight transformations in `dashboard/data.py`
- List Size Trends page with national/regional trend views, practice drill-down forecasting, and anomaly table support
- Clinical System Market Share page with practice/patient share views, regional comparisons, distribution views, and migration signals
- Deprivation Analysis page with practice marker maps, IMD scatter analysis, under-served practice table, cluster explorer, correlations, and inequality trends
- Dashboard cache builder in `scripts/build_dashboard_cache.py`
- Dashboard-ready Parquet outputs in `data/processed/dashboard/`

Run locally with:

```bash
python scripts/build_dashboard_cache.py
python -m streamlit run dashboard/app.py
```

---

## 8. Pipeline Automation

See `PIPELINE_IMPLEMENTATION_PLAN.md` for the full GitHub Actions specification.

**Summary:**
- Monthly cron trigger: 2nd Thursday of each month at 10:00 UTC (NHS Digital publishes ~2nd Thursday)
- Workflow: scrape → download → extract → transform → append to Parquet → commit → push
- On failure: create GitHub Issue with error detail; retry next day
- Manual trigger: `workflow_dispatch` with `month` and `year` inputs (for backfill or reruns)

---

## 9. Stack & Dependencies

### `requirements.txt`

```
# Pipeline
requests>=2.31.0
beautifulsoup4>=4.12.0
lxml>=5.0.0
pandas>=2.1.0
pyarrow>=14.0.0
duckdb>=0.10.0
openpyxl>=3.1.0

# Data science
prophet>=1.1.5
scikit-learn>=1.4.0
umap-learn>=0.5.6
scipy>=1.12.0

# Dashboard
streamlit>=1.32.0
plotly>=5.20.0
folium>=0.16.0
streamlit-folium>=0.18.0

# Enrichment / geo
geopandas>=0.14.0
shapely>=2.0.0
```

### `requirements-dev.txt`

```
pytest>=8.0.0
pytest-cov>=4.1.0
black>=24.0.0
ruff>=0.3.0
jupyter>=1.0.0
ipykernel>=6.29.0
```

### Runtime

| Component | Platform | Cost |
|-----------|----------|------|
| Pipeline (scheduled) | GitHub Actions | Free (2,000 min/month) |
| Data storage | GitHub repo (Parquet) | Free |
| Dashboard hosting | Streamlit Cloud | Free |
| Database | DuckDB (in-process) | Free |

---

## 10. Hosting & Deployment

### Streamlit Cloud

1. Push repo to GitHub (public)
2. Connect at https://share.streamlit.io
3. Set entry point: `dashboard/app.py`
4. No secrets required (all data is public Parquet in repo)
5. Streamlit Cloud auto-redeploys on every push to `main`

### GitHub Actions Pipeline

The monthly workflow commits updated Parquet files back to `main`. This triggers a Streamlit Cloud redeploy automatically, so new data is live within minutes of the pipeline completing.

### Environment Variables (GitHub Actions only)

| Variable | Purpose |
|----------|---------|
| `NHS_PIPELINE_EMAIL` | Optional: email for NHS Digital user-agent header |
| `GH_PAT` | GitHub PAT with `contents: write` scope — for committing Parquet back to repo |

---

## 11. Known Data Caveats

These must be documented on the dashboard with info tooltips or a dedicated "About the data" page.

| Caveat | Detail | Handling |
|--------|--------|---------|
| **NHAIS → PDS source change** | Data source changed ~early 2023; causes a discontinuity in some metrics | `DATA_SOURCE` column; Prophet change point; visual annotation on charts |
| **April ICB restructures** | NHS geography changes on 1 April each year; ICB codes/names may change | Re-map to a stable historical ICB reference table; annotate April datapoints |
| **List inflation** | Registered patients exceeds census population — known ghost patient issue | Note in dashboard; not corrected (use raw NHS figures) |
| **Retroactive file corrections** | NHS Digital patches earlier months' files after publication (e.g. ICB mapping errors) | Upsert-on-reload logic in loader; re-run pipeline for patched months |
| **Practice closures vs data gaps** | A practice disappearing from data may be closure, merger, or data issue | Anomaly detection distinguishes; label as `SUSPECTED` not confirmed |
| **Quarterly LSOA data** | LSOA breakdowns only published in Jan/Apr/Jul/Oct | Not used in this pipeline (practice-level only) |

---

## 12. Development Phases

### Phase 1 — Data Foundation (Week 1–2)

- [x] Set up repo structure
- [x] Run `backfill.py` to download all historical months
- [x] Build `transformer.py` and produce `list_size.parquet` + `mapping.parquet`
- [x] Download and join enrichment data (IMD + ONSPD)
- [x] Validate: row counts, schema, date range, no duplicate snapshots

Status note (2026-06-28): `pipeline/scraper.py`, `pipeline/transformer.py`, `pipeline/loader.py`, and `pipeline/backfill.py` are implemented and operating with enrichment joins in place. Phase 1 validation (`scripts/validate_phase1.py`) now passes with schema checks, duplicate-key checks, and snapshot coverage confirmed (`2020-01-01` to `2026-06-01`) for both processed parquet outputs.

### Phase 2 — Data Science (Week 2–3)

- [x] Build `forecasting.py` — Prophet on national + regional series
- [x] Build `anomaly.py` — Z-score + Isolation Forest flags
- [x] Build `clustering.py` — K-Means + UMAP
- [x] Build `deprivation.py` — IMD merge, under-served flags, Gini
- [x] Validate outputs in `notebooks/exploration.ipynb`

Status note (2026-06-29): Phase 2 helper modules are implemented and covered by focused tests in `tests/test_science.py`. Full test suite passes (`15 passed`), and clustering has been smoke-tested against the latest processed snapshot after adding compatibility for older scikit-learn releases. Remaining work before Phase 3 is to decide whether to precompute/cache heavy science outputs to Parquet for dashboard performance.

### Phase 3 — Dashboard (Week 3–4)

- [x] Build `dashboard/app.py` skeleton + shared sidebar filters
- [x] Page 1: List Size Trends (time series + forecast + anomaly table)
- [x] Page 2: Clinical System Market Share (stacked area + heatmap + violin)
- [x] Page 3: Deprivation Analysis (practice marker map + scatter + cluster explorer)
- [ ] Deploy to Streamlit Cloud; test on public URL

Scope note (2026-06-30): GeoJSON boundary choropleths are intentionally deferred to a later phase. Phase 3 should use cached practice latitude/longitude markers for spatial context and avoid adding ICB/LSOA boundary assets until a dedicated boundary-data task is planned.

Status note (2026-06-30): Phase 3 local implementation is complete. The Streamlit app, dashboard pages, shared components, cached data loader, and dashboard cache builder are implemented. Dashboard cache files are committed under `data/processed/dashboard/` and the app runs locally with `python -m streamlit run dashboard/app.py`. Public Streamlit Cloud deployment remains a hosting task.

### Phase 4 — Pipeline Automation (Week 4)

- [ ] Build `pipeline/monthly.py` entry point
- [ ] Write `monthly_pipeline.yml` GitHub Actions workflow
- [ ] Test manual `workflow_dispatch` trigger
- [ ] Verify commit-back and Streamlit redeploy on push

### Phase 5 — Polish (Week 4–5)

- [ ] Write `README.md` (project story, architecture diagram, live demo link)
- [ ] Add "About the data" page in dashboard with caveats
- [ ] Add `tests/` with at minimum scraper + transformer coverage
- [ ] Performance: cache heavy DS computations to disk (pre-computed Parquet outputs)
- [ ] Add `pipeline_log` display to dashboard sidebar
