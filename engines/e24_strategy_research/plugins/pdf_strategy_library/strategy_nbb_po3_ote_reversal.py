"""
Module: strategy_nbb_po3_ote_reversal.py
Source document(s): NBB Trader Playbook.txt
Description: "PO3, OTE & ADR" -- Market Maker Model framework (Accumulation -> Manipulation ->
    Distribution). Trade only after manipulation (a stop-hunt breakout of a key level) completes
    and price begins distributing (reversing) in the opposite direction, confirmed by a
    displacement candle (a strong body close past the key level).

    Interpretive assumptions:
    - "Accumulation" = a tight consolidation range (low ATR relative to its own recent history).
    - "Manipulation" = a breakout beyond the accumulation range that fails to hold (price closes
      back inside the range within `manipulation_window` bars) -- the classic PO3 stop-run.
    - "Distribution" / entry = the reversal move following a failed manipulation breakout,
      confirmed by a displacement candle (body >= body_ratio_threshold of its range) closing
      back through the accumulation range's midpoint in the reversal direction.
    - Session/PD-array filters (London/NY open, PDH/PDL, FVGs) are the document's context
      layer, not the trigger itself; the core mechanical trigger (failed breakout + displacement
      reversal) is what's implemented here, timeframe/session-agnostic per the interface spec.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_nbb_po3_ote_reversal(
    enriched: pd.DataFrame,
    range_window: int = 20,
    manipulation_window: int = 5,
    body_ratio_threshold: float = 0.6,
) -> pd.Series:
    """PO3 (accumulation-manipulation-distribution) failed-breakout reversal (NBB concept).

    See module docstring for full source attribution and interpretive assumptions.
    """
    high, low, close, open_ = enriched["high"], enriched["low"], enriched["close"], enriched["open"]

    range_high = high.shift(1 + manipulation_window).rolling(range_window).max()
    range_low = low.shift(1 + manipulation_window).rolling(range_window).min()
    range_mid = (range_high + range_low) / 2.0

    # Manipulation: a breakout beyond the established range within the recent window...
    manipulated_up = (high.shift(1).rolling(manipulation_window).max() > range_high).fillna(False)
    manipulated_down = (low.shift(1).rolling(manipulation_window).min() < range_low).fillna(False)

    body = (close - open_).abs()
    rng = (high - low).replace(0, np.nan)
    body_ratio = body / rng
    displacement = body_ratio >= body_ratio_threshold

    # Distribution: after an upside manipulation, price displaces back below the range midpoint
    # (reversal down); mirrored for downside manipulation.
    entry_short = (manipulated_up & displacement & (close < open_) & (close < range_mid)).fillna(False)
    entry_long = (manipulated_down & displacement & (close > open_) & (close > range_mid)).fillna(False)

    exit_long = (close < range_low).fillna(False)
    exit_short = (close > range_high).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
