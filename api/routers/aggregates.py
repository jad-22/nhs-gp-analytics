"""Region, ICB, PCN and national endpoints.

All four levels behave identically, so the routes are generated from one table rather
than written out four times.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from api import presenters, repository, serialization
from api.deps import not_found, source_meta
from api.models import EntityListResponse, ErrorResponse, ForecastResponse, ListSizeResponse

router = APIRouter(tags=["aggregates"])

# path segment -> (level, singular noun used in prose)
AGGREGATES = {
    "regions": ("region", "NHS England commissioning region"),
    "icbs": ("icb", "Integrated Care Board"),
    "pcns": ("pcn", "Primary Care Network"),
}

NATIONAL_CODE = "ENG"
NOT_FOUND = {404: {"model": ErrorResponse, "description": "No entity with that code at this level."}}


def _entity_or_404(level: str, entity_code: str) -> dict:
    record = repository.get_entity(level, entity_code)
    if record is None:
        raise not_found(
            f"No {level} with code {repository.normalise_code(entity_code)}.",
            f"{level}_not_found",
        )
    return record


def _register(segment: str, level: str, noun: str) -> None:
    # Explicit operation_ids: the three handlers below are generated once per level and
    # therefore share function names, which FastAPI would otherwise turn into duplicate
    # operationIds in the published spec — enough to break client generators.
    @router.get(
        f"/{segment}",
        response_model=EntityListResponse,
        summary=f"List every {noun}",
        operation_id=f"list_{segment}",
        tags=[segment],
    )
    def list_all(search: str | None = Query(None, description="Case-insensitive match on code or name.")) -> dict:
        frame = repository.list_entities(level, search=search)
        return {
            "entities": serialization.rows(
                frame, ["LEVEL", "ENTITY_CODE", "ENTITY_NAME", "PRACTICE_COUNT", "LATEST_PATIENTS", "AS_OF"]
            ),
            "meta": source_meta(),
        }

    @router.get(
        f"/{segment}/{{entity_code}}/list-size",
        response_model=ListSizeResponse,
        responses=NOT_FOUND,
        summary=f"Monthly registered-patient history for one {noun}",
        operation_id=f"{level}_list_size",
        description=(
            f"Total registered patients across every practice in the {noun}. Practices "
            "are assigned by their most recent membership, applied to their whole "
            "history, so the series describes the entity's current footprint rather "
            "than its historical boundaries — see /v1/meta."
        ),
        tags=[segment],
    )
    def history(entity_code: str) -> dict:
        record = _entity_or_404(level, entity_code)
        frame = repository.aggregate_history(level, record["ENTITY_CODE"])
        return presenters.list_size_response(level, record["ENTITY_CODE"], record.get("ENTITY_NAME"), frame)

    @router.get(
        f"/{segment}/{{entity_code}}/forecast",
        response_model=ForecastResponse,
        responses=NOT_FOUND,
        summary=f"12-month precomputed forecast for one {noun}",
        operation_id=f"{level}_forecast",
        tags=[segment],
    )
    def forecast(entity_code: str) -> dict:
        record = _entity_or_404(level, entity_code)
        return presenters.forecast_response(level, record["ENTITY_CODE"], record.get("ENTITY_NAME"))


for _segment, (_level, _noun) in AGGREGATES.items():
    _register(_segment, _level, _noun)


@router.get(
    "/national/list-size",
    response_model=ListSizeResponse,
    summary="Monthly registered-patient history for England",
    tags=["national"],
)
def national_list_size() -> dict:
    record = _entity_or_404("national", NATIONAL_CODE)
    frame = repository.aggregate_history("national", NATIONAL_CODE)
    return presenters.list_size_response("national", NATIONAL_CODE, record.get("ENTITY_NAME"), frame)


@router.get(
    "/national/forecast",
    response_model=ForecastResponse,
    summary="12-month precomputed forecast for England",
    tags=["national"],
)
def national_forecast() -> dict:
    record = _entity_or_404("national", NATIONAL_CODE)
    return presenters.forecast_response("national", NATIONAL_CODE, record.get("ENTITY_NAME"))
