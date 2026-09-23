"""
Module: strategy_thetraderoom_ema_crossover_pullback.py
Source document(s): THETRADEROOM EMA STRATEGY.txt
Description: EMA 9/15 crossover + pullback confirmation. Wait for a strong crossover
    (approximated as a genuine EMA-9-over-EMA-15 cross, with the crossing SLOPE serving as the
    "angle > 30 degrees" momentum-strength proxy since raw pixel angle isn't computable from
    OHLCV alone), then wait for price to pull back near the fast EMA, entering on a bullish/
    bearish confirmation candle at that pullback.

    Interpretive assumptions:
    - EMA 9/15 approximated with ema_8/ema_21 (closest available periods).
    - "Crossover angle > 30 degrees" approximated as the EMA spread's rate of change exceeding
      `slope_atr_mult` x ATR over `slope_lookback` bars right after the cross (strong,
      decisive separation, not a shallow/grinding cross).
    - "Pullback near EMA 9" = price returns to within `pullback_atr_mult` ATR of ema_8.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_thetraderoom_ema_crossover_pullback(
    enriched: pd.DataFrame,
    slope_lookback: int = 3,
    slope_atr_mult: float = 0.5,
    pullback_atr_mult: float = 0.4,
    max_pullback_wait: int = 10,
) -> pd.Series:
    """EMA 9/15 crossover + pullback confirmation entry (TheTradeRoom concept).

    See module docstring for full source attribution and interpretive assumptions.
    """
    close, ema_8, ema_21 = enriched["close"], enriched["ema_8"], enriched["ema_21"]
    atr = enriched["atr"]

    cross_up = (ema_8 > ema_21) & (ema_8.shift(1) <= ema_21.shift(1))
    cross_down = (ema_8 < ema_21) & (ema_8.shift(1) >= ema_21.shift(1))

    spread = ema_8 - ema_21
    slope = spread - spread.shift(slope_lookback)
    strong_up_cross = cross_up & (slope > (atr * slope_atr_mult))
    strong_down_cross = cross_down & (slope < -(atr * slope_atr_mult))

    strong_up_recent = strong_up_cross.shift(1).rolling(max_pullback_wait, min_periods=1).max().fillna(0).astype(bool)
    strong_down_recent = strong_down_cross.shift(1).rolling(max_pullback_wait, min_periods=1).max().fillna(0).astype(bool)

    near_ema8 = (close - ema_8).abs() <= (atr * pullback_atr_mult)
    bull_confirm = (close > close.shift(1)) & (close > ema_8)
    bear_confirm = (close < close.shift(1)) & (close < ema_8)

    entry_long = (strong_up_recent & near_ema8 & bull_confirm).fillna(False)
    entry_short = (strong_down_recent & near_ema8 & bear_confirm).fillna(False)

    exit_long = (close < ema_21).fillna(False)
    exit_short = (close > ema_21).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
