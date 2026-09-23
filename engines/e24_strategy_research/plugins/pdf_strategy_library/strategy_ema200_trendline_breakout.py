"""
Module: strategy_ema200_trendline_breakout.py
Source document(s): EMA + Trendline Breakout Trading Strategy.txt
Description: Use the 200 EMA as a regime filter (longs only above it, shorts only below it),
the 9/20 EMA pair to confirm short-term momentum, and a trendline break to trigger entry. Since
a manually-drawn trendline cannot be reconstructed from OHLCV alone, it is approximated with a
rolling linear-regression projection of price fitted on strictly prior closes -- a break is a
close crossing that projected line, which plays the same structural role ("price breaks a line
built from at least two recent touches") as a manually drawn trendline.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def _rolling_trendline_projection(series: pd.Series, window: int) -> pd.Series:
    """Project a linear trendline fitted on the PRIOR `window` values one step ahead.

    At bar i this uses only series[i-window .. i-1] (via shift(1) applied before the rolling
    window is formed), then extrapolates the fit to bar i's position -- series[i] itself is
    never part of the fit.
    """
    shifted = series.shift(1)
    x = np.arange(window, dtype=float)

    def _fit(y: np.ndarray) -> float:
        if np.any(np.isnan(y)):
            return np.nan
        slope, intercept = np.polyfit(x, y, 1)
        return slope * window + intercept

    return shifted.rolling(window).apply(_fit, raw=True)


def strategy_ema200_trendline_breakout(
    enriched: pd.DataFrame,
    trendline_window: int = 20,
) -> pd.Series:
    """200-EMA regime filter + rolling-trendline breakout continuation entry.

    Source document: "EMA + Trendline Breakout Trading Strategy.txt". Rule: only trade with
    the 200 EMA (buy above it, sell below it), use 9/20 EMA to confirm the short-term trend is
    intact, and enter when a trendline (>=2-touch, confirmed by candle close) breaks in the
    trend's favor, with a minimum 1:2 R:R.

    Interpretive assumptions:
    - "9 EMA" approximated with `ema_8` (closest available period).
    - The manually-drawn trendline is approximated with a rolling linear-regression projection
      (see `_rolling_trendline_projection`) fitted on the prior `trendline_window` closes; a
      "breakout confirmed by candle close" = the close crossing from one side of that
      projection to the other.
    """
    close, ema_fast, ema_slow, ema_200 = enriched["close"], enriched["ema_8"], enriched["ema_21"], enriched["ema_200"]

    projection = _rolling_trendline_projection(close, trendline_window)

    cross_up = ((close > projection) & (close.shift(1) <= projection.shift(1))).fillna(False)
    cross_down = ((close < projection) & (close.shift(1) >= projection.shift(1))).fillna(False)

    regime_bull = close > ema_200
    regime_bear = close < ema_200

    entry_long = (regime_bull & cross_up & (ema_fast > ema_slow)).fillna(False)
    entry_short = (regime_bear & cross_down & (ema_fast < ema_slow)).fillna(False)

    exit_long = ((close < ema_200) | (close < enriched["ema_50"])).fillna(False)
    exit_short = ((close > ema_200) | (close > enriched["ema_50"])).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
