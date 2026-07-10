from datetime import date

import pandas as pd

from dashboard.data import PageFilters, aggregate_list_size, aggregate_market_share, filter_frame
from scripts.build_dashboard_cache import build_cluster_k, build_list_size_geo, build_market_share


def test_build_cluster_k_produces_selectable_partitions() -> None:
    latest = pd.DataFrame(
        [
            {
                "SNAPSHOT_DATE": pd.Timestamp("2026-06-01"),
                "CODE": f"A{i}",
                "PRACTICE_CODE": f"A{i}",
                "NUMBER_OF_PATIENTS": 1000 + i * 977,
                "IMD_DECILE": ((i * 3) % 10) + 1,
                "REGION_NAME": "London" if i % 2 else "Midlands",
                "CLINICAL_SYSTEM": "EMIS Web" if i % 2 else "SystmOne",
            }
            for i in range(20)
        ]
    )

    cache = build_cluster_k(latest)

    assert {"K", "CLUSTER", "SILHOUETTE_SCORE", "UMAP_X", "UMAP_Y", "REGION_NAME"}.issubset(cache.columns)
    assert set(cache["K"].unique()).issubset(set(range(2, 11)))
    assert cache.groupby("K").size().eq(20).all()
    # The dashboard filters this frame by region, so region rows must survive per k.
    filters = PageFilters(date_from=pd.Timestamp("2026-01-01"), date_to=pd.Timestamp("2026-12-31"), regions=("London",))
    scoped = filter_frame(cache, filters)
    assert set(scoped["REGION_NAME"]) == {"London"}
    assert scoped["K"].nunique() == cache["K"].nunique()


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
