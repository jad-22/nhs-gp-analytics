# NHS GP Analytics

Portfolio project for building an automated analytics platform on open NHS England GP practice registration data.

## Project Context

This repository follows the product and engineering scope described in:

- [docs/PROJECT_SPEC.md](docs/PROJECT_SPEC.md)
- [docs/PIPELINE_IMPLEMENTATION_PLAN.md](docs/PIPELINE_IMPLEMENTATION_PLAN.md)
- [docs/DECISION_LOG.md](docs/DECISION_LOG.md)

The objective is a production-quality monthly pipeline that ingests NHS GP registration data and powers downstream science and dashboard modules.

## Phase 1 Plan (Reviewed)

Phase 1 is the data foundation milestone. The implementation approach is:

1. Finalise repository scaffold so all later phases can build without restructures.
2. Keep pipeline modules small and composable with stable public interfaces.
3. Port working prototype logic into package modules incrementally.
4. Validate each stage with lightweight tests before broad backfill runs.
5. Persist outputs and logs in deterministic locations under data.

### Phase 1 Deliverables

- Pipeline package scaffold in [pipeline](pipeline)
- Science package scaffold in [science](science)
- Dashboard scaffold in [dashboard](dashboard)
- Workflow scaffold in [.github/workflows](.github/workflows)
- Test scaffold in [tests](tests)
- Data directories for raw, processed, and enrichment assets

### Implementation Sequence

1. Scraper: implement publication page parsing and resilient downloads.
2. Extractor: keep zip-slip-safe extraction and robust file discovery.
3. Transformer: normalise schema and derive SNAPSHOT_DATE, DATA_SOURCE, CLINICAL_SYSTEM.
4. Loader: upsert into Parquet and expose DuckDB query helpers.
5. Backfill and monthly entry points: orchestrate month targeting, run logging, and retries.

### Definition of Done (Phase 1)

- Historical backfill can run month-by-month from Jan 2015 onward.
- data/processed/list_size.parquet and data/processed/mapping.parquet are generated.
- Duplicate snapshot rows are overwritten on rerun.
- data/pipeline_log.json records each execution outcome.
- Basic tests pass for scraper, transformer, and loader interfaces.

## Repository Layout

```text
nhs-gp-analytics/
├── .github/workflows/
├── data/
│   ├── enrichment/
│   ├── processed/
│   ├── raw/
│   └── pipeline_log.json
├── dashboard/
│   ├── components/
│   └── pages/
├── docs/
├── notebooks/
├── pipeline/
├── science/
├── scripts/
└── tests/
```

## Quickstart

Python 3.11+ is recommended.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

## Running Scaffold Commands

Run a dry-run backfill target:

```bash
python -m pipeline.backfill --month january --year 2015 --dry-run
```

Run the monthly entry point scaffold:

```bash
python -m pipeline.monthly
```

Run tests:

```bash
pytest -q
```

## Enrichment Run Order

Recommended order for enrichment preparation and join:

```bash
# 1) Stage/download prepared enrichment files
python scripts/download_enrichment.py --imd-local /path/to/imd_2025.parquet --onspd-local /path/to/onspd_postcode_lookup.parquet

# 2) Prepare IMD parquet from source CSV (if needed)
python scripts/prepare_imd_parquet.py --input data/enrichment/imd_2025.csv --output data/enrichment/imd_2025.parquet

# 3) Extract England-only ONSPD parquet with DuckDB (if needed)
python scripts/extract_onspd_england.py --input-glob "data/enrichment/onspd/*.csv" --output data/enrichment/onspd_postcode_lookup.parquet

# 4) Join enrichment into mapping parquet
python scripts/join_enrichment.py --mapping data/processed/mapping.parquet --imd data/enrichment/imd_2025.parquet --onspd data/enrichment/onspd_postcode_lookup.parquet
```

## Notes

- The current implementation is scaffold-first: interfaces and paths are in place while production logic is ported from legacy scripts.
- Existing prototype scripts are retained in [scripts](scripts) for reference during migration.
- Raw downloads under data/raw are ignored by git to control repository size.