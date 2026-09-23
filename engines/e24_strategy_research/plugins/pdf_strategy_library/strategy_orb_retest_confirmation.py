"""
Module: strategy_orb_retest_confirmation.py
Source document(s): BEST INTRADAY STRATEGY.txt
Description: "9:20 Open Range Breakout (Modified)" -- mark the high/low of the opening range
(default 9:15-9:20 AM IST, the times literally given in the document), then do NOT enter on
the initial breakout; wait for price to retest the broken opening-range level and confirm with
a Bullish Engulfing or Hammer (long) / Bearish Engulfing or Shooting Star (short) candle before
entering. Implemented symmetrically for both directions since the document's rules are stated
generically ("the level", "breakout") even though its own worked example is long-only.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_orb_retest_confirmation(
    enriched: pd.DataFrame,
    session_open_hour: int = 9,
    session_open_minute: int = 15,
    range_minutes: int = 5,
    session_tz: str = "Asia/Kolkata",
    retest_lookback: int = 20,
) -> pd.Series:
    """Opening-range breakout with mandatory retest + candle confirmation (no chase entries).

    Source document: "BEST INTRADAY STRATEGY.txt" (9:20 Open Range Breakout, modified).
    Rule: mark the opening range (default 9:15-9:20 AM IST -- the exact minutes named in the
    document; session_tz/hour/minute/range_minutes are parameterized for other markets), do
    NOT enter on the initial break, wait for price to come back and retest the broken level,
    then enter only on a confirmation candle (Bullish Engulfing/Hammer for longs, Bearish
    Engulfing/Shooting Star for shorts -- the document names these two patterns explicitly for
    the long case; mirrored for shorts since the rest of the rule is direction-agnostic).

    Interpretive assumptions:
    - The opening-range high/low for a given trading day only becomes usable for bars strictly
      AFTER the range window closes that same day (never during/before it), so no future
      information leaks from a day's own range into its own formation bars.
    - "Break the level and come back to retest" approximated as: a breakout occurred within the
      last `retest_lookback` bars (bounded window, not unbounded state), and the current bar's
      low/high has returned to touch the broken level.
    - Positions are flattened at the first bar of a new trading day (intraday-only strategy, no
      overnight holding), consistent with the document's intraday framing.
    """
    open_, high, low, close = enriched["open"], enriched["high"], enriched["low"], enriched["close"]
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
    broke_up_recent = broke_up.shift(1).rolling(retest_lookback, min_periods=1).max().fillna(0).astype(bool)
    broke_down_recent = broke_down.shift(1).rolling(retest_lookback, min_periods=1).max().fillna(0).astype(bool)

    retest_up = broke_up_recent & (low <= or_high).fillna(False)
    retest_down = broke_down_recent & (high >= or_low).fillna(False)

    body = (close - open_).abs()
    upper_wick = high - np.maximum(close, open_)
    lower_wick = np.minimum(close, open_) - low
    body_safe = body.replace(0, np.nan)

    bullish_engulfing = (close > open_) & (close.shift(1) < open_.shift(1)) & (close >= open_.shift(1)) & (open_ <= close.shift(1))
    bearish_engulfing = (close < open_) & (close.shift(1) > open_.shift(1)) & (close <= open_.shift(1)) & (open_ >= close.shift(1))
    hammer = (close > open_) & (lower_wick >= 2 * body) & (upper_wick <= 0.3 * body_safe)
    shooting_star = (close < open_) & (upper_wick >= 2 * body) & (lower_wick <= 0.3 * body_safe)

    confirm_long = (bullish_engulfing | hammer).fillna(False)
    confirm_short = (bearish_engulfing | shooting_star).fillna(False)

    entry_long = (retest_up & confirm_long & ~in_or_window).fillna(False)
    entry_short = (retest_down & confirm_short & ~in_or_window).fillna(False)

    new_day = (day != day.shift(1)).fillna(False)
    exit_long = new_day | (close < or_low).fillna(False)
    exit_short = new_day | (close > or_high).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
