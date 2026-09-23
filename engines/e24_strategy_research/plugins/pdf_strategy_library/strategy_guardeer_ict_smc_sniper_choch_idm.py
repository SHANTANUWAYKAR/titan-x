"""
Module: strategy_guardeer_ict_smc_sniper_choch_idm.py
Source document(s): ICT,SMC TRADING STRATEGY GUARDEER.txt
Description: "ICT & SMC Based Sniper Entry Strategy (Guardeer aka Nilesh Chaudhary Inspired
Setup)". Multi-timeframe cascade in the source (15-minute POI zone -> switch to 1-minute for
CHoCH -> IDM/liquidity sweep -> Order Block sniper entry) collapsed onto the single timeframe
of `enriched` (documented approximation below), since the platform passes one DataFrame per
call. Implements: price reaches a POI (a recent swing high/low +/- an ATR buffer) -> a
Change-of-Character (CHoCH) fires -> a subsequent Inducement (IDM) liquidity sweep of a minor
recent extreme reverses -> enter on the Order Block formed by that reversal, targeting a large
(1:5-1:10) R:R (external to this signal function, per interface spec).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_guardeer_ict_smc_sniper_choch_idm(
    enriched: pd.DataFrame,
    poi_k: int = 2,
    atr_buffer_mult: float = 0.25,
    choch_window: int = 15,
    idm_window: int = 10,
    idm_lookback: int = 5,
) -> pd.Series:
    """POI touch -> CHoCH -> IDM liquidity sweep -> Order Block sniper entry.

    Source document: "ICT,SMC TRADING STRATEGY GUARDEER.txt" ("ICT & SMC Based Sniper Entry
    Strategy (Guardeer aka Nilesh Chaudhary Inspired Setup)"). Rule: 1) mark a POI (Point of
    Interest -- Order Block / FVG) on a higher timeframe; 2) wait for price to touch that zone;
    3) on a lower timeframe wait for a CHoCH (Change of Character); 4) after CHoCH, wait for an
    IDM (Inducement) liquidity sweep / grab; 5) enter on the lower Order Block formed after that
    sweep, with a small stop and a 1:5-1:10 R:R target (external to this function).

    Interpretive assumptions / approximations (the source is an explicit 15m-POI / 1m-entry
    cascade; the platform passes one timeframe per call, so both legs are collapsed onto
    `enriched`'s own bars):
    - POI = a causal fractal swing high/low (confirmed `poi_k` bars later, never using data
      from after the confirming bar) with an ATR-based buffer (`atr_buffer_mult * atr`) turning
      the pivot point into a small zone, since `atr` is an available column -- this avoids
      fabricating a new indicator purely for "zone width".
    - CHoCH (Change of Character) is approximated with the already-available
      `supertrend_direction` flipping in the setup's favor -- both concepts describe "a
      directional character change"; this substitutes the platform's own trend-flip column for
      a bespoke lower-timeframe structure-break detector, stated here explicitly as a
      substitution rather than silently invented.
    - IDM (Inducement) sweep = price wicks beyond the extreme of the last `idm_lookback` bars
      and closes back on the origin side within the same bar (a minor stop-run and reclaim).
    - The "lower Order Block" = the last opposite-colored candle in the small window between the
      CHoCH and the IDM sweep.
    - Because true 1:5-1:10 R:R targeting is position-sizing/exit-level logic, not a direction
      trigger, it is intentionally NOT implemented here per the interface spec; exit instead
      uses a break back beyond the Order Block as a structural invalidation.
    """
    o = enriched["open"].to_numpy(dtype=float)
    h = enriched["high"].to_numpy(dtype=float)
    l = enriched["low"].to_numpy(dtype=float)
    c = enriched["close"].to_numpy(dtype=float)
    atr = enriched["atr"].to_numpy(dtype=float)
    st_dir = enriched["supertrend_direction"].to_numpy(dtype=float)
    n = len(enriched)

    is_green = c > o
    is_red = c < o

    k = max(int(poi_k), 1)
    high_s = pd.Series(h)
    low_s = pd.Series(l)
    roll_max_c = high_s.rolling(2 * k + 1, center=True).max()
    roll_min_c = low_s.rolling(2 * k + 1, center=True).min()
    confirmed_swing_high = (high_s == roll_max_c).shift(k).fillna(False).to_numpy()
    confirmed_swing_low = (low_s == roll_min_c).shift(k).fillna(False).to_numpy()
    swing_high_val = high_s.shift(k).to_numpy()
    swing_low_val = low_s.shift(k).to_numpy()

    # minor extreme reference for the IDM sweep (causal: excludes the current bar)
    minor_low_ref = pd.Series(l).shift(1).rolling(idm_lookback).min().to_numpy()
    minor_high_ref = pd.Series(h).shift(1).rolling(idm_lookback).max().to_numpy()

    entry_long = np.zeros(n, dtype=bool)
    entry_short = np.zeros(n, dtype=bool)
    exit_long = np.zeros(n, dtype=bool)
    exit_short = np.zeros(n, dtype=bool)

    last_sh = np.nan
    last_sl = np.nan

    # states: 0 idle, 1 touched (awaiting CHoCH), 2 CHoCH confirmed (awaiting IDM sweep),
    #         3 IDM swept (awaiting OB retracement entry)
    state_long = 0
    state_short = 0
    touch_bar_l = touch_bar_s = -1
    choch_bar_l = choch_bar_s = -1
    ob_low_l = ob_high_l = np.nan
    ob_low_s = ob_high_s = np.nan
    active_ob_low_long = np.nan
    active_ob_high_short = np.nan

    for i in range(k, n):
        if confirmed_swing_high[i]:
            last_sh = swing_high_val[i]
        if confirmed_swing_low[i]:
            last_sl = swing_low_val[i]

        buf = atr_buffer_mult * atr[i] if not np.isnan(atr[i]) else 0.0

        # -------- LONG side: POI = last swing low zone --------
        if state_long == 0:
            if not np.isnan(last_sl) and l[i] <= last_sl + buf:
                state_long = 1
                touch_bar_l = i
        elif state_long == 1:
            if (i - touch_bar_l) > choch_window:
                state_long = 0
            elif st_dir[i] > 0 and st_dir[i - 1] <= 0:
                state_long = 2
                choch_bar_l = i
        elif state_long == 2:
            if (i - choch_bar_l) > idm_window:
                state_long = 0
            elif not np.isnan(minor_low_ref[i]) and l[i] < minor_low_ref[i] and c[i] > minor_low_ref[i]:
                ob_j = None
                for j in range(i, max(choch_bar_l, i - idm_lookback) - 1, -1):
                    if is_red[j]:
                        ob_j = j
                        break
                if ob_j is not None:
                    ob_low_l, ob_high_l = l[ob_j], h[ob_j]
                    state_long = 3
                    touch_bar_l = i
                else:
                    state_long = 0
        elif state_long == 3:
            if (i - touch_bar_l) > idm_window:
                state_long = 0
            elif l[i] <= ob_high_l and h[i] >= ob_low_l and c[i] > o[i]:
                entry_long[i] = True
                active_ob_low_long = ob_low_l
                state_long = 0

        if not np.isnan(active_ob_low_long) and c[i] < active_ob_low_long:
            exit_long[i] = True
            active_ob_low_long = np.nan

        # -------- SHORT side: POI = last swing high zone --------
        if state_short == 0:
            if not np.isnan(last_sh) and h[i] >= last_sh - buf:
                state_short = 1
                touch_bar_s = i
        elif state_short == 1:
            if (i - touch_bar_s) > choch_window:
                state_short = 0
            elif st_dir[i] < 0 and st_dir[i - 1] >= 0:
                state_short = 2
                choch_bar_s = i
        elif state_short == 2:
            if (i - choch_bar_s) > idm_window:
                state_short = 0
            elif not np.isnan(minor_high_ref[i]) and h[i] > minor_high_ref[i] and c[i] < minor_high_ref[i]:
                ob_j = None
                for j in range(i, max(choch_bar_s, i - idm_lookback) - 1, -1):
                    if is_green[j]:
                        ob_j = j
                        break
                if ob_j is not None:
                    ob_low_s, ob_high_s = l[ob_j], h[ob_j]
                    state_short = 3
                    touch_bar_s = i
                else:
                    state_short = 0
        elif state_short == 3:
            if (i - touch_bar_s) > idm_window:
                state_short = 0
            elif l[i] <= ob_high_s and h[i] >= ob_low_s and c[i] < o[i]:
                entry_short[i] = True
                active_ob_high_short = ob_high_s
                state_short = 0

        if not np.isnan(active_ob_high_short) and c[i] > active_ob_high_short:
            exit_short[i] = True
            active_ob_high_short = np.nan

    idx = enriched.index
    return _stateful_from_entries_exits(
        pd.Series(entry_long, index=idx),
        pd.Series(exit_long, index=idx),
        pd.Series(entry_short, index=idx),
        pd.Series(exit_short, index=idx),
    )
