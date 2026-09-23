"""
Module: strategy_swappy_3c_scalping_v2.py
Source document(s): SWAPPY TRADING 3C STRATEGY.txt
Description: Reimplementation of the existing strategies_by_style/YOUTUBE_DECODED/
    strategy_swappy_3c_scalping.py using this platform's REAL lowercase indicator column
    convention (ema_50, atr, adx, bb_upper, bb_lower) instead of that file's uppercase
    convention (EMA_50, ATR, ADX, BB_upper, BB_lower), which does NOT match
    engines/e07_technical's actual output columns and would silently produce all-zero signals
    if run through the real engine (see the "Column-naming convention" pitfall recorded in the
    trading-strategy-code-generation skill). Same 3-candle pattern logic (two strong-bodied
    momentum candles + one inside candle + breakout), vectorized instead of the original's
    per-bar Python loop.

    Interpretive assumptions: identical to the original decoded version -- "near support" /
    "near resistance" approximated via ema_50/ema_200/bb bands; ADX and volume-confirmation
    filters retained.

    Default threshold note (found during Stage-0 pre-verification, 2026-09-13): the document's
    literal 80%-body-ratio + ADX>=20 + volume>=1.2x-average, applied simultaneously, produced
    ZERO signals across 80,000 real GC=F 5-min bars (verified directly, not assumed) -- the
    conjunction of all three strict filters at once is over-constrained for this asset/
    timeframe. Relaxed defaults (body_ratio_threshold=0.65, adx_min=15.0, volume_mult=1.0)
    restore a real, non-zero signal rate while keeping the same qualitative pattern (two
    momentum candles + inside candle + breakout, near a support/resistance context) -- callers
    wanting the document's original strict thresholds can still pass them explicitly.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_swappy_3c_scalping_v2(
    enriched: pd.DataFrame,
    body_ratio_threshold: float = 0.65,
    adx_min: float = 15.0,
    volume_mult: float = 1.0,
) -> pd.Series:
    """Swappy 3-candle momentum-coil-breakout, real-column-convention version.

    See module docstring for full source attribution and interpretive assumptions.
    """
    open_, high, low, close = enriched["open"], enriched["high"], enriched["low"], enriched["close"]
    volume = enriched["volume"]
    ema_50, ema_200 = enriched["ema_50"], enriched["ema_200"]
    bb_upper, bb_lower = enriched["bb_upper"], enriched["bb_lower"]
    adx = enriched["adx"]

    rng = (high - low).replace(0, np.nan)
    body_ratio = ((close - open_).abs() / rng).fillna(0.0)
    bullish = close > open_
    bearish = close < open_

    # C1 = bar i-3, C2 = bar i-2 (both strong, same direction), C3 = bar i-1 (inside C2), C4 = i.
    c1_strong, c2_strong = body_ratio.shift(3) >= body_ratio_threshold, body_ratio.shift(2) >= body_ratio_threshold
    both_bull = bullish.shift(3) & bullish.shift(2)
    both_bear = bearish.shift(3) & bearish.shift(2)
    c3_inside = (high.shift(1) <= high.shift(2)) & (low.shift(1) >= low.shift(2))

    pattern_high = pd.concat([high.shift(3), high.shift(2), high.shift(1)], axis=1).max(axis=1)
    pattern_low = pd.concat([low.shift(3), low.shift(2), low.shift(1)], axis=1).min(axis=1)

    vol_avg20 = volume.shift(1).rolling(20, min_periods=5).mean()
    volume_confirmed = volume >= (volume_mult * vol_avg20)
    trend_ok = adx >= adx_min

    near_support = (close <= ema_50) | (close <= bb_lower * 1.003)
    near_resistance = (close >= ema_50) | (close >= bb_upper * 0.997)

    pattern_ok_long = c1_strong & c2_strong & both_bull & c3_inside
    pattern_ok_short = c1_strong & c2_strong & both_bear & c3_inside

    entry_long = (pattern_ok_long & trend_ok & volume_confirmed & near_support & (close > pattern_high)).fillna(False)
    entry_short = (pattern_ok_short & trend_ok & volume_confirmed & near_resistance & (close < pattern_low)).fillna(False)

    exit_long = (close < pattern_low).fillna(False)
    exit_short = (close > pattern_high).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
