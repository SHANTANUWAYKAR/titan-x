"""
Module: strategy_gautam_intraday_breakout_variants_thin.py
Source document(s): GAUTAM TRADING STRATEGY.txt, GAUTAMJHA TRADING STRATEGY.txt
Description: Both documents describe the SAME core rule already implemented and covered in
batch2 as strategy_gautam_jha_pdh_pdl_breakout_reversal (source: "GAUTAM JHA STRATEGY.txt"):
mark PDH/PDL, wait for a full CLOSE-based break of the previous day's low/high, wait for one
green/red confirmation candle, enter on the break of that candle's high/low, mirrored for
sells. Per INTERFACE_SPEC.md's near-duplicate consolidation rule, this is a SHORT, THIN file
rather than a third and fourth full reimplementation: it reproduces the same minimal causal
core exactly once (`_pdh_pdl_break_confirm_core`) in this self-contained file (no cross-file
imports / file I/O, so each function stays independently testable) and exposes two thinly
named, real, working entry points so each source document still maps to a concrete function.

Differences noted between the two documents (both cosmetic, not new mechanics):
- GAUTAM TRADING STRATEGY.txt ("Gautam Jhaa Inspired Intraday Breakout") narrates only the BUY
  side explicitly; no SELL mirror text is present.
- GAUTAMJHA TRADING STRATEGY.txt ("...Professional Step-by-Step Trading Guide") explicitly
  narrates BOTH the BUY and SELL sides with a "strong" candle qualifier, matching the
  already-covered GAUTAM JHA STRATEGY.txt almost verbatim.
Both are implemented here bidirectionally (long+short) for consistency; the first document's
short side is therefore an interpretive, symmetric addition, exactly the same assumption the
already-covered batch2 file makes for internal consistency.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def _pdh_pdl_break_confirm_core(enriched: pd.DataFrame, break_lookback: int) -> pd.Series:
    """Shared causal core: PDH/PDL close-break -> green/red candle -> break of its high/low."""
    open_, high, low, close = enriched["open"], enriched["high"], enriched["low"], enriched["close"]

    day = enriched["timestamp"].dt.date
    daily = pd.DataFrame({"high": high, "low": low}).groupby(day).agg(d_high=("high", "max"), d_low=("low", "min"))
    daily_prev = daily.shift(1)
    pdh = day.map(daily_prev["d_high"])
    pdl = day.map(daily_prev["d_low"])

    broke_below = (close < pdl).fillna(False)
    broke_above = (close > pdh).fillna(False)

    broke_below_recent = broke_below.shift(1).rolling(break_lookback, min_periods=1).max().fillna(0).astype(bool)
    broke_above_recent = broke_above.shift(1).rolling(break_lookback, min_periods=1).max().fillna(0).astype(bool)

    green_after_break = broke_below_recent & (close > open_)
    red_after_break = broke_above_recent & (close < open_)

    entry_long = (green_after_break.shift(1).fillna(False) & (close > high.shift(1))).fillna(False)
    entry_short = (red_after_break.shift(1).fillna(False) & (close < low.shift(1))).fillna(False)

    exit_long = (close < pdl).fillna(False)
    exit_short = (close > pdh).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)


def strategy_gautam_trading_breakout(enriched: pd.DataFrame, break_lookback: int = 15) -> pd.Series:
    """PDH/PDL close-break -> green/red confirmation candle -> break of its high/low.

    Source document: "GAUTAM TRADING STRATEGY.txt" ("Gautam Jhaa Inspired Intraday Breakout").
    THIN near-duplicate of the already-covered "GAUTAM JHA STRATEGY.txt"
    (batch2: strategy_gautam_jha_pdh_pdl_breakout_reversal) -- same core mechanic (mark PDH/PDL,
    wait for a full close beyond the previous day's low, wait for one green candle, enter when
    the next candle breaks that candle's high; SL below the green candle's swing low; target =
    nearest swing high, left to the platform's R:R engine). This document's own text narrates
    only the BUY side; the SELL mirror is an interpretive symmetric addition, the same
    assumption the already-covered version makes. See module docstring for why this is a thin
    file rather than a third full reimplementation.
    """
    return _pdh_pdl_break_confirm_core(enriched, break_lookback)


def strategy_gautamjha_trading_breakout(enriched: pd.DataFrame, break_lookback: int = 15) -> pd.Series:
    """PDH/PDL close-break -> strong green/red confirmation candle -> break of its high/low.

    Source document: "GAUTAMJHA TRADING STRATEGY.txt" ("...Professional Step-by-Step Trading
    Guide"). THIN near-duplicate of the already-covered "GAUTAM JHA STRATEGY.txt" (batch2:
    strategy_gautam_jha_pdh_pdl_breakout_reversal) -- explicitly narrates both BUY and SELL
    sides with a "strong candle" qualifier, matching the already-covered document almost
    verbatim. See module docstring for why this is a thin file rather than a fourth full
    reimplementation.
    """
    return _pdh_pdl_break_confirm_core(enriched, break_lookback)
