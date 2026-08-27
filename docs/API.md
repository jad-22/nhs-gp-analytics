# NHS GP List Size & Forecast API

A free, public, read-only REST API over the data this repo already produces: monthly GP
practice registration counts for England since January 2020, plus a 12-month forecast for
every practice, PCN, ICB, region and for England as a whole.

No key, no signup, no auth. Interactive docs at `/docs`, machine-readable spec at
`/v1/openapi.json`.

---

## The one-line version

```bash
curl -s https://<host>/v1/practices/A81001/forecast
```

```json
{
  "level": "practice",
  "entity_code": "A81001",
  "entity_name": "The Densham Surgery",
  "forecast": {
    "model": "autoets",
    "calibrated": true,
    "interval_level": 0.8,
    "trained_through": "2026-06-01",
    "generated_at": "2026-08-04T15:41:00Z",
    "interval_warning": null,
    "points": [
      {"date": "2026-07-01", "horizon_month": 1, "yhat": 3781.4, "yhat_lower": 3702.1, "yhat_upper": 3860.7}
    ]
  },
  "accuracy": {"mase": 0.52, "mae": 40.1, "rmse": 55.3, "mape": 0.019, "coverage": 0.75, "coverage_native": 0.66, "n_forecasts": 72},
  "meta": {"source": "NHS England...", "licence": "Open Government Licence v3.0", "caveats_url": "/v1/meta", "run_id": "2026-06.ae37088a1f23"}
}
```

---

## Endpoints

| Method | Path | What it returns |
|---|---|---|
| GET | `/v1/practices` | Paginated search. `search`, `icb`, `pcn`, `region`, `active`, `page`, `page_size` |
| GET | `/v1/practices/{ods_code}` | Practice attributes as of the latest snapshot |
| GET | `/v1/practices/{ods_code}/list-size` | Full monthly history |
| GET | `/v1/practices/{ods_code}/forecast` | 12-month forecast + accuracy |
| GET | `/v1/regions` · `/v1/icbs` · `/v1/pcns` | List entities at that level (`search` supported) |
| GET | `/v1/{regions\|icbs\|pcns}/{code}/list-size` | Aggregate monthly history |
| GET | `/v1/{regions\|icbs\|pcns}/{code}/forecast` | Aggregate 12-month forecast |
| GET | `/v1/national/list-size` · `/v1/national/forecast` | England totals |
| GET | `/v1/meta` | Vintage, coverage, and the caveats you should read first |
| GET | `/v1/meta/models` | Which model serves which level, with measured accuracy |
| GET | `/health` | Liveness and vintage |

Codes are the primary keys — ODS code for practices, and the NHS England codes for PCN
(`U…`), ICB (`Q…`) and commissioning region (`Y…`). Names are attributes and can change.
Codes are case-insensitive.

---

## Reading a forecast honestly

Three fields matter as much as `yhat`:

**`model`** — `autoets` for practices and PCNs, `holt_winters` for ICBs, regions and
national. The accuracy ranking of these two *reverses* with aggregation level, so neither
is used everywhere; `/v1/meta/models` gives the measured table. A value of `linear` means
the series had under 24 months of history and no seasonal model could be fitted.

**`accuracy.mase`** — mean absolute scaled error from that series' own rolling-origin
backtest. Below 1 beats simply repeating last year's value. Practice-level median is
about 0.53; a practice at 3.0 is telling you its history is erratic.

**`calibrated`** — when `true`, the interval was derived from that series' own backtest
errors rather than the model's native band, which is badly overconfident. When `false`
the payload carries an `interval_warning`; treat the band as indicative.

> The interval is labelled 80% but **its measured out-of-sample coverage is lower**.
> `accuracy.coverage` is what that forecast's published band achieved on a backtest
> cutoff it was *not* calibrated on; `accuracy.coverage_native` is the model's own
> uncalibrated band, shown only for comparison. `/v1/meta` publishes the median measured
> figure across all served series — use it, not `interval_level`.

Roughly 1 in 1,000 series is withheld entirely because no model can track it — a merger
or code reassignment rather than a modelling failure. Those return `404` with
`"code": "forecast_withheld"` rather than a confident wrong answer.

---

## Errors

Every error is JSON with the same shape:

```json
{"detail": "No practice with ODS code ZZZ999. Search for one at /v1/practices?search=.", "code": "practice_not_found"}
```

| Status | `code` | Meaning |
|---|---|---|
| 404 | `practice_not_found`, `icb_not_found`, … | No entity with that code |
| 404 | `entity_closed` | Practice is not in the latest snapshot. `/list-size` still works |
| 404 | `forecast_withheld` | History too irregular to forecast responsibly |
| 422 | — | Invalid query parameter |
| 429 | `rate_limited` | Slow down; `Retry-After` says how long |

A closed practice returning 404 on `/forecast` is deliberate: its list has stopped, and
extrapolating it would be fiction.

---

## Caching and rate limits

Responses carry `Cache-Control: public, max-age=86400, stale-while-revalidate=604800` and
an `ETag` derived from the data vintage. The data changes **once a month** — send the ETag
back as `If-None-Match` and you'll get a `304`:

```bash
curl -s -H 'If-None-Match: "2026-06.ae37088a1f23"' https://<host>/v1/meta -o /dev/null -w '%{http_code}\n'
# 304
```

Limits are 60 requests/minute and 2,000/day per IP. They exist to bound abuse, not to
meter you; if you need a bulk extract, take the Parquet files from
`data/processed/` in this repo instead of crawling the API.

---

## Examples

**pandas — one practice's history and forecast on one axis**

```python
import pandas as pd, requests

BASE = "https://<host>/v1"
code = "A81001"

history = pd.DataFrame(requests.get(f"{BASE}/practices/{code}/list-size").json()["points"])
payload = requests.get(f"{BASE}/practices/{code}/forecast").json()
forecast = pd.DataFrame(payload["forecast"]["points"])

for frame in (history, forecast):
    frame["date"] = pd.to_datetime(frame["date"])

print(f"{payload['forecast']['model']}, MASE {payload['accuracy']['mase']:.2f}")
combined = history.set_index("date")["patients"].to_frame("actual").join(
    forecast.set_index("date")[["yhat", "yhat_lower", "yhat_upper"]], how="outer"
)
```

**Every practice in an ICB, biggest first**

```python
practices = requests.get(
    f"{BASE}/practices", params={"icb": "QHM", "active": True, "page_size": 500}
).json()["practices"]
top = sorted(practices, key=lambda p: p["patients"] or 0, reverse=True)[:10]
```

**curl — national trajectory**

```bash
curl -s https://<host>/v1/national/forecast \
  | python -m json.tool \
  | grep -E '"date"|"yhat"'
```

---

## Before you draw conclusions

`GET /v1/meta` returns these in full. The short version:

- **Registrations are not population.** Lists include people who have moved away or died
  but have not yet been removed.
- **The source changed in January 2023** (NHAIS → PDS). `data_source` records which
  applies; small level shifts around that month are a source change, not real movement.
- **ICB and PCN fields only exist from mid-2022.** Earlier ICB membership is bridged from
  the practice's CCG, so pre-2022-07 ICB history is a reconstruction.
- **Aggregate series use current membership** applied to the whole history, so they
  describe an entity's footprint as it stands today, not its historical boundaries.
- **April brings restructures**, and NHS England issues retroactive corrections.
- **A missing practice-month is ambiguous** — closure, merger and non-reporting look
  identical in the data.

---

## Licence

Source data is published by NHS England under the
[Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).
Attribution is required:

> Contains public sector information licensed under the Open Government Licence v3.0.
> Source: NHS England, *Patients Registered at a GP Practice*.

Forecasts are derived work from this repository and carry no warranty. They are
statistical extrapolations of registration counts, not projections of health need, and
should not be used for commissioning decisions without local validation.

---

## Running it yourself

```bash
pip install -r requirements-api.txt
python scripts/build_serving_db.py      # compiles data/processed/*.parquet -> serving.duckdb
uvicorn api.main:app --reload
```

Or the whole thing behind TLS:

```bash
API_DOMAIN=api.example.com docker compose up --build -d
```

Forecasts come from `scripts/build_forecast_cache.py`, which runs monthly in CI. The
methodology behind the model choice is in
[`FORECAST_VALIDATION.md`](FORECAST_VALIDATION.md) §7 and the decisions in
[`DECISION_LOG.md`](DECISION_LOG.md) (DEC-011, DEC-012).
