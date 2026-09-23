"""
Module: strategy_mambafx_1m_sr_breakout.py
Source document(s): BEST SCALPING STRATEGY MAMBAFX.txt
Description: "1 Minute Scalping Strategy (Mamba FX)" -- identify a strong, multiply-tested
support/resistance level on a higher timeframe, then take a breakout entry on the lower
timeframe once price closes beyond that level. Implemented on a single timeframe series (the
platform passes one `timeframe` per call) using a longer rolling lookback to stand in for the
"higher timeframe" level and a level-stability check to stand in for "tested multiple times".
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_mambafx_1m_sr_breakout(
    enriched: pd.DataFrame,
    sr_lookback: int = 60,
    stability_bars: int = 10,
    stability_tol_atr: float = 0.5,
) -> pd.Series:
    """Breakout of a stable (multiply-tested) rolling support/resistance level.

    Source document: "BEST SCALPING STRATEGY MAMBAFX.txt". Rule: on a higher timeframe, find a
    strong support/resistance level (one price has reacted from multiple times), switch to a
    lower timeframe, and buy/sell when price breaks and closes beyond that level.

    Interpretive assumptions (document assumes two chart timeframes; this function only
    receives one):
    - The "higher timeframe strong level" is approximated as the rolling max/min of high/low
      over `sr_lookback` bars (using only bars strictly before the current one).
    - "Strong / tested multiple times" is approximated by requiring that rolling extreme has
      not advanced in the last `stability_bars` bars (within `stability_tol_atr` x ATR) --
      i.e. price has been repeatedly capped/floored at roughly the same level rather than
      trending straight through it.
    - The breakout trigger itself is a plain close beyond the level, matching the document's
      "enter when price breaks the previous high and closes above it".
    """
    high, low, close, atr = enriched["high"], enriched["low"], enriched["close"], enriched["atr"]

    prior_high = high.shift(1).rolling(sr_lookback).max()
    prior_high_earlier = high.shift(1 + stability_bars).rolling(sr_lookback).max()
    high_stable = ((prior_high - prior_high_earlier).abs() <= stability_tol_atr * atr).fillna(False)

    prior_low = low.shift(1).rolling(sr_lookback).min()
    prior_low_earlier = low.shift(1 + stability_bars).rolling(sr_lookback).min()
    low_stable = ((prior_low - prior_low_earlier).abs() <= stability_tol_atr * atr).fillna(False)

    entry_long = ((close > prior_high) & high_stable).fillna(False)
    entry_short = ((close < prior_low) & low_stable).fillna(False)

    ema_fast = enriched["ema_8"]
    exit_long = ((close < prior_high) | (close < ema_fast)).fillna(False)
    exit_short = ((close > prior_low) | (close > ema_fast)).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
