# Learning Notes — Data Science Methodology in This Project

A personal study companion to `notebooks/exploration.ipynb`. Where
`FORECAST_VALIDATION.md` and `CLUSTER_VALIDATION.md` record *decisions*, this document
records *understanding*: what each part of the notebook does, why it was built that
way, and the transferable lessons behind it. It is written for a reader new to
time-series validation and unsupervised learning.

This is a living document — deep-dive sections are appended at the end as topics get
explored further (see §6).

---

## 1. The big picture: why the notebook is shaped the way it is

The notebook is not the pipeline. All real logic lives in importable, testable
modules — `pipeline/` (data loading) and `science/` (forecasting, anomalies,
clustering, deprivation, and their validation helpers). The notebook is where a human
checks that those modules behave sensibly on real data and records the reasoning.

**Lesson: modules hold logic, notebooks hold judgement.** Notebooks are bad places
for production code (hard to test, hard to diff, hidden execution-order state) but
excellent places for evidence and narrative. If a cell computes something the
dashboard needs, that computation belongs in `science/`, and the notebook should
import it.

The notebook has three acts:

1. **Phase 2 validation** — smoke-tests the science helpers against real parquet
   outputs.
2. **Forecast backtesting (DEC-004, DEC-007, DEC-010)** — proves the production
   forecaster beats simple baselines, and fixes its uncertainty band.
3. **Clustering validation (DEC-005, DEC-006)** — proves the practice segmentation
   has real structure and isn't circular.

The `DEC-nnn` labels are entries in `DECISION_LOG.md`: every methodology choice got a
numbered, documented decision rather than living only in someone's head.

## 2. Act 1 — smoke tests (Phase 2 validation)

The first cells load `latest_snapshot` (one row per practice, ~6,145 practices) and
`list_size_ts` (the full practice × month time series, ~500k rows), then run each
science helper once and assert on its output.

Things worth noticing:

- **`sys.path.insert(0, ROOT)`** — the notebook lives in `notebooks/` but imports
  from the repo root, so the root is added to the import path. A standard notebook
  pragmatic hack (the "proper" fix is an editable install).
- **The asserts check the contract, not the quality.** `assert not forecast.empty`
  and column-presence checks answer "did the function return the right shape?" —
  that is a smoke test. Whether the output is *good* is what Acts 2 and 3 measure.
  Keeping those two questions separate is deliberate.
- **Printing shapes and columns is not decoration.** It is the cheapest sanity check
  that the monthly pipeline produced what downstream code expects, and it leaves a
  human-inspectable record that pure pytest would not.
- **Early clues both later acts confirm.** The quick 3-month forecast shows a
  near-zero-width uncertainty band in its first months (absurd — no forecast is that
  certain), foreshadowing the coverage finding in Act 2. The clustering preview shows
  the first practices all in one cluster with one clinical system, foreshadowing the
  confound finding in Act 3. Reading smoke-test output carefully pays off.

**Lesson: a smoke-test section that re-runs after every monthly refresh is an
integration test you can read.**

## 3. Act 2 — forecast backtesting (DEC-004)

### 3.1 The question and the vocabulary

The production forecaster is Prophet. Fancy models often lose to embarrassingly
simple ones on real data, so DEC-004 demanded proof against three baselines:
**naive** (repeat last value), **seasonal naive** (repeat same month last year), and
**linear** (straight trend line — also the production fallback when Prophet can't
run).

Key vocabulary (full glossary in the notebook):

- **Cutoff** — the "pretend today". The model trains only on data up to the cutoff;
  everything after it is genuinely out-of-sample.
- **Rolling-origin backtesting** — train to a cutoff, forecast the horizon, compare
  with actuals, slide the cutoff forward, repeat. The time-series replacement for
  k-fold cross-validation.
- **MASE** — the primary metric: your model's MAE divided by seasonal naive's
  in-sample MAE. Below 1.0 = you beat "same month last year"; at or above 1.0 the
  model is eliminated. It bakes "beat the dumb method or die" into one number.
- **Coverage** — the fraction of actuals falling inside the forecast's uncertainty
  band, compared against the band's nominal level (80% here). It scores the *band*,
  not the point forecast.

No single metric suffices: MAE/RMSE aren't comparable across scales, MAPE has no
baseline, MASE says nothing about the band, coverage says nothing about point
accuracy — so they are read together.

### 3.2 The setup choices

`HORIZON=12, INITIAL=36, STEP=6`:

- **Horizon 12** because the dashboard serves 12-month forecasts — *evaluate the task
  you actually serve*, not an arbitrary one.
- **Initial 36** because Prophet needs a few yearly cycles to estimate seasonality.
- **Step 6** slides the cutoff to get multiple evaluation windows from limited
  history. With 78 months this yields 6 cutoffs × 12 horizon months = 72 honest
  out-of-sample forecast-months per model.

Every model is scored on **identical cutoffs** — otherwise you'd be comparing models
on different exam papers. The notebook also guards for short history (reducing
`INITIAL` gracefully) because these cells are meant to be re-run monthly as data
grows.

### 3.3 What the backtest found

| model | MASE | coverage (nominal 0.80) |
|---|---|---|
| prophet | **0.213** | 0.319 |
| linear | 0.357 | 0.639 |
| naive | 0.409 | 0.389 |
| seasonal_naive | 0.889 | 0.181 |

1. **Prophet wins point accuracy decisively** — ~40% better than the next model;
   average miss ≈ 153k patients on a ~63m national list (0.2%). DEC-004 gate passed.
2. **Seasonal naive is the worst baseline** — revealing in itself: the national
   series is dominated by steady *trend*, not seasonality, so repeating last year's
   value ignores a year of growth.
3. **The red flag: Prophet's uncertainty band is untrustworthy.** Nominal 80% band,
   actual coverage ~32%. The dashboard draws this band, so it is a product problem,
   not an academic one.

**Lesson: a model can be excellent at point forecasts and simultaneously terrible at
knowing its own uncertainty. Validate both.**

Two further checks back the summary table:

- **Error-by-horizon plot** — averaged scores can hide a model that is great at 1–3
  months and useless at 12; plotting MAPE per months-ahead exposes that.
- **The eyeball test** — plotting the best model's latest-cutoff forecast against
  reality. Summary statistics hide pathologies (systematic bias, kinks at the 2023
  NHAIS→PDS data-source transition) that one picture reveals. *Never trust a model
  you haven't plotted.*

### 3.4 Fixing the band — interval calibration (DEC-007)

Rather than tuning Prophet's internals, the fix is conformal-style empirical
calibration: take per-horizon quantiles of the backtest's own absolute errors and
rebuild the band that wide around the point forecast (`calibrate_intervals` /
`apply_interval_calibration` in `science/backtesting.py`).

The methodological subtlety: calibrate on all cutoffs *except* the latest, score
coverage on the held-out latest cutoff only. Calibrating and scoring on the same data
would make the coverage number self-fulfilling — the same train/test discipline as
everywhere else, applied to the uncertainty band.

### 3.5 Regional evaluation

A model that wins nationally can lose regionally (aggregation smooths noise), so the
comparison is re-run per NHS commissioning region and aggregated as median and
worst-case MASE. Findings: Prophet wins 5 of 7 regions and the median; linear beats
it in North East & Yorkshire and South West (likely Prophet over-flexing its
changepoints on essentially straight trends); Prophet's *worst* region still beats
seasonal naive comfortably. Conclusion: a single national model choice is defensible;
per-region selection is polish, not necessity.

The code comments state the shortcut taken (latest-snapshot region mapping drops
recently closed practices) and why it's acceptable. **Lesson: state your shortcuts.**

### 3.6 Expanded candidate registry (DEC-010)

Four classical models joined the candidate set: Holt-Winters, ARIMA(1,1,1)+drift,
airline SARIMA, and AutoETS. Design details worth copying:

- Candidates register only when their library is installed, so a lean environment
  never scores a fallback under a real model's name (`default_forecasters()` in
  `science/backtesting.py`).
- The expanded scoreboard reuses the already-computed backtests dict — no refits.
  Cache and reuse; slow notebooks stop being re-run.
- Findings: Holt-Winters ties Prophet on MASE with far more honest native coverage
  (0.65 vs 0.35) and edges ahead regionally. SARIMA loses badly — its double
  differencing *amplifies* the 2023 structural break instead of absorbing it.
  ARIMA-with-drift running close everywhere confirms trend + autocorrelation, not
  seasonality, drives these series.
- The open question is recorded, not hidden: DEC-004's own "simplest model within
  noise of the best" rule arguably now points at Holt-Winters. Pending decision.

### 3.7 Why not k-fold cross-validation?

Ordinary k-fold randomly shuffles observations into folds, assuming independence and
exchangeability. Time series violate both, and k-fold fails in two distinct ways:

1. **Temporal leakage** — random folds train on future months to predict past ones.
   On a trending, autocorrelated series the model then *interpolates* between known
   neighbours instead of *extrapolating* into the unknown; scores come out flattering
   and say nothing about real forecast skill.
2. **Task mismatch** — production asks exactly one question: "given history to month
   *t*, what happens in *t*+1 … *t*+12?" A random fold never poses that question.

Rolling-origin backtesting *is* cross-validation adapted to time: each cutoff plays
the role of a fold, but every split respects chronological order.

## 4. Act 3 — clustering validation (DEC-005, DEC-006)

### 4.1 Why validation looks different here

Clustering is unsupervised — there are no labels to hold out — so k-fold does not
even apply. The notebook uses four unsupervised analogues, all run on **the same
feature pipeline as production** (otherwise you'd validate a different model than the
one you ship):

| Question | Diagnostic | Analogue of |
|---|---|---|
| Redundant features double-weighting a dimension? | Feature correlation (Spearman) | Multicollinearity check |
| Real structure? How many clusters? | Silhouette / Davies-Bouldin / inertia sweep over k | Model selection |
| Did we fit noise? | Bootstrap stability — re-cluster 80% subsamples, compare via Adjusted Rand Index | k-fold CV |
| Clusters re-discovering an input category? | Cramér's V vs categoricals + cross-tab | Leakage check |

K-Means is pure distance geometry, which is why correlated features matter (a
dimension counted twice) and why categorical inputs in the distance are dangerous.

### 4.2 What the diagnostics found

- **Redundancy: clear** — size ↔ IMD Spearman ≈ 0.13. But the check exposed a real
  bug: `AGE_MONTHS` is computed as months since first appearance *within the input
  frame*, so on a single-month snapshot it is 0 for every practice — a constant,
  dead feature (its correlation row is NaN). Validation caught a genuine defect,
  which is the point of doing it.
- **Structure: weak** — silhouette peaks ≈ 0.225 at k=2, below the 0.25
  weak-structure threshold, no inertia elbow. GP practices form a continuous cloud,
  not naturally separated groups.
- **Stability: extremely high** — bootstrap ARI ≈ 0.985 across 20 subsamples.
  Weak-but-stable has a precise interpretation: the clusters are **reproducible
  slices of a continuum, not natural types**. Product consequence: the dashboard
  should say "similar-practice groups", never "we discovered five kinds of GP
  practice".
- **Confounding: severe** — Cramér's V ≈ 0.66 against `CLINICAL_SYSTEM`, and the
  cross-tab shows four of five clusters 100% pure by clinical system. K-Means was
  essentially partitioning by IT system because that categorical was one-hot encoded
  into the distance. Any claim "clusters differ by clinical system" would be
  perfectly circular — the system was an input. This is the unsupervised version of
  target leakage.

### 4.3 The fixes (DEC-006) and their measured effect

Applied in `science/clustering.py`: cluster on numeric features only (categoricals
demoted to *profiling* the clusters afterwards), drop constant columns like the dead
`AGE_MONTHS`, widen the k search, surface the silhouette as a `SILHOUETTE_SCORE`
column. Measured before → after on the same snapshot:

- Silhouette at best k: 0.225 → **0.398** (moderate — the segments-not-archetypes
  guidance stands)
- Cramér's V vs clinical system: 0.66 → **0.02** (confound eliminated; any
  cluster/system association is now a finding, not an echo of the inputs)
- Bootstrap ARI: unchanged ≈ 0.99
- Auto-k cluster count: 5 → **2** (the data's preferred split)

The post-fix note also flags the operational consequence — the dashboard shows two
segments after a cache rebuild — because **a modelling change is also a product
change**.

## 5. The transferable lessons

1. **Modules hold logic, notebooks hold judgement.** Everything the notebook imports
   is testable production code; the notebook is the evidence trail.
2. **Always fight a baseline.** MASE bakes "beat the dumb method or die" into a
   single number. Most modelling failures are fancy models that never faced a naive
   one.
3. **Never let the model grade its own homework.** Cutoffs before scoring, held-out
   cutoffs before calibration, subsamples before trusting clusters — every claim is
   out-of-sample.
4. **Validate the uncertainty, not just the prediction.** Prophet aced accuracy and
   flunked coverage; only checking both caught it.
5. **Write down what you found, especially the unflattering parts.** The
   overconfident band, the dead feature, the circular clusters, and the "maybe
   Holt-Winters should replace Prophet" question are all recorded rather than
   quietly buried.

## 6. Deep dives (appended as explored)

Placeholder for future sessions. Candidate topics:

- How MASE is computed, step by step, and its edge cases
- The conformal calibration code (`calibrate_intervals`) line by line
- What Prophet actually fits: piecewise trend, Fourier seasonality, changepoints
- Silhouette, Adjusted Rand Index, and Cramér's V — the maths behind the diagnostics
- UMAP: what the 2-D projection does and doesn't preserve
- Holt-Winters / ETS state-space models vs Prophet

*(none yet — add sections below as we go)*
