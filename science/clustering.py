"""Clustering helpers for the NHS GP Analytics project scaffold."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.impute import SimpleImputer
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

try:  # pragma: no cover - notebook validation exercises the happy path.
    import umap
except Exception:  # pragma: no cover - keep embedding functional without UMAP.
    umap = None


def _practice_column(frame: pd.DataFrame) -> str:
    if "PRACTICE_CODE" in frame.columns:
        return "PRACTICE_CODE"
    if "CODE" in frame.columns:
        return "CODE"
    raise ValueError("cluster_practices expects PRACTICE_CODE or CODE.")


def _age_months(frame: pd.DataFrame, code_column: str) -> pd.Series:
    if "SNAPSHOT_DATE" not in frame.columns:
        return pd.Series(0.0, index=frame.index)

    snapshot = pd.to_datetime(frame["SNAPSHOT_DATE"], errors="coerce").dt.to_period("M")
    first_seen = snapshot.groupby(frame[code_column]).transform("min")
    age = (snapshot.dt.year - first_seen.dt.year) * 12 + (snapshot.dt.month - first_seen.dt.month)
    return age.astype(float).fillna(0.0)


def _build_feature_frame(df: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    if df.empty:
        return pd.DataFrame(), "PRACTICE_CODE"

    frame = df.copy()
    code_column = _practice_column(frame)

    if "NUMBER_OF_PATIENTS" not in frame.columns:
        raise ValueError("cluster_practices expects NUMBER_OF_PATIENTS.")

    frame["NUMBER_OF_PATIENTS"] = pd.to_numeric(frame["NUMBER_OF_PATIENTS"], errors="coerce")
    frame["IMD_DECILE"] = pd.to_numeric(frame["IMD_DECILE"], errors="coerce") if "IMD_DECILE" in frame.columns else np.nan
    frame["AGE_MONTHS"] = _age_months(frame, code_column)
    frame["LOG_PATIENTS"] = np.log1p(frame["NUMBER_OF_PATIENTS"].fillna(0.0))
    return frame.reset_index(drop=True), code_column


def _feature_matrix(frame: pd.DataFrame) -> tuple[np.ndarray, pd.DataFrame]:
    """Standardised numeric feature matrix for K-Means.

    Categorical columns (region, clinical system) are deliberately excluded from the
    distance and used only to profile clusters afterwards: DEC-005 validation showed
    that one-hot columns dominated the partition, making four of five clusters 100%
    pure by clinical system (DEC-006). Constant columns (e.g. AGE_MONTHS on a
    single-snapshot input) are dropped for the same reason — they carry no signal.
    """

    numeric = frame[["LOG_PATIENTS", "IMD_DECILE", "AGE_MONTHS"]].copy()
    numeric = pd.DataFrame(SimpleImputer(strategy="median").fit_transform(numeric), columns=numeric.columns)
    varying = numeric.loc[:, numeric.nunique() > 1]
    if varying.empty:
        return np.zeros((len(numeric), 0)), varying
    return StandardScaler().fit_transform(varying), varying


def _choose_cluster_count(matrix: np.ndarray, requested: int) -> tuple[int, float]:
    """Pick a cluster count by silhouette over 2..requested+2 (DEC-006 widened search).

    Returns (cluster_count, silhouette). The previous requested ± 1 search could never
    move far from the caller's guess; the widened range lets the data vote while the
    requested value still caps the effective maximum.
    """

    sample_count = matrix.shape[0]
    if sample_count < 3 or matrix.shape[1] == 0:
        return 1, float("nan")

    upper = min(sample_count - 1, requested + 2)
    candidates = list(range(2, upper + 1)) or [min(2, sample_count - 1)]

    best_k = candidates[0]
    best_score = float("nan")
    for candidate in candidates:
        if candidate >= sample_count:
            continue
        model = KMeans(n_clusters=candidate, random_state=42, n_init=10)
        labels = model.fit_predict(matrix)
        if len(set(labels)) < 2:
            continue
        score = silhouette_score(matrix, labels)
        if np.isnan(best_score) or score > best_score:
            best_score = score
            best_k = candidate
    return best_k, float(best_score)


def umap_embed(df: pd.DataFrame) -> pd.DataFrame:
    """Add two-dimensional embedding columns for practice clusters."""

    frame, _ = _build_feature_frame(df)
    if frame.empty:
        return frame.assign(UMAP_X=pd.Series(dtype=float), UMAP_Y=pd.Series(dtype=float))

    matrix, _ = _feature_matrix(frame)
    if len(frame) < 3 or matrix.shape[1] == 0:
        frame["UMAP_X"] = 0.0
        frame["UMAP_Y"] = 0.0
        return frame

    if umap is None:
        # Deterministic linear fallback when UMAP is unavailable.
        centered = matrix - matrix.mean(axis=0, keepdims=True)
        _, _, vt = np.linalg.svd(centered, full_matrices=False)
        projection = centered @ vt[:2].T if vt.shape[0] >= 2 else np.column_stack([centered[:, 0], np.zeros(len(centered))])
    else:
        reducer = umap.UMAP(
            n_neighbors=min(15, len(frame) - 1),
            n_components=2,
            min_dist=0.15,
            metric="euclidean",
            random_state=42,
        )
        projection = reducer.fit_transform(matrix)

    frame["UMAP_X"] = projection[:, 0]
    frame["UMAP_Y"] = projection[:, 1]
    return frame


def cluster_practices(df: pd.DataFrame, n_clusters: int = 6, auto_k: bool = True) -> pd.DataFrame:
    """Cluster practices using K-Means and attach cluster-level profile summaries.

    Distances use standardised numeric features only; region and clinical system are
    reported as cluster profiles (dominant values), not used as features (DEC-006).
    The output includes SILHOUETTE_SCORE so consumers can qualify the segmentation
    (> 0.5 strong structure, < 0.25 weak — present the clusters as segments, not
    discovered archetypes).

    With ``auto_k`` (default) the cluster count is chosen by silhouette over
    2..n_clusters+2, so it may come out lower than requested when the data prefers a
    coarser split. Pass ``auto_k=False`` to use exactly ``n_clusters`` — legitimate
    when a consumer wants finer segments for slicing and accepts the silhouette cost.
    """

    frame, code_column = _build_feature_frame(df)
    if frame.empty:
        return frame.assign(CLUSTER=pd.Series(dtype=int), CLUSTER_LABEL=pd.Series(dtype=int))

    matrix, numeric = _feature_matrix(frame)
    if auto_k:
        cluster_count, silhouette = _choose_cluster_count(matrix, n_clusters)
    else:
        cluster_count = min(n_clusters, max(1, matrix.shape[0] - 1))
        if matrix.shape[1] == 0:
            cluster_count = 1
        silhouette = float("nan")
        if cluster_count >= 2:
            labels = KMeans(n_clusters=cluster_count, random_state=42, n_init=10).fit_predict(matrix)
            if len(set(labels)) >= 2:
                silhouette = float(silhouette_score(matrix, labels))
    if cluster_count <= 1:
        frame["CLUSTER"] = 0
    else:
        model = KMeans(n_clusters=cluster_count, random_state=42, n_init=10)
        frame["CLUSTER"] = model.fit_predict(matrix)
    frame["SILHOUETTE_SCORE"] = silhouette

    frame["CLUSTER_LABEL"] = frame["CLUSTER"]
    frame = umap_embed(frame)
    return _attach_cluster_profiles(frame, code_column)


def _attach_cluster_profiles(frame: pd.DataFrame, code_column: str) -> pd.DataFrame:
    """Merge per-cluster profile summaries onto clustered rows."""

    cluster_summary = (
        frame.groupby("CLUSTER", dropna=False)
        .agg(
            CLUSTER_SIZE=(code_column, "nunique"),
            CLUSTER_AVG_PATIENTS=("NUMBER_OF_PATIENTS", "mean"),
            CLUSTER_AVG_IMD_DECILE=("IMD_DECILE", "mean"),
            CLUSTER_AVG_AGE_MONTHS=("AGE_MONTHS", "mean"),
        )
        .reset_index()
    )

    if "CLINICAL_SYSTEM" in frame.columns:
        dominant_system = frame.groupby("CLUSTER")["CLINICAL_SYSTEM"].agg(lambda series: series.dropna().mode().iat[0] if not series.dropna().mode().empty else None)
        cluster_summary = cluster_summary.merge(dominant_system.rename("CLUSTER_DOMINANT_SYSTEM"), on="CLUSTER", how="left")
    if "COMM_REGION_NAME" in frame.columns:
        dominant_region = frame.groupby("CLUSTER")["COMM_REGION_NAME"].agg(lambda series: series.dropna().mode().iat[0] if not series.dropna().mode().empty else None)
        cluster_summary = cluster_summary.merge(dominant_region.rename("CLUSTER_DOMINANT_REGION"), on="CLUSTER", how="left")

    frame = frame.merge(cluster_summary, on="CLUSTER", how="left")
    return frame.sort_values(["CLUSTER", code_column]).reset_index(drop=True)


def cluster_practices_by_k(df: pd.DataFrame, k_values: range | list[int] = range(2, 11)) -> pd.DataFrame:
    """Cluster once per candidate k so a consumer can switch interactively (DEC-008).

    The feature matrix and UMAP embedding are k-independent and computed once; only
    the K-Means fit, silhouette, and profiles vary per k. Returns a long frame with
    one row per practice per K (columns K, CLUSTER, SILHOUETTE_SCORE plus the usual
    cluster_practices outputs); infeasible k values are skipped.
    """

    frame, code_column = _build_feature_frame(df)
    if frame.empty:
        return frame.assign(K=pd.Series(dtype=int), CLUSTER=pd.Series(dtype=int))

    matrix, _ = _feature_matrix(frame)
    frame = umap_embed(frame)

    partitions = []
    for k in k_values:
        if k < 2 or k >= len(frame) or matrix.shape[1] == 0:
            continue
        labels = KMeans(n_clusters=k, random_state=42, n_init=10).fit_predict(matrix)
        if len(set(labels)) < 2:
            continue
        partition = frame.copy()
        partition["K"] = int(k)
        partition["CLUSTER"] = labels
        partition["CLUSTER_LABEL"] = labels
        partition["SILHOUETTE_SCORE"] = float(silhouette_score(matrix, labels))
        partitions.append(_attach_cluster_profiles(partition, code_column))

    if not partitions:
        return frame.assign(K=pd.Series(dtype=int), CLUSTER=pd.Series(dtype=int))
    return pd.concat(partitions, ignore_index=True)
