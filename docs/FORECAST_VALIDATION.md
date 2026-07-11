# Forecast Validation and Model Selection

This document records the reasoning behind the project's forecasting model choice
(Prophet), the candidate alternatives worth benchmarking, and the methodology used to
validate forecast accuracy and select the best model. The methodology is implemented in
`science/backtesting.py`.

## 1. Current Approach: Prophet

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
2. **ARIMA-with-drift runs close everywhere despite ignoring seasonality** — these
   series are dominated by trend and autocorrelation, not seasonal structure.
3. **The airline SARIMA fails hard** (worse than seasonal naive in several regions):
   seasonal differencing amplifies the 2023 NHAIS→PDS structural break instead of
   absorbing it. A reminder that classical defaults are not robust to known breaks —
   exactly the situation Prophet's explicit changepoints were chosen for.

## 7. Related

- Implementation: `science/backtesting.py` and `science/stat_forecasting.py`,
  tests in `tests/test_backtesting.py` and `tests/test_stat_forecasting.py`
- Forecaster under test: `science/forecasting.py` (`forecast_list_size`)
- Decision records: `docs/DECISION_LOG.md` DEC-004, DEC-007, DEC-009, DEC-010
- Spec context: `docs/PROJECT_SPEC.md` §6.1
