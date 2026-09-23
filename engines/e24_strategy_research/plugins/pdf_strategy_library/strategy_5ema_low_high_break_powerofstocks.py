"""
Module: strategy_5ema_low_high_break_powerofstocks.py
Source document(s): 5EMA TRADING STRATEGY POWEROFSTOCKS.txt
Description: Classic "5 EMA" reversal-trigger strategy: find the most recent candle whose low
never touched the 5 EMA (a "signal candle"); once a later candle closes below that signal
candle's low, sell. Mirror logic for buys (signal candle's high never touches the EMA; a later
close above that high triggers a buy). Document specifies a 5 EMA; approximated with ema_8, the
closest available period, documented explicitly per interface-spec rule 3.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_5ema_low_high_break_powerofstocks(enriched: pd.DataFrame) -> pd.Series:
    """5 EMA signal-candle low/high break reversal trigger (5EMA TRADING STRATEGY
    POWEROFSTOCKS.txt).

    Source rule (15m chart): find a candle whose LOW does not touch the 5 EMA (it stayed fully
    above the EMA). Wait for a later candle to break that candle's low -> SELL. Mirror rule for
    buys: a candle whose HIGH does not touch the 5 EMA (stayed fully below it); a later candle
    breaking that high -> BUY. Target >=1:2 R:R (extendable to 1:3).

    Interpretive assumptions:
      - "5 EMA" -> ema_8 (closest available period).
      - "Break" = candle CLOSE beyond the signal candle's level (this project's standard
        resolution for ambiguous "break of" language), not merely an intrabar wick touch.
      - The reference level is always the MOST RECENT qualifying signal candle: as soon as a
        newer candle also doesn't touch the EMA, it replaces the older reference (implemented
        with `.shift(1)` so the reference level used at bar i is always fixed using only data
        up to bar i-1).
      - Exit: price closes back through ema_8 (mean-reversion back through the EMA invalidates
        the breakdown/breakout thesis).

    Returns:
        pd.Series[int] in {-1, 0, 1}, same index as `enriched`.
    """
    close = enriched["close"]; low = enriched["low"]; high = enriched["high"]
    ema = enriched["ema_8"]

    # candle whose low stayed fully above ema_8 (didn't touch it) -> sell-side signal candle
    sell_signal_candle_low = low.where(low > ema)
    # candle whose high stayed fully below ema_8 (didn't touch it) -> buy-side signal candle
    buy_signal_candle_high = high.where(high < ema)

    # most recent qualifying reference level, known only as of the PRIOR bar
    ref_low_for_sell = sell_signal_candle_low.ffill().shift(1)
    ref_high_for_buy = buy_signal_candle_high.ffill().shift(1)

    entry_short = (close < ref_low_for_sell).fillna(False)
    entry_long = (close > ref_high_for_buy).fillna(False)

    exit_long = (close < ema).fillna(False)
    exit_short = (close > ema).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
