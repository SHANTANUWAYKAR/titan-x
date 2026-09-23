"""
Module: strategy_915200_ema_trend_breakout.py
Source document(s): 9,15,200 EMA TRADING STRATEGY.txt
Description: Triple-EMA trend-alignment breakout ("21 Days 21 Trading Strategies - Day 3",
credited to Devansh Rai / DevanshRaiYT). Distinct from both the plain 200-EMA-only trend filter
group and the 9/15-EMA-only crossover group in this batch: this rule specifically requires the
9 EMA AND the 15 EMA to BOTH cross the 200 EMA together with momentum. Document specifies 9/15
EMA; approximated with ema_8/ema_21 (documented, batch-wide convention); ema_200 is an exact
match.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_915200_ema_trend_breakout(
    enriched: pd.DataFrame,
    sync_window: int = 3,
    momentum_lookback: int = 3,
    momentum_atr_mult: float = 0.5,
) -> pd.Series:
    """9 & 15 EMA both crossing the 200 EMA with momentum (9,15,200 EMA TRADING STRATEGY.txt).

    Source rule (plain English): price moves above the 200 EMA with strong momentum, AND the 9
    EMA and 15 EMA both cross above the 200 EMA -> enter long at the breakout candle's high,
    stop at its low, target >=1:2 R:R (sizing out of scope per interface-spec rule 7). Mirror
    rule for shorts (crossing below with momentum).

    Interpretive assumptions:
      - "9 EMA"/"15 EMA" -> `ema_8`/`ema_21`; `ema_200` is an exact match.
      - The two EMAs crossing "together" is approximated as both crossing within a
        `sync_window`-bar trailing window of each other, rather than requiring the exact same
        bar (which would rarely fire in practice).
      - "Strong momentum" = price change over `momentum_lookback` bars exceeds
        `momentum_atr_mult` * ATR, in the breakout direction.
      - Entry price ("high/low of the breakout candle") is an execution/fill detail for the
        platform's backtester, not the direction signal itself -- out of scope here.
      - Exit: close crosses back through the 200 EMA (trend filter invalidated).

    Returns:
        pd.Series[int] in {-1, 0, 1}, same index as `enriched`.
    """
    close = enriched["close"]
    atr = enriched["atr"].replace(0, np.nan)
    ema_fast = enriched["ema_8"]; ema_mid = enriched["ema_21"]; ema200 = enriched["ema_200"]

    cross_up_fast = (ema_fast.shift(1) <= ema200.shift(1)) & (ema_fast > ema200)
    cross_up_mid = (ema_mid.shift(1) <= ema200.shift(1)) & (ema_mid > ema200)
    cross_down_fast = (ema_fast.shift(1) >= ema200.shift(1)) & (ema_fast < ema200)
    cross_down_mid = (ema_mid.shift(1) >= ema200.shift(1)) & (ema_mid < ema200)

    both_crossed_up = (
        cross_up_fast.rolling(sync_window, min_periods=1).max().astype(bool)
        & cross_up_mid.rolling(sync_window, min_periods=1).max().astype(bool)
    )
    both_crossed_down = (
        cross_down_fast.rolling(sync_window, min_periods=1).max().astype(bool)
        & cross_down_mid.rolling(sync_window, min_periods=1).max().astype(bool)
    )

    strong_up = (close - close.shift(momentum_lookback)) > (momentum_atr_mult * atr)
    strong_down = (close.shift(momentum_lookback) - close) > (momentum_atr_mult * atr)

    entry_long = (
        both_crossed_up & strong_up & (close > ema200) & (ema_fast > ema200) & (ema_mid > ema200)
    ).fillna(False)
    entry_short = (
        both_crossed_down & strong_down & (close < ema200) & (ema_fast < ema200) & (ema_mid < ema200)
    ).fillna(False)

    exit_long = (close < ema200).fillna(False)
    exit_short = (close > ema200).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
