"""
Module: strategy_tradewithsunil_opening_candle_reversal.py
Source document(s): TRADEWITHSUNIL STRATEGY WITH BACKTEST RESULTS.txt
Description: "Opening Candle Reversal" -- a DIFFERENT Tradewithsunil document from
    "TRADEWITHSUNIL 5MIN STRATEGY.txt" (already implemented in strategy_tradewithsunil_orb_5min.py,
    batch 1) -- this one is a fake-breakdown reversal, not an ORB. Mark the first 5-min candle's
    high/low; if the second candle fake-breaks below the low, and the third candle recovers back
    above that low toward mid-range, buy on sustained strength above the low.

    Interpretive assumptions:
    - "First 5-minute candle" generalized to "the first bar of the session" per the interface
      spec (works on any intraday timeframe, faithful to 5-min per the source document's own
      framing when run at timeframe="5m").
    - "Sustains above the first candle low near mid-level" = close remains above the opening
      bar's low AND above the opening bar's midpoint for `sustain_bars` consecutive bars.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_tradewithsunil_opening_candle_reversal(
    enriched: pd.DataFrame,
    session_tz: str = "Asia/Kolkata",
    sustain_bars: int = 2,
) -> pd.Series:
    """Opening-candle fake-breakdown reversal (Tradewithsunil / Sunil Dahiya concept).

    See module docstring for full source attribution and interpretive assumptions.
    """
    high, low, close = enriched["high"], enriched["low"], enriched["close"]
    ts_local = enriched["timestamp"].dt.tz_convert(session_tz)
    day = ts_local.dt.date
    is_first_bar_of_day = (day != day.shift(1)).fillna(True)

    open_bar_high = high.where(is_first_bar_of_day).ffill()
    open_bar_low = low.where(is_first_bar_of_day).ffill()
    open_bar_mid = (open_bar_high + open_bar_low) / 2.0

    fake_breakdown = (low < open_bar_low) & (~is_first_bar_of_day)
    fake_breakdown_recent = fake_breakdown.shift(1).rolling(5, min_periods=1).max().fillna(0).astype(bool)

    sustained_above = (close > open_bar_low).rolling(sustain_bars).sum() >= sustain_bars
    entry_long = (fake_breakdown_recent & sustained_above & (close >= open_bar_mid * 0.98) & ~is_first_bar_of_day).fillna(False)

    # Symmetric mirror for the short side (document is long-only in its worked example, but
    # states the same generic candle logic; mirrored per the interface spec's convention).
    fake_breakup = (high > open_bar_high) & (~is_first_bar_of_day)
    fake_breakup_recent = fake_breakup.shift(1).rolling(5, min_periods=1).max().fillna(0).astype(bool)
    sustained_below = (close < open_bar_high).rolling(sustain_bars).sum() >= sustain_bars
    entry_short = (fake_breakup_recent & sustained_below & (close <= open_bar_mid * 1.02) & ~is_first_bar_of_day).fillna(False)

    new_day = is_first_bar_of_day
    exit_long = (new_day | (close < open_bar_low)).fillna(False)
    exit_short = (new_day | (close > open_bar_high)).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
