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

### DEC-010: Classical Statistical Forecasters Join the Registry

- Date: 2026-07-11
- Status: Accepted
- Scope: Data Science / Dashboard

Context
- `docs/FORECAST_VALIDATION.md` §2 named ETS, ARIMA/SARIMA, and AutoETS as Prophet's
  stiffest competition on smooth monthly administrative data, but none were
  implemented — the DEC-004 verdict rested on Prophet vs the harness baselines only.

Decision
- `science/stat_forecasting.py` implements four classical models behind the existing
  `Forecaster` contract: Holt-Winters (statsmodels state-space `ETSModel`, additive,
  12-month season), ARIMA(1,1,1) with drift, the airline SARIMA (0,1,1)(0,1,1)12,
  and statsforecast's `AutoETS` (AICc-selected ETS variant).
- All follow the Prophet guards: linear fallback below 24 months of history or on a
  failed fit, and excluded from `default_forecasters()` / the dashboard selector
  when their library is not installed, so a fallback is never scored or served
  under a real model's name.
- The dashboard drill-down offers all four alongside Prophet and the baselines; the
  DEC-007 calibration wraps whichever model the user picks.

Rationale (measured, rolling-origin backtest on real data)
- National (78 months): Holt-Winters MASE 0.211 ties Prophet 0.213, with far better
  native coverage (0.65 vs 0.35 at nominal 0.80); ARIMA 0.227, AutoETS 0.250.
- Regional medians: Holt-Winters 0.183, ARIMA 0.195, AutoETS 0.197, Prophet 0.198;
  Prophet and Holt-Winters win three regions each, ARIMA one.
- The airline SARIMA loses badly (regional median 1.289 — behind seasonal naive):
  its seasonal differencing amplifies the 2023 NHAIS→PDS structural break.

Impact
- The DEC-004 verdict is now measured against its full candidate table. Prophet stays
  the recommended default for the moment (changepoint support, established docs),
  but Holt-Winters ties or edges it — whether the DEC-004 "simplest model within
  noise" rule should hand it the recommendation is an open product decision.

Implementation Notes
- `science/stat_forecasting.py`; registry hooks in `science/backtesting.py`
  (`default_forecasters`) and `dashboard/data.py` (`FORECAST_MODELS`,
  `_MODEL_REQUIREMENTS`); `requirements.txt` gains statsmodels + statsforecast;
  tests in `tests/test_stat_forecasting.py`.

---

### DEC-011: AutoETS Becomes the Practice-Level Default; Prophet Retired as Default

- Date: 2026-08-04
- Status: Accepted
- Scope: Data Science / Dashboard
- Supersedes: the open question left by DEC-010 ("Prophet stays the recommended
  default for the moment")

Context
- DEC-004 and DEC-010 both selected models using the backtest evidence available at
  the time: **one national series and seven regional series**. The dashboard
  drill-down and the planned open API both serve *individual practices*, and no
  practice had ever been backtested. The verdict was being generalised from 8
  aggregate series to 6,145 practices.
- Prophet is also absent from the working Anaconda environment, and
  `forecast_list_size` silently returns the linear fallback when it is missing — so
  any local "Prophet" timing or accuracy figure taken there was measuring a trend line.

Decision
- **AutoETS is the default forecaster for practice-level and PCN-level series.**
  Holt-Winters remains the choice for ICB, regional and national series.
- **Prophet is no longer the default anywhere.** It stays in `FORECAST_MODELS` and
  `default_forecasters()` for comparison.
- The dashboard drill-down selector now lists `AutoETS (recommended)` first;
  `dashboard/data.py` gains `DEFAULT_FORECAST_MODEL` and `default_forecast_model()`
  so the default is stated once rather than implied by dict ordering, and degrades to
  an available model when statsforecast is missing (preserving the DEC-009 guard).

Rationale (measured; full methodology in `docs/FORECAST_VALIDATION.md` §7)
- Run in an isolated venv with Prophet 1.3.0 installed and verified; the harness first
  reproduced DEC-010's §6 numbers exactly, then extended to 999 size-stratified
  practices, 120 PCNs and all 36 ICBs.
- **The ranking reverses with aggregation level.** Median MASE — practice: AutoETS
  0.525, ARIMA 0.552, Holt-Winters 0.594, Prophet 0.723. PCN: AutoETS 0.389, ARIMA
  0.478, naive 0.518, Holt-Winters 0.536, Prophet 0.629. Holt-Winters still wins ICB
  (0.272), region (0.183) and national (0.211). **Practices and PCNs are 99.4% of all
  forecastable series.**
- **Prophet fails the §4 protocol**: it loses to the plain naive baseline at both
  practice (0.723 vs 0.630) and PCN (0.629 vs 0.518) level. Paired, AutoETS beats it on
  80.5% of practices (median −25.6%) and 89.2% of PCNs (median −30.2%), Wilcoxon
  p ≈ 1e-57. It exceeds MASE 1 on 33.8% of practices vs AutoETS 17.0%.
- **Prophet's stated justification does not hold.** At the 2022-12 cutoff — the one
  forecasting through the NHAIS→PDS break — Prophet is the worst of the three tested
  models at every level. `_default_changepoints` only injects `PDS_START` when it lies
  inside the *training* range, so at that cutoff Prophet has no PDS changepoint at all;
  changepoints help retrospectively, not for forecasting through a coming break.
- **Cost is not the driver.** Per series (6-cutoff backtest + fit): AutoETS 0.94s,
  Holt-Winters 2.35s, Prophet 3.58s. Prophet is only ~1.5× slower than Holt-Winters.
  AutoETS is both the most accurate at practice level and the cheapest of the three.
- **ARIMA is excluded despite ranking 2nd**: it diverges on 15 of 999 practices, max
  MASE 2.3 × 10¹⁰.
- **Per-series model selection was tested and rejected**: 0.6% median gain, winning on
  only 37% of practices, at 6.8× the compute.

Impact
- Practice forecasts shown in the dashboard change. They are more accurate on ~73–80%
  of practices, but any figure previously screenshotted or quoted from the drill-down
  will differ.
- Interval semantics are unchanged (DEC-007 calibration still wraps whichever model is
  selected), but §7.5 establishes that the calibrated 80% band delivers **≈74%**
  coverage out of sample; §5's 0.83 is self-calibrated and optimistic. Dashboard copy
  now says so.
- The planned open API precomputes AutoETS for practices/PCNs and Holt-Winters for
  aggregates, and records `MODEL` per row so consumers never have to infer it.

Implementation Notes
- `dashboard/data.py` (`FORECAST_MODELS` ordering and labels, `DEFAULT_FORECAST_MODEL`,
  `default_forecast_model`, `_MODEL_REQUIREMENTS`, `practice_history_with_forecast`);
  `dashboard/pages/1_List_Size_Trends.py` (selector help text and drill-down copy);
  tests in `tests/test_stat_forecasting.py`; methodology and full results in
  `docs/FORECAST_VALIDATION.md` §7.
- No change to `science/` — `rolling_origin_backtest`, `score_backtest`,
  `calibrate_intervals` and `apply_interval_calibration` were used as-is.

---

### DEC-012: Serve Forecasts from a Precomputed Artifact, Not On Demand

- Date: 2026-08-04
- Status: Accepted
- Scope: Data Science / API
- Related: DEC-007 (interval calibration), DEC-009 (silent-fallback guard), DEC-011
  (per-level model choice)

Context
- The repo had no forecast artifact of any kind. Forecasts existed only inside a running
  Streamlit process, memoised in memory: no Parquet, no metrics, no model metadata, no
  run timestamp. Nothing outside the dashboard could reach them.
- A public API cannot fit models per request. `calibrated_forecast()` runs a six-cutoff
  rolling-origin backtest and then fits again — seven fits, measured at 0.94s per series
  for AutoETS. On an unauthenticated endpoint that is a denial-of-service vector: an
  attacker simply requests 6,145 distinct ODS codes.

Decision
- **Precompute every served series into two committed Parquet files** —
  `data/processed/forecasts.parquet` (12 rows per entity) and
  `forecast_metrics.parquet` (1 row per entity) — built by
  `scripts/build_forecast_cache.py` and refreshed monthly in CI as a job separate from
  the data pipeline.
- **Compile those into `serving.duckdb` at Docker build time**
  (`scripts/build_serving_db.py`). Parquet stays the source of truth because git can
  diff it; the DuckDB file is a build artifact and is git-ignored.
- **The serving image contains no forecasting library.** Not statsforecast, not
  statsmodels, not Prophet. It cannot fit a model even by accident.
- **Aggregate membership is fixed at each practice's latest known assignment** and
  applied to its whole history.

Rationale
- Cost is not the obstacle: the full 7,488-series build takes about 15 minutes on six
  workers, well inside the CI budget. A hybrid cache-on-call design was considered and
  rejected — it would add ~800 MB of forecasting libraries to the image, require a
  writable volume, make results depend on when a code was first requested, and leave the
  1–3s uncached path exposed.
- A separate SQL server buys nothing: the workload is read-only, single-node, refreshed
  monthly, and the whole dataset fits in page cache. But a native DuckDB file with
  indexes still beats querying Parquet directly — measured 1.0 ms versus 6.0 ms for a
  point lookup, and the 14.8 ms practice-to-geography join disappears entirely.
- Fixed membership is the only definition available at ICB level (`ICB_CODE` exists only
  from 2022-07) and is what the DEC-011 ICB backtests already used. It also keeps April
  restructures out of the series as step changes no model could forecast. The cost is
  visible: region median MASE is 0.202 under fixed membership versus 0.183 under
  per-month membership.
- `ICB_CODE` starting in 2022-07 while `CCG_CODE` ends in 2022-06 leaves no overlapping
  month to join on. Practices present in both months provide a crosswalk; without it the
  352 practices that closed before the handover carry no ICB, and every ICB series gains
  a spurious ~2.9% growth trend at its start.

Three guards, each closing a failure that would otherwise be invisible
1. **A missing library is a hard error.** Every forecaster silently falls back to a
   linear trend when its library is absent, so a lean CI environment would publish
   straight lines labelled `autoets`. The build refuses to start.
2. **Aggregates are summed, never averaged.** `science.forecasting._prepare_series`
   collapses duplicate months with `groupby("ds").mean()`, so passing it a multi-practice
   frame yields a mean per practice — an order-of-magnitude error that still looks like a
   plausible number.
3. **The recorded model is the one that ran.** Output is compared bit-for-bit against
   `_linear_forecast`; a series that fell back is recorded as `linear`, never as the
   model that was requested.

Plus a quarantine: any series whose backtest MASE exceeds 50 is recorded in the metrics
file but **excluded from the forecast file**, and the API returns 404 with
`forecast_withheld`. These are genuine data breaks (mergers, code reassignments), not
model failures, but they must not be served as confident forecasts.

A fourth guard, added after the first full build published the wrong number
- `score_backtest` reports coverage of the model's **native** band, but the API serves
  the DEC-007 *calibrated* band. The first build therefore advertised a coverage figure
  describing an interval nobody receives (median 0.68 native). Calibrating on every
  cutoff and scoring those same cutoffs would be no better — it is in-sample, and
  FORECAST_VALIDATION §5's 0.83 is exactly that flattery.
- The metrics file now carries **`COVERAGE`** — calibrate on all cutoffs but the last,
  score the last — alongside `COVERAGE_NATIVE` for comparison. It is pure arithmetic on
  the backtest already computed, so it costs nothing, and it is what `/v1/meta`
  publishes as `measured_coverage`.

Impact
- Every API response is a lookup, single-digit milliseconds, fully deterministic and
  reproducible from the committed artifacts.
- Repo growth is a few MB per month, consistent with the existing commit-Parquet
  approach.
- The API publishes **measured** out-of-sample interval coverage at `/v1/meta` rather
  than the nominal 80%, per DEC-011 §7.5.

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
- Commit messages deliberately omit `[skip ci]`, so a forecast-cache workflow can trigger
  on the data push. Resolved 2026-08-27: `feature/statistical-forecasters` merged (PR #7),
  and `monthly_pipeline.yml` now rebuilds the forecast cache after ingestion.
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

---

### DEC-014: The Dashboard Forecasts Aggregates Too, Defaulting to Holt-Winters

- Date: 2026-08-26
- Status: Accepted
- Scope: Dashboard
- Related: DEC-007 (interval calibration), DEC-009 (silent-fallback guard),
  DEC-011 (per-level model choice), DEC-012 (precomputed serving artifacts)

Context
- DEC-011 established that the best model *depends on aggregation level*: AutoETS wins
  practice and PCN series, Holt-Winters wins ICB, regional and national. The API acts on
  both halves — `scripts/build_forecast_cache.py` has `DEFAULT_PRACTICE_MODEL` and
  `DEFAULT_AGGREGATE_MODEL`.
- The dashboard acted on only one. It forecast nothing above practice level: the
  national and regional charts were history-only, so the Holt-Winters half of the
  finding had no expression in the UI. A dashboard user could not see a forecast for
  the selection they had just filtered to.

Decision
- The List Size Trends page gains a **forecast for the current selection**, sitting
  between the national/regional charts and the practice drill-down. It forecasts the
  summed total, so it follows the sidebar filters — national with no filters, a region
  or ICB once one is chosen.
- **Holt-Winters is the default there**, with the same selector offering every other
  model for comparison. `AGGREGATE_FORECAST_MODEL` and `default_aggregate_forecast_model()`
  state it once, mirroring the existing practice-level pair.
- Both selectors now set an explicit `index` from their default rather than relying on
  dict ordering, and carry explicit `key`s.

Rationale
- Measured, not assumed: the aggregate path costs **0.30s** for a Holt-Winters fit plus
  the six-cutoff calibration backtest on the 78-month national series, and the result
  calibrates (`calibrated=True`). That is cheap enough to run on page load rather than
  hiding it behind an expander, and it is `@st.cache_data`-memoised per filter selection.
- Reusing `calibrated_forecast` means the aggregate band gets the DEC-007 calibration
  on the same terms as the practice band, rather than a second interval implementation.
- `practice_forecast_chart` was generalised to `forecast_chart` rather than copied; the
  practice entry point stays as a thin wrapper so its empty-state message ("Search for a
  practice…") does not leak into the aggregate chart.

The guard this needed
- `science.forecasting._prepare_series` collapses duplicate months with
  `groupby("ds").mean()` — the DEC-012 guard-2 hazard. Passing an unaggregated
  multi-practice frame would therefore forecast a *mean per practice*: roughly 8,000
  instead of 63,000,000. Wrong by four orders of magnitude, but still a plausible-looking
  patient count on an unlabelled axis.
- `aggregate_history_with_forecast` requires the output of `aggregate_list_size` (which
  sums) and **raises on duplicate months**, converting a silent scale error into a loud
  failure. A test asserts the raise, and the smoke check asserts the forecast lands
  near the summed total rather than a per-practice mean.

Impact
- The dashboard and the API now agree on which model serves which level; a test
  (`test_dashboard_aggregate_default_matches_the_cache_builder`) asserts
  `dashboard/data.py` and `scripts/build_forecast_cache.py` resolve to the same
  callables, so the two cannot drift apart silently.
- Prophet remains selectable at both levels and is the default at neither.

Implementation Notes
- `dashboard/data.py`: `AGGREGATE_FORECAST_MODEL`, `default_aggregate_forecast_model()`,
  `aggregate_history_with_forecast()`, and `_available_or_fallback()` shared by both
  defaults (preserving the DEC-009 guard for each).
- `dashboard/components/charts.py`: `forecast_chart()`, with `practice_forecast_chart()`
  delegating to it.
- `dashboard/pages/1_List_Size_Trends.py`: the new section and both selector `index`/`key`s.
- Tests in `tests/test_stat_forecasting.py`.

