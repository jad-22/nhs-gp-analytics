"""Data science module scaffold for the NHS GP Analytics project."""

from .anomaly import flag_anomalies
from .backtesting import compare_models, rolling_origin_backtest, score_backtest, score_by_horizon
from .clustering import cluster_practices, umap_embed
from .deprivation import flag_underserved, regional_inequality, size_imd_correlation
from .forecasting import forecast_list_size

__all__ = [
	"cluster_practices",
	"compare_models",
	"flag_anomalies",
	"flag_underserved",
	"forecast_list_size",
	"regional_inequality",
	"rolling_origin_backtest",
	"score_backtest",
	"score_by_horizon",
	"size_imd_correlation",
	"umap_embed",
]