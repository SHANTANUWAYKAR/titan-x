"""
Module: strategy_blackbox_fakeout_reclaim.py
Source document(s): BLACKBOX STRATEGY.txt, BLACKBOX TRADING STRATEGY.txt
Description: Both documents describe the identical core setup under the same name ("Black Box
Strategy"): mark a strong support/resistance level, let price fake-break through it (a stop
hunt), wait for the breakout to fail and price to reclaim the level, then enter in the reclaim
direction with the stop beyond the fake-breakout extreme and a >=1:3 R:R target. Per the
near-duplicate consolidation rule these two near-identical write-ups are implemented as ONE
function; the docstring lists both source filenames.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_blackbox_fakeout_reclaim(
    enriched: pd.DataFrame,
    level_lookback: int = 40,
    sweep_window: int = 5,
) -> pd.Series:
    """Fake-breakout / stop-hunt reclaim reversal (consolidates two "Black Box" documents).

    Source documents: "BLACKBOX STRATEGY.txt" and "BLACKBOX TRADING STRATEGY.txt" (same rule,
    both titled "Black Box Strategy"). Rule: mark a strong support/resistance level, wait for
    price to break it (trapping breakout traders), wait for the break to fail, then enter when
    price reclaims the level in the opposite direction of the fake break.

    Interpretive assumptions:
    - "Strong support/resistance level" = rolling high/low over `level_lookback` bars, using
      only bars strictly before the sweep window (see bug note below), never the current bar.
    - "Fake breakdown then reclaim" (bullish case) = the lowest low in the last `sweep_window`
      bars (all strictly before the current bar) traded below the support level, and the
      current bar's close is the first close back above it. Mirrored for the bearish case
      (fake breakout above resistance, then reclaim below it).

    Bug found and fixed during Stage-0 pre-audit (2026-09-12): the original version computed
    `support = low.shift(1).rolling(level_lookback).min()` and then compared the SAME trailing
    window's most recent `sweep_window` bars against it -- but since the sweep window is a
    strict SUBSET of the support window ending at the same point, `subset_min < full_set_min` is
    mathematically impossible (a subset's min can never be lower than the full set's min that
    already includes it). Verified empirically: 0 sweep conditions fired across 5,000-20,000 real
    bars on 3 different assets/timeframes -- this is the identical "entry_n/exit_n subset" bug
    class already documented in this repo's CLAUDE.md for the donchian family. Fixed by pushing
    the support/resistance window BACK by `sweep_window` bars so it no longer overlaps the sweep
    window at all -- support is now a genuinely OLDER, separately-established level that the
    recent sweep can actually undercut.
    """
    high, low, close = enriched["high"], enriched["low"], enriched["close"]

    support = low.shift(1 + sweep_window).rolling(level_lookback).min()
    resistance = high.shift(1 + sweep_window).rolling(level_lookback).max()

    swept_below_support = (low.shift(1).rolling(sweep_window).min() < support).fillna(False)
    swept_above_resistance = (high.shift(1).rolling(sweep_window).max() > resistance).fillna(False)

    reclaim_long = (close > support) & (close.shift(1) <= support.shift(1))
    reclaim_short = (close < resistance) & (close.shift(1) >= resistance.shift(1))

    entry_long = (swept_below_support & reclaim_long).fillna(False)
    entry_short = (swept_above_resistance & reclaim_short).fillna(False)

    exit_long = (close < support).fillna(False)
    exit_short = (close > resistance).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
