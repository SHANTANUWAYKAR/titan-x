"""
Module: strategy_fabio_valentini_pullback_scalp.py
Source document(s): FABIO VALENTINI SCALPING STRATEGY.txt
Description: Trend-following pullback scalp -- confirm a strong trend, wait for a pullback into
a lower-volume area, then enter on the next strong momentum candle in the trend direction.
Trend strength/direction uses ADX + DI (a direct, real proxy for "higher highs/higher lows" /
"lower highs/lower lows" structure); the "low-volume area" pullback is approximated with the
platform's own `volume` column falling below its trailing average.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_fabio_valentini_pullback_scalp(
    enriched: pd.DataFrame,
    adx_trend_threshold: float = 25.0,
    body_ratio_threshold: float = 0.6,
    volume_ma_window: int = 20,
) -> pd.Series:
    """Trend pullback into a low-volume zone, then a strong momentum confirmation candle.

    Source document: "FABIO VALENTINI SCALPING STRATEGY.txt". Rule: identify a strong
    trending market, wait for a pullback into a low-volume area, then enter at the close of a
    strong confirmation candle in the trend direction, targeting 1:3 R:R.

    Interpretive assumptions:
    - "Strong bullish/bearish trend" (higher-highs/higher-lows or the reverse) approximated
      with ADX > `adx_trend_threshold` plus +DI/-DI direction, a direct causal trend-strength
      and direction read already available on the platform.
    - "Low-volume area" = a pullback bar (against the trend) whose volume is below its own
      trailing `volume_ma_window`-bar average.
    - "Strong momentum candle" = body >= `body_ratio_threshold` of the bar's range, in the
      trend direction.
    """
    open_, high, low, close, volume = enriched["open"], enriched["high"], enriched["low"], enriched["close"], enriched["volume"]
    adx, plus_di, minus_di = enriched["adx"], enriched["plus_di"], enriched["minus_di"]

    trend_up = (adx > adx_trend_threshold) & (plus_di > minus_di)
    trend_down = (adx > adx_trend_threshold) & (minus_di > plus_di)

    vol_avg = volume.shift(1).rolling(volume_ma_window).mean()
    low_volume = (volume < vol_avg).fillna(False)

    rng = (high - low).replace(0, np.nan)
    body_ratio = (close - open_).abs() / rng

    pullback_in_uptrend = trend_up & low_volume & (close < open_)
    pullback_in_downtrend = trend_down & low_volume & (close > open_)

    strong_bull_candle = (close > open_) & (body_ratio >= body_ratio_threshold)
    strong_bear_candle = (close < open_) & (body_ratio >= body_ratio_threshold)

    entry_long = (strong_bull_candle & pullback_in_uptrend.shift(1).fillna(False) & trend_up).fillna(False)
    entry_short = (strong_bear_candle & pullback_in_downtrend.shift(1).fillna(False) & trend_down).fillna(False)

    exit_long = (~trend_up).fillna(False)
    exit_short = (~trend_down).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
