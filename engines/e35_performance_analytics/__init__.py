"""Engine 35 -- Performance Analytics."""

from project_titan_x.engines.e35_performance_analytics.engine import (
    PerformanceAnalyticsEngine,
    PerformanceSummary,
    average_win_loss_r,
    equity_curve_from_pnl_pct,
    expectancy_r,
    max_drawdown_pct,
    profit_factor,
    summarize,
    win_rate,
)

__all__ = [
    "PerformanceAnalyticsEngine",
    "PerformanceSummary",
    "average_win_loss_r",
    "equity_curve_from_pnl_pct",
    "expectancy_r",
    "max_drawdown_pct",
    "profit_factor",
    "summarize",
    "win_rate",
]
