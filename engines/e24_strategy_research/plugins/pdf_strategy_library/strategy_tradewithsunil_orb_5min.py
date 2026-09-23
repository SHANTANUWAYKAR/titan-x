"""
Module: strategy_tradewithsunil_orb_5min.py
Source document(s): TRADEWITHSUNIL 5MIN STRATEGY.txt
Description: BankNifty 5-minute Opening Range Breakout. The first 5-minute candle of each day
marks the day's opening range High/Low; a break of that High is bullish, a break of the Low is
bearish. The document flags the retest-of-broken-level entry as the "High Probability" version,
which is what is implemented (rather than a naive same-candle breakout chase), plus the "if both
High and Low break the same day, stop trading it" filter.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_tradewithsunil_orb_5min(
    enriched: pd.DataFrame,
    retest_tolerance_atr_mult: float = 0.15,
) -> pd.Series:
    """BankNifty 5-min opening-range breakout + retest (TRADEWITHSUNIL 5MIN STRATEGY.txt).

    Source document rule: mark the High/Low of the FIRST 5-minute candle of the trading day.
    A break of the High is a BUY signal, a break of the Low is a SELL signal; if the market
    breaks BOTH the High and Low on the same day, stop trading that day (sideways trap). The
    document's "Retest Entry (High Probability)" variant -- wait for price to pull back and
    retest the broken opening-range level before entering -- is implemented as the entry
    mechanic (the higher-probability version the document itself recommends).

    Opening-range construction (causal): for each calendar day, `or_high`/`or_low` are built via
    a same-day `cummax`/`cummin` restricted to the day's FIRST bar only, then forward-filled for
    the rest of that day -- so a bar only ever sees the opening range once that opening candle
    has actually closed, never a same-day future value.

    "Broken before this bar" flags use `.groupby(day).shift(1)` (not a plain `.shift(1)`), so the
    lag resets at each day boundary instead of leaking the previous day's final state into a new
    day's first bar.

    Entry (long): opening range is known, the High has been broken by a PRIOR bar today (but the
    Low has NOT also been broken today -- the "don't trade both-broke" filter), price has pulled
    back to within `retest_tolerance_atr_mult` * ATR of `or_high`, and the current bar closes
    back above `or_high` (retest confirmation). Entry (short) is the mirror image off `or_low`.
    Exit: price closes back through the OTHER side of the opening range (additional
    invalidation), or the opposite entry fires, via the shared stateful helper.
    """
    close = enriched["close"]
    high = enriched["high"]
    low = enriched["low"]
    atr = enriched["atr"]
    ts = pd.to_datetime(enriched["timestamp"], utc=True)
    day = ts.dt.floor("D")

    is_first_bar = enriched.groupby(day).cumcount() == 0

    or_high_only = high.where(is_first_bar)
    or_low_only = low.where(is_first_bar)
    running_or_high = or_high_only.groupby(day).cummax()
    running_or_low = or_low_only.groupby(day).cummin()
    or_high = running_or_high.groupby(day).ffill()
    or_low = running_or_low.groupby(day).ffill()

    broke_high_ever = high > or_high
    broke_low_ever = low < or_low
    broke_high_today = broke_high_ever.groupby(day).cummax()
    broke_low_today = broke_low_ever.groupby(day).cummax()
    broke_high_before = broke_high_today.groupby(day).shift(1).fillna(False).astype(bool)
    broke_low_before = broke_low_today.groupby(day).shift(1).fillna(False).astype(bool)
    both_broke_before = broke_high_before & broke_low_before

    tol = atr * retest_tolerance_atr_mult

    retest_long = (
        broke_high_before
        & ~both_broke_before
        & (low <= or_high + tol)
        & (close > or_high)
    )
    retest_short = (
        broke_low_before
        & ~both_broke_before
        & (high >= or_low - tol)
        & (close < or_low)
    )

    entry_long = retest_long
    entry_short = retest_short

    exit_long = close < or_low
    exit_short = close > or_high

    entry_long = entry_long.fillna(False)
    entry_short = entry_short.fillna(False)
    exit_long = exit_long.fillna(False)
    exit_short = exit_short.fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
