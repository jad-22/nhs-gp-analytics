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
| Cluster × system cross-tab | **4 of 5 clusters are 100% pure by system** (two all-EMIS, two all-SystmOne; cluster 4 mixes 69/31) | K-Means partitions by system *first*, then subdivides within each system; the silhouette peak at k = 2 is the EMIS/SystmOne split itself |
| Cramér's V vs region | 0.33 | Moderate — clusters are not simply regions |

**Interpretation.** Stable-but-weak is a coherent combination: the clusters are
reproducible *segments* (useful for dashboard slicing) but not natural *types*. They
should be presented as "similar-practice groups", not as discovered archetypes, and
the clinical-system alignment means "cluster differs by system" is circular — the
system was an input. The purity of the cross-tab shows the one-hot columns are not
merely *influencing* the partition, they are its top-level split.

## 4. Fixes applied (DEC-006)

1. **Constant features dropped automatically** — `AGE_MONTHS` no longer pollutes the
   matrix on single-snapshot input (computing it from the full time series remains a
   possible enhancement).
2. **Categoricals removed from the distance.** The feature matrix is numerics-only;
   region and clinical system are reported as cluster profiles (dominant values).
3. **Silhouette surfaced** as a SILHOUETTE_SCORE output column, and the k search
   widened to 2..requested+2 (with `auto_k=False` to pin an exact count).

## 5. Post-fix results (June 2026 snapshot)

| Check | Before (§3) | After DEC-006 |
|---|---|---|
| Silhouette at best k | 0.225 (k = 2) | **0.398** (k = 2); 0.32–0.35 across k = 3–12 |
| Davies-Bouldin range | 1.42–1.70 | 0.79–1.01 |
| Cramér's V vs clinical system | 0.66 (4 of 5 clusters 100% pure) | **0.02** — confound eliminated |
| Cramér's V vs region | 0.33 | 0.27 (legitimate geography/deprivation association, no longer circular) |
| Bootstrap ARI | 0.985 | 0.989 |
| Production cluster count (`auto_k`) | 5 | **2** — the data's preferred split |

The structure is still moderate rather than strong (silhouette < 0.5), so the
"segments, not archetypes" presentation guidance stands. Note the `auto_k` default
now yields two segments in the dashboard cluster explorer after a cache rebuild —
pass `auto_k=False` in `scripts/build_dashboard_cache.py` if six fixed segments are
preferred for slicing.

## 6. Related

- Implementation: `science/cluster_validation.py`; tests: `tests/test_cluster_validation.py`
- Module under test: `science/clustering.py` (`cluster_practices`)
- Decision record: `docs/DECISION_LOG.md` DEC-005
- Companion methodology for forecasting: `docs/FORECAST_VALIDATION.md` (DEC-004)
