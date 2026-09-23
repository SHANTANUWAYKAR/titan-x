"""
Module: strategy_travelling_trader_catalyst_retrace.py
Source document(s): The Travelling Trader Playbook.txt
Description: "Universal Strategy" -- three-part story: (1) Liquidity Catalyst (a sweep of equal
    highs/lows, a break of major S/R, a trendline break, or a market structure shift), (2)
    Displacement (a decisive move away from the catalyst confirming it mattered), (3)
    Retracement into a logical area (broken S/R, retested trendline, moving average) for the
    actual entry.

    Interpretive assumptions:
    - Catalyst = a break of a rolling swing high/low (market structure shift proxy).
    - Displacement = the break is followed by `displacement_bars` of continued momentum in the
      same direction with body_ratio >= displacement_body_ratio.
    - Retracement entry = price pulls back to within `retrace_atr_mult` ATR of ema_21 (the
      "moving average used as dynamic support/resistance", the specific MA type the document
      names among its listed retracement targets) and resumes in the catalyst direction. The
      retracement is checked over the same `structure_lookback` window as the catalyst/
      displacement (a later, separate event from the displacement itself, not the same bar).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_travelling_trader_catalyst_retrace(
    enriched: pd.DataFrame,
    structure_lookback: int = 20,
    displacement_bars: int = 3,
    displacement_body_ratio: float = 0.55,
    retrace_atr_mult: float = 0.6,
) -> pd.Series:
    """Catalyst -> displacement -> retracement entry (The Travelling Trader "Universal Strategy").

    See module docstring for full source attribution and interpretive assumptions.
    """
    high, low, close, open_ = enriched["high"], enriched["low"], enriched["close"], enriched["open"]
    ema_21, atr = enriched["ema_21"], enriched["atr"]

    swing_high = high.shift(1).rolling(structure_lookback).max()
    swing_low = low.shift(1).rolling(structure_lookback).min()

    catalyst_up = (close > swing_high) & (close.shift(1) <= swing_high.shift(1))
    catalyst_down = (close < swing_low) & (close.shift(1) >= swing_low.shift(1))

    body = (close - open_).abs()
    rng = (high - low).replace(0, np.nan)
    strong = (body / rng) >= displacement_body_ratio

    displaced_up = (catalyst_up.shift(displacement_bars).fillna(False) &
                    (strong & (close > open_)).rolling(displacement_bars).sum().ge(displacement_bars - 1))
    displaced_down = (catalyst_down.shift(displacement_bars).fillna(False) &
                       (strong & (close < open_)).rolling(displacement_bars).sum().ge(displacement_bars - 1))

    catalyst_up_recent = catalyst_up.shift(1).rolling(structure_lookback, min_periods=1).max().fillna(0).astype(bool)
    catalyst_down_recent = catalyst_down.shift(1).rolling(structure_lookback, min_periods=1).max().fillna(0).astype(bool)

    # Displacement CONFIRMED at some point within the recent window (not pinned to exactly one
    # bar) -- the retracement into the MA is a SEPARATE, LATER event than the displacement
    # itself (displacement pushes price away from the MA; retracement is price coming back to
    # it afterward), so "displaced" must be evaluated as "did this happen recently", not "is
    # this true on the exact same bar as the retracement check" -- fixed bug found during
    # Stage-0 pre-verification 2026-09-13: the original single-bar AND produced zero signals
    # across two different real assets/timeframes because displacement-away-from-MA and
    # retracement-back-to-MA are logically exclusive on the same bar.
    displaced_up_recent = displaced_up.shift(1).rolling(structure_lookback, min_periods=1).max().fillna(0).astype(bool)
    displaced_down_recent = displaced_down.shift(1).rolling(structure_lookback, min_periods=1).max().fillna(0).astype(bool)

    retraced_to_ma = (close - ema_21).abs() <= (atr * retrace_atr_mult)

    entry_long = (catalyst_up_recent & displaced_up_recent & retraced_to_ma & (close > close.shift(1))).fillna(False)
    entry_short = (catalyst_down_recent & displaced_down_recent & retraced_to_ma & (close < close.shift(1))).fillna(False)

    exit_long = (close < swing_low).fillna(False)
    exit_short = (close > swing_high).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
