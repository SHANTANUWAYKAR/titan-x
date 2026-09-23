"""
Module: strategy_tom_vorwald_pbd_method.py
Source document(s): TOM VORWALD TRADING STRATEGY.txt
Description: Tom Vorwald's "PBD Method" classifies the market into D (balanced/range), P (buyer
dominance) or B (seller dominance) shapes and trades accordingly (range in D, follow buyers in P,
follow sellers in B). Approximated mechanically: trend strength/direction via ADX + plus_di/
minus_di distinguishes P/B from D; D-shape (low ADX) is traded as a Bollinger Band mean-reversion
range-fade since the document gives no explicit range-trade mechanics.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_tom_vorwald_pbd_method(
    enriched: pd.DataFrame,
    adx_trend_threshold: float = 25.0,
) -> pd.Series:
    """PBD Method: D=range, P=follow buyers, B=follow sellers (Tom Vorwald, TOM VORWALD TRADING
    STRATEGY.txt).

    Source document rule: classify the market profile shape --
      D-shape (balanced): buyers/sellers roughly equal -> range trade.
      P-shape (buyer dominance): follow buyers, look long.
      B-shape (seller dominance): follow sellers, look short.
    No mechanical definition of "balanced" vs "dominant" is given in the source document.

    Approximation: ADX measures trend strength (balanced vs imbalanced) and plus_di/minus_di
    measure which side is dominant -- exactly what this document describes in words, so:
      adx > adx_trend_threshold & plus_di > minus_di  => P-shape (buyer dominance) -> long bias
      adx > adx_trend_threshold & minus_di > plus_di  => B-shape (seller dominance) -> short bias
      adx <= adx_trend_threshold                      => D-shape (balanced) -> range-fade using
        Bollinger Bands (buy at bb_lower, sell at bb_upper) since the document does not specify
        a concrete range-trading mechanic and Bollinger Bands are the closest available proxy
        for "range extremes." adx_trend_threshold defaults to 25, matching this platform's own
        documented "strong trend = ADX > 25" convention.

    Entry (long): P-shape trend entry (close breaks above the prior bar's high while in a fresh
    P-shape), OR D-shape range-buy (close <= bb_lower while in D-shape). Entry (short) is the
    mirror image. Exit: for a P-shape trend long, exit only when the shape flips to B (bearish
    dominance) -- NOT on a simple bb_middle touch, since that would prematurely exit a healthy
    uptrend; for a D-shape range long, exit at bb_middle (target reached) or if the shape flips
    to B. Mirror logic for shorts.
    """
    close = enriched["close"]
    high = enriched["high"]
    low = enriched["low"]
    adx = enriched["adx"]
    plus_di = enriched["plus_di"]
    minus_di = enriched["minus_di"]
    bb_upper = enriched["bb_upper"]
    bb_lower = enriched["bb_lower"]
    bb_middle = enriched["bb_middle"]

    trending = adx > adx_trend_threshold
    p_shape = trending & (plus_di > minus_di)
    b_shape = trending & (minus_di > plus_di)
    d_shape = ~trending

    prior_high = high.shift(1)
    prior_low = low.shift(1)

    p_trend_entry_long = p_shape & (close > prior_high)
    b_trend_entry_short = b_shape & (close < prior_low)

    d_range_entry_long = d_shape & (close <= bb_lower)
    d_range_entry_short = d_shape & (close >= bb_upper)

    entry_long = p_trend_entry_long | d_range_entry_long
    entry_short = b_trend_entry_short | d_range_entry_short

    exit_long = b_shape | (d_shape & (close >= bb_middle))
    exit_short = p_shape | (d_shape & (close <= bb_middle))

    entry_long = entry_long.fillna(False)
    entry_short = entry_short.fillna(False)
    exit_long = exit_long.fillna(False)
    exit_short = exit_short.fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
