import numpy as np
import pandas as pd
import pytest

from science.cluster_validation import (
    bootstrap_stability,
    category_crosstab,
    cramers_v,
    feature_correlations,
    sweep_cluster_counts,
)


def _three_blob_practices(per_group: int = 25, seed: int = 0) -> pd.DataFrame:
    """Synthetic practices forming three well-separated groups in feature space."""

    rng = np.random.default_rng(seed)
    groups = [
        {"patients": 2_000, "imd": 1.0, "region": "North East"},
        {"patients": 20_000, "imd": 5.0, "region": "Midlands"},
        {"patients": 90_000, "imd": 10.0, "region": "London"},
    ]
    rows = []
    for group_index, group in enumerate(groups):
        for i in range(per_group):
            rows.append(
                {
                    "PRACTICE_CODE": f"G{group_index}P{i}",
                    "NUMBER_OF_PATIENTS": group["patients"] * rng.uniform(0.95, 1.05),
                    "IMD_DECILE": group["imd"],
                    "COMM_REGION_NAME": group["region"],
                }
            )
    return pd.DataFrame(rows)


def test_feature_correlations_shape_and_diagonal() -> None:
    correlations = feature_correlations(_three_blob_practices())

    assert list(correlations.columns) == ["LOG_PATIENTS", "IMD_DECILE", "AGE_MONTHS"]
    assert np.allclose(np.diag(correlations.iloc[:2, :2]), 1.0)
    # Size and IMD are constructed to move together across the blobs.
    assert correlations.loc["LOG_PATIENTS", "IMD_DECILE"] > 0.9


def test_sweep_cluster_counts_prefers_true_k() -> None:
    sweep = sweep_cluster_counts(_three_blob_practices(), k_values=range(2, 8))

    assert list(sweep["k"]) == [2, 3, 4, 5, 6, 7]
    assert sweep["inertia"].is_monotonic_decreasing
    best_k = int(sweep.loc[sweep["silhouette"].idxmax(), "k"])
    assert best_k == 3


def test_sweep_skips_impossible_k() -> None:
    tiny = _three_blob_practices(per_group=1)  # 3 practices

    sweep = sweep_cluster_counts(tiny, k_values=range(2, 10))

    assert list(sweep["k"]) == [2]


def test_bootstrap_stability_high_for_separated_blobs() -> None:
    stability = bootstrap_stability(_three_blob_practices(), n_clusters=3, n_runs=10)

    assert len(stability) == 10
    assert set(stability.columns) == {"run", "ari", "n_samples"}
    assert stability["ari"].mean() > 0.9


def test_bootstrap_stability_empty_when_k_too_large() -> None:
    tiny = _three_blob_practices(per_group=1)

    stability = bootstrap_stability(tiny, n_clusters=5, n_runs=3)

    assert stability.empty


def test_category_crosstab_rows_sum_to_one() -> None:
    clustered = pd.DataFrame(
        {
            "CLUSTER": [0, 0, 0, 1, 1, 1],
            "COMM_REGION_NAME": ["London", "London", "Midlands", "North East", None, "North East"],
        }
    )

    crosstab = category_crosstab(clustered)

    assert np.allclose(crosstab.sum(axis=1), 1.0)
    assert "Unknown" in crosstab.columns
    with pytest.raises(ValueError):
        category_crosstab(clustered.drop(columns=["CLUSTER"]))


def test_cramers_v_detects_perfect_and_no_association() -> None:
    aligned = pd.DataFrame(
        {
            "CLUSTER": [0] * 30 + [1] * 30,
            "COMM_REGION_NAME": ["London"] * 30 + ["Midlands"] * 30,
        }
    )
    rng = np.random.default_rng(1)
    independent = pd.DataFrame(
        {
            "CLUSTER": rng.integers(0, 2, size=400),
            "COMM_REGION_NAME": rng.choice(["London", "Midlands"], size=400),
        }
    )

    assert cramers_v(aligned) > 0.95
    assert cramers_v(independent) < 0.2


def test_cramers_v_nan_for_single_category() -> None:
    single = pd.DataFrame({"CLUSTER": [0, 1, 0, 1], "COMM_REGION_NAME": ["London"] * 4})

    assert np.isnan(cramers_v(single))
