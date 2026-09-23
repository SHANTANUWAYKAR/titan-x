"""
Module: strategy_trader_kane_po3_manipulation.py
Source document(s): Trader Kane Playbook.txt
Description: "SMT Divergence + PO3" -- Power of Three (Accumulation/Manipulation/Distribution)
reversal trading around a liquidity sweep back into the 50% level of the swept range. The SMT
divergence leg (a genuine two-instrument concept comparing NQ vs ES) cannot be computed from a
single-symbol `enriched` DataFrame and is honestly dropped/documented as out of scope; the PO3
sweep-and-revert-to-midpoint mechanic, which IS mechanically describable from one symbol's OHLC,
is implemented in full.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_trader_kane_po3_manipulation(
    enriched: pd.DataFrame,
    range_window: int = 20,
    session_filter: bool = True,
    session_start_utc_hour: int = 13,
    session_end_utc_hour: int = 16,
) -> pd.Series:
    """PO3 Accumulation-Manipulation-Distribution: sweep-and-revert-to-50% (Trader Kane
    Playbook.txt, "SMT Divergence + PO3").

    Source document rule: mark a recent range (accumulation), wait for a liquidity sweep beyond
    the range's high/low (manipulation, typically ~10:00 AM EST), then a reversal back toward the
    range's 50% level (distribution) is the trade -- entering on the break of structure back
    through an "inversion zone," stop beyond the sweep, target the range midpoint ("base hit").

    APPROXIMATION / EXPLICIT SCOPE REDUCTION: the document's SMT divergence confirmation (NQ vs
    ES making non-confirming highs/lows) requires a SECOND correlated instrument's price series,
    which is not available in a single-symbol `enriched` DataFrame -- there is no cross-asset
    column to compute it from. Per the interface spec's guidance (implement the closest honest
    mechanical approximation rather than fabricating a substitute indicator or returning
    all-zero), this function implements the single-symbol PO3 sweep-and-revert mechanic ONLY,
    clearly dropping the SMT confirmation leg. The optional ~10:00 AM EST session filter
    (approximated as 13:00-16:00 UTC, covering the standard/DST straddle around 9-11 AM EST) is
    retained since it needs only `timestamp`.

    Range/sweep construction (all via `.shift(1)` before the rolling window, so the range is
    fixed using bars strictly before the current one):
      range_high = high.shift(1).rolling(range_window).max()
      range_low  = low.shift(1).rolling(range_window).min()
      range_mid  = (range_high + range_low) / 2
    Manipulation (bearish): current bar's high exceeds range_high (a sweep above the prior
      range) but the bar closes back BELOW range_high (rejection) -> expect reversion down to
      range_mid -> entry_short.
    Manipulation (bullish): mirror image using range_low -> entry_long.
    Exit: price reaches range_mid (the base-hit target), or a fresh sweep forms in the opposite
      direction (a new manipulation event invalidates the prior read).
    """
    close = enriched["close"]
    high = enriched["high"]
    low = enriched["low"]

    range_high = high.shift(1).rolling(range_window).max()
    range_low = low.shift(1).rolling(range_window).min()
    range_mid = (range_high + range_low) / 2.0

    sweep_high = high > range_high
    sweep_low = low < range_low

    bearish_manipulation = sweep_high & (close < range_high)
    bullish_manipulation = sweep_low & (close > range_low)

    if session_filter and "timestamp" in enriched.columns:
        ts = pd.to_datetime(enriched["timestamp"], utc=True)
        hour = ts.dt.hour
        in_session = (hour >= session_start_utc_hour) & (hour <= session_end_utc_hour)
        bearish_manipulation = bearish_manipulation & in_session
        bullish_manipulation = bullish_manipulation & in_session

    entry_short = bearish_manipulation
    entry_long = bullish_manipulation

    reached_mid_from_short = close <= range_mid
    reached_mid_from_long = close >= range_mid

    exit_short = reached_mid_from_short | bullish_manipulation
    exit_long = reached_mid_from_long | bearish_manipulation

    entry_long = entry_long.fillna(False)
    entry_short = entry_short.fillna(False)
    exit_long = exit_long.fillna(False)
    exit_short = exit_short.fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
