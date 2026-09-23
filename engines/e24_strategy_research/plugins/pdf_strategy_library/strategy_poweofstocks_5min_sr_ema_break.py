"""
Module: strategy_poweofstocks_5min_sr_ema_break.py
Source document(s): POWEROFSTOCKS 5MIN STRATEGY.txt ("Powerofstocks Premium Crypto Strategy,
    5-Min Chart Setup")
Description: Same core 5-EMA signal-candle break mechanic as strategy_5ema_low_high_break_
    powerofstocks.py, but with an ADDED support/resistance zone filter that the original 5EMA
    document does not have (entries only near marked S/R, not anywhere) -- genuinely different
    from the plain 5EMA break per the interface spec (an added mandatory filter changes the
    rule's selectivity, not just cosmetic wording), so implemented as its own function rather
    than consolidated.

    Interpretive assumptions:
    - "Support/Resistance zones" = rolling swing extremes over `sr_lookback` bars.
    - "Price near Resistance/Support" = within `zone_atr_mult` ATR of that rolling extreme.
    - 5 EMA approximated with ema_8 (closest available period), same as the other 5EMA-based
      strategies in this library.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_poweofstocks_5min_sr_ema_break(
    enriched: pd.DataFrame,
    sr_lookback: int = 30,
    zone_atr_mult: float = 0.5,
) -> pd.Series:
    """5-EMA signal-candle break, filtered to S/R zones only (Powerofstocks 5-min crypto concept).

    See module docstring for full source attribution and interpretive assumptions.
    """
    high, low, close = enriched["high"], enriched["low"], enriched["close"]
    ema_8, atr = enriched["ema_8"], enriched["atr"]

    resistance = high.shift(1).rolling(sr_lookback).max()
    support = low.shift(1).rolling(sr_lookback).min()
    near_resistance = (resistance - close).abs() <= (atr * zone_atr_mult)
    near_support = (close - support).abs() <= (atr * zone_atr_mult)

    # Signal candle: high/low doesn't touch ema_8 -- weakness/strength signature.
    sell_signal_candle = low > ema_8
    buy_signal_candle = high < ema_8

    # Most recent such signal candle's extreme, forward-filled until broken.
    last_sell_signal_low = low.where(sell_signal_candle).ffill()
    last_buy_signal_high = high.where(buy_signal_candle).ffill()

    entry_short = (near_resistance & sell_signal_candle.shift(1).fillna(False) & (close < last_sell_signal_low.shift(1))).fillna(False)
    entry_long = (near_support & buy_signal_candle.shift(1).fillna(False) & (close > last_buy_signal_high.shift(1))).fillna(False)

    exit_long = (close < ema_8).fillna(False)
    exit_short = (close > ema_8).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
