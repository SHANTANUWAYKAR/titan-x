"""
Module: strategy_gautam_jha_pdh_pdl_breakout_reversal.py
Source document(s): GAUTAM JHA STRATEGY.txt
Description: "Pro Trader's Simple Intraday Trading Strategy - Day 12". Wait for price to
CLOSE fully beyond the previous day's low (a genuine break, not just a touch -- this is what
distinguishes it from BOX TRADING STRATEGY.txt's touch-and-bounce rule elsewhere in this
batch), then wait for a green candle to print after that break, then buy when the next candle
breaks that green candle's high. Mirrored at the previous day's high for sells.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_gautam_jha_pdh_pdl_breakout_reversal(
    enriched: pd.DataFrame,
    break_lookback: int = 15,
) -> pd.Series:
    """Previous-day-low breakdown -> green reversal candle -> break of its high (and mirror).

    Source document: "GAUTAM JHA STRATEGY.txt". Buy rule: mark PDH/PDL, wait for price to
    COMPLETELY BREAK the previous day's low (a close beyond it, not merely a touch), then wait
    for a bullish candle to print, then buy when the next candle breaks that bullish candle's
    high. Stop loss = that candle's low; target = the swing high the down-move started from
    (left to the platform's R:R engine, per the interface spec, since it is not a fixed
    structural level like PDH/PDL). Sell rule is the exact mirror at the previous day's high.

    Interpretive assumptions:
    - "Previous day" = the previous UTC calendar date present in the data, computed the same
      causal way as BOX TRADING STRATEGY.txt in this batch (groupby day, shift(1)), so a
      day's PDH/PDL are entirely fixed before that day's own bars begin.
    - "Completely break" = a bar CLOSES beyond PDL/PDH (stricter than a mere high/low touch).
    - The break is considered "active" for a bounded `break_lookback` window (not held
      indefinitely) while waiting for the green/red confirmation candle.
    - Exit uses a reclaim of the broken level as invalidation of the setup (a document-implied
      structural stop, distinct from R:R sizing).
    """
    open_, high, low, close = enriched["open"], enriched["high"], enriched["low"], enriched["close"]

    day = enriched["timestamp"].dt.date
    daily = pd.DataFrame({"high": high, "low": low}).groupby(day).agg(d_high=("high", "max"), d_low=("low", "min"))
    daily_prev = daily.shift(1)
    pdh = day.map(daily_prev["d_high"])
    pdl = day.map(daily_prev["d_low"])

    broke_below = (close < pdl).fillna(False)
    broke_above = (close > pdh).fillna(False)

    broke_below_recent = broke_below.shift(1).rolling(break_lookback, min_periods=1).max().fillna(0).astype(bool)
    broke_above_recent = broke_above.shift(1).rolling(break_lookback, min_periods=1).max().fillna(0).astype(bool)

    green_after_break = broke_below_recent & (close > open_)
    red_after_break = broke_above_recent & (close < open_)

    entry_long = (green_after_break.shift(1).fillna(False) & (close > high.shift(1))).fillna(False)
    entry_short = (red_after_break.shift(1).fillna(False) & (close < low.shift(1))).fillna(False)

    exit_long = (close < pdl).fillna(False)
    exit_short = (close > pdh).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
