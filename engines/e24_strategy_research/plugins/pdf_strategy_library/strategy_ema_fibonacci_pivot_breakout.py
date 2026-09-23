"""
Module: strategy_ema_fibonacci_pivot_breakout.py
Source document(s): EMA+Pivot Intraday Strategy.txt
Description: "EMA + Fibonacci Pivot Intraday Strategy" -- buy when a strong bullish candle with
above-average volume closes above BOTH the 9 EMA and the day's Fibonacci pivot point together;
mirrored for sells. The 9 EMA is approximated with ema_8; the Fibonacci pivot point (not a
platform column) is computed honestly from the platform's own OHLC/timestamp columns using the
standard formula PP = (prevHigh + prevLow + prevClose) / 3 on the previous trading day.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_ema_fibonacci_pivot_breakout(
    enriched: pd.DataFrame,
    body_ratio_threshold: float = 0.6,
    volume_ma_window: int = 20,
) -> pd.Series:
    """Strong candle cutting both the 9 EMA and the daily Fibonacci pivot together.

    Source document: "EMA+Pivot Intraday Strategy.txt". Rule: a strong bullish (bearish) candle
    with real momentum/volume crosses above (below) BOTH the 9 EMA and the Fibonacci Pivot
    Point at the same time -> buy (sell), min 1:2 R:R.

    Interpretive assumptions:
    - "9 EMA" approximated with `ema_8`.
    - "Fibonacci Pivot" (not a platform column) computed honestly from the platform's own
      OHLC: PP = (previous day's high + low + close) / 3, the standard pivot-point formula,
      with "previous day" = the previous UTC calendar date present in the data (same causal
      groupby-then-shift(1) approach as the PDH/PDL strategies elsewhere in this batch, so a
      day's pivot is entirely fixed before that day's own bars begin). Only the central pivot
      (PP) is used as "the" pivot line the document refers to price "cutting".
    - "Strong candle" = body >= `body_ratio_threshold` (default 60%) of the bar's high-low
      range, matching the interface spec's own example definition of "strong candle".
    - "Volume" confirmation = current volume above its own trailing `volume_ma_window`-bar
      average (computed from strictly prior bars).
    """
    open_, high, low, close, volume = enriched["open"], enriched["high"], enriched["low"], enriched["close"], enriched["volume"]
    ema9 = enriched["ema_8"]

    day = enriched["timestamp"].dt.date
    daily = pd.DataFrame({"high": high, "low": low, "close": close}).groupby(day).agg(
        d_high=("high", "max"), d_low=("low", "min"), d_close=("close", "last")
    )
    daily_prev = daily.shift(1)
    pp = day.map((daily_prev["d_high"] + daily_prev["d_low"] + daily_prev["d_close"]) / 3.0)

    rng = (high - low).replace(0, np.nan)
    body_ratio = (close - open_).abs() / rng

    vol_avg = volume.shift(1).rolling(volume_ma_window).mean()
    strong_volume = (volume > vol_avg).fillna(False)

    strong_bull = (close > open_) & (body_ratio >= body_ratio_threshold)
    strong_bear = (close < open_) & (body_ratio >= body_ratio_threshold)

    cuts_up = (close > ema9) & (close > pp) & ((close.shift(1) <= ema9.shift(1)) | (close.shift(1) <= pp.shift(1)))
    cuts_down = (close < ema9) & (close < pp) & ((close.shift(1) >= ema9.shift(1)) | (close.shift(1) >= pp.shift(1)))

    entry_long = (strong_bull & cuts_up & strong_volume).fillna(False)
    entry_short = (strong_bear & cuts_down & strong_volume).fillna(False)

    exit_long = ((close < ema9) | (close < pp)).fillna(False)
    exit_short = ((close > ema9) | (close > pp)).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
