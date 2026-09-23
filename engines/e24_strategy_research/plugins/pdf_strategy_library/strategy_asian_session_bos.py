"""
Module: strategy_asian_session_bos.py
Source document(s): ASIAN SESSION BOS STRATEGY.txt
Description: EUR/USD (generalizable to any instrument) Asian-session liquidity-sweep + Break of
Structure (BOS) reversal. Marks the Asian session's high/low, waits for that level to be swept
(price trades through it), then enters on a subsequent structural break in the OPPOSITE
direction of the sweep (a classic liquidity-grab-then-reversal model).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_asian_session_bos(
    enriched: pd.DataFrame,
    asian_start_utc_hour: int = 0,
    asian_end_utc_hour: int = 8,
    sweep_lookback: int = 12,
    bos_swing_lookback: int = 5,
) -> pd.Series:
    """Asian session sweep + Break of Structure reversal (ASIAN SESSION BOS STRATEGY.txt).

    Source rule (5m EUR/USD chart): mark the Asian session's high and low. If price sweeps the
    session HIGH (trades through it) and then prints a bearish Break of Structure, go SHORT. If
    price sweeps the session LOW and then prints a bullish BOS, go LONG. Target 1:2-1:3 R:R
    (sizing out of scope per interface-spec rule 7); stop beyond the swept level.

    Interpretive assumptions:
      - Asian session window given in UTC hours (`asian_start_utc_hour`/`asian_end_utc_hour`,
        default 00:00-08:00 UTC, a standard Tokyo-session approximation) since the platform's
        `timestamp` column is tz-aware UTC directly -- no extra conversion needed/assumed.
      - Session high/low built with a causal (expanding, backward-looking) cumulative max/min
        restricted to in-session bars, forward-filled for the rest of the day -- a value used by
        any post-session bar is therefore always fully determined by strictly earlier bars.
      - "Sweep" = a post-session bar's high/low trades through the session high/low.
        "Break of Structure" = a subsequent candle CLOSE beyond a recent `bos_swing_lookback`-
        bar swing extreme (this project's standard "break of" = close-beyond-level resolution).
        A sweep stays "active" (eligible to be resolved by a BOS) for `sweep_lookback` bars.
      - Exit: thesis invalidation -- price reclaims back through the swept level, or a new
        Asian session begins (forces flat at the start of each new session/day).

    Returns:
        pd.Series[int] in {-1, 0, 1}, same index as `enriched`.
    """
    high = enriched["high"]; low = enriched["low"]; close = enriched["close"]

    date = enriched["timestamp"].dt.date
    hour = enriched["timestamp"].dt.hour
    in_session = (hour >= asian_start_utc_hour) & (hour < asian_end_utc_hour)
    after_session = ~in_session

    high_in_session = high.where(in_session)
    low_in_session = low.where(in_session)
    session_high = high_in_session.groupby(date).cummax().groupby(date).ffill()
    session_low = low_in_session.groupby(date).cummin().groupby(date).ffill()

    new_day = date.ne(date.shift(1)).fillna(True)

    sweep_high_event = (after_session & session_high.notna() & (high > session_high)).fillna(False)
    sweep_low_event = (after_session & session_low.notna() & (low < session_low)).fillna(False)
    recent_sweep_high = sweep_high_event.shift(1).rolling(sweep_lookback, min_periods=1).max().fillna(0).astype(bool)
    recent_sweep_low = sweep_low_event.shift(1).rolling(sweep_lookback, min_periods=1).max().fillna(0).astype(bool)

    swing_low_recent = low.shift(1).rolling(bos_swing_lookback).min()
    swing_high_recent = high.shift(1).rolling(bos_swing_lookback).max()
    bos_down = close < swing_low_recent
    bos_up = close > swing_high_recent

    entry_short = (recent_sweep_high & bos_down & after_session).fillna(False)
    entry_long = (recent_sweep_low & bos_up & after_session).fillna(False)

    exit_short = ((close > session_high) | new_day).fillna(False)
    exit_long = ((close < session_low) | new_day).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
