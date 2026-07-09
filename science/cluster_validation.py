"""Validation diagnostics for the practice clustering in ``science/clustering.py``.

Clustering is unsupervised, so k-fold cross-validation does not apply — there are no
labels to score against. The analogues implemented here are documented in
``docs/CLUSTER_VALIDATION.md`` (decision record DEC-005):

- ``feature_correlations`` — redundancy between numeric features (the clustering
  version of a multicollinearity check: correlated features double-weight a
  dimension in the Euclidean distance).
- ``sweep_cluster_counts`` — internal validity (silhouette, Davies-Bouldin, inertia)
  across a real range of k, not just the production ``requested ± 1`` search.
- ``bootstrap_stability`` — the cross-validation analogue: re-cluster resampled
  subsets and measure agreement with the full-data clustering (Adjusted Rand Index).
- ``category_crosstab`` / ``cramers_v`` — confounding check: do the clusters simply
  re-discover a categorical input such as region?

All diagnostics run on the same feature pipeline as ``cluster_practices`` so they
measure what production actually does.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score, davies_bouldin_score, silhouette_score

from science.clustering import _build_feature_frame, _feature_matrix

NUMERIC_FEATURES = ["LOG_PATIENTS", "IMD_DECILE", "AGE_MONTHS"]


def _matrix_from_input(df: pd.DataFrame) -> np.ndarray:
    frame, _ = _build_feature_frame(df)
    if frame.empty:
        return np.empty((0, 0))
    matrix, _ = _feature_matrix(frame)
    return matrix


def feature_correlations(df: pd.DataFrame) -> pd.DataFrame:
    """Spearman correlation matrix of the numeric clustering features.

    Pairs above ~0.7 in absolute value effectively double-weight one underlying
    dimension in the K-Means distance and are candidates for dropping or combining.
    """

    frame, _ = _build_feature_frame(df)
    if frame.empty:
        return pd.DataFrame(columns=NUMERIC_FEATURES, index=NUMERIC_FEATURES, dtype=float)
    return frame[NUMERIC_FEATURES].corr(method="spearman")


def sweep_cluster_counts(
    df: pd.DataFrame,
    k_values: range | list[int] = range(2, 13),
    random_state: int = 42,
) -> pd.DataFrame:
    """Fit K-Means for each candidate k and score internal validity.

    Returns one row per k with inertia (for the elbow heuristic), silhouette
    (higher is better; > 0.5 strong, < 0.25 weak), and Davies-Bouldin
    (lower is better). Candidates that cannot produce 2+ clusters are skipped.
    """

    matrix = _matrix_from_input(df)
    rows = []
    for k in k_values:
        if matrix.shape[0] <= k or k < 2:
            continue
        model = KMeans(n_clusters=k, random_state=random_state, n_init=10)
        labels = model.fit_predict(matrix)
        if len(set(labels)) < 2:
            continue
        rows.append(
            {
                "k": k,
                "inertia": float(model.inertia_),
                "silhouette": float(silhouette_score(matrix, labels)),
                "davies_bouldin": float(davies_bouldin_score(matrix, labels)),
            }
        )
    return pd.DataFrame(rows, columns=["k", "inertia", "silhouette", "davies_bouldin"])


def bootstrap_stability(
    df: pd.DataFrame,
    n_clusters: int,
    n_runs: int = 20,
    sample_frac: float = 0.8,
    random_state: int = 42,
) -> pd.DataFrame:
    """Cluster resampled subsets and compare against the full-data clustering.

    For each run, a random ``sample_frac`` subset is re-clustered from a fresh seed
    and agreement with the reference labels on that subset is measured with the
    Adjusted Rand Index (1 = identical partitions, 0 = chance agreement). Mean ARI
    above ~0.8 indicates stable, real structure; below ~0.6 the clusters should not
    be narrated as meaningful segments.
    """

    matrix = _matrix_from_input(df)
    if matrix.shape[0] <= n_clusters or n_clusters < 2:
        return pd.DataFrame(columns=["run", "ari", "n_samples"])

    reference = KMeans(n_clusters=n_clusters, random_state=random_state, n_init=10).fit_predict(matrix)
    rng = np.random.default_rng(random_state)

    rows = []
    for run in range(n_runs):
        size = max(n_clusters + 1, int(matrix.shape[0] * sample_frac))
        indices = rng.choice(matrix.shape[0], size=min(size, matrix.shape[0]), replace=False)
        labels = KMeans(n_clusters=n_clusters, random_state=random_state + 1 + run, n_init=10).fit_predict(
            matrix[indices]
        )
        rows.append(
            {
                "run": run,
                "ari": float(adjusted_rand_score(reference[indices], labels)),
                "n_samples": int(len(indices)),
            }
        )
    return pd.DataFrame(rows)


def category_crosstab(clustered: pd.DataFrame, column: str = "COMM_REGION_NAME") -> pd.DataFrame:
    """Row-normalised CLUSTER x category composition (rows sum to 1).

    A row concentrated in one category means that cluster is mostly re-discovering
    the category — expected to a degree when the category is a clustering feature,
    but a near-diagonal table means the segmentation adds nothing beyond it.
    """

    if "CLUSTER" not in clustered.columns:
        raise ValueError("category_crosstab expects a CLUSTER column (output of cluster_practices).")
    if column not in clustered.columns:
        raise ValueError(f"category_crosstab expects a {column} column.")

    counts = pd.crosstab(clustered["CLUSTER"], clustered[column].fillna("Unknown"))
    return counts.div(counts.sum(axis=1), axis=0)


def cramers_v(clustered: pd.DataFrame, column: str = "COMM_REGION_NAME") -> float:
    """Bias-corrected Cramér's V between cluster assignment and a categorical column.

    0 = independent, 1 = the category fully determines the cluster. Values above
    ~0.8 mean the clustering is largely a re-labelling of that category.
    """

    if "CLUSTER" not in clustered.columns or column not in clustered.columns:
        raise ValueError(f"cramers_v expects CLUSTER and {column} columns.")

    counts = pd.crosstab(clustered["CLUSTER"], clustered[column].fillna("Unknown"))
    if counts.shape[0] < 2 or counts.shape[1] < 2:
        return float("nan")

    chi2 = chi2_contingency(counts)[0]
    n = counts.to_numpy().sum()
    phi2 = chi2 / n
    r, k = counts.shape
    # Bergsma-Wicher bias correction.
    phi2_corrected = max(0.0, phi2 - (k - 1) * (r - 1) / (n - 1))
    r_corrected = r - (r - 1) ** 2 / (n - 1)
    k_corrected = k - (k - 1) ** 2 / (n - 1)
    denominator = min(k_corrected - 1, r_corrected - 1)
    if denominator <= 0:
        return float("nan")
    return float(np.sqrt(phi2_corrected / denominator))
