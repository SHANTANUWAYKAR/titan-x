"""
Module: strategy_traders_paradise_black_box.py
Source document(s): TRADERS PARADISE BB STRATEGY.txt
Description: "Black Box Strategy" -- despite the "BB" in the filename this document is NOT about
Bollinger Bands; its own title (confirmed by reading the full extracted text) is "BLACK BOX
STRATEGY: Professional Step-by-Step Guide to Trading Fake Breakouts." It trades fake breakouts of
support/resistance: price pokes beyond a level, traps breakout traders, then reverses back inside
the range -- entering in the reversal direction once confirmed. NOTE: this document's core "trap
breakout traders, trade the reversal" concept is conceptually similar to the previously
implemented strategy_blackbox_strategy / strategy_blackbox_trading_strategy (from an earlier
batch's BLACKBOX STRATEGY.txt / BLACKBOX TRADING STRATEGY.txt) -- flagged here for the record,
but implemented fresh as its own function since it is one of this batch's required 16 source
documents and the interface spec's near-duplicate rule applies primarily within a single batch.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_traders_paradise_black_box(
    enriched: pd.DataFrame,
    level_window: int = 20,
    confirm_window: int = 5,
) -> pd.Series:
    """Fake-breakout trap-and-reverse (TRADERS PARADISE BB STRATEGY.txt, "Black Box Strategy").

    Source document rule: mark strong support/resistance; when price breaks a level, gets
    breakout traders trapped, then FAILS to sustain and re-enters the range, enter in the
    reversal direction once confirmed.

    Level construction: resistance/support = prior `level_window`-bar rolling high/low
    (`.shift(1)` before `.rolling()`, matching the spec's breakout-level idiom). A breakout event
    is flagged when a bar's high/low pierces that level; the fake-breakout confirmation requires
    a breakout to have occurred within the last `confirm_window` bars (checked via
    `.shift(1).rolling(confirm_window).max()` on the breakout flag, so "was there a breakout in
    the last few bars BEFORE this one" never reads the current bar's own breakout flag) followed
    by the current bar's close falling back inside the range.

    Entry (short): a resistance breakout occurred recently AND the current close is back below
    resistance (bearish fake-breakout confirmed).
    Entry (long): a support breakdown occurred recently AND the current close is back above
    support (bullish fake-breakdown confirmed).
    Exit: price re-breaks beyond the ORIGINAL level in the original (trapped) direction,
    invalidating the reversal read (exit_short when close reclaims above resistance again;
    exit_long when close fails back below support again).
    """
    close = enriched["close"]
    high = enriched["high"]
    low = enriched["low"]

    resistance = high.shift(1).rolling(level_window).max()
    support = low.shift(1).rolling(level_window).min()

    breakout_up = high > resistance
    breakout_down = low < support

    # NOTE: rolling().max() on a boolean series returns NaN for the initial warm-up rows; casting
    # NaN directly to bool would incorrectly become True, so NaN is coerced to 0 BEFORE the bool
    # cast (never after) to keep the warm-up period correctly flagged as "no recent breakout."
    recent_breakout_up = (breakout_up.shift(1).rolling(confirm_window).max().fillna(0) > 0)
    recent_breakout_down = (breakout_down.shift(1).rolling(confirm_window).max().fillna(0) > 0)

    entry_short = recent_breakout_up & (close < resistance)
    entry_long = recent_breakout_down & (close > support)

    exit_short = close > resistance
    exit_long = close < support

    entry_long = entry_long.fillna(False)
    entry_short = entry_short.fillna(False)
    exit_long = exit_long.fillna(False)
    exit_short = exit_short.fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
