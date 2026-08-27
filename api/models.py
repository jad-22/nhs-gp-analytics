"""Pydantic response models.

These exist mainly for the OpenAPI document: every field carries a description and an
example so ``/docs`` explains the data rather than just listing types. Handlers build
plain dicts via ``serialization`` and FastAPI validates them against these shapes.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SourceMeta(BaseModel):
    source: str = Field(description="Attribution required by the licence.")
    licence: str = Field(description="Licence the data is published under.")
    licence_url: str
    caveats_url: str = Field(description="Where the interpretation caveats are listed.")
    run_id: str = Field(description="Identifies the data vintage; also the ETag.", examples=["2026-06.ae37088a1f23"])


class Practice(BaseModel):
    ods_code: str = Field(description="ODS practice code — the primary key.", examples=["A81001"])
    practice_name: str | None = None
    postcode: str | None = None
    pcn_code: str | None = Field(default=None, description="Primary Care Network code.")
    pcn_name: str | None = None
    icb_code: str | None = Field(default=None, description="Integrated Care Board code.")
    icb_name: str | None = None
    region_code: str | None = Field(default=None, description="NHS England commissioning region code.")
    region_name: str | None = None
    clinical_system: str | None = None
    supplier_name: str | None = None
    imd_score: float | None = Field(default=None, description="Index of Multiple Deprivation score for the practice postcode.")
    imd_decile: float | None = Field(default=None, description="IMD decile, 1 = most deprived.")
    latitude: float | None = None
    longitude: float | None = None
    patients: int | None = Field(default=None, description="Registered patients at the latest snapshot.")
    active: bool = Field(description="Whether the practice appears in the latest snapshot.")
    first_month: str | None = Field(default=None, examples=["2020-01-01"])
    last_month: str | None = Field(default=None, examples=["2026-06-01"])
    as_of: str | None = Field(default=None, description="Snapshot the attributes are taken from.")


class EntitySummary(BaseModel):
    level: str = Field(description="One of national, region, icb, pcn.", examples=["icb"])
    entity_code: str = Field(examples=["QHM"])
    entity_name: str | None = None
    practice_count: int = Field(description="Active practices in this entity at the latest snapshot.")
    latest_patients: int | None = None
    as_of: str | None = None


class ListSizePoint(BaseModel):
    date: str = Field(description="First day of the month.", examples=["2026-06-01"])
    patients: int
    data_source: str | None = Field(default=None, description="NHAIS or PDS. Only present for practice series.")


class ListSizeResponse(BaseModel):
    level: str
    entity_code: str
    entity_name: str | None = None
    points: list[ListSizePoint]
    meta: SourceMeta


class ForecastPoint(BaseModel):
    date: str = Field(examples=["2026-07-01"])
    horizon_month: int = Field(description="Months ahead of the last observed month, 1-12.", ge=1)
    yhat: float = Field(description="Point forecast.")
    yhat_lower: float
    yhat_upper: float


class Accuracy(BaseModel):
    mase: float | None = Field(
        default=None,
        description="Mean absolute scaled error from this series' own rolling-origin backtest. Below 1 beats a seasonal-naive forecast.",
        examples=[0.52],
    )
    mae: float | None = None
    rmse: float | None = None
    mape: float | None = Field(default=None, description="Mean absolute percentage error, as a fraction.")
    coverage: float | None = Field(
        default=None,
        description=(
            "What the published interval achieved on a backtest cutoff it was not "
            "calibrated on — the honest figure. Null when the history was too short to "
            "hold a cutoff back."
        ),
        examples=[0.75],
    )
    coverage_native: float | None = Field(
        default=None,
        description="What the model's own uncalibrated band would have achieved. For comparison only; it is not the interval served.",
    )
    n_forecasts: int | None = Field(default=None, description="Backtest observations the metrics are computed over.")


class ForecastBlock(BaseModel):
    model: str = Field(
        description="The model that actually produced these numbers — autoets for practices and PCNs, holt_winters for ICB/region/national, linear where history was too short for either.",
        examples=["autoets"],
    )
    calibrated: bool = Field(
        description="True when the interval was calibrated from this series' own backtest errors rather than left as the model's native band."
    )
    interval_level: float = Field(description="Nominal interval level.", examples=[0.8])
    trained_through: str = Field(description="Last month of observed data used to fit.", examples=["2026-06-01"])
    generated_at: str | None = Field(default=None, description="When the cache was built.")
    interval_warning: str | None = Field(
        default=None, description="Present only when calibrated is false."
    )
    points: list[ForecastPoint]


class ForecastResponse(BaseModel):
    level: str
    entity_code: str
    entity_name: str | None = None
    forecast: ForecastBlock
    accuracy: Accuracy
    meta: SourceMeta


class Page(BaseModel):
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int
    pages: int


class PracticeListResponse(BaseModel):
    practices: list[Practice]
    page: Page
    meta: SourceMeta


class EntityListResponse(BaseModel):
    entities: list[EntitySummary]
    meta: SourceMeta


class ModelAccuracy(BaseModel):
    level: str
    model: str
    entities: int
    median_mase: float | None = Field(default=None, description="Median MASE across this level's series.")
    mean_coverage: float | None = Field(
        default=None, description="Mean held-out coverage of the published interval at this level."
    )
    mean_coverage_native: float | None = Field(
        default=None, description="Mean coverage of the model's own band, for comparison."
    )
    uncalibrated: int = Field(description="Series whose history was too short to calibrate an interval.")
    quarantined: int = Field(description="Series withheld because no model could track them.")


class ModelsResponse(BaseModel):
    models: list[ModelAccuracy]
    notes: list[str]
    meta: SourceMeta


class MetaResponse(BaseModel):
    run_id: str
    generated_at: str | None = None
    trained_through: str
    earliest_month: str
    latest_month: str
    practice_count: int = Field(description="Practices in the latest snapshot.")
    practice_count_all: int = Field(description="Practices with any history, including closed ones.")
    entity_count: int = Field(description="Aggregate entities (region, ICB, PCN, national).")
    forecast_count: int
    quarantined_count: int
    interval_level: float = Field(description="Nominal level of the published intervals.")
    measured_coverage: float = Field(
        description=(
            "The share of held-out actuals that actually landed inside the published "
            "interval, averaged across every served series. This is lower than "
            "interval_level — use it, not the nominal figure."
        ),
        examples=[0.75],
    )
    median_mase: float
    caveats: list[str]
    licence: str
    licence_url: str
    source: str
    source_url: str


class ErrorResponse(BaseModel):
    detail: str = Field(description="What went wrong, in plain English.")
    code: str | None = Field(default=None, description="Stable machine-readable reason.", examples=["practice_not_found"])
