"""Practice-level endpoints — the core of the API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from api import presenters, repository, serialization
from api.deps import Pagination, not_found, pagination, source_meta
from api.models import ErrorResponse, ForecastResponse, ListSizeResponse, PracticeListResponse, Practice

router = APIRouter(prefix="/practices", tags=["practices"])

NOT_FOUND = {404: {"model": ErrorResponse, "description": "No practice with that ODS code."}}


def _practice_or_404(ods_code: str) -> dict:
    record = repository.get_practice(ods_code)
    if record is None:
        raise not_found(
            f"No practice with ODS code {repository.normalise_code(ods_code)}. "
            "Search for one at /v1/practices?search=.",
            "practice_not_found",
        )
    return record


@router.get(
    "",
    response_model=PracticeListResponse,
    summary="Search and list practices",
    description=(
        "Paginated practice lookup. Combine `search` with `icb`, `pcn` or `region` to "
        "narrow by geography. Closed practices are included by default — pass "
        "`active=true` for only those in the latest snapshot."
    ),
)
def list_practices(
    search: str | None = Query(None, description="Case-insensitive match on ODS code or practice name."),
    icb: str | None = Query(None, description="Filter by ICB code."),
    pcn: str | None = Query(None, description="Filter by PCN code."),
    region: str | None = Query(None, description="Filter by NHS England commissioning region code."),
    active: bool | None = Query(None, description="Restrict to practices present in the latest snapshot."),
    page: Pagination = Depends(pagination),
) -> dict:
    frame, total = repository.search_practices(
        search=search,
        icb=icb,
        pcn=pcn,
        region=region,
        active=active,
        limit=page.page_size,
        offset=page.offset,
    )
    return {
        "practices": serialization.rows(frame, repository.PRACTICE_COLUMNS),
        "page": page.envelope(total),
        "meta": source_meta(),
    }


@router.get(
    "/{ods_code}",
    response_model=Practice,
    responses=NOT_FOUND,
    summary="Get one practice",
    description="Attributes as of the latest snapshot. Historical attribute lookup is not in v1.",
)
def get_practice(ods_code: str) -> dict:
    return serialization.row(_practice_or_404(ods_code), repository.PRACTICE_COLUMNS)


@router.get(
    "/{ods_code}/list-size",
    response_model=ListSizeResponse,
    responses=NOT_FOUND,
    summary="Monthly registered-patient history",
    description=(
        "The full monthly series for this practice, oldest first. Available for closed "
        "practices too. `data_source` records whether the month came from NHAIS or PDS "
        "— see /v1/meta for why that matters."
    ),
)
def practice_list_size(ods_code: str) -> dict:
    record = _practice_or_404(ods_code)
    history = repository.practice_history(ods_code)
    return presenters.list_size_response(
        "practice", record["ODS_CODE"], record.get("PRACTICE_NAME"), history
    )


@router.get(
    "/{ods_code}/forecast",
    response_model=ForecastResponse,
    responses={
        404: {
            "model": ErrorResponse,
            "description": "No practice with that code, or the practice has closed or been withheld.",
        }
    },
    summary="12-month precomputed forecast",
    description=(
        "Twelve monthly points with an 80% interval calibrated from this practice's own "
        "rolling-origin backtest, plus the backtest accuracy behind it. Forecasts are "
        "precomputed monthly — no model runs in the request. Practices absent from the "
        "latest snapshot return 404: their list has stopped, and extrapolating it would "
        "be fiction."
    ),
)
def practice_forecast(ods_code: str) -> dict:
    record = _practice_or_404(ods_code)
    return presenters.forecast_response(
        "practice",
        record["ODS_CODE"],
        record.get("PRACTICE_NAME"),
        closed=not bool(record["ACTIVE"]),
    )
