"""
Module: strategy_fxalexg_mtf_swing.py
Source document(s): FXAlexG Swing Trading Strategy (Step-by-Step Guide).txt
Description: Multi-timeframe trend alignment (weekly/daily/4h) + an area-of-interest S/R zone
+ a lower-timeframe confirmation pattern (engulfing or EMA rejection). Only one timeframe of
data is available per call, so the "weekly/daily/4h all agree" trend check is approximated with
a nested EMA/ADX-DI structure on the single series provided (a standard single-series MTF-trend
proxy). "Head & Shoulders" (one of three named confirmation patterns) is NOT implemented -- it
requires genuine multi-swing pattern recognition that cannot be done reliably/honestly from
OHLCV alone with the available columns; engulfing and EMA-rejection (the other two named
patterns) ARE implemented, so this is a real, working, non-placeholder signal, just narrower in
confirmation-pattern coverage than the source document.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_fxalexg_mtf_swing(
    enriched: pd.DataFrame,
    zone_lookback: int = 60,
    stability_bars: int = 15,
    stability_tol_atr: float = 0.75,
) -> pd.Series:
    """MTF-trend-aligned area-of-interest swing entry (engulfing / EMA-rejection confirmation).

    Source document: "FXAlexG Swing Trading Strategy (Step-by-Step Guide).txt". Rule: only
    trade with the trend when weekly/daily/4h all agree, at a marked area-of-interest S/R zone
    touched >=3 times, confirmed on a lower timeframe by Bullish/Bearish Engulfing, Head &
    Shoulders, or EMA Rejection, with 1:2 or 1:3 R:R.

    Interpretive assumptions:
    - Multi-timeframe alignment approximated on the single series provided: close vs ema_50 vs
      ema_200 nesting plus +DI/-DI direction stand in for "weekly/daily/4h all bullish/bearish".
    - "Area of interest touched >=3 times" approximated the same way as the Mamba FX strategy
      in this batch: a rolling S/R extreme that has not advanced in `stability_bars` bars
      (within `stability_tol_atr` x ATR), i.e. repeatedly capped/floored at roughly one level.
    - Confirmation = Bullish/Bearish Engulfing OR an EMA-21 rejection (see EMA REJECTION
      STRATEGY in this batch for the same rejection definition). Head & Shoulders is explicitly
      NOT implemented (see module docstring).
    """
    open_, high, low, close = enriched["open"], enriched["high"], enriched["low"], enriched["close"]
    ema21, ema50, ema200 = enriched["ema_21"], enriched["ema_50"], enriched["ema_200"]
    plus_di, minus_di, atr = enriched["plus_di"], enriched["minus_di"], enriched["atr"]

    trend_bull_mtf = (close > ema50) & (ema50 > ema200) & (plus_di > minus_di)
    trend_bear_mtf = (close < ema50) & (ema50 < ema200) & (minus_di > plus_di)

    prior_high = high.shift(1).rolling(zone_lookback).max()
    prior_high_earlier = high.shift(1 + stability_bars).rolling(zone_lookback).max()
    resistance_stable = ((prior_high - prior_high_earlier).abs() <= stability_tol_atr * atr).fillna(False)

    prior_low = low.shift(1).rolling(zone_lookback).min()
    prior_low_earlier = low.shift(1 + stability_bars).rolling(zone_lookback).min()
    support_stable = ((prior_low - prior_low_earlier).abs() <= stability_tol_atr * atr).fillna(False)

    near_support = ((low <= prior_low * 1.005) & support_stable).fillna(False)
    near_resistance = ((high >= prior_high * 0.995) & resistance_stable).fillna(False)

    bullish_engulfing = (close > open_) & (close.shift(1) < open_.shift(1)) & (close >= open_.shift(1)) & (open_ <= close.shift(1))
    bearish_engulfing = (close < open_) & (close.shift(1) > open_.shift(1)) & (close <= open_.shift(1)) & (open_ >= close.shift(1))

    ema_reject_up = (low <= ema21) & (close > ema21) & (close > open_)
    ema_reject_down = (high >= ema21) & (close < ema21) & (close < open_)

    confirm_long = (bullish_engulfing | ema_reject_up).fillna(False)
    confirm_short = (bearish_engulfing | ema_reject_down).fillna(False)

    entry_long = (trend_bull_mtf & near_support & confirm_long).fillna(False)
    entry_short = (trend_bear_mtf & near_resistance & confirm_short).fillna(False)

    exit_long = (~trend_bull_mtf).fillna(False)
    exit_short = (~trend_bear_mtf).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
