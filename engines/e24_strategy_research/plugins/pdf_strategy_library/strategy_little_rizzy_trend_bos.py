"""
Module: strategy_little_rizzy_trend_bos.py
Source document(s): LITTLE RIZZY PRO STRATEGY.txt, LITTLE RIZZY TRADING STRATEGY.txt
Description: Both documents describe the identical "Little Rizzy" trend-following setup
(credited to Marci Silfrain) with only wording/detail differences -- consolidated into one
function per the interface spec's near-duplicate-consolidation rule (the "Pro" version
just adds more detail plus the optional Fibonacci step; mechanically they are the same
setup). Core idea: trade only with the trend (EMA alignment substitutes for the
document's hand-drawn trendline), wait for a break-of-structure / temporary trendline
breakdown, then enter on a strong confirmation candle back in the trend's direction,
optionally requiring the confirmation candle to sit in the 50%-61.8% Fibonacci
retracement zone of the recent swing.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_little_rizzy_trend_bos(
    enriched: pd.DataFrame,
    swing_lookback: int = 20,
    confirm_window: int = 5,
    body_ratio: float = 0.6,
    use_fib_filter: bool = False,
    fib_low: float = 0.5,
    fib_high: float = 0.618,
) -> pd.Series:
    """Little Rizzy trend + break-of-structure + confirmation-candle strategy.

    Consolidates: LITTLE RIZZY PRO STRATEGY.txt and LITTLE RIZZY TRADING STRATEGY.txt
    (same author/setup; the "Pro" version is just a more detailed writeup of the exact
    same mechanical rule plus the optional Fibonacci step already present in outline
    form in the shorter document).

    Rule (plain English): determine the trend, draw a trendline off two swing points,
    wait for that trendline to break (a "break of structure" / temporary breakdown),
    then enter only after a strong confirmation candle closes back in the trend's
    direction. Optionally require the 50%-61.8% Fibonacci retracement zone of the
    recent swing to line up with the confirmation candle for extra confidence.

    Mechanical translation of undrawable manual concepts:
    - "Trend": ema_50 > ema_200 = uptrend, ema_50 < ema_200 = downtrend (the document
      doesn't name a specific indicator; EMA alignment is the standard mechanical proxy
      for a "higher highs/higher lows" vs "lower highs/lower lows" regime).
    - "Trendline" support/resistance: approximated with a single rolling swing extreme,
      `low.shift(1).rolling(swing_lookback).min()` (support in an uptrend) and
      `high.shift(1).rolling(swing_lookback).max()` (resistance in a downtrend) -- a
      trailing rolling level rather than a hand-drawn diagonal line.
    - "Break of structure / temporary breakdown": price briefly trades through that
      rolling level (a shakeout) within the last `confirm_window` bars.
    - "Strong confirmation candle": body >= `body_ratio` (default 60%) of the candle's
      high-low range, closing in the trend direction, AND back on the correct side of
      the rolling level (reclaim) -- the reclaim is what actually confirms the
      breakdown was a fakeout/continuation rather than a real trend change.
    - Target ("previous Higher High" / "previous Lower Low"): the opposite rolling
      swing extreme, used here purely as an exit condition (not a sizing calculation).

    No lookahead: both rolling swing levels are computed on `.shift(1)`-ed price series
    (i.e. strictly bars before the current one); the "recent breakdown" check applies
    `.shift(1)` again before its own rolling window; the confirmation candle's body and
    reclaim checks use only the current bar's own OHLC, which is legitimate since that
    is the signal bar itself.
    """
    close = enriched["close"]
    open_ = enriched["open"]
    high = enriched["high"]
    low = enriched["low"]
    rng = (high - low).replace(0, np.nan)

    uptrend = enriched["ema_50"] > enriched["ema_200"]
    downtrend = enriched["ema_50"] < enriched["ema_200"]

    swing_low = low.shift(1).rolling(swing_lookback).min()
    swing_high = high.shift(1).rolling(swing_lookback).max()

    breakdown = low < swing_low
    breakout = high > swing_high
    breakdown_recent = (
        breakdown.shift(1, fill_value=False).rolling(confirm_window).max().fillna(0).astype(bool)
    )
    breakout_recent = (
        breakout.shift(1, fill_value=False).rolling(confirm_window).max().fillna(0).astype(bool)
    )

    body = close - open_
    strong_bull = (body > 0) & (body >= body_ratio * rng)
    strong_bear = (body < 0) & (-body >= body_ratio * rng)

    reclaim_up = close > swing_low
    reclaim_down = close < swing_high

    entry_long = uptrend & breakdown_recent & strong_bull & reclaim_up
    entry_short = downtrend & breakout_recent & strong_bear & reclaim_down

    if use_fib_filter:
        impulse = swing_high - swing_low

        fib_zone_lo_long = swing_high - fib_high * impulse
        fib_zone_hi_long = swing_high - fib_low * impulse
        in_fib_long = (low <= fib_zone_hi_long) & (low >= fib_zone_lo_long)

        fib_zone_lo_short = swing_low + fib_low * impulse
        fib_zone_hi_short = swing_low + fib_high * impulse
        in_fib_short = (high >= fib_zone_lo_short) & (high <= fib_zone_hi_short)

        entry_long = entry_long & in_fib_long
        entry_short = entry_short & in_fib_short

    exit_long = close >= swing_high
    exit_short = close <= swing_low

    return _stateful_from_entries_exits(
        entry_long.fillna(False),
        exit_long.fillna(False),
        entry_short.fillna(False),
        exit_short.fillna(False),
    )
