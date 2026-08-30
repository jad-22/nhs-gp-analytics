# Roadmap and Delivery Checklists

Build-phase tracking for the platform. The README carries the short status summary; this
document carries the item-level detail and the open work.

Phases 1–3 (data foundation, science modules, dashboard) are complete and are not tracked
item-by-item here — their outputs are described in the README.

## Phase 4 — Pipeline Automation

Complete.

- [x] Build monthly entry point (`pipeline/monthly.py`)
- [x] Implement monthly GitHub Actions workflow (`.github/workflows/monthly_pipeline.yml`)
- [x] Move the schedule to a local task after CI proved unreachable from GitHub runners (DEC-013)
- [x] Verify commit-back end to end from a clean clone (august 2026, 6,129 practices)
- [x] Backfill july 2026, missed while the CI runs were 403-blocked (2026-08-25; 2020-01 → 2026-08 now gapless)
- [x] Register the scheduled task on the local machine (`docs/LOCAL_REFRESH.md`) — armed 2026-08-28, first scheduled fire 2026-09-01
- [x] Verify Streamlit redeploy after a successful pushed run

One gap is carried forward: `git push` has not yet run from the scheduled task's own
non-interactive context. The september 2026 publication is the first run that will
exercise it.

## Phase 5 — Portfolio Presentation

Complete. Project story, architecture diagram, the About the Data dashboard page, test
coverage, cached science outputs, and the pipeline-log display are all in place.

## Phase 6 — Public API

In progress. The forecast precompute, the FastAPI service, its tests and its container
image are implemented and building in CI. What remains is public hosting.

- [x] Precompute forecasts for every served series (`scripts/build_forecast_cache.py`, DEC-012)
- [x] Compile the serving database (`scripts/build_serving_db.py` → `serving.duckdb`)
- [x] Build the FastAPI service (`api/`) with rate limiting, ETags and cache headers
- [x] Document the contract and its caveats (`docs/API.md`)
- [x] Cover the public contract with tests (`tests/test_api.py`)
- [x] Build and publish the container image from CI (`.github/workflows/api_image.yml` → GHCR)
- [x] Rebuild the forecast cache automatically after each monthly ingest (`.github/workflows/forecast_cache.yml`), chained ahead of the image build
- [x] Point `docker-compose.yml` at the right GHCR owner
- [x] Vendor the Swagger UI and ReDoc bundles into the image so the running service makes no outbound calls at all (`api/docs.py`)
- [ ] Make the GHCR package public (or `docker login` on the host) so `docker compose pull` works
- [ ] Point a domain at the Hetzner box and bring it up behind Cloudflare
- [ ] Verify the deployed API end to end and publish the public base URL in `docs/API.md`

## Deferred

- Boundary GeoJSON choropleths. The dashboard uses cached practice latitude/longitude
  marker maps instead.
