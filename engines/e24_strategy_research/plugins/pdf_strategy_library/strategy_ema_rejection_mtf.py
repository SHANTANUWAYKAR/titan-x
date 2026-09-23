"""
Module: strategy_ema_rejection_mtf.py
Source document(s): EMA REJECTION STRATEGY.txt
Description: "Day 9: The Trade Room (Mayank Raj) Crypto Strategy" -- use a higher timeframe to
find the prevailing trend, then enter when price touches a moving average on the trend side and
rejects (bounces) off it with a confirmation candle. Since only one timeframe of data is
available per call, the higher-timeframe trend read is approximated with ema_50 vs ema_200 on
the same series (a standard single-series MTF-trend proxy), and the rejection EMA (document
does not name a period) is approximated with ema_21.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_ema_rejection_mtf(enriched: pd.DataFrame) -> pd.Series:
    """Higher-timeframe-trend + EMA-rejection bounce entry.

    Source document: "EMA REJECTION STRATEGY.txt". Rule: identify the trend on a higher
    timeframe, find key support/resistance on a lower timeframe, and enter when price touches
    and clearly rejects an EMA in the trend direction.

    Interpretive assumptions:
    - Higher-timeframe trend approximated as ema_50 vs ema_200 on the single series provided
      (bullish when ema_50 > ema_200, bearish when ema_50 < ema_200).
    - The EMA price "rejects" from (document names no period) approximated with ema_21.
    - "Clear rejection" = the bar's low (high) touches or pierces the EMA but the bar still
      closes back above (below) it, in the direction of the higher-timeframe trend.
    """
    high, low, close, open_ = enriched["high"], enriched["low"], enriched["close"], enriched["open"]
    ema21, ema50, ema200 = enriched["ema_21"], enriched["ema_50"], enriched["ema_200"]

    trend_up = ema50 > ema200
    trend_down = ema50 < ema200

    reject_up = (low <= ema21) & (close > ema21) & (close > open_)
    reject_down = (high >= ema21) & (close < ema21) & (close < open_)

    entry_long = (trend_up & reject_up).fillna(False)
    entry_short = (trend_down & reject_down).fillna(False)

    exit_long = ((close < ema21) | (ema50 < ema200)).fillna(False)
    exit_short = ((close > ema21) | (ema50 > ema200)).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
