"""
Module: strategy_tg_capital_trident_fvg.py
Source document(s): TG Capital Playbook.txt
Description: "Trident Pattern" -- stacked EMA trend alignment (5/9/13/21/200) + a Fair Value
    Gap + doji wick into the FVG's midpoint + confirmation candle, traded during the London
    Kill Zone.

    Interpretive assumptions:
    - Stacked EMAs approximated with ema_8/ema_21/ema_50/ema_200 (closest available periods to
      the document's 5/9/13/21/200 set) -- "clearly stacked" = strictly monotonic ordering.
    - FVG + doji-wick-into-midpoint approximated as: a 3-candle FVG forms, then a subsequent
      candle wicks into the FVG's midpoint without closing through it (a doji-like rejection),
      then a confirmation candle closes back in the trend direction.
    - Session filter (London Kill Zone, 3:00-6:30 AM NY) is a context filter the document
      itself applies on top of the pattern; NOT baked into this function's own logic so it stays
      composable with strategies.apply_session_filter, per this module's design choice (matches
      how other session-flavored strategies in this library keep session filtering external
      unless the session IS the entire trigger, e.g. Asian-range strategies).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_tg_capital_trident_fvg(
    enriched: pd.DataFrame,
    fvg_lookback: int = 15,
) -> pd.Series:
    """Trident Pattern -- stacked-EMA trend + FVG doji-wick + confirmation (TG Capital concept).

    See module docstring for full source attribution and interpretive assumptions.
    """
    high, low, close, open_ = enriched["high"], enriched["low"], enriched["close"], enriched["open"]
    ema_8, ema_21, ema_50, ema_200 = enriched["ema_8"], enriched["ema_21"], enriched["ema_50"], enriched["ema_200"]

    stacked_bull = (ema_8 > ema_21) & (ema_21 > ema_50) & (ema_50 > ema_200)
    stacked_bear = (ema_8 < ema_21) & (ema_21 < ema_50) & (ema_50 < ema_200)

    bull_fvg = low > high.shift(2)
    bear_fvg = high < low.shift(2)
    fvg_mid_bull = (low + high.shift(2)) / 2.0
    fvg_mid_bear = (high + low.shift(2)) / 2.0

    recent_bull_fvg = bull_fvg.shift(1).rolling(fvg_lookback, min_periods=1).max().fillna(0).astype(bool)
    recent_bear_fvg = bear_fvg.shift(1).rolling(fvg_lookback, min_periods=1).max().fillna(0).astype(bool)
    recent_bull_mid = fvg_mid_bull.where(bull_fvg).ffill()
    recent_bear_mid = fvg_mid_bear.where(bear_fvg).ffill()

    # Doji-wick-into-midpoint: wicked to/through the midpoint but closed on the trend side of it.
    wicked_into_bull_mid = (low <= recent_bull_mid) & (close > recent_bull_mid)
    wicked_into_bear_mid = (high >= recent_bear_mid) & (close < recent_bear_mid)

    # Confirmation candle: the NEXT bar closes further in the trend direction.
    confirm_long = (close > close.shift(1)) & (close > open_)
    confirm_short = (close < close.shift(1)) & (close < open_)

    entry_long = (stacked_bull & recent_bull_fvg & wicked_into_bull_mid.shift(1).fillna(False) & confirm_long).fillna(False)
    entry_short = (stacked_bear & recent_bear_fvg & wicked_into_bear_mid.shift(1).fillna(False) & confirm_short).fillna(False)

    exit_long = (~stacked_bull).fillna(False)
    exit_short = (~stacked_bear).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
