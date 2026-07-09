from datetime import datetime

import pandas as pd

from science.anomaly import flag_anomalies
from science.clustering import cluster_practices
from science.deprivation import flag_underserved, regional_inequality, size_imd_correlation
from science.forecasting import forecast_list_size


def test_forecast_list_size_returns_future_months() -> None:
    frame = pd.DataFrame(
        {
            "SNAPSHOT_DATE": pd.date_range("2024-01-01", periods=6, freq="MS"),
            "NUMBER_OF_PATIENTS": [100, 105, 110, 120, 125, 130],
        }
    )

    forecast = forecast_list_size(frame, periods=2)

    assert list(forecast.columns) == ["ds", "yhat", "yhat_lower", "yhat_upper"]
    assert len(forecast) == 2
    assert forecast.iloc[0]["ds"] == pd.Timestamp("2024-07-01")
    assert forecast["yhat"].ge(0).all()


def test_flag_anomalies_labels_closure_and_spike() -> None:
    frame = pd.DataFrame(
        [
            {"SNAPSHOT_DATE": datetime(2024, 1, 1), "CODE": "A1", "NUMBER_OF_PATIENTS": 1000},
            {"SNAPSHOT_DATE": datetime(2024, 2, 1), "CODE": "A1", "NUMBER_OF_PATIENTS": 100},
            {"SNAPSHOT_DATE": datetime(2024, 1, 1), "CODE": "A2", "NUMBER_OF_PATIENTS": 100},
            {"SNAPSHOT_DATE": datetime(2024, 2, 1), "CODE": "A2", "NUMBER_OF_PATIENTS": 200},
        ]
    )

    result = flag_anomalies(frame)

    labels = dict(zip(result["CODE"] + result["SNAPSHOT_DATE"].dt.strftime("%Y-%m"), result["ANOMALY_TYPE"]))
    assert labels["A12024-02"] == "CLOSURE_SUSPECTED"
    assert labels["A22024-02"] == "SPIKE"
    assert {"MOM_CHANGE_ABS", "MOM_CHANGE_PCT", "ANOMALY_FLAG", "ANOMALY_SCORE"}.issubset(result.columns)


def test_cluster_practices_adds_cluster_and_profile_columns() -> None:
    frame = pd.DataFrame(
        [
            {
                "SNAPSHOT_DATE": datetime(2024, 1, 1),
                "PRACTICE_CODE": f"A{i}",
                "NUMBER_OF_PATIENTS": 1000 + i * 100,
                "IMD_DECILE": (i % 10) + 1,
                "COMM_REGION_NAME": "London" if i % 2 else "North East",
                "CLINICAL_SYSTEM": "EMIS Web" if i % 2 else "SystmOne",
            }
            for i in range(12)
        ]
    )

    result = cluster_practices(frame, n_clusters=3)

    expected = {
        "CLUSTER",
        "CLUSTER_LABEL",
        "UMAP_X",
        "UMAP_Y",
        "CLUSTER_SIZE",
        "CLUSTER_AVG_PATIENTS",
        "CLUSTER_DOMINANT_SYSTEM",
    }
    assert expected.issubset(result.columns)
    assert len(result) == len(frame)
    assert result["CLUSTER"].nunique() >= 2


def test_cluster_features_exclude_categoricals_and_constants() -> None:
    frame = pd.DataFrame(
        [
            {
                "SNAPSHOT_DATE": datetime(2024, 1, 1),
                "PRACTICE_CODE": f"A{i}",
                "NUMBER_OF_PATIENTS": 1000 + i * 500,
                "IMD_DECILE": (i % 10) + 1,
                "COMM_REGION_NAME": "London" if i % 2 else "North East",
                "CLINICAL_SYSTEM": "EMIS Web" if i % 2 else "SystmOne",
            }
            for i in range(12)
        ]
    )

    from science.clustering import _build_feature_frame, _feature_matrix

    built, _ = _build_feature_frame(frame)
    matrix, used = _feature_matrix(built)

    # Single snapshot -> AGE_MONTHS is constant and dropped; categoricals are
    # profiling-only (DEC-006), so only the two varying numerics remain.
    assert list(used.columns) == ["LOG_PATIENTS", "IMD_DECILE"]
    assert matrix.shape == (12, 2)


def test_cluster_practices_not_partitioned_by_clinical_system() -> None:
    # Identical numerics, alternating systems: with categoricals out of the distance
    # (DEC-006), the system must no longer force practices into separate clusters.
    frame = pd.DataFrame(
        [
            {
                "SNAPSHOT_DATE": datetime(2024, 1, 1),
                "PRACTICE_CODE": f"A{i}",
                "NUMBER_OF_PATIENTS": 5000 if i < 6 else 50000,
                "IMD_DECILE": 2.0 if i < 6 else 9.0,
                "CLINICAL_SYSTEM": "EMIS Web" if i % 2 else "SystmOne",
            }
            for i in range(12)
        ]
    )

    result = cluster_practices(frame, n_clusters=2)

    assert "SILHOUETTE_SCORE" in result.columns
    assert result["SILHOUETTE_SCORE"].notna().all()
    # Clusters follow the numeric split, mixing both systems within each cluster.
    clusters_per_system_group = result.groupby(result["NUMBER_OF_PATIENTS"] > 10000)["CLUSTER"].nunique()
    assert clusters_per_system_group.eq(1).all()
    assert result.groupby("CLUSTER")["CLINICAL_SYSTEM"].nunique().eq(2).all()


def test_cluster_practices_fixed_k_honours_request() -> None:
    frame = pd.DataFrame(
        [
            {
                "SNAPSHOT_DATE": datetime(2024, 1, 1),
                "PRACTICE_CODE": f"A{i}",
                "NUMBER_OF_PATIENTS": 1000 + i * 977,
                "IMD_DECILE": ((i * 3) % 10) + 1,
            }
            for i in range(20)
        ]
    )

    result = cluster_practices(frame, n_clusters=4, auto_k=False)

    assert result["CLUSTER"].nunique() == 4
    assert result["SILHOUETTE_SCORE"].notna().all()


def test_deprivation_helpers_flag_and_summarise() -> None:
    frame = pd.DataFrame(
        [
            {
                "SNAPSHOT_DATE": datetime(2024, 1, 1),
                "PRACTICE_CODE": "A1",
                "NUMBER_OF_PATIENTS": 100,
                "IMD_DECILE": 1,
                "COMM_REGION_NAME": "London",
            },
            {
                "SNAPSHOT_DATE": datetime(2024, 1, 1),
                "PRACTICE_CODE": "A2",
                "NUMBER_OF_PATIENTS": 500,
                "IMD_DECILE": 5,
                "COMM_REGION_NAME": "London",
            },
            {
                "SNAPSHOT_DATE": datetime(2024, 1, 1),
                "PRACTICE_CODE": "A3",
                "NUMBER_OF_PATIENTS": 900,
                "IMD_DECILE": 9,
                "COMM_REGION_NAME": "London",
            },
        ]
    )

    flagged = flag_underserved(frame)
    inequality = regional_inequality(frame)
    correlation = size_imd_correlation(frame)

    assert bool(flagged.loc[flagged["PRACTICE_CODE"] == "A1", "UNDER_SERVED"].iloc[0]) is True
    assert {"GINI_COEFFICIENT", "PRACTICE_COUNT", "MEAN_PATIENTS", "MEDIAN_PATIENTS"}.issubset(inequality.columns)
    assert {"PEARSON_R", "P_VALUE", "N"}.issubset(correlation.columns)
