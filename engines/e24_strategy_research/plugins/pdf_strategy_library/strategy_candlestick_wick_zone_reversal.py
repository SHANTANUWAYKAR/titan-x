"""
Module: strategy_candlestick_wick_zone_reversal.py
Source document(s): CANDLESTICK WICK STRATEGY.txt
Description: During consolidation, find the candle with the most aggressive rejection wick,
mark its extreme as a reaction zone, and wait for price to revisit that zone and print a
confirmation candle before trading the reversal. "Consolidation" is approximated with ADX <= 25
(standard ranging threshold); "strongest wick" is approximated as any wick that is at least 50%
of that candle's total range, with the zone level held as the most recent such wick's price
extreme (a rolling max/min over qualifying candles only).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_candlestick_wick_zone_reversal(
    enriched: pd.DataFrame,
    consolidation_adx_threshold: float = 25.0,
    wick_ratio_threshold: float = 0.5,
    zone_lookback: int = 30,
) -> pd.Series:
    """Long-wick rejection-zone retest reversal during consolidation.

    Source document: "CANDLESTICK WICK STRATEGY.txt". Rule: find sideways consolidation, mark
    the strongest rejection wick inside it as a reaction zone, wait for price to revisit that
    zone, and enter on a confirmation candle closing away from the zone with a >=1:2 R:R.

    Interpretive assumptions (the document defines none of these numerically):
    - "Consolidation" = ADX <= 25 (standard ranging threshold).
    - "Strongest wick" = a candle whose upper (or lower) wick is >= `wick_ratio_threshold`
      (default 50%) of its own high-low range; the zone level is the rolling max (for upper
      wicks) / min (for lower wicks) of the HIGH/LOW of only those qualifying candles over the
      trailing `zone_lookback` bars, all strictly before the current bar.
    - "Confirmation candle" = a candle that touches the zone and closes back on the far side
      of it in the reversal direction.
    """
    high, low, close, open_ = enriched["high"], enriched["low"], enriched["close"], enriched["open"]
    adx = enriched["adx"]

    rng = (high - low).replace(0, np.nan)
    upper_wick_ratio = (high - np.maximum(open_, close)) / rng
    lower_wick_ratio = (np.minimum(open_, close) - low) / rng

    strong_upper = upper_wick_ratio >= wick_ratio_threshold
    strong_lower = lower_wick_ratio >= wick_ratio_threshold

    zone_resistance = high.where(strong_upper).shift(1).rolling(zone_lookback, min_periods=1).max()
    zone_support = low.where(strong_lower).shift(1).rolling(zone_lookback, min_periods=1).min()

    consolidating = (adx <= consolidation_adx_threshold).fillna(False)

    entry_short = (consolidating & (high >= zone_resistance) & (close < open_) & (close < zone_resistance)).fillna(False)
    entry_long = (consolidating & (low <= zone_support) & (close > open_) & (close > zone_support)).fillna(False)

    exit_long = (close < zone_support).fillna(False)
    exit_short = (close > zone_resistance).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
