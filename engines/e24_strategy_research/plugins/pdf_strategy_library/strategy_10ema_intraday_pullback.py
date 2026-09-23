"""
Module: strategy_10ema_intraday_pullback.py
Source document(s): 10EMA INTRADAY STRATEGY.txt
Description: Intraday momentum-continuation setup: after a strong directional move, price
consolidates near the 10 EMA (small-range Doji/Inside candle), then a breakout of that
consolidation candle's high/low in the direction of the prior move triggers entry. Document
specifies a "10 EMA"; the platform only provides ema_8/ema_21/ema_50/ema_200, so ema_8 (the
closest available period) is used as an honest approximation and is stated here explicitly.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_10ema_intraday_pullback(
    enriched: pd.DataFrame,
    momentum_lookback: int = 10,
    momentum_threshold_atr: float = 1.5,
    proximity_atr: float = 0.5,
    consolidation_body_ratio: float = 0.35,
    arm_window: int = 8,
) -> pd.Series:
    """10 EMA intraday pullback-continuation breakout (10EMA INTRADAY STRATEGY.txt).

    Source rule (plain English): use a 5m/15m chart with the 10 EMA plotted. After a strong
    bullish (or bearish) move, wait for the market to consolidate near the 10 EMA with small
    candles (a Doji or Inside candle). Enter on the breakout of that consolidation candle's
    high (long) / low (short), stop at the nearest prior candle's low/high, target >=1:2 R:R.

    Implementation / interpretive assumptions:
      - "10 EMA" approximated with `ema_8`, the closest available EMA period (documented here
        per interface-spec rule 3).
      - "Strong up/down move" = price change over `momentum_lookback` bars exceeds
        `momentum_threshold_atr` * ATR.
      - "Consolidation near EMA" = |close - ema_8| <= proximity_atr * ATR.
      - "Doji or Inside candle" = body <= consolidation_body_ratio * range, OR the candle's
        high/low are both inside the prior candle's high/low (inside bar).
      - Entry triggers on breakout of the *prior* (consolidation) candle's high/low, so the
        breakout level is fixed with `.shift(1)` before comparison against the current bar.
      - Exit: close crosses back through ema_8 by > proximity_atr * ATR (pullback thesis
        invalidated), or the opposite entry condition fires (handled by the stateful helper).

    Args:
        enriched: platform OHLCV + indicator DataFrame (see interface spec for columns).
        momentum_lookback: bars used to measure the initiating strong move.
        momentum_threshold_atr: minimum move size (in ATRs) to qualify as "strong".
        proximity_atr: max distance from ema_8 (in ATRs) to count as "near the EMA".
        consolidation_body_ratio: max candle body / range ratio to count as Doji/Inside.
        arm_window: how many bars back a qualifying strong move stays "active" waiting for
            a consolidation + breakout to occur.

    Returns:
        pd.Series[int] in {-1, 0, 1}, same index as `enriched`.
    """
    close = enriched["close"]; open_ = enriched["open"]
    high = enriched["high"]; low = enriched["low"]
    atr = enriched["atr"].replace(0, np.nan)
    ema = enriched["ema_8"]

    strong_up = (close - close.shift(momentum_lookback)) > (momentum_threshold_atr * atr)
    strong_down = (close.shift(momentum_lookback) - close) > (momentum_threshold_atr * atr)
    # a strong move stays "armed" for arm_window bars while we wait for the pullback pattern
    armed_up = strong_up.shift(1).rolling(arm_window, min_periods=1).max().fillna(0).astype(bool)
    armed_down = strong_down.shift(1).rolling(arm_window, min_periods=1).max().fillna(0).astype(bool)

    body = (close - open_).abs()
    rng = (high - low).replace(0, np.nan)
    doji_or_inside = (body <= consolidation_body_ratio * rng) | (
        (high <= high.shift(1)) & (low >= low.shift(1))
    )
    near_ema = (close - ema).abs() <= (proximity_atr * atr)
    consolidation_candle = (doji_or_inside & near_ema).fillna(False)

    # breakout of the PRIOR (consolidation) candle's high/low -> level fixed before this bar
    prior_consol = consolidation_candle.shift(1).fillna(False)
    prior_high = high.shift(1)
    prior_low = low.shift(1)

    entry_long = (armed_up & prior_consol & (close > prior_high)).fillna(False)
    entry_short = (armed_down & prior_consol & (close < prior_low)).fillna(False)

    exit_long = (close < (ema - proximity_atr * atr)).fillna(False)
    exit_short = (close > (ema + proximity_atr * atr)).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
