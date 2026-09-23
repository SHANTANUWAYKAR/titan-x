"""
Module: strategy_guardeer_smc_structure_bos_ob.py
Source document(s): GUARDEER SMC STRATEGY.txt, GUARDEER SMC STRATEGY (2).txt
Description: These two source files are BYTE-IDENTICAL (verified directly: `diff` shows no
difference and both MD5-hash to 75377c163ba3be9e3b05b0749bcbf56f at 2038 bytes / 51 lines) --
"Guardeer Strategy (Smart Money Concept Based)": identify market bias from swing structure
(HH/HL = bullish, LH/LL = bearish), wait for a liquidity sweep of the recent opposite-side
swing extreme, confirm a Break of Structure (BOS) in the bias direction, then enter when price
retraces into the Order Block / POI formed just before the BOS impulse leg. One implementation
covers both identically-worded documents (per INTERFACE_SPEC.md's near-duplicate
consolidation rule); note that the task brief describing this batch expected these two files
to differ -- they do not, confirmed byte-for-byte before writing a second, redundant copy.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_guardeer_smc_structure_bos_ob(
    enriched: pd.DataFrame,
    swing_k: int = 3,
    sweep_lookback: int = 30,
    retrace_lookback: int = 20,
    body_ratio_threshold: float = 0.0,
) -> pd.Series:
    """Market structure bias -> liquidity sweep -> BOS -> Order Block retracement entry.

    Source documents: "GUARDEER SMC STRATEGY.txt" and "GUARDEER SMC STRATEGY (2).txt"
    (verified byte-identical -- same MD5 hash -- so one implementation covers both). Rule
    (translated from the original Hinglish): 1) determine market bias from swing structure
    (Higher-High + Higher-Low = bullish, Lower-High + Lower-Low = bearish); 2) wait for a
    liquidity sweep of the most recent opposite-side swing point; 3) confirm a Break of
    Structure (BOS) -- a close beyond the most recent same-side swing extreme -- in the bias
    direction; 4) enter when price retraces into the Order Block / POI (the last opposite-
    colored candle before the BOS impulse leg). Stop loss beyond the Order Block; target = next
    liquidity zone with >= 1:2/1:3 R:R (both external to this signal function per interface
    spec).

    Interpretive assumptions:
    - Swing highs/lows are detected with a causal fractal: a bar `i - swing_k` is confirmed as
      a pivot only once `swing_k` further bars have printed (computed as a centered rolling
      extreme, then the confirmation flag is shifted forward by `swing_k` bars so nothing at
      bar `i` ever depends on data after bar `i` -- confirming bar i-k needs data only through
      (i-k)+k == i).
    - "Liquidity sweep" = a bar's wick trades beyond the tracked swing extreme (high beyond the
      last swing high while a bearish-biased sweep is being watched, low beyond the last swing
      low while bullish) and closes back on the origin side of that level within the same bar.
    - "Order Block" = the last opposite-colored candle between the sweep bar and the BOS bar (a
      standard, mechanical, widely-used SMC definition).
    - Retracement entry requires price to trade back into the Order Block's [low, high] range
      and close in the bias direction, bounded by `retrace_lookback` bars after the BOS (a
      stale, un-retraced OB is abandoned rather than held indefinitely).
    - Exit uses a break back beyond the swing level that was broken to create the BOS, as a
      structural invalidation -- recomputed fresh every bar from the running structure state,
      never a value frozen at entry time.
    - `body_ratio_threshold` defaults to 0.0 (the document does not require a "strong" candle
      for the retracement reaction, unlike the Gautam-Jha-style documents elsewhere in this
      project); raise it to require a stronger reaction candle.
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

    k = max(int(swing_k), 1)
    high_s = pd.Series(h)
    low_s = pd.Series(l)
    roll_max_centered = high_s.rolling(2 * k + 1, center=True).max()
    roll_min_centered = low_s.rolling(2 * k + 1, center=True).min()
    raw_swing_high = (high_s == roll_max_centered)
    raw_swing_low = (low_s == roll_min_centered)
    # shift(k): at row i this reports whether row (i-k) was a confirmed pivot -- causal,
    # because confirming row (i-k) needed data only through (i-k)+k == i.
    confirmed_swing_high = raw_swing_high.shift(k).fillna(False).to_numpy()
    confirmed_swing_low = raw_swing_low.shift(k).fillna(False).to_numpy()
    swing_high_val = high_s.shift(k).to_numpy()
    swing_low_val = low_s.shift(k).to_numpy()

    entry_long = np.zeros(n, dtype=bool)
    entry_short = np.zeros(n, dtype=bool)
    exit_long = np.zeros(n, dtype=bool)
    exit_short = np.zeros(n, dtype=bool)

    last_sh = prev_sh = np.nan
    last_sl = prev_sl = np.nan
    bias = 0

    swept_low_bar = None
    swept_high_bar = None

    retrace_dir = 0
    ob_low = ob_high = np.nan
    retrace_deadline = -1

    running_break_level_long = np.full(n, np.nan)
    running_break_level_short = np.full(n, np.nan)

    for i in range(k, n):
        if confirmed_swing_high[i]:
            prev_sh = last_sh
            last_sh = swing_high_val[i]
        if confirmed_swing_low[i]:
            prev_sl = last_sl
            last_sl = swing_low_val[i]

        if not (np.isnan(last_sh) or np.isnan(prev_sh) or np.isnan(last_sl) or np.isnan(prev_sl)):
            if last_sh > prev_sh and last_sl > prev_sl:
                bias = 1
            elif last_sh < prev_sh and last_sl < prev_sl:
                bias = -1
            # mixed structure: keep prior bias unchanged (documented assumption)

        # --- sweep detection ---
        if bias == 1 and not np.isnan(last_sl) and l[i] < last_sl and c[i] > last_sl:
            swept_low_bar = i
        if bias == -1 and not np.isnan(last_sh) and h[i] > last_sh and c[i] < last_sh:
            swept_high_bar = i

        # --- BOS confirmation (bullish) ---
        if (bias == 1 and swept_low_bar is not None and (i - swept_low_bar) <= sweep_lookback
                and not np.isnan(last_sh) and c[i] > last_sh):
            ob_j = None
            for j in range(i, swept_low_bar - 1, -1):
                if is_red[j]:
                    ob_j = j
                    break
            if ob_j is not None:
                ob_low, ob_high = l[ob_j], h[ob_j]
                retrace_dir = 1
                retrace_deadline = i + retrace_lookback
            swept_low_bar = None

        # --- BOS confirmation (bearish) ---
        if (bias == -1 and swept_high_bar is not None and (i - swept_high_bar) <= sweep_lookback
                and not np.isnan(last_sl) and c[i] < last_sl):
            ob_j = None
            for j in range(i, swept_high_bar - 1, -1):
                if is_green[j]:
                    ob_j = j
                    break
            if ob_j is not None:
                ob_low, ob_high = l[ob_j], h[ob_j]
                retrace_dir = -1
                retrace_deadline = i + retrace_lookback
            swept_high_bar = None

        # --- retracement entry ---
        if retrace_dir == 1:
            if i > retrace_deadline:
                retrace_dir = 0
            elif l[i] <= ob_high and h[i] >= ob_low and c[i] > o[i] and body_ratio[i] >= body_ratio_threshold:
                entry_long[i] = True
                retrace_dir = 0
        elif retrace_dir == -1:
            if i > retrace_deadline:
                retrace_dir = 0
            elif l[i] <= ob_high and h[i] >= ob_low and c[i] < o[i] and body_ratio[i] >= body_ratio_threshold:
                entry_short[i] = True
                retrace_dir = 0

        running_break_level_long[i] = last_sl
        running_break_level_short[i] = last_sh

    idx = enriched.index
    rbl_long = pd.Series(running_break_level_long, index=idx)
    rbl_short = pd.Series(running_break_level_short, index=idx)
    close_s = enriched["close"]
    exit_long_s = (close_s < rbl_long).fillna(False)
    exit_short_s = (close_s > rbl_short).fillna(False)

    return _stateful_from_entries_exits(
        pd.Series(entry_long, index=idx),
        exit_long_s,
        pd.Series(entry_short, index=idx),
        exit_short_s,
    )
