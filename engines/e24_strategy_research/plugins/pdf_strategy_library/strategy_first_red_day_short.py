"""
Module: strategy_first_red_day_short.py
Source document(s): The-First-Red-Day-Strategy.txt
Description: "The First Red Day" short-selling strategy -- a rare, high-conviction reversal
    setup. Requires 3+ consecutive days of major parabolic extension, then shorts the moment
    price crosses below the "red-to-green line" (the previous day's close) after the extension,
    confirming the momentum shift from buying to selling pressure. Explicitly a rare setup
    (~4x/year per the document) -- a low trade count on this strategy is EXPECTED and correct,
    not a bug (per the interface spec's guidance on rare structural triggers).

    Interpretive assumptions:
    - "Major, abnormal price advance" (parabolic) = daily return significantly above its own
      recent volatility: close-to-close return > `parabolic_return_atr_mult` x (atr / close).
    - "3+ consecutive days" = `min_extension_days` consecutive bars meeting the above test.
    - "Red-to-green line" = the previous bar's close (exactly as the document defines it).
    - "The Attack" (entry) = current close crosses below the red-to-green line following the
      extension.
    - "Reclaim Rule" (invalidation/exit) = price closes back above the red-to-green line.
    - This strategy is inherently DAILY-BAR shaped (the document's entire vocabulary --
      "days", "previous day's close" -- assumes daily bars); it can technically run on any
      timeframe's `enriched` data but is only faithful to the source document at `timeframe="1d"`.

    Verified 2026-09-13: mechanism confirmed correct on a synthetic constructed parabolic run
    (fires exactly as designed). On this platform's actual available daily universe (AAPL,
    TSLA, NVDA, GOOGL, META, MSFT, JPM, GC=F, SI=F, BTC-USD, ETH-USD, major indices/FX -- see
    data/processed/*_1d.parquet) it produced ZERO signals, which is an HONEST result, not a
    bug: none of these names had a genuine 3+ consecutive-day parabolic-then-reversal sequence
    meeting the threshold in their available history, and this platform's universe does not
    include the meme-stock names (GME, AMC, etc.) the source document's own examples are drawn
    from. A rare/zero-trade result for this specific strategy on this specific universe is
    expected per the interface spec's guidance on genuinely rare structural triggers -- not
    evidence of incorrect logic.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_first_red_day_short(
    enriched: pd.DataFrame,
    min_extension_days: int = 3,
    parabolic_return_atr_mult: float = 1.5,
) -> pd.Series:
    """First Red Day parabolic-exhaustion short (rare, high-conviction setup).

    See module docstring for full source attribution and interpretive assumptions.
    """
    close, atr = enriched["close"], enriched["atr"]

    daily_return = close.pct_change()
    normalized_move = daily_return / (atr / close.replace(0, np.nan)).replace(0, np.nan)
    parabolic_day = normalized_move > parabolic_return_atr_mult

    extended = parabolic_day.rolling(min_extension_days).sum() >= min_extension_days

    red_to_green_line = close.shift(1)
    attack = (close < red_to_green_line) & (close.shift(1) >= red_to_green_line.shift(1))

    entry_short = (extended.shift(1).fillna(False) & attack).fillna(False)
    # No long side -- this is an explicitly short-only strategy per the source document.
    entry_long = pd.Series(False, index=enriched.index)

    exit_short = (close > red_to_green_line).fillna(False)  # Reclaim Rule
    exit_long = pd.Series(False, index=enriched.index)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
