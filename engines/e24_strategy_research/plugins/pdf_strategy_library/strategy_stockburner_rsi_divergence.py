"""
Module: strategy_stockburner_rsi_divergence.py
Source document(s): STOCKBURNER RSI DIVERGENCE STRATEGY.txt
Description: RSI Divergence reversal at support/resistance. Bearish divergence (price Higher
    High, RSI Lower High) near resistance -> sell after a confirmation candle. Bullish
    divergence (price Lower Low, RSI Higher Low) near support -> buy after confirmation.

    Interpretive assumptions:
    - "Higher High / Lower Low" for both price and RSI detected via local pivot comparison over
      `pivot_lookback` bars (a swing high/low that exceeds the PRIOR swing high/low of the same
      type, both confirmed with a `confirm_bars` right-side lag so the pivot is real, not a
      lookahead-guessed one).
    - "Near support/resistance" = within `zone_atr_mult` ATR of a rolling swing extreme.
    - "Confirmation candle" = a candle closing back in the reversal direction immediately after
      the divergence is confirmed.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def _confirmed_pivots(series: pd.Series, lookback: int, confirm_bars: int, kind: str) -> pd.Series:
    """A causal pivot-high/low detector: bar i-confirm_bars is a pivot if it's the
    max/min over the window [i-confirm_bars-lookback, i] -- confirmed only once `confirm_bars`
    bars have passed since it, so no lookahead into bars not yet closed at evaluation time."""
    roll = series.rolling(lookback + confirm_bars + 1)
    if kind == "high":
        is_pivot = series.shift(confirm_bars) == roll.max()
    else:
        is_pivot = series.shift(confirm_bars) == roll.min()
    return is_pivot.fillna(False)


def strategy_stockburner_rsi_divergence(
    enriched: pd.DataFrame,
    pivot_lookback: int = 10,
    confirm_bars: int = 3,
    zone_atr_mult: float = 0.75,
) -> pd.Series:
    """RSI price-divergence reversal at S/R (Stockburner concept).

    See module docstring for full source attribution and interpretive assumptions.
    """
    high, low, close = enriched["high"], enriched["low"], enriched["close"]
    rsi, atr = enriched["rsi"], enriched["atr"]

    price_high_pivot = _confirmed_pivots(high, pivot_lookback, confirm_bars, "high")
    price_low_pivot = _confirmed_pivots(low, pivot_lookback, confirm_bars, "low")

    # Value of price/RSI at the confirmed pivot bar, forward-filled to "most recent pivot".
    pivot_price_high = high.shift(confirm_bars).where(price_high_pivot).ffill()
    pivot_rsi_high = rsi.shift(confirm_bars).where(price_high_pivot).ffill()
    prior_pivot_price_high = pivot_price_high.where(price_high_pivot).shift(1).ffill()
    prior_pivot_rsi_high = pivot_rsi_high.where(price_high_pivot).shift(1).ffill()

    pivot_price_low = low.shift(confirm_bars).where(price_low_pivot).ffill()
    pivot_rsi_low = rsi.shift(confirm_bars).where(price_low_pivot).ffill()
    prior_pivot_price_low = pivot_price_low.where(price_low_pivot).shift(1).ffill()
    prior_pivot_rsi_low = pivot_rsi_low.where(price_low_pivot).shift(1).ffill()

    bearish_divergence = (price_high_pivot & (pivot_price_high > prior_pivot_price_high) & (pivot_rsi_high < prior_pivot_rsi_high)).fillna(False)
    bullish_divergence = (price_low_pivot & (pivot_price_low < prior_pivot_price_low) & (pivot_rsi_low > prior_pivot_rsi_low)).fillna(False)

    resistance = high.shift(1).rolling(pivot_lookback * 2).max()
    support = low.shift(1).rolling(pivot_lookback * 2).min()
    near_resistance = (resistance - close).abs() <= (atr * zone_atr_mult)
    near_support = (close - support).abs() <= (atr * zone_atr_mult)

    div_signal_short = bearish_divergence.rolling(confirm_bars + 2, min_periods=1).max().fillna(0).astype(bool)
    div_signal_long = bullish_divergence.rolling(confirm_bars + 2, min_periods=1).max().fillna(0).astype(bool)

    entry_short = (div_signal_short.shift(1).fillna(False) & near_resistance & (close < close.shift(1))).fillna(False)
    entry_long = (div_signal_long.shift(1).fillna(False) & near_support & (close > close.shift(1))).fillna(False)

    exit_long = (close < support).fillna(False)
    exit_short = (close > resistance).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
