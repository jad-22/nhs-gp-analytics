# Decision Log

This log records key project decisions that affect data conventions, pipeline behaviour, and long-term maintainability.

## Status Legend

- Proposed: under discussion, not yet implemented
- Accepted: approved and implemented
- Superseded: replaced by a newer decision

## How to Add a New Decision

When introducing a significant change, add a new `DEC-XXX` entry with:

- Date, status, and scope
- Context (problem being solved)
- Decision (what was chosen)
- Rationale (why this option)
- Impact (what changes downstream)
- Implementation notes (where it is reflected)

## Decision Entries

### DEC-001: Standardise Raw Data Folder Naming

- Date: 2026-06-28
- Status: Accepted
- Scope: Data Engineering

Context
- Raw data folder naming was inconsistent and harder to sort chronologically when using names like `january-2026`.

Decision
- Standardise raw snapshot folder naming to `YYYY-MM-month-name`.
- Example: `2026-01-january`.

Rationale
- Ensures lexical sort order equals chronological order.
- Improves discoverability for manual inspection and debugging.
- Reduces ambiguity when scripting month/year targeting.

Impact
- Existing and new raw snapshot folders should follow the standard format.
- Pipeline utilities that read raw snapshot paths should assume the standard format.

Implementation Notes
- Reflected in project documentation and repository raw data structure examples.

---

### DEC-002: Preprocess Enrichment Data (ONSPD and IMD) Before Join

- Date: 2026-06-28
- Status: Accepted
- Scope: Data Engineering / Analytics

Context
- Upstream ONSPD data is extremely large and contains fields and rows not needed for this project.
- Carrying full raw enrichment datasets increases storage footprint and slows join steps.

Decision
- Introduce preprocessing for ONSPD and IMD before enrichment joins.
- Keep only columns and rows required for analytics and mapping workflows.

Rationale
- Keeps the repository and runtime data footprint lean.
- Improves join performance and memory efficiency.
- Simplifies downstream transformations by enforcing canonical enrichment schemas.

Impact
- Enrichment join steps now depend on preprocessed, scoped enrichment files.
- Any future enrichment refresh should run through the same preprocessing policy.

Implementation Notes
- ONSPD is filtered to England and required columns only.
- IMD is retained with selected metrics used in deprivation analysis and visualisation.
- Detailed retained-column policy is documented in `docs/PROJECT_SPEC.md`.

---

### DEC-003: Use DuckDB + Parquet for Enrichment Preprocessing

- Date: 2026-06-28
- Status: Accepted
- Scope: Data Engineering / Analytics

Context
- ONSPD source extracts are large (approximately 1.5GB) and expensive to process as fully materialised pandas DataFrames.
- Enrichment assets are read repeatedly by pipeline and analysis steps; CSV re-parsing adds avoidable overhead.

Decision
- Use DuckDB for ONSPD preprocessing to query large CSV inputs via glob, select required columns, filter to England, and write Parquet.
- Store both ONSPD and IMD enrichment assets as Parquet.
- Keep both `lsoa11cd` and `lsoa21cd` in the ONSPD extract to improve join compatibility with IMD.
- Note: Polars remains a possible alternative for future lazy-processing exploration.

Rationale
- DuckDB provides efficient scan/query behaviour for large tabular inputs without eagerly materialising all rows in memory.
- Parquet preserves typed columns and improves read performance versus repeated CSV parsing.
- Retaining both LSOA vintages reduces mismatch risk across enrichment datasets.

Impact
- Enrichment preprocessing and join scripts are Parquet-first.
- Enrichment defaults are updated to IMD 2025 assets.
- Downstream consumers can rely on typed enrichment files and dual LSOA keys.

Implementation Notes
- ONSPD preprocessing script: `scripts/extract_onspd_england.py`.
- IMD preprocessing script: `scripts/prepare_imd_parquet.py`.
- Enrichment join script: `scripts/join_enrichment.py`.

---

### DEC-004: Validate Forecast Accuracy via Rolling-Origin Backtesting

- Date: 2026-07-09
- Status: Accepted
- Scope: Data Science

Context
- `science/forecasting.py` uses Prophet for 12-month list-size forecasts, but the choice
  was justified qualitatively (changepoint support for NHS structural breaks,
  interpretability) with no quantitative evidence.
- Published benchmarks show Prophet is often beaten by simpler models (ETS, Theta,
  seasonal naive) on generic series, so the accuracy claim must be measured.

Decision
- Add a model-agnostic rolling-origin (expanding-window) backtesting harness in
  `science/backtesting.py` with naive, seasonal-naive, and linear baselines.
- Adopt MASE (vs seasonal naive) as the primary accuracy metric, with MAE, RMSE, MAPE,
  and prediction-interval coverage as secondary metrics.
- Any candidate forecaster must beat seasonal naive (MASE < 1) to be considered; prefer
  the simplest model within noise of the best.

Rationale
- Rolling-origin evaluation mirrors real dashboard use (forecast 12 months from a past
  cutoff, compare against actuals) and avoids judging models on in-sample fit.
- MASE is scale-free, so results are comparable across national, regional, and
  practice-level series of very different sizes.
- A shared harness lets Prophet, its linear fallback, and future candidates
  (AutoETS, AutoARIMA, Theta) be compared under identical conditions.

Impact
- Forecast model choice becomes evidence-based; Prophet keeps its place only while it
  beats the baselines on backtested MASE.
- Future model candidates plug into `compare_models` as simple callables without
  changes to the harness.

Implementation Notes
- Harness and baselines: `science/backtesting.py`; tests: `tests/test_backtesting.py`.
- Methodology and model-selection protocol: `docs/FORECAST_VALIDATION.md`.
