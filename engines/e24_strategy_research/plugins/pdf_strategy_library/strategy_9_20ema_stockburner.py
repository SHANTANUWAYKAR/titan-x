"""
Module: strategy_9_20ema_stockburner.py
Source document(s): 9 20 EMA STOCKBURNER STRATEGY.txt
Description: Asymmetric 9/20 EMA trend-following system (kept separate from "9 20EMA
STRATEGY.txt" -- read both fully; despite the similar filename this one's rule structure is
materially different, see the comparison note below). The BUY side is a continuous regime
("9 EMA should REMAIN above the 20 EMA... look for long opportunities") with an "expanding
EMAs" strength filter, entered on pullback-to-fast-EMA continuation; the SELL side is an
explicit discrete crossunder event. Document specifies 9 EMA / 20 EMA; approximated with
ema_8 / ema_21 (documented, batch-wide convention).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_9_20ema_stockburner(
    enriched: pd.DataFrame,
    expand_lookback: int = 10,
    pullback_confirm: bool = True,
) -> pd.Series:
    """Stockburner 9/20 EMA expanding-trend continuation + crossunder short
    (9 20 EMA STOCKBURNER STRATEGY.txt).

    Source rule (plain English): both EMAs "expanding and moving upward" = a strong trend. Buy
    Setup: 9 EMA stays above the 20 EMA -> look for longs in the trend direction. Sell Setup:
    when the 9 EMA crosses below the 20 EMA, a bearish reversal may begin -> look for shorts.
    Target >=1:3 R:R (sizing out of scope per interface-spec rule 7); exit immediately if
    stopped out (handled by the platform, not this function).

    Interpretive assumptions:
      - "9 EMA"/"20 EMA" -> `ema_8`/`ema_21`.
      - "Expanding" = the absolute distance between the two EMAs is wider now than
        `expand_lookback` bars ago.
      - The Buy Setup is a continuous regime condition, not a single discrete event, so its
        mechanical entry TRIGGER (a concrete row where the direction flips from flat to long)
        is taken as a pullback-and-continuation: price dips to touch `ema_8` while the expanding
        uptrend regime holds, then closes back above it (`pullback_confirm=True`, default). Set
        `pullback_confirm=False` to instead trigger on every bar the regime holds and the
        position is flat (a looser reading of "look for long opportunities").
      - The Sell Setup is implemented literally as the doc's explicit discrete crossunder event.
      - Exit: long exits on the crossunder (the doc's own Sell Setup trigger); short exits when
        the regime flips back to the Buy Setup condition (`ema_8` > `ema_21`).

    Returns:
        pd.Series[int] in {-1, 0, 1}, same index as `enriched`.
    """
    open_ = enriched["open"]; high = enriched["high"]; low = enriched["low"]; close = enriched["close"]
    ema_fast = enriched["ema_8"]; ema_slow = enriched["ema_21"]

    spread = (ema_fast - ema_slow).abs()
    expanding = spread > spread.shift(expand_lookback)

    bullish_regime = (ema_fast > ema_slow) & expanding
    cross_down = (ema_fast.shift(1) >= ema_slow.shift(1)) & (ema_fast < ema_slow)
    cross_up = (ema_fast.shift(1) <= ema_slow.shift(1)) & (ema_fast > ema_slow)

    if pullback_confirm:
        touch = (low <= ema_fast) & (high >= ema_fast)
        entry_long = (bullish_regime & touch & (close > ema_fast) & (close > open_)).fillna(False)
    else:
        entry_long = bullish_regime.fillna(False)

    entry_short = cross_down.fillna(False)

    exit_long = cross_down.fillna(False)
    exit_short = cross_up.fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
