"""
Module: strategy_orb_anish_retest_sr.py
Source document(s): ORB STRATEGY ANISH BOOMING BULLS.txt
Description: Classic Opening Range Breakout -- mark the first 15-minute candle's high/low,
    enter on a decisive breakout candle beyond that range, stop beyond the breakout candle's
    opposite extreme, 1:2 minimum R:R. This is a SIMPLER, more direct ORB variant than
    strategy_orb_retest_confirmation.py (that one requires a retest + candlestick-pattern
    confirmation before entry; this one enters on the breakout candle itself, no retest wait) --
    kept as a separate function since the two documents describe genuinely different entry
    timing philosophies, not the same rule.

    Interpretive assumptions:
    - "Strong decisive candle" = body_ratio >= 0.5 of the candle's range.
    - Opening range window defaults to the first 15 minutes of the session per the document;
      parameterized the same way as the other ORB variant for consistency.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_orb_anish_retest_sr(
    enriched: pd.DataFrame,
    session_open_hour: int = 9,
    session_open_minute: int = 15,
    range_minutes: int = 15,
    session_tz: str = "America/New_York",
    body_ratio_threshold: float = 0.5,
) -> pd.Series:
    """Direct Opening Range Breakout, no retest wait (Anish Booming Bulls concept).

    See module docstring for full source attribution and interpretive assumptions.
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

    body = (close - open_).abs()
    rng = (high - low).replace(0, np.nan)
    decisive = (body / rng) >= body_ratio_threshold

    entry_long = ((close > or_high) & (close.shift(1) <= or_high.shift(1)) & decisive & ~in_or_window).fillna(False)
    entry_short = ((close < or_low) & (close.shift(1) >= or_low.shift(1)) & decisive & ~in_or_window).fillna(False)

    new_day = (day != day.shift(1)).fillna(False)
    exit_long = (new_day | (close < or_low)).fillna(False)
    exit_short = (new_day | (close > or_high)).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
