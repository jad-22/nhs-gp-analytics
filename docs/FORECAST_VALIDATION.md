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
| ETS / exponential smoothing | `statsmodels` Holt-Winters or `statsforecast.AutoETS` | Frequently the best performer on smooth monthly administrative data. |
| (S)ARIMA | `statsforecast.AutoARIMA` or `pmdarima` | Classical workhorse; handles autocorrelation Prophet ignores. |
| Theta | `statsforecast.AutoTheta` | Won the M3 competition; absurdly strong for its simplicity. |
| Gradient boosting on lag features | LightGBM via `mlforecast` / `sktime` | Wins when many related series are pooled into one global model; higher engineering cost. |
| Neural (NeuralProphet, N-BEATS, TFT) | `neuralprophet`, `darts` | Usually overkill for smooth monthly data with 5–10 years of history. |

Expectation: AutoETS / Theta are Prophet's stiffest competition here. The interesting
question is whether Prophet's changepoint handling around the April 2023 PDS transition
buys back any accuracy difference.

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

## 5. Related

- Implementation: `science/backtesting.py`, tests in `tests/test_backtesting.py`
- Forecaster under test: `science/forecasting.py` (`forecast_list_size`)
- Decision record: `docs/DECISION_LOG.md` DEC-004
- Spec context: `docs/PROJECT_SPEC.md` §6.1
