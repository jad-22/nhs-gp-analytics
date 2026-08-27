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
from .clustering import cluster_practices, cluster_practices_by_k, umap_embed
from .deprivation import flag_underserved, regional_inequality, size_imd_correlation
from .forecasting import forecast_list_size
from .stat_forecasting import (
	arima_forecast,
	autoets_forecast,
	holt_winters_forecast,
	sarima_forecast,
	statistical_forecasters,
)

__all__ = [
	"apply_interval_calibration",
	"arima_forecast",
	"autoets_forecast",
	"bootstrap_stability",
	"calibrate_intervals",
	"category_crosstab",
	"cluster_practices",
	"cluster_practices_by_k",
	"compare_models",
	"cramers_v",
	"feature_correlations",
	"flag_anomalies",
	"flag_underserved",
	"forecast_list_size",
	"holt_winters_forecast",
	"regional_inequality",
	"rolling_origin_backtest",
	"sarima_forecast",
	"score_backtest",
	"score_by_horizon",
	"size_imd_correlation",
	"statistical_forecasters",
	"sweep_cluster_counts",
	"umap_embed",
]