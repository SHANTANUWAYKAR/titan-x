"""
Module: strategy_umar_punjabi_orderblock_breakout.py
Source document(s): UMAR PUNJABI ORDERBLOCK STRATEGY.txt
Description: Order Block + breakout confirmation for Crypto/Forex. Identify a strong order
    block (the last opposite-colored candle before an aggressive momentum move), wait for price
    to revisit or break the range, enter on breakout confirmation in market-structure direction.

    Interpretive assumptions:
    - "Order Block" = the last down-candle immediately before an up-impulse (bullish OB), or
      the last up-candle immediately before a down-impulse (bearish OB) -- the standard SMC/ICT
      order-block definition.
    - "Impulse" = `impulse_bars` consecutive strong-bodied candles in one direction
      (body_ratio >= impulse_body_ratio).
    - "Price revisits or breaks the range" + "breakout confirmation" = price returns into the
      OB zone and then closes back out of it in the original impulse direction (a mitigation +
      continuation, not a fade).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_umar_punjabi_orderblock_breakout(
    enriched: pd.DataFrame,
    impulse_bars: int = 3,
    impulse_body_ratio: float = 0.55,
) -> pd.Series:
    """Order Block mitigation + continuation breakout (Umar Punjabi Order Block concept).

    See module docstring for full source attribution and interpretive assumptions.
    """
    high, low, close, open_ = enriched["high"], enriched["low"], enriched["close"], enriched["open"]

    body = (close - open_).abs()
    rng = (high - low).replace(0, np.nan)
    strong = (body / rng) >= impulse_body_ratio
    bullish, bearish = close > open_, close < open_

    bull_impulse_start = (bullish & strong).rolling(impulse_bars).sum() >= impulse_bars
    bear_impulse_start = (bearish & strong).rolling(impulse_bars).sum() >= impulse_bars

    # Order block = the down/up candle immediately preceding the impulse window.
    bull_ob_high = high.shift(impulse_bars).where(bull_impulse_start & bearish.shift(impulse_bars)).ffill()
    bull_ob_low = low.shift(impulse_bars).where(bull_impulse_start & bearish.shift(impulse_bars)).ffill()
    bear_ob_high = high.shift(impulse_bars).where(bear_impulse_start & bullish.shift(impulse_bars)).ffill()
    bear_ob_low = low.shift(impulse_bars).where(bear_impulse_start & bullish.shift(impulse_bars)).ffill()

    revisited_bull_ob = (low <= bull_ob_high) & (low >= bull_ob_low)
    revisited_bear_ob = (high >= bear_ob_low) & (high <= bear_ob_high)

    entry_long = (revisited_bull_ob.shift(1).fillna(False) & (close > bull_ob_high) & bullish).fillna(False)
    entry_short = (revisited_bear_ob.shift(1).fillna(False) & (close < bear_ob_low) & bearish).fillna(False)

    exit_long = (close < bull_ob_low).fillna(False)
    exit_short = (close > bear_ob_high).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
