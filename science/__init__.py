"""Data science module scaffold for the NHS GP Analytics project."""

from .anomaly import flag_anomalies
from .backtesting import (
	apply_interval_calibration,
	calibrate_intervals,
	compare_models,
	rolling_origin_backtest,
	score_backtest,
	score_by_horizon,
)
from .cluster_validation import (
	bootstrap_stability,
	category_crosstab,
	cramers_v,
	feature_correlations,
	sweep_cluster_counts,
)
from .clustering import cluster_practices, umap_embed
from .deprivation import flag_underserved, regional_inequality, size_imd_correlation
from .forecasting import forecast_list_size

__all__ = [
	"apply_interval_calibration",
	"bootstrap_stability",
	"calibrate_intervals",
	"category_crosstab",
	"cluster_practices",
	"compare_models",
	"cramers_v",
	"feature_correlations",
	"flag_anomalies",
	"flag_underserved",
	"forecast_list_size",
	"regional_inequality",
	"rolling_origin_backtest",
	"score_backtest",
	"score_by_horizon",
	"size_imd_correlation",
	"sweep_cluster_counts",
	"umap_embed",
]