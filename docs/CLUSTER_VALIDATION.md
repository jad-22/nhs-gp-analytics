# Clustering Validation

This document records how the practice clustering (`science/clustering.py`) is
validated, why k-fold cross-validation does not apply, and what the diagnostics found
on real data. The diagnostics are implemented in `science/cluster_validation.py`
(decision record DEC-005).

## 1. Why k-fold cross-validation does not apply

Cross-validation measures predictive error against held-out ground truth. Clustering
is unsupervised — there is no label to be wrong about, so there is nothing to score on
a held-out fold. The unsupervised analogues are:

| Question | Supervised tool | Unsupervised analogue |
|---|---|---|
| Did we fit noise or structure? | k-fold CV | **Bootstrap stability** — re-cluster resampled subsets, measure agreement (Adjusted Rand Index) |
| Is the model any good? | Accuracy / RMSE | **Internal validity** — silhouette, Davies-Bouldin, inertia elbow |
| Redundant predictors? | Multicollinearity / VIF | **Feature correlation** — correlated features double-weight a dimension in the Euclidean distance |
| Confounding? | Confounder adjustment | **Cluster × category association** (Cramér's V) — are the clusters just re-discovering region or clinical system? |

## 2. Diagnostics implemented

All run on the *same feature pipeline* as `cluster_practices`, so they measure what
production actually does:

- `feature_correlations` — Spearman matrix of the numeric features
  (`LOG_PATIENTS`, `IMD_DECILE`, `AGE_MONTHS`). Pairs above ~0.7 |ρ| are redundant.
- `sweep_cluster_counts` — K-Means at every k in 2–12 with silhouette (> 0.5 strong,
  < 0.25 weak), Davies-Bouldin (lower better) and inertia (elbow heuristic). The
  production `_choose_cluster_count` only searches `requested ± 1`, so this sweep is
  the real model-selection check.
- `bootstrap_stability` — re-cluster 80% subsamples from fresh seeds, compare with the
  full-data partition via ARI (1 = identical, 0 = chance). Mean ARI > 0.8 = stable;
  < 0.6 = do not narrate the clusters as meaningful segments.
- `category_crosstab` / `cramers_v` — association between cluster assignment and a
  categorical column (0 = independent, 1 = fully determined).

## 3. Findings on the June 2026 snapshot (6,145 practices)

| Check | Result | Reading |
|---|---|---|
| Size ↔ IMD correlation | Spearman 0.13 | No redundancy problem between the numeric features |
| `AGE_MONTHS` | Constant 0 for every practice | **Dead feature.** It is computed as months since first appearance *within the input frame*; on a single-snapshot input that is always 0 |
| Silhouette across k = 2–12 | Peak 0.225 at k = 2; ~0.20 at production k ≈ 5 | **Weak structure** — the practice population is a continuous cloud, not well-separated groups. No clear inertia elbow |
| Bootstrap stability (k = 5) | Mean ARI 0.99 | **Highly stable** — K-Means reproducibly carves the same slices |
| Cramér's V vs clinical system | **0.66** | Substantial confound: the segmentation largely re-discovers the EMIS/SystmOne split, which is itself a one-hot feature |
| Cramér's V vs region | 0.33 | Moderate — clusters are not simply regions |

**Interpretation.** Stable-but-weak is a coherent combination: the clusters are
reproducible *segments* (useful for dashboard slicing) but not natural *types*. They
should be presented as "similar-practice groups", not as discovered archetypes, and
the clinical-system alignment means "cluster differs by system" is circular — the
system was an input.

## 4. Recommended follow-ups (evidence-based, not yet applied)

1. **Drop `AGE_MONTHS`** from the feature set, or compute it from the full time series
   (first month each practice appears in `list_size`) rather than the input frame.
2. **Reconsider the one-hot categoricals.** Raw 0/1 region/system columns sit
   unscaled next to standardised numerics and drive the clinical-system confound.
   Standard options: cluster on numerics only and use categoricals to *profile*
   clusters afterwards, or switch to K-Prototypes/Gower distance for mixed types.
3. **Surface the silhouette score** from `cluster_practices` so the dashboard can
   qualify the segmentation, and widen `_choose_cluster_count`'s search range.
4. Present clusters on the dashboard as segments, with the caveat above.

## 5. Related

- Implementation: `science/cluster_validation.py`; tests: `tests/test_cluster_validation.py`
- Module under test: `science/clustering.py` (`cluster_practices`)
- Decision record: `docs/DECISION_LOG.md` DEC-005
- Companion methodology for forecasting: `docs/FORECAST_VALIDATION.md` (DEC-004)
