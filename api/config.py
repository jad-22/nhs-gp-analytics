"""Configuration for the public API. Every value is environment-overridable."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SERVING_DB_PATH = Path(os.getenv("SERVING_DB_PATH", REPO_ROOT / "data" / "processed" / "serving.duckdb"))

API_TITLE = "NHS GP List Size & Forecast API"
API_VERSION = "1.0.0"
API_PREFIX = "/v1"

# Read-only, unauthenticated, and every response is a static lookup, so the limits exist
# to bound abuse rather than to meter usage. Applied per IP in-process so they hold on
# any host, with Cloudflare in front absorbing the bulk.
RATE_LIMIT_PER_MINUTE = os.getenv("RATE_LIMIT_PER_MINUTE", "60/minute")
RATE_LIMIT_PER_DAY = os.getenv("RATE_LIMIT_PER_DAY", "2000/day")

# The data changes once a month. Long TTLs plus stale-while-revalidate mean the origin
# should serve almost nothing; ETags built from RUN_ID turn refreshes into 304s.
CACHE_MAX_AGE = int(os.getenv("CACHE_MAX_AGE", 86_400))
CACHE_STALE_WHILE_REVALIDATE = int(os.getenv("CACHE_STALE_WHILE_REVALIDATE", 604_800))

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 500

LICENCE_NAME = "Open Government Licence v3.0"
LICENCE_URL = "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/"
ATTRIBUTION = "NHS England, Patients Registered at a GP Practice. Contains public sector information licensed under the Open Government Licence v3.0."
SOURCE_URL = "https://digital.nhs.uk/data-and-information/publications/statistical/patients-registered-at-a-gp-practice"

# Surfaced at /v1/meta. A public API that omits these invites wrong conclusions from
# people who never read the source publication (docs/PROJECT_SPEC.md §11).
CAVEATS = [
    "Registration counts are not the same as population. Lists include patients who have moved away or died but have not yet been removed ('list inflation' or 'ghost patients').",
    "The data source changed from NHAIS to PDS in January 2023. The DATA_SOURCE field records which applies; small level shifts around that month are a source change, not real movement.",
    "ICB, PCN and supplier fields only exist from mid-2022. Earlier ICB membership is bridged from the practice's CCG, so pre-2022-07 ICB history is a reconstruction.",
    "Aggregate series (region, ICB, PCN, national) use each practice's most recent membership applied to its whole history, so they describe the entity's current footprint rather than its historical boundaries.",
    "April brings ICB and PCN restructures. Comparisons that span an April may not be like for like.",
    "NHS England issues retroactive corrections; a month's figures can change after first publication.",
    "A practice absent from a month may have closed, merged, or simply not reported. The data does not distinguish these.",
]
