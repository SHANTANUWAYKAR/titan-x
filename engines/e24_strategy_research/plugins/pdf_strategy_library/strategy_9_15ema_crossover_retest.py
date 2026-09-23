"""
Module: strategy_9_15ema_crossover_retest.py
Source document(s): 9 15 EMA DETAILED STRATEGY.txt, 9 15EMA STRATEGY.txt
Description: Both source documents describe the literal same core setup: a 9/15 EMA crossover
with a strong-momentum ("~30 degree") angle filter, wait for the FIRST retest of the fast EMA
after the cross, then enter on a rejection candle at that retest. Consolidated per
interface-spec rule 5 into one well-parameterized function. Document specifies 9 EMA / 15 EMA;
the platform provides ema_8/ema_21/ema_50/ema_200, so ema_8 (9 EMA) and ema_21 (15 EMA, the
closer of the two remaining columns to 15) are used, documented explicitly.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_9_15ema_crossover_retest(
    enriched: pd.DataFrame,
    angle_lookback: int = 5,
    angle_atr_mult: float = 0.8,
    max_retest_wait: int = 20,
    rejection_wick_ratio: float = 0.4,
) -> pd.Series:
    """9/15 EMA crossover + first-retest + rejection-candle entry (consolidates "9 15 EMA
    DETAILED STRATEGY.txt" and "9 15EMA STRATEGY.txt").

    Source rule (plain English, both docs): wait for the 9 EMA to cross the 15 EMA with strong
    momentum (~30 degree angle). Do NOT enter on the cross itself -- wait for price's FIRST
    pullback ("retest") to the fast EMA, and enter only after a rejection candle confirms the
    retest held. Both docs explicitly warn against late entries after multiple retests, so
    "first retest only" is treated as a real, load-bearing rule, not a stylistic detail.
    Target >=1:2 R:R (sizing out of scope per interface-spec rule 7).

    Interpretive assumptions:
      - "9 EMA"/"15 EMA" -> `ema_8`/`ema_21` (closest available periods, documented in the
        module docstring).
      - "~30 degree angle" cannot be computed without the chart's pixel/axis geometry;
        approximated as the fast EMA's `angle_lookback`-bar change exceeding `angle_atr_mult` *
        ATR, checked at the moment of retest (so momentum must still be intact, not just at the
        instant of the original cross).
      - "First retest" is implemented exactly (not just "a retest within a fuzzy window"): each
        qualifying cross opens a new causal group (`cumsum` of cross events); within that group,
        the retest flag fires only on the bar where the touch-count-so-far first reaches 1
        (`touch.groupby(group).cumsum() == 1`), which is a fully vectorized, backward-looking
        (causal) construction. The retest must also occur within `max_retest_wait` bars of the
        cross, or it's considered stale and ignored.
      - "Rejection candle" = candle body closes back beyond `rejection_wick_ratio` of the range
        from the EMA-side wick (i.e. a real reversal candle, not just any touch).
      - Exit: close crosses back through the slow EMA (`ema_21`) -- the trend-defining EMA is
        invalidated.

    Returns:
        pd.Series[int] in {-1, 0, 1}, same index as `enriched`.
    """
    open_ = enriched["open"]; high = enriched["high"]; low = enriched["low"]; close = enriched["close"]
    atr = enriched["atr"].replace(0, np.nan)
    ema_fast = enriched["ema_8"]; ema_slow = enriched["ema_21"]

    cross_up = (ema_fast.shift(1) <= ema_slow.shift(1)) & (ema_fast > ema_slow)
    cross_down = (ema_fast.shift(1) >= ema_slow.shift(1)) & (ema_fast < ema_slow)

    slope_up = (ema_fast - ema_fast.shift(angle_lookback)) > (angle_atr_mult * atr)
    slope_down = (ema_fast.shift(angle_lookback) - ema_fast) > (angle_atr_mult * atr)

    touch = (low <= ema_fast) & (high >= ema_fast)

    group_up = cross_up.cumsum()
    group_down = cross_down.cumsum()
    bars_since_up = close.groupby(group_up).cumcount()
    bars_since_down = close.groupby(group_down).cumcount()
    first_retest_up = touch & (touch.groupby(group_up).cumsum() == 1) & (group_up > 0) & (bars_since_up <= max_retest_wait)
    first_retest_down = touch & (touch.groupby(group_down).cumsum() == 1) & (group_down > 0) & (bars_since_down <= max_retest_wait)

    rng = (high - low).replace(0, np.nan)
    reject_bull = (close > open_) & ((pd.concat([open_, close], axis=1).min(axis=1) - low) >= rejection_wick_ratio * rng)
    reject_bear = (close < open_) & ((high - pd.concat([open_, close], axis=1).max(axis=1)) >= rejection_wick_ratio * rng)

    entry_long = (first_retest_up & slope_up & reject_bull & (close > ema_fast)).fillna(False)
    entry_short = (first_retest_down & slope_down & reject_bear & (close < ema_fast)).fillna(False)

    exit_long = (close < ema_slow).fillna(False)
    exit_short = (close > ema_slow).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
