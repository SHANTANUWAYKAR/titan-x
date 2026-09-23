"""
Module: strategy_9_15ema_mayankraj_sr_rejection.py
Source document(s): 9 15EMA MAYANKRAJ STRATEGY.txt
Description: Support/resistance rejection strategy that uses the 9/15 EMA pair as a
confluence/trend-context filter rather than a crossover trigger -- genuinely different
mechanics from the other "9/15 EMA" documents in this batch (which are crossover+retest
systems), so it is kept as its own function rather than consolidated with them. Sell at
resistance with a bearish rejection near the EMA; buy at support with a bullish rejection near
the EMA. Document specifies 9 EMA / 15 EMA; approximated with ema_8 / ema_21 respectively
(documented, see module docstring convention used across this batch).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_9_15ema_mayankraj_sr_rejection(
    enriched: pd.DataFrame,
    sr_lookback: int = 20,
    proximity_atr: float = 0.5,
    rejection_wick_ratio: float = 0.4,
    require_trend_alignment: bool = False,
) -> pd.Series:
    """S/R rejection near the 9/15 EMA (9 15EMA MAYANKRAJ STRATEGY.txt).

    Source rule (plain English): identify the trend (15m chart), mark support/resistance (5m
    chart), then SELL when price reaches resistance and shows a rejection near the EMA, or BUY
    when price reaches support and shows a rejection near the EMA. Target = the next
    support/resistance level (out of scope, this function only produces direction); stop beyond
    support/resistance.

    Interpretive assumptions:
      - "9 EMA"/"15 EMA" -> `ema_8`/`ema_21` (documented batch-wide convention).
      - Only one timeframe of data is available per call; the doc's "identify trend on 15m,
        mark S/R on 5m" two-timeframe process is approximated on the single timeframe provided.
      - Support/resistance = a rolling `sr_lookback`-bar high/low, fixed with `.shift(1)` before
        comparison against the current bar so the level can never include the current bar.
        "Reaches" resistance/support = close within `proximity_atr` ATR of that level.
      - "Rejection near the EMA" = a same-direction rejection candle (body closes back beyond
        `rejection_wick_ratio` of the range from the S/R-side wick) whose range also touches
        `ema_8`.
      - The source doc's "identify trend" step is not stated as a hard direction filter (sell
        setups are not explicitly restricted to downtrends only) -- implemented as an OPTIONAL
        filter (`require_trend_alignment`, default off) rather than silently assumed on, since
        the text doesn't make the restriction explicit.
      - Exit: EMA trend flip (`ema_8` crosses back through `ema_21`), approximating "target
        reached" without hardcoding a specific price distance.

    Returns:
        pd.Series[int] in {-1, 0, 1}, same index as `enriched`.
    """
    open_ = enriched["open"]; high = enriched["high"]; low = enriched["low"]; close = enriched["close"]
    atr = enriched["atr"].replace(0, np.nan)
    ema_fast = enriched["ema_8"]; ema_slow = enriched["ema_21"]

    resistance = high.shift(1).rolling(sr_lookback).max()
    support = low.shift(1).rolling(sr_lookback).min()
    near_resistance = close >= (resistance - proximity_atr * atr)
    near_support = close <= (support + proximity_atr * atr)

    rng = (high - low).replace(0, np.nan)
    bearish_rejection = (close < open_) & ((high - pd.concat([open_, close], axis=1).max(axis=1)) >= rejection_wick_ratio * rng)
    bullish_rejection = (close > open_) & ((pd.concat([open_, close], axis=1).min(axis=1) - low) >= rejection_wick_ratio * rng)

    ema_touch = (low <= ema_fast) & (high >= ema_fast)

    entry_short = near_resistance & bearish_rejection & ema_touch
    entry_long = near_support & bullish_rejection & ema_touch

    if require_trend_alignment:
        entry_short = entry_short & (ema_fast <= ema_slow)
        entry_long = entry_long & (ema_fast >= ema_slow)

    entry_short = entry_short.fillna(False)
    entry_long = entry_long.fillna(False)

    cross_up = (ema_fast.shift(1) <= ema_slow.shift(1)) & (ema_fast > ema_slow)
    cross_down = (ema_fast.shift(1) >= ema_slow.shift(1)) & (ema_fast < ema_slow)
    exit_short = cross_up.fillna(False)
    exit_long = cross_down.fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
