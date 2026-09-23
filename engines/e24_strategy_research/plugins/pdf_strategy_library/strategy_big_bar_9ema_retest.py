"""
Module: strategy_big_bar_9ema_retest.py
Source document(s): BIG BAR STRATEGY.txt
Description: "Big Bar Strategy (9 EMA Retest Strategy)" -- wait for price to touch the 9 EMA,
then take the direction the very next candle closes relative to that EMA. Document's "9 EMA"
is approximated with the platform's `ema_8` column (closest available period). A trend filter
(ADX > 25, the industry-standard "trending" threshold) is added to honor the document's own
"trade only in trending conditions, avoid sideways market" instruction, since it names no
numeric threshold itself.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_big_bar_9ema_retest(
    enriched: pd.DataFrame,
    adx_trend_threshold: float = 25.0,
) -> pd.Series:
    """9-EMA retest-and-confirm strategy (document calls it "Big Bar Strategy").

    Source document: "BIG BAR STRATEGY.txt". Rule: wait for a candle to touch (retest) the 9
    EMA; if the NEXT candle closes above the EMA, buy; if it closes below, sell. Stop loss at
    the retest candle's low/high, target 1:1 R:R (R:R/sizing is left to the platform).

    Interpretive assumptions:
    - "9 EMA" approximated with `ema_8` (closest available period to 9).
    - "Trending conditions" (document gives no threshold) approximated as ADX > 25, the
      standard trend/no-trend cutoff used elsewhere on this platform.
    - Exit is not specified beyond the 1:1 target; the signal itself exits when price loses the
      EMA again or the trend filter turns off, so the position doesn't run indefinitely.
    """
    high, low, close, ema9 = enriched["high"], enriched["low"], enriched["close"], enriched["ema_8"]
    adx = enriched["adx"]

    retest = ((low.shift(1) <= ema9.shift(1)) & (high.shift(1) >= ema9.shift(1))).fillna(False)
    trending = (adx > adx_trend_threshold).fillna(False)

    entry_long = (retest & (close > ema9) & trending).fillna(False)
    entry_short = (retest & (close < ema9) & trending).fillna(False)

    exit_long = ((close < ema9) | (~trending)).fillna(False)
    exit_short = ((close > ema9) | (~trending)).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
