"""
Module: strategy_marco_liquidity_trap_reversal.py
Source document(s): Marco Trades Playbook.txt
Description: "Liquidity Playbook" -- price seeks liquidity resting beyond respected swing
highs/lows; retail traders get trapped when price sweeps beyond those levels and reverses.
Buy below a swept low (never above), sell above a swept high (never below), targeting the
opposite side's liquidity.

Interpretive assumptions:
- "Respected high/low that caused price to move away" = a rolling swing extreme over
  `level_lookback` bars that price has NOT revisited in the following `respect_bars` bars
  (i.e. genuinely left alone, not chopped through repeatedly).
- "Confirmation (internal structure, false reaction, trap)" approximated as a rejection
  candle: the sweep bar's close reverses back inside the prior range with a wick beyond it.
- Session filter (document explicitly wants a specific window, e.g. NY Open) approximated
  generically since the document doesn't name exact hours; no session filter applied here to
  keep the function timeframe-agnostic. A caller wanting a session restriction should compose
  this with strategies.apply_session_filter.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_marco_liquidity_trap_reversal(
    enriched: pd.DataFrame,
    level_lookback: int = 30,
    respect_bars: int = 10,
    wick_ratio: float = 0.4,
) -> pd.Series:
    """Liquidity-sweep trap reversal (Marco Trades' "Liquidity Playbook").

    See module docstring for full source attribution and interpretive assumptions.
    """
    high, low, close, open_ = enriched["high"], enriched["low"], enriched["close"], enriched["open"]

    # A "respected" level: the rolling extreme over an OLDER window, established before the
    # more recent `respect_bars` window (so the sweep candidate can't be part of the level
    # that defines itself -- avoids the same subset-window trap documented elsewhere).
    resistance = high.shift(1 + respect_bars).rolling(level_lookback).max()
    support = low.shift(1 + respect_bars).rolling(level_lookback).min()

    swept_below = (low < support) & (low.shift(1) >= support.shift(1))
    swept_above = (high > resistance) & (high.shift(1) <= resistance.shift(1))

    rng = (high - low).replace(0, np.nan)
    lower_wick_ratio = (np.minimum(close, open_) - low) / rng
    upper_wick_ratio = (high - np.maximum(close, open_)) / rng

    trap_reject_long = (swept_below & (lower_wick_ratio >= wick_ratio) & (close > support)).fillna(False)
    trap_reject_short = (swept_above & (upper_wick_ratio >= wick_ratio) & (close < resistance)).fillna(False)

    exit_long = (close < support).fillna(False)
    exit_short = (close > resistance).fillna(False)

    return _stateful_from_entries_exits(trap_reject_long, exit_long, trap_reject_short, exit_short)
