"""
Module: strategy_jadecap_swing_sweep_trap_breakout.py
Source document(s): JADECAP TRADING STRATEGY.txt
Description: "ICT Liquidity + SMC Trading Strategy -- Professional Step-by-Step Guide Inspired
by JadeCap Style Trading". Mark a prior swing high/low, wait for it to be swept and for price to
close back inside the range (a "Smart Money Trap"), then enter when a subsequent strong candle
breaks beyond that trap reaction candle's high/low.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_jadecap_swing_sweep_trap_breakout(
    enriched: pd.DataFrame,
    level_lookback: int = 50,
    level_gap: int = 10,
    confirm_window: int = 10,
    body_ratio_threshold: float = 0.60,
) -> pd.Series:
    """Higher-timeframe swing sweep -> "smart money trap" reclaim -> strong-candle breakout.

    Source document: "JADECAP TRADING STRATEGY.txt". Rule: on a 1-Hour chart mark the previous
    swing high (for shorts) / swing low (for longs); wait for the market to sweep it; wait for
    price to return and CLOSE back inside the range (the "Smart Money Trap" / false breakout);
    switch to the 5-Minute chart and wait for one strong candle in the trade direction; enter on
    a break of that candle's high (long) / low (short). Stop loss beyond the swing extreme;
    target the nearest opposing support/resistance zone with >= 1:2 R:R (external to this
    function per interface spec).

    Interpretive assumptions / approximations:
    - The source is an explicit two-timeframe design (1H level, 5M trigger); the platform
      passes a single timeframe per call, so both legs are collapsed onto `enriched`'s own bars:
      the "1H swing level" is proxied by a LONGER rolling extreme (`level_lookback` bars) that
      ends `level_gap` bars before the current bar, and the "5M reaction/entry" is proxied by
      the bars immediately following. The level window is deliberately made to END BEFORE the
      more-recent lookup zone begins (`high.shift(1 + level_gap).rolling(level_lookback)` vs. a
      check against the current bar directly) so the two windows never overlap -- an
      overlapping subset/superset rolling-window comparison can never fire (a known bug class:
      a `rolling(N)` window is mathematically guaranteed to contain the extreme of any
      `rolling(M<N)` sub-window ending at the same point, so comparing them is a tautology that
      can never trigger).
    - "Strong candle" = body >= body_ratio_threshold (0.60) of its high-low range, matching the
      convention already used for "strong candle" elsewhere in this project.
    - The trap, then the strong candle, then the breakout are each bounded by `confirm_window`
      bars so a stale, long-abandoned trap cannot fire on an unrelated later candle.
    - Exit uses a reclaim back beyond the tracked swing level as a structural invalidation,
      recomputed fresh from the same rolling series every bar (never a value frozen at entry).
    """
    o = enriched["open"].to_numpy(dtype=float)
    h = enriched["high"].to_numpy(dtype=float)
    l = enriched["low"].to_numpy(dtype=float)
    c = enriched["close"].to_numpy(dtype=float)
    n = len(enriched)

    rng = h - l
    body = np.abs(c - o)
    with np.errstate(divide="ignore", invalid="ignore"):
        body_ratio = np.where(rng > 0, body / rng, 0.0)
    body_ratio = np.nan_to_num(body_ratio, nan=0.0)
    is_green = c > o
    is_red = c < o

    # "1H" swing level proxy: a longer rolling extreme fixed BEFORE the recent window begins.
    level_high = enriched["high"].shift(1 + level_gap).rolling(level_lookback).max().to_numpy()
    level_low = enriched["low"].shift(1 + level_gap).rolling(level_lookback).min().to_numpy()

    entry_long = np.zeros(n, dtype=bool)
    entry_short = np.zeros(n, dtype=bool)
    exit_long = np.zeros(n, dtype=bool)
    exit_short = np.zeros(n, dtype=bool)

    # state machine per side: 0 idle, 1 trapped (awaiting strong candle), 2 strong candle found (awaiting break)
    state_long = state_short = 0
    trap_bar_l = trap_bar_s = -1
    anchor_low_l = anchor_high_l = np.nan
    anchor_low_s = anchor_high_s = np.nan

    min_start = level_lookback + level_gap + 1
    for i in range(min_start, n):
        lvl_h, lvl_l = level_high[i], level_low[i]
        if np.isnan(lvl_h) or np.isnan(lvl_l):
            continue

        # -------- LONG: sweep below level_low then same-bar reclaim = trap --------
        if state_long == 0:
            if l[i] < lvl_l and c[i] > lvl_l:
                state_long = 1
                trap_bar_l = i
        elif state_long == 1:
            if (i - trap_bar_l) > confirm_window:
                state_long = 0
            elif is_green[i] and body_ratio[i] >= body_ratio_threshold:
                anchor_low_l = l[i]
                anchor_high_l = h[i]
                state_long = 2
                trap_bar_l = i
        elif state_long == 2:
            if (i - trap_bar_l) > confirm_window:
                state_long = 0
            elif c[i] > anchor_high_l:
                entry_long[i] = True
                state_long = 0

        # -------- SHORT: sweep above level_high then same-bar reclaim = trap --------
        if state_short == 0:
            if h[i] > lvl_h and c[i] < lvl_h:
                state_short = 1
                trap_bar_s = i
        elif state_short == 1:
            if (i - trap_bar_s) > confirm_window:
                state_short = 0
            elif is_red[i] and body_ratio[i] >= body_ratio_threshold:
                anchor_low_s = l[i]
                anchor_high_s = h[i]
                state_short = 2
                trap_bar_s = i
        elif state_short == 2:
            if (i - trap_bar_s) > confirm_window:
                state_short = 0
            elif c[i] < anchor_low_s:
                entry_short[i] = True
                state_short = 0

        # exits: fresh structural reclaim beyond the currently tracked level
        exit_long[i] = c[i] < lvl_l
        exit_short[i] = c[i] > lvl_h

    idx = enriched.index
    return _stateful_from_entries_exits(
        pd.Series(entry_long, index=idx),
        pd.Series(exit_long, index=idx),
        pd.Series(entry_short, index=idx),
        pd.Series(exit_short, index=idx),
    )
