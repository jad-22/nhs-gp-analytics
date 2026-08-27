"""FastAPI application for the public NHS GP list-size and forecast API.

Read-only, unauthenticated, and entirely served from a compiled DuckDB file: no model
runs in a request, so every response is a lookup measured in single-digit milliseconds.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from api import db
from api.config import (
    API_PREFIX,
    API_TITLE,
    API_VERSION,
    ATTRIBUTION,
    CACHE_MAX_AGE,
    CACHE_STALE_WHILE_REVALIDATE,
    LICENCE_NAME,
    LICENCE_URL,
    RATE_LIMIT_PER_DAY,
    RATE_LIMIT_PER_MINUTE,
    SOURCE_URL,
)
from api.routers import aggregates, meta, practices

DESCRIPTION = f"""
Monthly GP practice registration counts for England, with 12-month forecasts.

**Look up a practice by ODS code and get its forecast** — that is the core of it:

    GET /v1/practices/A81001/forecast

Everything is free, unauthenticated and read-only. Forecasts are precomputed once a
month, so responses are static lookups; please cache them rather than re-requesting.

### Reading the forecasts

Each forecast carries the model that produced it, the accuracy of that model on *this
series* (`mase` — below 1 beats repeating last year's value), and whether its interval
was calibrated from the series' own backtest errors. Intervals are nominally 80% but
measured out-of-sample coverage is closer to 74%; `/v1/meta` publishes the measured
figure. Different aggregation levels use different models because their accuracy
ranking reverses — `/v1/meta/models` says which and why.

### Before you draw conclusions

Registration counts are not population counts, the data source changed in January 2023,
and ICB boundaries move. `/v1/meta` lists the caveats in full.

### Licence

{ATTRIBUTION}
"""

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[RATE_LIMIT_PER_MINUTE, RATE_LIMIT_PER_DAY],
    headers_enabled=True,
)

app = FastAPI(
    title=API_TITLE,
    version=API_VERSION,
    description=DESCRIPTION,
    openapi_url=f"{API_PREFIX}/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    license_info={"name": LICENCE_NAME, "url": LICENCE_URL},
    contact={"name": "NHS GP Analytics", "url": SOURCE_URL},
    openapi_tags=[
        {"name": "practices", "description": "Individual GP practices, keyed by ODS code."},
        {"name": "regions", "description": "NHS England commissioning regions."},
        {"name": "icbs", "description": "Integrated Care Boards."},
        {"name": "pcns", "description": "Primary Care Networks."},
        {"name": "national", "description": "England as a whole."},
        {"name": "meta", "description": "Data vintage, caveats, and model accuracy."},
        {"name": "service", "description": "Operational endpoints."},
    ],
)

app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
# Open CORS: the data is public and read-only, and browser notebooks are a first-class
# client. Only GET is allowed because nothing else exists.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
    expose_headers=["ETag", "Cache-Control", "Retry-After"],
)

app.include_router(practices.router, prefix=API_PREFIX)
app.include_router(aggregates.router, prefix=API_PREFIX)
app.include_router(meta.router, prefix=API_PREFIX)


@app.middleware("http")
async def cache_headers(request: Request, call_next):
    """Attach long-lived caching and a vintage ETag, and answer If-None-Match with 304.

    The data changes once a month, so a conditional request should almost always be a
    304 and the origin should serve almost nothing.
    """

    if request.method != "GET" or not request.url.path.startswith(API_PREFIX):
        return await call_next(request)

    try:
        etag = f'"{db.run_id()}"'
    except RuntimeError:  # database missing — let the handler report it
        return await call_next(request)

    if request.headers.get("if-none-match") == etag:
        # Response, not JSONResponse: a 304 must not carry a body (RFC 9110 §15.4.5).
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": _cache_control()})

    response = await call_next(request)
    if response.status_code == 200:
        response.headers["ETag"] = etag
        response.headers["Cache-Control"] = _cache_control()
    return response


def _cache_control() -> str:
    return f"public, max-age={CACHE_MAX_AGE}, stale-while-revalidate={CACHE_STALE_WHILE_REVALIDATE}"


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Return the documented error shape rather than FastAPI's bare ``detail``."""

    code = (exc.headers or {}).get("X-Error-Code")
    headers = {key: value for key, value in (exc.headers or {}).items() if key != "X-Error-Code"}
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "code": code},
        headers=headers or None,
    )


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={
            "detail": (
                f"Rate limit exceeded ({exc.detail}). This data changes monthly — please "
                "cache responses rather than re-requesting them."
            ),
            "code": "rate_limited",
        },
        headers={"Retry-After": "60"},
    )


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc), "code": "bad_request"})


@app.get("/health", tags=["service"], summary="Liveness and vintage check", include_in_schema=True)
def health() -> dict:
    """Cheap enough to poll: confirms the serving database opens and reports its vintage."""

    record = db.meta()
    return {
        "status": "ok",
        "run_id": str(record["RUN_ID"]),
        "trained_through": str(record["TRAINED_THROUGH"])[:10],
        "practices": int(record["PRACTICE_COUNT"]),
    }


@app.get("/", include_in_schema=False)
def root() -> dict:
    return {
        "name": API_TITLE,
        "version": API_VERSION,
        "docs": "/docs",
        "openapi": f"{API_PREFIX}/openapi.json",
        "start_here": f"{API_PREFIX}/practices/A81001/forecast",
        "caveats": f"{API_PREFIX}/meta",
        "licence": LICENCE_NAME,
    }
