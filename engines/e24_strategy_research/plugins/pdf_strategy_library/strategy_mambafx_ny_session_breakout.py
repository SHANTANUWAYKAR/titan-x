"""
Module: strategy_mambafx_ny_session_breakout.py
Source document(s): MAMBAFX NY SESSION STRATEGY.txt
Description: "Session Breakout Strategy Guide (For Indian Traders)" -- a once-a-day
breakout strategy for trading NASDAQ/US30 around the New York session open (7:00 PM IST).
Support/resistance is prepared shortly before the session opens; the entry is a breakout
of that level right at the session-open window, filtered by candle-wick behavior so a
breakout with a large opposing wick (rejection) is not taken.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_mambafx_ny_session_breakout(
    enriched: pd.DataFrame,
    prep_lookback: int = 20,
    session_start_min_utc: int = 810,
    session_window_minutes: int = 60,
    wick_threshold: float = 0.5,
) -> pd.Series:
    """MambaFX-style New York session-open breakout for NASDAQ/US30.

    Source: MAMBAFX NY SESSION STRATEGY.txt.

    Rule (plain English): before the New York session opens (document says prep at
    6:45 PM IST, trade at 7:00 PM IST), mark a support and resistance level. At the
    session open, react (don't predict): a close above resistance is a BUY, a close
    below support is a SELL. Candle-wick behavior confirms/denies the breakout: a large
    wick AGAINST the breakout direction signals the opposing side is still strong and
    should suppress the entry. The document specifies only one trade per day; this
    function evaluates every bar within the session-open window and lets the platform's
    own stateful position tracking (the helper below) govern repeat same-direction
    entries, since deduplicating to "first signal of the day only" is a scheduling
    concern, not a signal-direction concern.

    Interpretive assumptions: (1) "7:00 PM IST" is approximated as 13:30 UTC
    (`session_start_min_utc=810`), consistent with the New York cash-equity open
    (9:30 AM US Eastern) under Eastern *Daylight* Time -- the document itself uses one
    fixed local clock time with no DST adjustment, so a single fixed UTC time mirrors
    that same simplification; the tradeable window stays open for
    `session_window_minutes` (default 60) after that. (2) Support/resistance ("drawn"
    manually in the document before the session) is approximated as a rolling
    `prep_lookback`-bar high/low computed off bars strictly before the current one --
    because it is `.shift(1)`-based it automatically reflects only pre-session price
    action once entries are gated to the session window. (3) "Large opposing wick" =
    opposing wick >= `wick_threshold` (default 50%) of the bar's total range.

    No lookahead: the support/resistance levels use `.shift(1)` before their rolling
    window; the wick ratios and the breakout comparison all use only the current bar's
    own OHLC, which is legitimate since that is the signal bar itself.
    """
    ts = enriched["timestamp"]
    tod_minutes = ts.dt.hour * 60 + ts.dt.minute
    high = enriched["high"]
    low = enriched["low"]
    open_ = enriched["open"]
    close = enriched["close"]
    rng = (high - low).replace(0, np.nan)

    resistance = high.shift(1).rolling(prep_lookback).max()
    support = low.shift(1).rolling(prep_lookback).min()

    session_mask = (tod_minutes >= session_start_min_utc) & (
        tod_minutes < (session_start_min_utc + session_window_minutes)
    )

    upper_body = pd.concat([open_, close], axis=1).max(axis=1)
    lower_body = pd.concat([open_, close], axis=1).min(axis=1)
    upper_wick_ratio = (high - upper_body) / rng
    lower_wick_ratio = (lower_body - low) / rng

    breakout_up = close > resistance
    breakout_down = close < support

    entry_long = session_mask & breakout_up & (upper_wick_ratio < wick_threshold)
    entry_short = session_mask & breakout_down & (lower_wick_ratio < wick_threshold)

    exit_long = close < resistance
    exit_short = close > support

    return _stateful_from_entries_exits(
        entry_long.fillna(False),
        exit_long.fillna(False),
        entry_short.fillna(False),
        exit_short.fillna(False),
    )
