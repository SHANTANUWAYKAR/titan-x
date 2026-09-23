"""
Module: strategy_trendline_based_4h_breakout.py
Source document(s): TRENDLINE BASED STRATEGY.txt
Description: Simple 4H trendline-break strategy -- draw a trendline across swing highs/lows,
    enter when a strong candle closes beyond it, exit when a NEW trendline (drawn on the move
    that follows) itself breaks. Simpler/more generic than the Tori Trades trendline pair
    (which has the more elaborate Action-Line/Safety-Line mechanic) -- kept separate per the
    interface spec since this document's rule genuinely lacks that extra structure.

    Interpretive assumptions:
    - Trendline approximated as a rolling OLS fit over `trendline_window` bars of swing
      highs (downtrend line) or swing lows (uptrend line), projected forward one bar (same
      causal technique as strategy_measured_move_trendline_projection.py).
    - "New trendline breaks" (exit) = a fresh trendline fit AFTER entry breaks in the adverse
      direction -- approximated here as a fresh rolling trendline (recomputed each bar) turning
      against the position.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def _rolling_trendline_value(series: pd.Series, window: int) -> pd.Series:
    x = np.arange(window)
    x_mean = x.mean()
    denom = ((x - x_mean) ** 2).sum()

    def _fit_and_project(vals: np.ndarray) -> float:
        y_mean = vals.mean()
        slope = ((x - x_mean) * (vals - y_mean)).sum() / denom
        intercept = y_mean - slope * x_mean
        return intercept + slope * window

    return series.shift(1).rolling(window).apply(_fit_and_project, raw=True)


def strategy_trendline_based_4h_breakout(
    enriched: pd.DataFrame,
    trendline_window: int = 20,
) -> pd.Series:
    """Simple trendline break + trail-until-new-trendline-breaks (generic concept, 4H-framed).

    See module docstring for full source attribution and interpretive assumptions.
    """
    high, low, close = enriched["high"], enriched["low"], enriched["close"]

    resistance_line = _rolling_trendline_value(high, trendline_window)
    support_line = _rolling_trendline_value(low, trendline_window)

    entry_long = (close > resistance_line) & (close.shift(1) <= resistance_line.shift(1))
    entry_short = (close < support_line) & (close.shift(1) >= support_line.shift(1))

    # Exit: the NEW trendline (formed on the move since entry) breaks against the position --
    # approximated as the currently-active rolling trendline crossing back through price.
    exit_long = (close < support_line).fillna(False)
    exit_short = (close > resistance_line).fillna(False)

    return _stateful_from_entries_exits(entry_long.fillna(False), exit_long, entry_short.fillna(False), exit_short)
