"""
Module: strategy_fibonacci_deep_retracement_pullback.py
Source document(s): BEST FIBONACCI STRATEGY.txt, FIBONACCI TRADING STRATEGY.txt
Description: Both source documents describe the same core setup -- during a strong trending
move, draw a Fibonacci retracement from the swing origin to the swing extreme and wait for
price to pull back into a deep-retracement zone before entering in the direction of the
original trend on a confirmation candle. "BEST FIBONACCI STRATEGY" names the zone as the
0.70-0.786 band; "FIBONACCI TRADING STRATEGY" names it as a custom 0.60-0.705 band. Per the
near-duplicate consolidation rule these are implemented as ONE parameterized function with a
`variant` switch selecting which documented band to use (default "classic" = 0.70/0.786).
Swing high/low anchors and the "confirmation" candle are mechanical approximations (see
function docstring) since neither document defines an exact swing-detection algorithm.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_fibonacci_deep_retracement_pullback(
    enriched: pd.DataFrame,
    swing_lookback: int = 30,
    fib_zone_low: float = 0.70,
    fib_zone_high: float = 0.786,
    variant: str = "classic",
) -> pd.Series:
    """Fibonacci deep-retracement pullback entry (consolidates two source docs).

    Source documents: "BEST FIBONACCI STRATEGY.txt" (0.70/0.786 retracement zone) and
    "FIBONACCI TRADING STRATEGY.txt" (custom 0.60/0.705 retracement zone). Both describe:
    identify a strong trending swing, draw a Fibonacci retracement across it, wait for price
    to pull back into a deep-retracement band, then enter in the ORIGINAL trend direction on a
    confirmation candle, with the stop beyond the swing extreme.

    variant="classic" (default) uses fib_zone_low/high = 0.70/0.786 (BEST FIBONACCI STRATEGY).
    variant="custom" overrides the zone to 0.60/0.705 (FIBONACCI TRADING STRATEGY's exact
    levels), ignoring the fib_zone_low/high arguments.

    Interpretive assumptions (neither doc defines these mechanically):
    - "Swing low"/"swing high" = rolling min/max of low/high over `swing_lookback` bars,
      computed from bars strictly BEFORE the current one (shift(1) before rolling) so the
      swing anchors are fixed, known data at the time the current bar forms.
    - Trend context ("strong aggressive move") approximated with the platform's own
      `supertrend_direction` column (1 = up, -1 = down) rather than re-deriving swing
      direction, since supertrend_direction is already provided and causal.
    - "Confirmation" = a candle that dips into the retracement zone (low/high reaches it) and
      then closes back on the trend side of the zone's near boundary (a rejection close).
    """
    if variant == "custom":
        lo, hi = 0.60, 0.705
    else:
        lo, hi = fib_zone_low, fib_zone_high

    open_, high, low, close = enriched["open"], enriched["high"], enriched["low"], enriched["close"]
    trend = enriched["supertrend_direction"]

    swing_high = high.shift(1).rolling(swing_lookback).max()
    swing_low = low.shift(1).rolling(swing_lookback).min()
    swing_range = swing_high - swing_low

    # Bullish retracement zone measured down from swing_high (higher fib level => lower price).
    bull_zone_upper = swing_high - swing_range * lo
    bull_zone_lower = swing_high - swing_range * hi

    # Bearish retracement zone measured up from swing_low.
    bear_zone_lower = swing_low + swing_range * lo
    bear_zone_upper = swing_low + swing_range * hi

    in_bull_zone = (low <= bull_zone_upper) & (low >= bull_zone_lower)
    in_bear_zone = (high >= bear_zone_lower) & (high <= bear_zone_upper)

    bull_confirm = in_bull_zone & (close > open_) & (close > bull_zone_lower)
    bear_confirm = in_bear_zone & (close < open_) & (close < bear_zone_upper)

    entry_long = ((trend == 1) & bull_confirm).fillna(False)
    entry_short = ((trend == -1) & bear_confirm).fillna(False)

    exit_long = ((trend == -1) | (close < swing_low)).fillna(False)
    exit_short = ((trend == 1) | (close > swing_high)).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
