"""
Module: strategy_trading_geek_gold_supply_demand.py
Source document(s): THE TRADING GEEK STRATEGY.txt
Description: Gold (XAUUSD) supply/demand zone strategy -- mark the origin of aggressive
    multi-candle buying/selling moves as demand/supply zones, wait for price to retest the
    zone, confirm with an 8-EMA-based momentum candle before entering.

    Interpretive assumptions:
    - "Aggressive move" (multiple strong same-direction candles) = `impulse_bars` consecutive
      candles closing in the same direction with body_ratio >= impulse_body_ratio.
    - Zone = the origin candle's range immediately before that impulse sequence began.
    - "Candles closing above/below 8 EMA" confirmation = close vs ema_8 crossing in the trade
      direction at the retest.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_trading_geek_gold_supply_demand(
    enriched: pd.DataFrame,
    impulse_bars: int = 3,
    impulse_body_ratio: float = 0.5,
    zone_lookback: int = 40,
) -> pd.Series:
    """Gold supply/demand zone retest + 8-EMA confirmation (The Trading Geek concept).

    See module docstring for full source attribution and interpretive assumptions.
    """
    high, low, close, open_ = enriched["high"], enriched["low"], enriched["close"], enriched["open"]
    ema_8 = enriched["ema_8"]

    body = (close - open_).abs()
    rng = (high - low).replace(0, np.nan)
    strong = (body / rng) >= impulse_body_ratio
    bullish, bearish = close > open_, close < open_

    bull_impulse = (bullish & strong).rolling(impulse_bars).sum() >= impulse_bars
    bear_impulse = (bearish & strong).rolling(impulse_bars).sum() >= impulse_bars

    # Demand zone = the low just before a fresh bullish impulse sequence started.
    demand_zone = low.shift(impulse_bars).where(bull_impulse & ~bull_impulse.shift(1).fillna(False)).ffill()
    supply_zone = high.shift(impulse_bars).where(bear_impulse & ~bear_impulse.shift(1).fillna(False)).ffill()

    atr = enriched["atr"]
    retest_demand = (close - demand_zone).abs() <= atr
    retest_supply = (supply_zone - close).abs() <= atr

    confirm_long = (close > ema_8) & (close.shift(1) <= ema_8.shift(1))
    confirm_short = (close < ema_8) & (close.shift(1) >= ema_8.shift(1))

    entry_long = (retest_demand & confirm_long).fillna(False)
    entry_short = (retest_supply & confirm_short).fillna(False)

    exit_long = (close < demand_zone).fillna(False)
    exit_short = (close > supply_zone).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
