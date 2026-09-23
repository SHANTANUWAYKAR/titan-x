"""
Module: strategy_photon_smc_supply_demand.py
Source document(s): PHOTON TRADING STRATEGY.txt (Matt Donlevey, Hinglish guide)
Description: Smart Money supply/demand zone strategy -- identify HTF trend (HH/HL vs LH/LL),
    find a liquidity sweep of equal highs/lows or a swing extreme, mark the supply/demand zone
    the sweep originated from, wait for price to pull back into that zone, enter on confirmation.

    Interpretive assumptions:
    - HTF trend: ema_50 vs ema_200.
    - "Liquidity sweep" = price breaks a recent swing high/low by a small margin then closes
      back inside (a standard sweep-and-reject signature).
    - "Supply/demand zone origin" = the last strong-momentum candle (body_ratio >=
      zone_body_ratio) immediately preceding the sweep's opposite-direction move.
    - "Confirmation" = price returns to within `zone_atr_mult` ATR of that origin candle's body
      and closes in the trend direction.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_photon_smc_supply_demand(
    enriched: pd.DataFrame,
    swing_lookback: int = 20,
    zone_body_ratio: float = 0.6,
    zone_atr_mult: float = 0.75,
) -> pd.Series:
    """Smart-money supply/demand zone retest strategy (Photon Trading / Matt Donlevey concept).

    See module docstring for full source attribution and interpretive assumptions.
    """
    high, low, close, open_ = enriched["high"], enriched["low"], enriched["close"], enriched["open"]
    ema_50, ema_200, atr = enriched["ema_50"], enriched["ema_200"], enriched["atr"]

    uptrend = ema_50 > ema_200
    downtrend = ema_50 < ema_200

    swing_high = high.shift(1).rolling(swing_lookback).max()
    swing_low = low.shift(1).rolling(swing_lookback).min()

    swept_high = (high > swing_high) & (close < swing_high)   # sweep + close-back-inside
    swept_low = (low < swing_low) & (close > swing_low)

    body = (close - open_).abs()
    rng = (high - low).replace(0, np.nan)
    strong_candle = (body / rng) >= zone_body_ratio

    # Demand zone origin: last strong bullish candle before an upside sweep-and-reject
    # (i.e. the impulse that created the level worth defending on a pullback).
    demand_origin_close = close.where(strong_candle & (close > open_)).ffill()
    supply_origin_close = close.where(strong_candle & (close < open_)).ffill()

    near_demand = (close - demand_origin_close).abs() <= (atr * zone_atr_mult)
    near_supply = (close - supply_origin_close).abs() <= (atr * zone_atr_mult)

    entry_long = (swept_low.shift(1).fillna(False) & near_demand & uptrend & (close > open_)).fillna(False)
    entry_short = (swept_high.shift(1).fillna(False) & near_supply & downtrend & (close < open_)).fillna(False)

    exit_long = (downtrend | (close < swing_low)).fillna(False)
    exit_short = (uptrend | (close > swing_high)).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
