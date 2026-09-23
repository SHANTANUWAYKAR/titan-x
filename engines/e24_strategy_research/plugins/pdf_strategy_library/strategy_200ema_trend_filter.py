"""
Module: strategy_200ema_trend_filter.py
Source document(s): 200_EMA_Trading_Strategy_Guide.txt, 200EMA DEVANSHRAI STRATEGY.txt,
                     200EMA TRADING STRATEGY.txt
Description: All three source documents describe the literal same core setup: use the 200 EMA
(typically on a 15-minute chart) purely as a trend filter (price above -> longs only, price
below -> shorts only), and enter either on a fresh EMA crossover or on a pullback to the EMA
that closes back in the trend direction, targeting >=1:2 R:R. Consolidated per interface-spec
rule 5 into one well-parameterized function; a `use_pullback_entry` / `use_crossover_entry`
pair of booleans lets a caller isolate either entry style if desired (both are on by default,
matching the documents' "crossover OR pullback confirmation" wording).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_200ema_trend_filter(
    enriched: pd.DataFrame,
    use_crossover_entry: bool = True,
    use_pullback_entry: bool = True,
    pullback_atr: float = 0.25,
) -> pd.Series:
    """200 EMA trend-following filter with crossover/pullback entries (3 consolidated docs).

    Consolidates: 200_EMA_Trading_Strategy_Guide.txt, 200EMA DEVANSHRAI STRATEGY.txt,
    200EMA TRADING STRATEGY.txt -- all three specify: trade only in the direction of the 200
    EMA (long-only above it, short-only below it), enter on either a fresh EMA crossover or a
    pullback-to-EMA that closes back in trend direction, minimum 1:2 R:R, exit when price
    closes back through the 200 EMA (trend filter invalidated).

    Interpretive assumptions:
      - No approximation needed: `ema_200` is provided directly.
      - "Pullback confirmation" = the bar's low/high touches ema_200 while the close remains
        on (or returns to) the trend side, closing within `pullback_atr` ATR of the EMA on the
        trend side, with a same-direction candle body.
      - Exit = price closes back through the 200 EMA on the opposite side (standard project
        convention: "break of" = candle close beyond level).

    Args:
        enriched: platform OHLCV + indicator DataFrame.
        use_crossover_entry: allow fresh EMA-crossover entries.
        use_pullback_entry: allow pullback-to-EMA entries while already in-trend.
        pullback_atr: max distance (in ATRs) from ema_200 for a "touch" pullback entry.

    Returns:
        pd.Series[int] in {-1, 0, 1}, same index as `enriched`.
    """
    close = enriched["close"]; open_ = enriched["open"]
    high = enriched["high"]; low = enriched["low"]
    ema200 = enriched["ema_200"]
    atr = enriched["atr"].replace(0, np.nan)

    cross_up = (close.shift(1) <= ema200.shift(1)) & (close > ema200)
    cross_down = (close.shift(1) >= ema200.shift(1)) & (close < ema200)

    touched_from_above = (low <= ema200) & (close > ema200) & (close > open_)
    touched_from_below = (high >= ema200) & (close < ema200) & (close < open_)
    near_after_touch_long = (close - ema200) <= (pullback_atr * atr)
    near_after_touch_short = (ema200 - close) <= (pullback_atr * atr)

    pullback_long = touched_from_above & near_after_touch_long
    pullback_short = touched_from_below & near_after_touch_short

    entry_long = pd.Series(False, index=enriched.index)
    entry_short = pd.Series(False, index=enriched.index)
    if use_crossover_entry:
        entry_long = entry_long | cross_up
        entry_short = entry_short | cross_down
    if use_pullback_entry:
        entry_long = entry_long | pullback_long
        entry_short = entry_short | pullback_short
    entry_long = entry_long.fillna(False)
    entry_short = entry_short.fillna(False)

    exit_long = (close < ema200).fillna(False)
    exit_short = (close > ema200).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
