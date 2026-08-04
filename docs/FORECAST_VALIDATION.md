# Forecast Validation and Model Selection

This document records the reasoning behind the project's forecasting model choice, the
candidate alternatives worth benchmarking, and the methodology used to validate
forecast accuracy and select the best model. The methodology is implemented in
`science/backtesting.py`.

> **Current defaults (DEC-011, §7): AutoETS for practice and PCN series, Holt-Winters
> for ICB / regional / national series.** Prophet was the original choice and is still
> available for comparison, but it is no longer the default anywhere. Sections 1–6 are
> kept as the historical record of how that conclusion was reached — read §7 first.

## 1. Original Approach: Prophet

`science/forecasting.py` forecasts monthly registered-patient list sizes with
[Prophet](https://facebook.github.io/prophet/), a decomposable additive model:

```
y(t) = trend(t) + seasonality(t) + holiday effects(t) + noise
```

- **Trend** is piecewise linear, with "changepoints" where the slope may bend.
- **Seasonality** is modelled with Fourier series (this project enables yearly only —
  the data is monthly snapshots, so weekly/daily seasonality is meaningless).
- Fitting is Bayesian curve-fitting (via Stan), which yields uncertainty intervals
  (`yhat_lower` / `yhat_upper`) for free.

### Why Prophet fits this dataset

1. **Explicit changepoint support.** GP list-size data has *known, dated* structural
   breaks: the NHAIS→PDS data source transition (~early 2023) and April ICB
   restructures. Prophet accepts those exact dates as changepoints; classical models
   (ARIMA, exponential smoothing) have no native equivalent.
2. **Robust to missing months and outliers** — relevant given NHS Digital's
   retroactive file corrections.
3. **Interpretable decomposition** — trend and seasonality components can be plotted
   and explained on the dashboard.
4. **Low-effort defaults across many series** — one configuration works for national,
   regional, and practice-level series without per-series tuning.

### The honest counterpoint

In the M-competitions and most published benchmarks, Prophet is often *beaten* by
simpler statistical models (ETS, Theta, ARIMA, even seasonal naive) on generic series.
Its advantage is situational — known event dates, many series, interpretability — not
raw accuracy. That claim must therefore be **measured, not assumed**, which is what the
backtesting harness exists to do.

## 2. Candidate Alternatives

Roughly in order of priority for this dataset (monthly, smooth, strongly trended):

| Family | Implementation | Why relevant |
|---|---|---|
| Naive baselines | `science/backtesting.py` (seasonal naive, naive, linear) | The yardstick. Any model that cannot beat seasonal naive is not earning its keep. |
| ETS / exponential smoothing | **Implemented (DEC-010):** `science/stat_forecasting.py` — Holt-Winters via statsmodels `ETSModel`, plus `statsforecast.AutoETS` | Frequently the best performer on smooth monthly administrative data. |
| (S)ARIMA | **Implemented (DEC-010):** `science/stat_forecasting.py` — ARIMA(1,1,1)+drift and airline SARIMA (0,1,1)(0,1,1)₁₂ via statsmodels `SARIMAX` | Classical workhorse; handles autocorrelation Prophet ignores. |
| Theta | `statsforecast.AutoTheta` | Won the M3 competition; absurdly strong for its simplicity. |
| Gradient boosting on lag features | LightGBM via `mlforecast` / `sktime` | Wins when many related series are pooled into one global model; higher engineering cost. |
| Neural (NeuralProphet, N-BEATS, TFT) | `neuralprophet`, `darts` | Usually overkill for smooth monthly data with 5–10 years of history. |

Expectation: AutoETS / Theta are Prophet's stiffest competition here. The interesting
question is whether Prophet's changepoint handling around the April 2023 PDS transition
buys back any accuracy difference. **Measured answer: see §6.**

## 3. Validation Methodology: Rolling-Origin Backtesting

Forecasts are judged **out of sample only** — never on in-sample fit. The harness in
`science/backtesting.py` implements rolling-origin (expanding-window) cross-validation:

1. Stand at a past month (the *cutoff*), train on all data up to and including it.
2. Forecast `horizon` months ahead and compare against the actuals.
3. Slide the cutoff forward by `step` months and repeat.

Defaults: `initial=36` months minimum training window, `horizon=12` months,
`step=6` months — chosen so each evaluation mirrors the dashboard's real use
(12-month forecast) while yielding several cutoffs from ~5 years of history.

### Metrics

| Metric | What it tells you | Caveat |
|---|---|---|
| MAE / RMSE | Absolute error in patients | Not comparable across differently sized practices/regions |
| MAPE | Percentage error, comparable across series | Unstable near zero (not an issue for list sizes) |
| **MASE** | Error scaled by the in-sample seasonal-naive error. **Primary metric**: MASE < 1 means "beats seasonal naive" | Needs ≥ 13 months of training history for the seasonal scale |
| Interval coverage | Fraction of actuals inside the forecast band | A confidently wrong band is worse than no band; compare against the nominal level (Prophet default 80%) |

Also inspect errors **by horizon** (is month 1 good but month 12 useless?) and
**around known breaks** (does the model recover after April 2023?).

## 4. Model Selection Protocol

1. **One harness for all candidates.** Same cutoffs, same horizon, same metrics,
   applied identically to every model (`compare_models` in `science/backtesting.py`).
2. **Evaluate at the level forecasts are served** — region level by default, per
   `PROJECT_SPEC.md` §6.1. Aggregate as median MASE across regions plus worst case.
3. **Baselines first.** Candidates that do not beat seasonal naive are eliminated.
4. **Prefer the simplest model within noise of the best.** If two models are within
   ~2% on MASE, tie-break on interpretability, changepoint support, and integration
   cost — but only after accuracy has been measured.
5. Optional extensions: Diebold-Mariano test for statistical significance of accuracy
   differences; per-region model selection if winners genuinely differ by region.

## 5. Interval calibration (DEC-007)

Backtesting on real data confirmed Prophet's point accuracy (national MASE 0.213) but
exposed a badly overconfident uncertainty band: ~28-35% coverage at a nominal 80%.
The fix is conformal-style empirical calibration, implemented in
`science/backtesting.py`:

1. `calibrate_intervals(backtest_results, level=0.8)` — per months-ahead horizon,
   take the `level` quantile of the absolute backtest errors. That half-width would
   have covered `level` of the actuals at that horizon.
2. `apply_interval_calibration(forecast, calibration)` — rebuild the band around the
   point forecast using those widths (widest known width beyond the calibrated range;
   lower bound clipped at 0).

Measured on the national series: self-calibrated coverage 0.83 (nominal 0.80), and
1.0 on a held-out cutoff where the native band managed 0.5. The calibrated widths grow
monotonically from ≈69k patients at 1 month to ≈444k at 12 months — a sanity check
that the error distribution behaves as expected.

Dashboard integration landed as DEC-009: the practice drill-down calibrates the band
from each practice's own backtest via `calibrated_forecast` (falling back to the
native band, clearly captioned, when the history is shorter than ~4 years), and users
can switch between Prophet and the baseline models it was benchmarked against.

## 6. Classical statistical models, measured (DEC-010)

`science/stat_forecasting.py` implements the priority candidates from §2 behind the
same `Forecaster` contract and guards as Prophet (native 80% band, linear fallback
below 24 months or on a failed fit, excluded from every registry when the library is
missing). `default_forecasters()` and the dashboard's drill-down selector pick them
up automatically.

Rolling-origin results on real data (July 2026 vintage, defaults: horizon 12,
initial 36, step 6):

**National series (78 months, 72 scored forecasts per model):**

| Model | MASE | MAE (patients) | Native 80% coverage |
|---|---|---|---|
| Holt-Winters | **0.211** | 152,339 | 0.65 |
| Prophet | 0.213 | 152,904 | 0.35 |
| ARIMA(1,1,1)+drift | 0.227 | 162,450 | 0.65 |
| AutoETS | 0.250 | 178,708 | 0.58 |
| Linear | 0.357 | 253,552 | 0.64 |
| Naive | 0.409 | 287,293 | 0.39 |
| SARIMA (airline) | 0.549 | 377,153 | 0.72 |
| Seasonal naive | 0.889 | 627,673 | 0.18 |

**Regional (median MASE across the 7 commissioning regions):** Holt-Winters 0.183,
ARIMA 0.195, AutoETS 0.197, Prophet 0.198, linear 0.274, naive 0.396, seasonal naive
0.873, SARIMA 1.289. Prophet and Holt-Winters each win 3 regions, ARIMA one.

Takeaways:

1. **Holt-Winters ties Prophet nationally and edges it regionally**, with a far more
   honest native band. Under the §4 "simplest model within noise" rule it is now a
   live candidate for the recommended default — an open product decision; Prophet
   keeps the recommendation for the moment on changepoint support.
   **→ Superseded by §7.** These results are correct but cover only 8 aggregate
   series; §7 shows the ranking reverses on the 99.4% of series that are practices
   and PCNs, and retires Prophet as the default.
2. **ARIMA-with-drift runs close everywhere despite ignoring seasonality** — these
   series are dominated by trend and autocorrelation, not seasonal structure.
3. **The airline SARIMA fails hard** (worse than seasonal naive in several regions):
   seasonal differencing amplifies the 2023 NHAIS→PDS structural break instead of
   absorbing it. A reminder that classical defaults are not robust to known breaks —
   exactly the situation Prophet's explicit changepoints were chosen for.

## 7. Practice- and PCN-level results, measured (DEC-011)

§6 is a sound experiment with a narrow sample: it scores **8 series** — one national
plus seven regions. Both the dashboard drill-down and the planned open API serve
*individual practices*, and no practice had ever been backtested. This section closes
that gap and reverses the §6 conclusion for the levels that carry almost all the data.

### 7.1 Methodology

Same harness, same parameters, no code changes: `rolling_origin_backtest` with
`horizon=12, initial=36, step=6` on the July 2026 vintage (78 months, 2020-01 →
2026-06), MASE as the primary metric.

- **Environment.** Prophet is not installed in the working Anaconda environment, and
  `forecast_list_size` silently returns the linear fallback when it is missing. The
  study therefore ran in an isolated virtualenv with Prophet 1.3.0, statsmodels 0.14.6,
  statsforecast 2.0.3. **Any benchmark of Prophet run without confirming
  `science.forecasting.Prophet is not None` is measuring the linear fallback.**
- **Control.** The harness first reproduced §6 exactly — national Holt-Winters MASE
  0.211 / Prophet 0.213, MAE 152,339 / 152,904; regional medians 0.183 / 0.195 / 0.197
  / 0.198. Same instrument, so §6 and §7 numbers are directly comparable.
- **Sampling.** All 7 regions, all 36 ICBs, 120 PCNs sampled at random from 1,299, and
  999 practices drawn **stratified across size deciles** (so the ~4k-patient practices
  are not swamped by the ~18k ones). Only practices present in the latest snapshot.
- **Aggregate series are summed, not averaged.** `_prepare_series` ends with
  `groupby("ds").mean()`, so passing a multi-practice frame yields a mean per practice.
  Every aggregate here is built with an explicit `.sum()` first.
- **Paired testing.** Models are compared per series (Wilcoxon signed-rank on matched
  MASE), not by comparing group medians, since series difficulty varies enormously.
- **Honest interval scoring.** Coverage is reported two ways: *self-calibrated* (widths
  fitted and scored on the same backtest — what §5 reports) and *held-out* (widths
  fitted on all cutoffs but the last, scored on the last). Only the second is
  out-of-sample.
- **Fallback detection.** Each model's final fit is compared against `_linear_forecast`
  output; a bit-identical result is recorded as a silent fallback. Measured rate ≈ 0.1%
  (1 practice in 1,000), so the guard matters for correctness, not volume.

### 7.2 Median MASE by aggregation level

| Model | national (1) | region (7) | ICB (36) | PCN (120) | practice (999) |
|---|---|---|---|---|---|
| Holt-Winters | **0.211** | **0.183** | **0.272** | 0.536 | 0.594 |
| AutoETS | 0.250 | 0.197 | 0.295 | **0.389** | **0.525** |
| ARIMA(1,1,1)+drift | 0.227 | 0.195 | 0.296 | 0.478 | 0.552 |
| Prophet | 0.213 | 0.198 | 0.366 | 0.629 | 0.723 |
| Naive | 0.409 | 0.396 | 0.398 | 0.518 | 0.630 |
| Linear | 0.357 | 0.274 | 0.491 | 0.942 | 1.089 |
| Seasonal naive | 0.889 | 0.873 | 0.858 | 0.918 | 1.085 |

**The ranking flips between ICB and PCN.** Holt-Winters wins national, region and ICB;
AutoETS wins PCN and practice. At PCN level Holt-Winters falls to 4th, behind the naive
baseline. Median series size: ICB ≈ 1.2M patients, PCN ≈ 43k, practice ≈ 8.8k — the
crossover sits in that gap. Heavily aggregated series are smooth enough for
Holt-Winters' damped seasonal trend; noisier small series reward AutoETS' AICc search
over ETS variants.

This matters because **PCNs and practices are 7,444 of 7,488 forecastable series
(99.4%)**. The eight series §6 measured are the only ones where its conclusion holds.

### 7.3 Prophet fails the §4 protocol at the levels that matter

- It **loses to the plain naive last-value baseline** at practice (0.723 vs 0.630) and
  PCN (0.629 vs 0.518) level. §4 step 3 eliminates candidates that cannot beat the
  baselines.
- Paired across 999 practices: Holt-Winters beats Prophet on **72.7%** (median −16.6%,
  Wilcoxon p ≈ 1e-57); AutoETS beats it on **80.5%** (median −25.6%). At PCN level
  AutoETS beats Prophet on **89.2%** (median −30.2%).
- **Tail risk:** Prophet exceeds MASE 1 on **33.8%** of practices, versus AutoETS 17.0%
  and Holt-Winters 20.5%.
- **Short horizons are its weakest point:** median MASE at 1 month ahead is 0.273 versus
  0.113 (AutoETS) and 0.130 (Holt-Winters) — Prophet's smooth trend does not anchor to
  the last observation.

### 7.4 Changepoint support does not pay off

§1 justifies Prophet on explicit changepoints at the NHAIS→PDS transition. The default
cutoff grid puts a cutoff at **2022-12**, whose 12-month forecast runs straight through
the break. Scoring each cutoff separately (median MASE):

| Level | cutoff 2022-12 (break) | median of the 5 calm cutoffs |
|---|---|---|
| National | HW **0.096** · ARIMA 0.104 · Prophet 0.152 | HW 0.257 · ARIMA 0.179 · Prophet 0.231 |
| Region | HW **0.080** · ARIMA 0.102 · Prophet 0.163 | HW 0.183 · ARIMA 0.152 · Prophet 0.225 |
| Practice | ARIMA **0.487** · HW 0.533 · Prophet 0.655 | ARIMA 0.448 · HW 0.436 · Prophet 0.566 |

Prophet is the **worst of the three at the break cutoff at every level** — the exact
scenario the feature was chosen for. There is a mechanical reason:
`_default_changepoints` only injects `PDS_START` when it falls inside the *training*
range, so at the 2022-12 cutoff Prophet gets no PDS changepoint at all. Changepoints
can only help retrospectively, never for forecasting *through* a break that has not
happened yet. At later cutoffs where the changepoint is in range, Prophet still loses.

### 7.5 Interval calibration is honest but weaker than advertised

Held-out-cutoff coverage at a nominal 0.80: Holt-Winters 0.743, Prophet 0.746, AutoETS
0.712, ARIMA 0.720 — statistically indistinguishable. Two consequences:

1. **Calibration fully repairs Prophet's native band** (0.33 → 0.75), so "Holt-Winters
   has a more honest band" is only an argument for the handful of series too short to
   calibrate.
2. **The calibrated 80% band delivers ≈74% out of sample.** §5's 0.83 figure is
   *self*-calibrated and therefore optimistic. Anything published to users — dashboard
   caption or API response — should quote the measured out-of-sample figure.

### 7.6 Rejected alternatives

- **ARIMA**, despite ranking 2nd at practice level, is **excluded**: it diverges on 15
  of 999 practices, with a maximum MASE of **2.3 × 10¹⁰**. Any automated pipeline
  serving it needs a sanity bound; not worth the exposure for a ~4% median gain over
  AutoETS.
- **Per-series model selection.** Tested honestly — pick the best model on all cutoffs
  but the last, score it on the held-out cutoff (300 practices). Median MASE 0.429
  versus fixed AutoETS 0.432: a **0.6% gain**, beating fixed AutoETS on only **37%** of
  practices, at **6.8× the compute** (every candidate must be fitted). Selection noise
  over 6 cutoffs eats the benefit.
- **Pooled interval calibration** (fit one relative width curve on a sample, reuse it):
  relative half-width varies **5–7×** between the 10th and 90th percentile of practices
  at every horizon. A shared curve would be badly overconfident for volatile practices.
  Per-series calibration stays.

### 7.7 Cost

Seconds per series for a 6-cutoff backtest plus the final fit (12 cores, Prophet 1.3.0):

| Model | s/series | 7,488 series, 1 core | on 4 cores |
|---|---|---|---|
| ARIMA | 0.60 | 1.24 h | 19 min |
| **AutoETS** | **0.94** | 1.95 h | 29 min |
| Holt-Winters | 2.35 | 4.88 h | 73 min |
| Prophet | 3.58 | 7.44 h | 112 min |

Holt-Winters is only ~1.5× faster than Prophet, not the order of magnitude a single
fit suggests (0.05s vs 0.98s) — the backtest dominates. **Cost is not the reason to
retire Prophet; practice-level accuracy is.**

### 7.8 Conclusion

Use **AutoETS for practice and PCN series, Holt-Winters for ICB, regional and national
series.** Prophet is retained in the registry for comparison but is no longer the
default anywhere. See DEC-011.

## 8. Related

- Implementation: `science/backtesting.py` and `science/stat_forecasting.py`,
  tests in `tests/test_backtesting.py` and `tests/test_stat_forecasting.py`
- Forecaster under test: `science/forecasting.py` (`forecast_list_size`)
- Dashboard default: `dashboard/data.py` (`DEFAULT_FORECAST_MODEL`,
  `default_forecast_model`)
- Decision records: `docs/DECISION_LOG.md` DEC-004, DEC-007, DEC-009, DEC-010, DEC-011
- Spec context: `docs/PROJECT_SPEC.md` §6.1

### Reproducing §7

The study is not committed (it needs Prophet, which the pipeline does not). To rerun:

```powershell
python -m venv .venv-forecast
.\.venv-forecast\Scripts\Activate.ps1
pip install prophet statsmodels statsforecast pandas pyarrow scikit-learn scipy
python -c "from science.forecasting import Prophet; assert Prophet is not None"
```

Then, per level, for each candidate forecaster: build the series (summing for
aggregates), call `rolling_origin_backtest(series, forecaster, horizon=12, initial=36,
step=6)`, and score with `score_backtest` / `score_by_horizon`. Group backtest rows by
`cutoff` to reproduce §7.4, and split the last cutoff off before `calibrate_intervals`
to reproduce the held-out coverage in §7.5.
