"""Resolve practices into the aggregation hierarchy the forecasts and API serve.

Both ``scripts/build_forecast_cache.py`` and ``scripts/build_serving_db.py`` need the
same answer to "which PCN / ICB / region does this practice belong to, and what is the
monthly total for each of them" — and they must agree exactly, or the API would serve a
history that its own forecast was not trained on. The logic lives here so there is one
definition rather than two.

Deliberately imports nothing beyond pandas and ``pipeline.config``: the API's Docker
build runs this, and pulling ``science`` in would drag statsmodels and statsforecast
into an image whose whole point is that it contains no forecasting libraries.

Two conventions are fixed here and documented in DEC-012:

*Membership is fixed at each practice's latest known assignment* and applied to its
whole history, so an aggregate series describes the entity's current footprint
consistently over time. The alternative — the entity as constituted each month — makes
ICB series impossible (``ICB_CODE`` only exists from 2022-07) and injects April
restructures as step changes no model can forecast.

*Aggregates are summed over every practice that reported that month*, including ones
that have since closed. Dropping closed practices from history would manufacture a
spurious growth trend.
"""

from __future__ import annotations

import pandas as pd

# The month CCGs were replaced by ICBs. Before it, mapping rows carry CCG_CODE and no
# ICB_CODE; from it, the reverse. There is no overlapping month to join on.
ICB_HANDOVER = pd.Timestamp("2022-07-01")
CCG_FINAL_MONTH = pd.Timestamp("2022-06-01")

LEVELS = ("national", "region", "icb", "pcn", "practice")
NATIONAL_CODE = "ENG"
NATIONAL_NAME = "England"

# The practice-level column that identifies each level's entity. National is a constant.
LEVEL_COLUMNS = {"region": "REGION_CODE", "icb": "ICB_CODE", "pcn": "PCN_CODE", "practice": "CODE"}


def month_start(values: pd.Series) -> pd.Series:
    """Normalise a date column to the first of its month."""

    return pd.to_datetime(values, errors="coerce").dt.to_period("M").dt.to_timestamp(how="start")


def _last_known(mapping: pd.DataFrame, column: str) -> pd.Series:
    """Each practice's most recent non-null value for a column."""

    present = mapping.loc[mapping[column].notna(), ["PRACTICE_CODE", column]]
    return present.groupby("PRACTICE_CODE")[column].last()


def _ccg_to_icb(mapping: pd.DataFrame) -> pd.Series:
    """Bridge the CCG era onto ICBs so pre-handover history is not silently truncated.

    Practices present in both the last CCG month and the first ICB month provide the
    crosswalk. Without it the 352 practices that closed before the handover carry no ICB
    at all, their patients vanish from ICB history, and every ICB series gains a
    spurious ~2.9% growth trend at its start — large enough to bias a forecast and
    invisible in the output.
    """

    before = mapping.loc[mapping["SNAPSHOT_DATE"] == CCG_FINAL_MONTH, ["PRACTICE_CODE", "CCG_CODE"]]
    after = mapping.loc[mapping["SNAPSHOT_DATE"] == ICB_HANDOVER, ["PRACTICE_CODE", "ICB_CODE"]]
    bridge = before.merge(after, on="PRACTICE_CODE", how="inner").dropna(subset=["CCG_CODE", "ICB_CODE"])
    if bridge.empty:
        return pd.Series(dtype=object)
    # A handful of CCGs were split across ICBs; the modal destination is the right
    # answer for an aggregate total and the residual is a few practices.
    return bridge.groupby("CCG_CODE")["ICB_CODE"].agg(lambda codes: codes.mode().iloc[0])


def practice_entities(mapping: pd.DataFrame) -> pd.DataFrame:
    """One row per practice giving its stable code at every aggregation level.

    ``mapping`` must have a month-start ``SNAPSHOT_DATE`` and be sorted by it, so
    "last known" means what it says.
    """

    entities = pd.DataFrame(index=pd.Index(sorted(mapping["PRACTICE_CODE"].unique()), name="PRACTICE_CODE"))
    entities["PRACTICE_NAME"] = _last_known(mapping, "PRACTICE_NAME")
    entities["PCN_CODE"] = _last_known(mapping, "PCN_CODE")
    entities["ICB_CODE"] = _last_known(mapping, "ICB_CODE")
    entities["REGION_CODE"] = _last_known(mapping, "COMM_REGION_CODE")

    crosswalk = _ccg_to_icb(mapping)
    if not crosswalk.empty:
        missing = entities["ICB_CODE"].isna()
        bridged = _last_known(mapping, "CCG_CODE").reindex(entities.index).map(crosswalk)
        entities.loc[missing, "ICB_CODE"] = bridged[missing]
    return entities


def entity_names(mapping: pd.DataFrame) -> dict[str, pd.Series]:
    """Display name per entity code, from the most recent snapshot that names it."""

    names: dict[str, pd.Series] = {}
    for level, code_column, name_column in (
        ("pcn", "PCN_CODE", "PCN_NAME"),
        ("icb", "ICB_CODE", "ICB_NAME"),
        ("region", "COMM_REGION_CODE", "COMM_REGION_NAME"),
    ):
        present = mapping.dropna(subset=[code_column, name_column])
        names[level] = present.groupby(code_column)[name_column].last()
    return names


def build_series(list_size: pd.DataFrame, mapping: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Monthly totals for every served entity, plus a one-row-per-entity register.

    Returns ``(series, register)`` where ``series`` has
    LEVEL / ENTITY_CODE / SNAPSHOT_DATE / NUMBER_OF_PATIENTS and ``register`` has
    LEVEL / ENTITY_CODE / ENTITY_NAME.

    Totals are **summed**. ``science.forecasting._prepare_series`` collapses duplicate
    months with ``groupby("ds").mean()``, so handing it a multi-practice frame would
    yield a mean per practice — an order-of-magnitude error that still looks like a
    plausible number.
    """

    entities = practice_entities(mapping)
    joined = list_size.merge(entities, left_on="CODE", right_index=True, how="left")

    latest_month = joined["SNAPSHOT_DATE"].max()
    active = joined.loc[joined["SNAPSHOT_DATE"] == latest_month]
    names = entity_names(mapping)

    frames = []
    register = []
    for level in LEVELS:
        keys = pd.Series(NATIONAL_CODE, index=joined.index) if level == "national" else joined[LEVEL_COLUMNS[level]]
        block = pd.DataFrame(
            {
                "LEVEL": level,
                "ENTITY_CODE": keys.to_numpy(),
                "SNAPSHOT_DATE": joined["SNAPSHOT_DATE"].to_numpy(),
                "NUMBER_OF_PATIENTS": joined["NUMBER_OF_PATIENTS"].to_numpy(),
            }
        ).dropna(subset=["ENTITY_CODE"])

        # Only entities that still exist are served. Closed practices keep their history
        # but get no forecast — the API explains that rather than extrapolating a list
        # that stopped.
        live = {NATIONAL_CODE} if level == "national" else set(active[LEVEL_COLUMNS[level]].dropna().unique())
        block = block.loc[block["ENTITY_CODE"].isin(live)]

        series = (
            block.groupby(["LEVEL", "ENTITY_CODE", "SNAPSHOT_DATE"], as_index=False)["NUMBER_OF_PATIENTS"]
            .sum()
            .sort_values(["ENTITY_CODE", "SNAPSHOT_DATE"])
        )
        frames.append(series)

        if level == "national":
            lookup = pd.Series({NATIONAL_CODE: NATIONAL_NAME})
        elif level == "practice":
            lookup = entities["PRACTICE_NAME"]
        else:
            lookup = names[level]
        codes = pd.Index(sorted(series["ENTITY_CODE"].unique()))
        register.append(
            pd.DataFrame({"LEVEL": level, "ENTITY_CODE": codes, "ENTITY_NAME": codes.map(lookup).fillna("Unknown")})
        )

    return pd.concat(frames, ignore_index=True), pd.concat(register, ignore_index=True)
