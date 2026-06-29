"""Clustering helpers for the NHS GP Analytics project scaffold."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.impute import SimpleImputer
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import OneHotEncoder, StandardScaler

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
    numeric = frame[["LOG_PATIENTS", "IMD_DECILE", "AGE_MONTHS"]].copy()
    numeric = pd.DataFrame(SimpleImputer(strategy="median").fit_transform(numeric), columns=numeric.columns)
    numeric_scaled = StandardScaler().fit_transform(numeric)

    categorical_columns = [column for column in ("COMM_REGION_NAME", "CLINICAL_SYSTEM") if column in frame.columns]
    if categorical_columns:
        encoder = OneHotEncoder(handle_unknown="ignore", sparse_output=False)
        categorical = encoder.fit_transform(frame[categorical_columns].fillna("Unknown"))
        feature_matrix = np.hstack([numeric_scaled, categorical])
    else:
        feature_matrix = numeric_scaled
    return feature_matrix, numeric


def _choose_cluster_count(matrix: np.ndarray, requested: int) -> int:
    sample_count = matrix.shape[0]
    if sample_count < 3:
        return 1

    lower = max(2, requested - 1)
    upper = min(sample_count - 1, requested + 1)
    candidates = list(range(lower, upper + 1)) or [min(max(2, requested), sample_count - 1)]

    best_k = candidates[0]
    best_score = float("-inf")
    for candidate in candidates:
        if candidate >= sample_count:
            continue
        model = KMeans(n_clusters=candidate, random_state=42, n_init=10)
        labels = model.fit_predict(matrix)
        if len(set(labels)) < 2:
            continue
        score = silhouette_score(matrix, labels)
        if score > best_score:
            best_score = score
            best_k = candidate
    return best_k


def umap_embed(df: pd.DataFrame) -> pd.DataFrame:
    """Add two-dimensional embedding columns for practice clusters."""

    frame, _ = _build_feature_frame(df)
    if frame.empty:
        return frame.assign(UMAP_X=pd.Series(dtype=float), UMAP_Y=pd.Series(dtype=float))

    matrix, _ = _feature_matrix(frame)
    if len(frame) < 3:
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


def cluster_practices(df: pd.DataFrame, n_clusters: int = 6) -> pd.DataFrame:
    """Cluster practices using K-Means and attach cluster-level profile summaries."""

    frame, code_column = _build_feature_frame(df)
    if frame.empty:
        return frame.assign(CLUSTER=pd.Series(dtype=int), CLUSTER_LABEL=pd.Series(dtype=int))

    matrix, numeric = _feature_matrix(frame)
    cluster_count = _choose_cluster_count(matrix, n_clusters)
    if cluster_count <= 1:
        frame["CLUSTER"] = 0
    else:
        model = KMeans(n_clusters=cluster_count, random_state=42, n_init=10)
        frame["CLUSTER"] = model.fit_predict(matrix)

    frame["CLUSTER_LABEL"] = frame["CLUSTER"]
    frame = umap_embed(frame)

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