"""
Module: strategy_martin_luke_momentum_swing.py
Source document(s): martin-luke-swing-trading.txt
Description: High-momentum swing trading -- trend-following breakout on high-ADR names, tight
    structural stops, ~23% win rate offset by high reward-to-risk asymmetry. Entry triggers:
    Prior-Day-High (PDH) breakout after a tightening "inside day" sequence, held with a 9-EMA
    trailing stop.

    Interpretive assumptions:
    - "High ADR" (Average Daily Range > 5%) approximated as atr / close > adr_pct_threshold on
      the daily-equivalent bars available.
    - "Inside days" (day's range fully inside previous day's range) approximated as
      high <= high.shift(1) and low >= low.shift(1), counted over a rolling window.
    - "9 EMA trailing stop for longs" -- exit when close crosses back below ema_8 (closest
      available period to the document's literal 9 EMA).
    - Position sizing / 0.5% risk / 5% max stop are position-management concerns, not part of
      the signal-generation function per the interface spec (E26 handles sizing).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_martin_luke_momentum_swing(
    enriched: pd.DataFrame,
    inside_day_window: int = 3,
    adr_pct_threshold: float = 0.02,
    pdh_lookback: int = 1,
) -> pd.Series:
    """High-momentum swing breakout with tightening-range filter (Martin Luke concept).

    See module docstring for full source attribution and interpretive assumptions.
    """
    high, low, close = enriched["high"], enriched["low"], enriched["close"]
    atr, ema_8, ema_21, ema_50 = enriched["atr"], enriched["ema_8"], enriched["ema_21"], enriched["ema_50"]

    high_adr = (atr / close.replace(0, np.nan)) > adr_pct_threshold

    is_inside = (high <= high.shift(1)) & (low >= low.shift(1))
    tightening = is_inside.shift(1).rolling(inside_day_window).sum() >= (inside_day_window - 1)

    prior_high = high.shift(pdh_lookback).rolling(pdh_lookback).max() if pdh_lookback > 1 else high.shift(1)
    trend_up = (ema_8 > ema_21) & (ema_21 > ema_50)
    trend_down = (ema_8 < ema_21) & (ema_21 < ema_50)

    entry_long = (high_adr & tightening & (close > prior_high) & trend_up).fillna(False)
    entry_short = (high_adr & tightening & (close < low.shift(pdh_lookback)) & trend_down).fillna(False)

    # 9-EMA trailing exit (document's core hold-rule for longs; mirrored for shorts).
    exit_long = (close < ema_8).fillna(False)
    exit_short = (close > ema_8).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
