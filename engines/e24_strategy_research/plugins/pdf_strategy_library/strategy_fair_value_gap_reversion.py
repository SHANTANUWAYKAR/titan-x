"""
Module: strategy_fair_value_gap_reversion.py
Source document(s): FARE VALUE GAP.txt
Description: Classic ICT-style 3-candle Fair Value Gap (FVG): a bullish FVG is the gap between
candle-1's high and candle-3's low when price is running up (mirrored for bearish); wait for
price to return into the gap and print a rejection candle before entering in the direction the
gap implies (continuation of the original imbalance direction). No fabricated indicator needed
-- FVG is directly computable from open/high/low/close.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_fair_value_gap_reversion(enriched: pd.DataFrame) -> pd.Series:
    """3-candle Fair Value Gap: wait for the gap to be revisited, enter on rejection.

    Source document: "FARE VALUE GAP.txt" (Fair Value Gap / SMC concept, Hindi-English mixed
    text). Rule: a bullish FVG forms when candle-1's high is below candle-3's low (a 3-candle
    imbalance); mark that gap as a zone; when price later returns into the zone and shows a
    rejection/confirmation candle, enter in the original (gap) direction. Bearish FVG mirrors
    this with candle-1's low above candle-3's high.

    Interpretive assumptions:
    - "Liquidity sweep or rejection confirmation" approximated as a bullish (bearish) candle
      (close > open / close < open) on the FIRST bar that touches the still-open gap zone.
    - The most recent unfilled gap's boundaries are carried forward with a forward-fill (using
      only past/current values, never future ones -- ffill is causal by construction) until a
      new gap of the same side forms.
    """
    open_, high, low, close = enriched["open"], enriched["high"], enriched["low"], enriched["close"]

    bullish_fvg = low > high.shift(2)
    bearish_fvg = high < low.shift(2)

    bull_top = low.where(bullish_fvg).ffill()
    bull_bottom = high.shift(2).where(bullish_fvg).ffill()
    bear_bottom = high.where(bearish_fvg).ffill()
    bear_top = low.shift(2).where(bearish_fvg).ffill()

    touch_bull = (low <= bull_top) & (close >= bull_bottom)
    touch_bear = (high >= bear_bottom) & (close <= bear_top)

    first_touch_bull = (touch_bull & ~(low.shift(1) <= bull_top.shift(1)).fillna(False)).fillna(False)
    first_touch_bear = (touch_bear & ~(high.shift(1) >= bear_bottom.shift(1)).fillna(False)).fillna(False)

    entry_long = (first_touch_bull & (close > open_)).fillna(False)
    entry_short = (first_touch_bear & (close < open_)).fillna(False)

    exit_long = (close < bull_bottom).fillna(False)
    exit_short = (close > bear_top).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
