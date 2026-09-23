"""
Module: strategy_inna_rosputnia_sma_trend.py
Source document(s): Inna Rosputnia STRATEGY.txt
Description: "Inna Rosputnia Trading Strategy (Extracted from Script)" -- Trend Following Swing
Trading Strategy on the Daily chart. Enter long after two consecutive daily closes above an 18
SMA, triggered by a break of the second candle's high, filtered by price being above a 200 SMA
and entry-day volume exceeding its trailing 20-day average. Exit when price closes back below
the 18 SMA.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_inna_rosputnia_sma_trend(
    enriched: pd.DataFrame,
    volume_lookback: int = 20,
) -> pd.Series:
    """18-SMA trend-following: two closes above the MA, breakout of the 2nd candle's high.

    Source document: "Inna Rosputnia STRATEGY.txt". Rule: apply an 18-period SMA on the daily
    chart; wait for two consecutive daily candles to CLOSE above it; enter long when price
    breaks above the high of that second candle. Stop loss below the previous swing low
    (external, per interface spec -- not implemented here). Exit when price closes back below
    the 18 SMA. Filters: entry-day volume above its trailing 20-day average, and price above
    the 200 SMA.

    Interpretive assumptions:
    - No raw SMA column exists on `enriched` (only ema_8/21/50/200). The 18-period SMA is
      approximated with `ema_21`, the closest available period, and the 200-period SMA with
      `ema_200` (exact period match, EMA instead of SMA type) -- both documented approximations
      per the interface spec's guidance to use the closest available column and say so.
    - "Two consecutive closes above the MA" is checked on the two bars STRICTLY BEFORE the
      current bar (`shift(1)`, `shift(2)`), and the "break of the second candle's high" check
      uses the current bar's own high vs. the immediately preceding bar's high -- both are
      causal (no data from after the current bar is used for either check).
    - "Previous 20-day average volume" excludes the entry day itself
      (`volume.shift(1).rolling(volume_lookback).mean()`).
    - Long-only, matching the source document (no short setup is described anywhere in it).
    """
    close = enriched["close"]
    high = enriched["high"]
    volume = enriched["volume"]
    ma_fast = enriched["ema_21"]     # approximates the document's 18 SMA
    ma_slow = enriched["ema_200"]    # approximates the document's 200 SMA

    two_closes_above = (close.shift(1) > ma_fast.shift(1)) & (close.shift(2) > ma_fast.shift(2))
    breakout = high > high.shift(1)
    above_200 = close > ma_slow
    vol_avg_prev = volume.shift(1).rolling(volume_lookback).mean()
    vol_ok = volume > vol_avg_prev

    entry_long = (two_closes_above & breakout & above_200 & vol_ok).fillna(False)
    exit_long = (close < ma_fast).fillna(False)

    idx = enriched.index
    entry_short = pd.Series(False, index=idx)
    exit_short = pd.Series(False, index=idx)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
