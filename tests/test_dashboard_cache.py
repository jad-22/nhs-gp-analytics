from datetime import date

import pandas as pd

from dashboard.data import PageFilters, aggregate_list_size, aggregate_market_share, filter_frame
from scripts.build_dashboard_cache import build_list_size_geo, build_market_share


def test_build_dashboard_grouped_caches() -> None:
    joined = pd.DataFrame(
        [
            {
                "SNAPSHOT_DATE": pd.Timestamp("2026-01-01"),
                "CODE": "A1",
                "NUMBER_OF_PATIENTS": 100,
                "REGION_NAME": "London",
                "ICB_NAME": "North London",
                "CLINICAL_SYSTEM": "EMIS Web",
            },
            {
                "SNAPSHOT_DATE": pd.Timestamp("2026-01-01"),
                "CODE": "A2",
                "NUMBER_OF_PATIENTS": 300,
                "REGION_NAME": "London",
                "ICB_NAME": "North London",
                "CLINICAL_SYSTEM": "SystmOne",
            },
        ]
    )

    list_size_geo = build_list_size_geo(joined)
    market_share = build_market_share(joined)

    assert int(list_size_geo.iloc[0]["PATIENT_COUNT"]) == 400
    assert int(list_size_geo.iloc[0]["PRACTICE_COUNT"]) == 2
    assert set(market_share["CLINICAL_SYSTEM"]) == {"EMIS Web", "SystmOne"}


def test_dashboard_filter_and_aggregates_recompute_shares() -> None:
    filters = PageFilters(date_from=date(2026, 1, 1), date_to=date(2026, 1, 31), regions=("London",), icbs=())
    frame = pd.DataFrame(
        [
            {
                "SNAPSHOT_DATE": pd.Timestamp("2026-01-01"),
                "REGION_NAME": "London",
                "ICB_NAME": "North London",
                "CLINICAL_SYSTEM": "EMIS Web",
                "PATIENT_COUNT": 100,
                "PRACTICE_COUNT": 1,
            },
            {
                "SNAPSHOT_DATE": pd.Timestamp("2026-01-01"),
                "REGION_NAME": "London",
                "ICB_NAME": "North London",
                "CLINICAL_SYSTEM": "SystmOne",
                "PATIENT_COUNT": 300,
                "PRACTICE_COUNT": 3,
            },
            {
                "SNAPSHOT_DATE": pd.Timestamp("2026-01-01"),
                "REGION_NAME": "Midlands",
                "ICB_NAME": "Birmingham",
                "CLINICAL_SYSTEM": "EMIS Web",
                "PATIENT_COUNT": 999,
                "PRACTICE_COUNT": 9,
            },
        ]
    )

    scoped = filter_frame(frame, filters)
    totals = aggregate_list_size(scoped)
    shares = aggregate_market_share(scoped)

    assert set(scoped["REGION_NAME"]) == {"London"}
    assert int(totals.iloc[0]["PATIENT_COUNT"]) == 400
    assert float(shares.loc[shares["CLINICAL_SYSTEM"] == "SystmOne", "PATIENT_SHARE"].iloc[0]) == 0.75
