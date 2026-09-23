"""
Module: strategy_worlds_best_orb_retest_sr.py
Source document(s): worlds best scalping strategy.txt
Description: "Professional Opening Range Breakout (ORB) Scalping Strategy" -- NYSE/NASDAQ,
    15-minute opening range, but UNLIKE strategy_orb_anish_retest_sr.py this document requires
    a breakout candle CLOSE beyond the range, THEN a retracement into the nearest recent
    support/resistance area, entering only on renewed strength/weakness from that S/R zone
    (not on the breakout candle itself) -- genuinely different entry timing, implemented
    separately per the interface spec's near-duplicate rule (these two ORB documents are
    similar in setup but differ in exactly WHEN the entry triggers).

    Interpretive assumptions:
    - "Nearest recent support/resistance area" approximated as a rolling swing extreme over
      `sr_lookback` bars, established before the breakout (not the breakout level itself).
    - "Price shows strength/weakness from the support/resistance zone" = a rejection candle
      (closes back in the breakout direction) after touching that zone.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_worlds_best_orb_retest_sr(
    enriched: pd.DataFrame,
    session_open_hour: int = 9,
    session_open_minute: int = 30,
    range_minutes: int = 15,
    session_tz: str = "America/New_York",
    sr_lookback: int = 20,
    touch_atr_mult: float = 0.5,
) -> pd.Series:
    """ORB breakout + pullback-to-S/R entry (worlds-best-scalping-strategy concept).

    See module docstring for full source attribution and interpretive assumptions.
    """
    high, low, close = enriched["high"], enriched["low"], enriched["close"]
    atr = enriched["atr"]
    ts_local = enriched["timestamp"].dt.tz_convert(session_tz)
    day = ts_local.dt.date
    minutes_of_day = ts_local.dt.hour * 60 + ts_local.dt.minute
    or_start = session_open_hour * 60 + session_open_minute
    or_end = or_start + range_minutes

    in_or_window = (minutes_of_day >= or_start) & (minutes_of_day < or_end)
    after_or_window = minutes_of_day >= or_end

    or_high_by_day = high[in_or_window].groupby(day[in_or_window]).max()
    or_low_by_day = low[in_or_window].groupby(day[in_or_window]).min()
    or_high = day.map(or_high_by_day).where(after_or_window)
    or_low = day.map(or_low_by_day).where(after_or_window)

    broke_up = (close > or_high).fillna(False)
    broke_down = (close < or_low).fillna(False)
    broke_up_recent = broke_up.shift(1).rolling(20, min_periods=1).max().fillna(0).astype(bool)
    broke_down_recent = broke_down.shift(1).rolling(20, min_periods=1).max().fillna(0).astype(bool)

    # Nearest S/R zone established BEFORE the breakout (older window, no overlap with the
    # breakout-detection window -- avoids the subset-window trap).
    nearby_support = low.shift(1 + range_minutes).rolling(sr_lookback).min()
    nearby_resistance = high.shift(1 + range_minutes).rolling(sr_lookback).max()

    touched_support = (low - nearby_support).abs() <= (atr * touch_atr_mult)
    touched_resistance = (high - nearby_resistance).abs() <= (atr * touch_atr_mult)

    strength_from_support = touched_support & (close > close.shift(1))
    weakness_from_resistance = touched_resistance & (close < close.shift(1))

    entry_long = (broke_up_recent & strength_from_support & ~in_or_window).fillna(False)
    entry_short = (broke_down_recent & weakness_from_resistance & ~in_or_window).fillna(False)

    new_day = (day != day.shift(1)).fillna(False)
    exit_long = (new_day | (close < or_low)).fillna(False)
    exit_short = (new_day | (close > or_high)).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
