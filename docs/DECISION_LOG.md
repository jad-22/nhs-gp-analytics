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

---

### DEC-005: Validate Practice Clustering via Stability and Internal Metrics

- Date: 2026-07-09
- Status: Accepted
- Scope: Data Science

Context
- `science/clustering.py` segments practices with K-Means but had no validation beyond
  a narrow silhouette tie-break (`requested ± 1` cluster counts), and the quality score
  was never surfaced.
- k-fold cross-validation cannot be applied: clustering has no ground-truth labels to
  score against on held-out folds.

Decision
- Add clustering diagnostics in `science/cluster_validation.py`: feature correlation
  (redundancy), a full k sweep with silhouette/Davies-Bouldin/inertia (internal
  validity), bootstrap stability via Adjusted Rand Index (the cross-validation
  analogue), and cluster-vs-category association via Cramér's V (confounding).
- Adopt reading thresholds: silhouette < 0.25 = weak structure; mean bootstrap
  ARI < 0.6 = clusters must not be narrated as meaningful segments; Cramér's V > 0.8 =
  the clustering is re-labelling that category.

Rationale
- Bootstrap stability answers the question k-fold answers for supervised models —
  "did we fit noise?" — while respecting that there are no labels.
- Running diagnostics on the production feature pipeline measures what
  `cluster_practices` actually does, rather than an idealised variant.

Impact
- First run (June 2026 snapshot) found: weak-but-stable structure (silhouette ~0.2,
  ARI ~0.99), a dead `AGE_MONTHS` feature (constant 0 on snapshot input), and a
  substantial clinical-system confound (Cramér's V 0.66) caused by one-hot features.
- Findings and recommended fixes are recorded in `docs/CLUSTER_VALIDATION.md`; fixes
  to `science/clustering.py` are deliberately deferred to a follow-up so they can cite
  this evidence.

Implementation Notes
- Diagnostics: `science/cluster_validation.py`; tests: `tests/test_cluster_validation.py`.
- Findings and interpretation: `docs/CLUSTER_VALIDATION.md`; notebook section in
  `notebooks/exploration.ipynb`.

---

### DEC-006: Cluster on Numeric Features Only; Categoricals Become Profiles

- Date: 2026-07-10
- Status: Accepted
- Scope: Data Science

Context
- DEC-005 validation showed the K-Means partition was dominated by the one-hot
  clinical-system/region columns: four of five clusters were 100% pure by clinical
  system (Cramér's V 0.66), making cluster-vs-system observations circular.
- `AGE_MONTHS` was constant (0) on single-snapshot input — a dead feature.
- The silhouette-based k search only examined `requested ± 1`, and the quality score
  was discarded.

Decision
- The K-Means feature matrix uses standardised numeric features only
  (`LOG_PATIENTS`, `IMD_DECILE`, `AGE_MONTHS`); constant columns are dropped
  automatically. Region and clinical system are no longer distance features — they
  are reported as cluster profiles (dominant values) only.
- Widen the k search to 2..requested+2 and surface the winning silhouette as a
  SILHOUETTE_SCORE output column.
- Add `auto_k=False` for consumers that need exactly `n_clusters` segments.

Rationale
- Removing the confound makes cluster→category observations legitimate findings
  rather than echoes of the inputs.
- Measured on the June 2026 snapshot, the fix raised silhouette from 0.225 to 0.398,
  collapsed the clinical-system Cramér's V from 0.66 to 0.02, and kept bootstrap
  stability at ARI ≈ 0.99.

Impact
- With `auto_k` the production cluster count drops to the data-preferred k = 2, so the
  dashboard cluster explorer shows two segments after a cache rebuild; pass
  `auto_k=False` in `scripts/build_dashboard_cache.py` to keep six fixed segments.
- Post-fix numbers: `docs/CLUSTER_VALIDATION.md` §5.

Implementation Notes
- `science/clustering.py` (`_feature_matrix`, `_choose_cluster_count`,
  `cluster_practices`); tests in `tests/test_science.py`.

---

### DEC-007: Calibrate Forecast Intervals from Backtest Errors

- Date: 2026-07-10
- Status: Accepted
- Scope: Data Science

Context
- DEC-004 backtesting showed Prophet's point accuracy is best-in-class here, but its
  nominal-80% uncertainty band covered only ~28-35% of actuals — the dashboard's
  confidence band was materially overconfident.

Decision
- Add conformal-style empirical calibration in `science/backtesting.py`:
  `calibrate_intervals` takes per-horizon quantiles of absolute backtest errors, and
  `apply_interval_calibration` rebuilds the band around the point forecast. Horizons
  beyond the calibrated range reuse the widest known width; lower bounds clip at 0.

Rationale
- Backtest residuals measure the *actual* error distribution at each horizon, so a
  band built from their quantiles attains the nominal level by construction on the
  data it was fitted to, and approximately out of sample.
- Measured on the national series: coverage 0.83 after self-calibration (nominal
  0.80), and 1.0 on a held-out cutoff (vs 0.5 native).

Impact
- Dashboard integration (calibrating the drill-down forecast band during cache build)
  is the follow-up step; until then the native Prophet band remains on the dashboard
  and should be treated as indicative only.

Implementation Notes
- `science/backtesting.py`; tests in `tests/test_backtesting.py`; demo cells in
  `notebooks/exploration.ipynb`; methodology note in `docs/FORECAST_VALIDATION.md`.

---

### DEC-008: Precompute Cluster Partitions for k = 2..10; User-Selectable k

- Date: 2026-07-10
- Status: Accepted
- Scope: Data Science / Dashboard

Context
- DEC-006's `auto_k` follows the silhouette, which picks k = 2 on current data — a
  statistically honest but coarse segmentation for the dashboard cluster explorer.
- K-Means is cheap once features and the UMAP embedding are fixed (both are
  k-independent), so alternative partitions can be precomputed rather than chosen
  once at build time.

Decision
- `cluster_practices_by_k` (science/clustering.py) computes features and UMAP once,
  then fits K-Means for each k in a restricted 2..10 range, returning a long frame
  (one row per practice per K) with per-k SILHOUETTE_SCORE.
- The cache build writes it as `cluster_k.parquet`; the Deprivation Analysis page
  renders a k slider defaulting to the silhouette-best k, with the silhouette shown
  as a caption so users see the quality cost of their choice.

Rationale
- Lets users trade statistical honesty (k = 2) against slicing granularity without a
  rebuild, while the default still follows the evidence.
- Restricting to k ≤ 10 bounds cache size (~9 × practice count rows) and avoids
  offering partitions the silhouette sweep showed to be meaningless.

Impact
- New cache file `cluster_k.parquet`; `cache_health` treats it as required, so
  existing deployments show the rebuild warning until
  `python scripts/build_dashboard_cache.py` is re-run.
- `deprivation_latest.parquet` is unchanged (still carries the auto_k partition) so
  the map, KPIs, and under-served table are unaffected; the page falls back to it if
  the new cache file is missing.

Implementation Notes
- `science/clustering.py` (`cluster_practices_by_k`, `_attach_cluster_profiles`),
  `scripts/build_dashboard_cache.py` (`build_cluster_k`), `dashboard/data.py`
  (`load_cluster_k`), `dashboard/pages/3_Deprivation_Analysis.py`.

---

### DEC-009: Drill-Down Forecasts Get Calibrated Bands and a Model Selector

- Date: 2026-07-10
- Status: Accepted
- Scope: Data Science / Dashboard

Context
- DEC-007 built interval calibration but left the dashboard's practice drill-down
  serving Prophet's native band, which backtesting showed is overconfident.
- DEC-004 established Prophet as the accuracy winner, but users had no way to see the
  baselines it was measured against.

Decision
- `calibrated_forecast` (science/backtesting.py) wraps any forecaster: it backtests
  the series' own history, calibrates the 80% band per horizon, and reports whether
  calibration was feasible (needs ~initial + horizon months of history).
- The drill-down (`practice_history_with_forecast`) uses it and gains a model
  selector: Prophet (recommended/default), linear trend, seasonal naive, and naive.
  The Prophet option is hidden when the package is unavailable, so its label never
  silently serves the linear fallback.
- A caption states whether the band is calibrated or native-indicative.

Rationale
- Per-practice calibration reflects that individual practice series are far noisier
  than the national aggregate — one national calibration would misstate them.
- Measured on a full-history practice: Prophet + calibration completes in ~3 seconds
  (cached per practice/model for an hour); baselines are instant. Short histories
  degrade gracefully to the native band with an honest caption.

Impact
- The dashboard band becomes trustworthy where history allows, and the model choice
  is the user's, with Prophet's recommendation visible rather than imposed.

Implementation Notes
- `science/backtesting.py` (`calibrated_forecast`), `dashboard/data.py`
  (`FORECAST_MODELS`, `forecast_model_options`, `practice_history_with_forecast`),
  `dashboard/pages/1_List_Size_Trends.py`; tests in `tests/test_backtesting.py`.

---

### DEC-013: Move Monthly Ingestion Off GitHub Actions to a Local Scheduled Task

- Date: 2026-08-26
- Status: Accepted
- Scope: Pipeline / Infrastructure

Context
- The July and August 2026 scheduled runs both failed at `fetch_html` with a 403 from
  `digital.nhs.uk`, a page that is plainly present when opened by hand.
- The block is by source IP, not by request shape: from a residential IP the page returns
  200 with the pipeline's own User-Agent, with a Chrome UA, and with a bare `curl/8.x` UA.
  Cloudflare is scoring the runner's Azure range.
- Retrying does not address it. All attempts leave the same runner IP within a few seconds.
- The publication page cannot be bypassed: download URLs carry an opaque per-file hex
  segment (`/45/E255E0/gp-reg-pat-prac-all.zip`) that changes monthly and differs between
  the two files of one publication, so the links must be scraped, not reconstructed.

Decision
- `scripts/local_refresh.ps1` runs ingestion plus the dashboard cache rebuild from a local
  machine and pushes `data/processed/` to `main`, driven by a daily Windows Task Scheduler
  job (`scripts/nhs-gp-monthly-refresh.xml`). Setup is in `docs/LOCAL_REFRESH.md`.
- The `schedule:` trigger is removed from `monthly_pipeline.yml`; `workflow_dispatch`
  stays as a manual fallback.
- A self-hosted runner was rejected: it would have kept the workflow intact, but this
  repository is public and a fork PR can execute arbitrary code on a self-hosted host.

Rationale
- Only the scrape needs a residential IP. `build_dashboard_cache.py` and
  `build_forecast_cache.py` make no network calls, so the expensive work stays on
  GitHub's runners and only ~30 seconds of scraping moves local.
- The task runs daily and no-ops when the month is already ingested on `origin/main`, so a
  machine that is off on publication day catches up on its next run — something a
  once-monthly trigger cannot do.
- The script reads `data/pipeline_log.json` rather than the exit code of `pipeline.monthly`,
  which returns 1 for both `failed` and `not_published`; conflating them would make every
  pre-publication run look like a failure.

Impact
- Monthly refresh depends on a personal machine being switched on at some point in the
  publication window, which is a real availability regression against CI — accepted
  because the CI path cannot reach the source at all.
- Data commits now come from a local identity instead of `github-actions[bot]`.

Implementation Notes
- `scripts/local_refresh.ps1`, `scripts/nhs-gp-monthly-refresh.xml`,
  `docs/LOCAL_REFRESH.md`, `.github/workflows/monthly_pipeline.yml`.
- Commit messages deliberately omit `[skip ci]`, so a future forecast-cache workflow can
  trigger on the data push. That workflow is not wired up yet: `build_forecast_cache.py`
  exists only on the unmerged `feature/statistical-forecasters` branch.
- End-to-end verified from a clean clone: august 2026, 6,129 practices, ~90 seconds,
  100% IMD and geo coverage.

Follow-on Fix
- The first end-to-end run surfaced a second, pre-existing break that the 403 had been
  masking: neither the workflow nor any other step re-ran `scripts/join_enrichment.py`
  after ingestion. A newly ingested month's mapping rows come straight from the NHS
  extract with no IMD or ONSPD columns, so `IMD_DECILE` was entirely NaN for the latest
  snapshot. `build_dashboard_cache.py` then died in `cluster_practices`: `SimpleImputer`
  silently drops an all-NaN column, so the imputed matrix is rebuilt against a column
  index one wider than itself (`Shape of passed values is (6129, 2), indices imply
  (6129, 3)`). Fixing the 403 alone would only have moved the failure one step later.
- `join_enrichment.py` now runs between ingestion and the cache rebuild, in both
  `local_refresh.ps1` and `monthly_pipeline.yml`. It rewrites `data/processed/mapping.parquet`
  in place, re-enriching every month including the new one.
