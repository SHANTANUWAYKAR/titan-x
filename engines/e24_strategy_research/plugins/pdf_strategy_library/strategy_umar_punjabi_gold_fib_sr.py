"""
Module: strategy_umar_punjabi_gold_fib_sr.py
Source document(s): UMAR PUNJABI GOLD STRATEGY.txt
Description: Gold S/R + Fibonacci retracement strategy -- DIFFERENT from the existing
    strategies_by_style/YOUTUBE_DECODED/strategy_umar_punjabi_gold_london.py (that one is the
    Asia-range-sweep-then-London-BOS concept; confirmed by reading THIS document in full that it
    is a separate, S/R + 0.382-Fibonacci-retracement concept with no session/Asia-sweep
    mechanic at all) -- implemented fresh per the interface spec.

    Rule: identify a strong reaction from a support zone (an upward rally), fit a Fibonacci
    retracement from that swing low to the resulting swing high, and buy when price retraces to
    and holds the 0.382 level. Mirror logic for sells (resistance -> downward move -> 0.382
    retracement).

    Interpretive assumptions:
    - "Support/Resistance zones" and "swing low/high" = rolling extremes over
      `swing_lookback` bars.
    - "Holds the 0.382 level" = price touches within `fib_tolerance_atr_mult` ATR of the 0.382
      retracement level and closes back in the rally/decline direction.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_umar_punjabi_gold_fib_sr(
    enriched: pd.DataFrame,
    swing_lookback: int = 30,
    fib_level: float = 0.382,
    fib_tolerance_atr_mult: float = 0.5,
) -> pd.Series:
    """Gold S/R + 0.382 Fibonacci retracement entry (Umar Punjabi Gold concept).

    See module docstring for full source attribution and interpretive assumptions.
    """
    high, low, close = enriched["high"], enriched["low"], enriched["close"]
    atr = enriched["atr"]

    swing_low = low.shift(1).rolling(swing_lookback).min()
    swing_high = high.shift(1).rolling(swing_lookback).max()

    # Rally from support: current bar is a new local high after a swing low was set.
    rally_range = swing_high - swing_low
    fib_up_level = swing_high - fib_level * rally_range     # retracement DOWN from the high
    fib_down_level = swing_low + fib_level * rally_range    # retracement UP from the low

    near_fib_up = (close - fib_up_level).abs() <= (atr * fib_tolerance_atr_mult)
    near_fib_down = (close - fib_down_level).abs() <= (atr * fib_tolerance_atr_mult)

    uptrend_context = close > swing_low + rally_range * 0.5   # rally happened, we're above midline
    downtrend_context = close < swing_high - rally_range * 0.5

    entry_long = (uptrend_context & near_fib_up & (close > close.shift(1))).fillna(False)
    entry_short = (downtrend_context & near_fib_down & (close < close.shift(1))).fillna(False)

    exit_long = (close < swing_low).fillna(False)
    exit_short = (close > swing_high).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
