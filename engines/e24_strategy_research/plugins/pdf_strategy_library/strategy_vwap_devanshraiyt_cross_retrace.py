"""
Module: strategy_vwap_devanshraiyt_cross_retrace.py
Source document(s): VWAP STRATEGY OF DEVANSHRAIYT.txt
Description: Simple VWAP cross-and-retrace intraday strategy -- DIFFERENT from
    strategy_anish_singh_vwap_stochrsi_pivot.py (that one adds stochastic + daily-pivot
    confirmation; this document has neither, it's pure VWAP-only) -- confirmed distinct,
    implemented separately. Wait for price to cross the VWAP line, then retrace back to VWAP,
    then enter on a strong confirmation candle at the retest.

    Interpretive assumptions:
    - "Strong bullish/bearish candle forming near VWAP" = a candle closing on the trend side of
      VWAP with body_ratio >= body_ratio_threshold, after having touched within
      `retest_atr_mult` ATR of VWAP.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_vwap_devanshraiyt_cross_retrace(
    enriched: pd.DataFrame,
    retest_atr_mult: float = 0.3,
    body_ratio_threshold: float = 0.5,
    cross_lookback: int = 10,
) -> pd.Series:
    """VWAP cross + retrace + confirmation-candle entry (Devanshraiyt VWAP concept).

    See module docstring for full source attribution and interpretive assumptions.
    """
    high, low, close, open_ = enriched["high"], enriched["low"], enriched["close"], enriched["open"]
    vwap, atr = enriched["vwap"], enriched["atr"]

    cross_up = (close > vwap) & (close.shift(1) <= vwap.shift(1))
    cross_down = (close < vwap) & (close.shift(1) >= vwap.shift(1))
    cross_up_recent = cross_up.shift(1).rolling(cross_lookback, min_periods=1).max().fillna(0).astype(bool)
    cross_down_recent = cross_down.shift(1).rolling(cross_lookback, min_periods=1).max().fillna(0).astype(bool)

    near_vwap = (close - vwap).abs() <= (atr * retest_atr_mult)

    body = (close - open_).abs()
    rng = (high - low).replace(0, np.nan)
    strong_bull_candle = ((body / rng) >= body_ratio_threshold) & (close > open_) & (close > vwap)
    strong_bear_candle = ((body / rng) >= body_ratio_threshold) & (close < open_) & (close < vwap)

    entry_long = (cross_up_recent & near_vwap.shift(1).fillna(False) & strong_bull_candle).fillna(False)
    entry_short = (cross_down_recent & near_vwap.shift(1).fillna(False) & strong_bear_candle).fillna(False)

    exit_long = (close < vwap).fillna(False)
    exit_short = (close > vwap).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
