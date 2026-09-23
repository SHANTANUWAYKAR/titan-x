"""
Module: strategy_measured_move_trendline_projection.py
Source document(s): Marci.txt (Marci Silfrain's "Measured Move Trend Strategy" -- full detailed
    playbook), Measured move trend strategy.txt (a simplified rewrite of the SAME core idea,
    explicitly subtitled "Inspired by Marci Silfrain")
Description: Consolidates two documents describing the identical core rule per the interface
    spec's near-duplicate rule. Core idea ("Little RZY" structure): in a trend, price makes an
    impulse move, then a pullback that can be bounded by a short trendline (approximated here as
    a rolling linear-regression trendline over the pullback window); the vertical distance from
    the pullback's extreme point to that trendline is measured, then projected the same distance
    in the trend direction once price resumes. Bollinger Bands provide an "exhaustion" context
    filter (Marci.txt explicitly ties BB extremes to trend exhaustion).

    Interpretive assumptions:
    - "Trendline across the pullback highs/lows" approximated as a rolling OLS trendline fit
      over the last `pullback_window` bars of the counter-trend swing.
    - "Trend" determined by ema_50 vs ema_200 (bullish: ema_50 > ema_200, bearish: reverse).
    - Entry = price resuming in the trend direction (closing back beyond the trendline value)
      after the pullback, filtered to NOT be in BB-extreme exhaustion territory (per Marci's own
      point 9: later/exhausted structures near extreme bands are lower-probability).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def _rolling_trendline_value(series: pd.Series, window: int) -> pd.Series:
    """Fit a simple OLS line over the trailing `window` bars (ending at t-1, never including the
    current bar) and return the line's PROJECTED value at the current bar -- causal by
    construction since every fit uses only already-closed bars."""
    x = np.arange(window)
    x_mean = x.mean()
    denom = ((x - x_mean) ** 2).sum()

    def _fit_and_project(vals: np.ndarray) -> float:
        y_mean = vals.mean()
        slope = ((x - x_mean) * (vals - y_mean)).sum() / denom
        intercept = y_mean - slope * x_mean
        # Project one step beyond the fitted window (position `window`, i.e. "now")
        return intercept + slope * window

    return series.shift(1).rolling(window).apply(_fit_and_project, raw=True)


def strategy_measured_move_trendline_projection(
    enriched: pd.DataFrame,
    pullback_window: int = 10,
    bb_exhaustion_mult: float = 0.98,
) -> pd.Series:
    """Measured-Move / "Little RZY" trend-continuation strategy (Marci Silfrain concept).

    See module docstring for full source attribution and interpretive assumptions.
    """
    close, high, low = enriched["close"], enriched["high"], enriched["low"]
    ema_50, ema_200 = enriched["ema_50"], enriched["ema_200"]
    bb_upper, bb_lower = enriched["bb_upper"], enriched["bb_lower"]

    uptrend = ema_50 > ema_200
    downtrend = ema_50 < ema_200

    trend_low_line = _rolling_trendline_value(low, pullback_window)
    trend_high_line = _rolling_trendline_value(high, pullback_window)

    # Exhaustion filter: skip new entries when price already sits in the outer BB extremes
    # (Marci's own point 9 -- later structures near extreme bands are lower-probability).
    not_exhausted_long = close < bb_upper * bb_exhaustion_mult
    not_exhausted_short = close > bb_lower * (2 - bb_exhaustion_mult)

    # Entry: trend resumes -- price closes back above/below the pullback trendline projection.
    entry_long = (uptrend & (close > trend_high_line) & (close.shift(1) <= trend_high_line.shift(1)) & not_exhausted_long).fillna(False)
    entry_short = (downtrend & (close < trend_low_line) & (close.shift(1) >= trend_low_line.shift(1)) & not_exhausted_short).fillna(False)

    # Exit: trend context itself flips, or price breaks back through the pullback trendline
    # in the adverse direction (Marci's own "invalid conditions" rule: close beyond the line).
    exit_long = (downtrend | (close < trend_low_line)).fillna(False)
    exit_short = (uptrend | (close > trend_high_line)).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
