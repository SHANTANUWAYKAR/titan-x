"""
Module: tearsheet.py
Description: quantstats-based HTML tear sheet generator for a real
    BacktestResult's equity curve -- REPO_REFERENCE.md Tier 1 ("full tear
    sheet in one call -- Sortino, Calmar, CVaR, drawdowns, rolling
    metrics").

    E26's own BacktestMetrics ALREADY computes Sharpe/Sortino/Calmar/CAGR/
    drawdown natively, with this platform's own fixed-fractional sizing and
    commission conventions -- this module does NOT duplicate that (Rule 4:
    don't compute the same expensive thing twice). It uses quantstats for
    the one thing this platform has never had: a real, shareable VISUAL
    report (equity curve, drawdown chart, monthly-returns heatmap, rolling
    Sharpe/volatility, return distribution) rendered from a real backtest's
    own equity curve.

    quantstats recomputes every number in its report independently from the
    return series alone, using its OWN conventions (geometric compounding,
    its own risk-free-rate handling) -- these numbers WILL differ somewhat
    from BacktestMetrics' own bespoke figures, even though both start from
    the same underlying equity curve. This is a supplementary artifact,
    read by nothing else in this codebase -- same "informational only,
    never a decision input" discipline as knowledge_context elsewhere in
    this project. Never feed tear-sheet output back into any validation or
    promotion decision.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from .engine import BacktestResult


def equity_curve_to_returns(result: BacktestResult, df: pd.DataFrame) -> pd.Series:
    """Real per-bar returns from a BacktestResult's own equity curve,
    indexed by the source data's real timestamps.

    `result.equity_curve` is positionally aligned with `df` one entry per
    bar (see `BacktestingEngine._simulate`'s own construction) -- never
    re-derived or resampled here, just given a real DatetimeIndex so
    quantstats' calendar-based views (monthly heatmap, rolling windows)
    describe real calendar time rather than a bar-count axis.
    """
    n = len(result.equity_curve)
    if n < 2:
        raise ValueError(f"equity curve has {n} point(s); need at least 2 to form returns")
    if "timestamp" in df.columns:
        ts = pd.DatetimeIndex(df["timestamp"].iloc[:n])
    elif isinstance(df.index, pd.DatetimeIndex):
        ts = df.index[:n]
    else:
        raise ValueError("df has no 'timestamp' column and no DatetimeIndex -- "
                          "quantstats needs real calendar time, not a positional index")
    if len(ts) != n:
        raise ValueError(f"timestamp series has {len(ts)} rows but the equity curve has "
                          f"{n} -- pass the SAME df that run_backtest was called with")
    equity = pd.Series(result.equity_curve.to_numpy(dtype=float), index=pd.DatetimeIndex(ts))
    if equity.index.tz is not None:
        equity.index = equity.index.tz_localize(None)   # quantstats assumes tz-naive
    returns = equity.pct_change().fillna(0.0)
    returns.name = "returns"
    return returns


def generate_tearsheet(
    result: BacktestResult,
    df: pd.DataFrame,
    output_path: str | Path,
    title: str = "Strategy Tear Sheet",
    periods_per_year: int = 252,
) -> Path:
    """Render a real quantstats HTML tear sheet from a real BacktestResult.

    Raises on a flat equity curve (no real trades to report on) rather
    than emitting a report built from an undefined/zero-variance Sharpe --
    an honest failure, not a placeholder artifact.
    """
    import quantstats as qs

    returns = equity_curve_to_returns(result, df)
    if float(returns.std()) == 0.0:
        raise ValueError("equity curve never moved -- no real trades to report on")

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    qs.reports.html(
        returns,
        title=title,
        output=str(out),
        periods_per_year=periods_per_year,
        download_filename=str(out),
    )
    return out
