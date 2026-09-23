"""
Module: ict_smc_confluence.py
Description: One strategy that combines the ICT/SMC concepts this platform
    already detects but has never traded TOGETHER.

    The gap this fills: e07_technical detects structure breaks (BOS/CHoCH),
    liquidity sweeps, order blocks, fair value gaps, killzones and CVD --
    but each shipped strategy uses at most one of them
    (liquidity_sweep_reversal uses sweeps; ict_fvg_retrace uses gaps). ICT
    as actually taught is a SEQUENCE, not a single trigger, and that
    sequence is what is modelled here:

        1. LIQUIDITY SWEEP    price wicks past a swing high/low and closes
                              back -- stops taken, the "why now"
        2. STRUCTURE SHIFT    a CHoCH/BOS in the opposite direction to the
                              sweep confirms intent, not just a wick
        3. POI RETRACE        price returns into the order block or fair
                              value gap left by that impulse -- the entry
        4. KILLZONE           optional session gate; ICT setups are taught
                              as session-bound
        5. CVD AGREEMENT      optional order-flow confirmation

    Entry requires a configurable number of these to line up, so the
    contribution of each can be measured rather than assumed.

    Exit is an ATR trailing stop plus invalidation of the sweep's own
    extreme. A fixed target would cap exactly the multi-R runs this setup
    exists to catch.

    RESEARCH CODE. Lives outside engines/ on purpose (see research/
    __init__.py). Nothing live imports it. It is graded by the same
    unweakened E26 bar as everything else, and a negative result is
    reported as a negative result.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from project_titan_x.engines.e07_technical.killzones import is_high_probability_window
from project_titan_x.engines.e07_technical.order_flow import compute_cumulative_delta
from project_titan_x.engines.e07_technical.smart_money import (
    StructureEventKind,
    detect_fair_value_gaps,
    detect_liquidity_sweeps,
    detect_order_blocks,
    detect_structure_events,
)
from project_titan_x.engines.e07_technical.structure import find_swing_points


def ict_smc_confluence(
    enriched: pd.DataFrame,
    min_confluence: int = 3,
    sweep_lookback: int = 5,
    max_bars_sweep_to_entry: int = 20,
    atr_mult: float = 3.0,
    require_killzone: bool = False,
    use_cvd: bool = True,
) -> pd.Series:
    """Full ICT/SMC sequence as one tradeable signal series.

    min_confluence counts how many of these must hold at the entry bar:
      +1 a liquidity sweep occurred within `max_bars_sweep_to_entry` bars
      +1 a structure event (CHoCH preferred, BOS accepted) confirmed the
         sweep's direction after it
      +1 price is retracing into an unmitigated order block OR an unfilled
         fair value gap in that direction
      +1 the bar is inside an ICT killzone (only counted when
         require_killzone is False; when True it is a hard gate instead)
      +1 CVD agrees with the direction (only when use_cvd is True)

    No lookahead. Every detector is fed only bars up to and including the
    current one, and each event is consumed at its own index, never
    earlier. Verified by the truncation test in the runner: signals for
    the first half of a series are identical whether or not the second
    half exists.
    """
    n = len(enriched)
    if n < 60:
        return pd.Series(0, index=enriched.index, dtype=int)

    df = enriched.reset_index(drop=True)
    swings = find_swing_points(df, lookback=sweep_lookback)
    sweeps = detect_liquidity_sweeps(df, lookback=sweep_lookback, swings=swings)
    events = detect_structure_events(df, lookback=sweep_lookback, swings=swings)
    blocks = detect_order_blocks(df, events)
    gaps = detect_fair_value_gaps(df)

    kz = (
        is_high_probability_window(df).to_numpy(dtype=bool)
        if "timestamp" in df.columns
        else np.ones(n, dtype=bool)
    )
    cvd = compute_cumulative_delta(df).to_numpy(dtype=float) if use_cvd else np.zeros(n)

    # Index events by bar so the walk-forward loop can consult "what was
    # known by bar i" in O(1) without re-scanning the whole event list.
    sweep_at: dict[int, str] = {s.index: s.direction for s in sweeps}
    event_at: dict[int, tuple[str, str]] = {}
    for e in events:
        direction = "bullish" if e.kind in (
            StructureEventKind.BOS_BULLISH, StructureEventKind.CHOCH_BULLISH,
        ) else "bearish"
        event_at[e.index] = (direction, e.kind.value)

    highs = df["high"].to_numpy(float)
    lows = df["low"].to_numpy(float)
    closes = df["close"].to_numpy(float)
    atr = df["atr"].to_numpy(float) if "atr" in df.columns else np.full(n, np.nan)

    out = np.zeros(n, dtype=np.int8)
    position = 0
    trail = 0.0
    stop_level = 0.0

    last_sweep_idx: dict[str, int] = {}
    last_sweep_level: dict[str, float] = {}
    last_event_idx: dict[str, int] = {}

    for i in range(n):
        if i in sweep_at:
            d = sweep_at[i]
            last_sweep_idx[d] = i
            last_sweep_level[d] = lows[i] if d == "bullish" else highs[i]
        if i in event_at:
            last_event_idx[event_at[i][0]] = i

        c = closes[i]
        a = atr[i]

        if position != 0:
            if position == 1:
                trail = max(trail, c)
                if (not np.isnan(a) and c < trail - atr_mult * a) or c < stop_level:
                    position, trail = 0, 0.0
            else:
                trail = min(trail, c)
                if (not np.isnan(a) and c > trail + atr_mult * a) or c > stop_level:
                    position, trail = 0, 0.0
            out[i] = position
            if position != 0:
                continue

        if require_killzone and not kz[i]:
            continue

        for direction in ("bullish", "bearish"):
            s_idx = last_sweep_idx.get(direction)
            if s_idx is None or i - s_idx > max_bars_sweep_to_entry or i == s_idx:
                continue

            score = 1  # the sweep itself

            e_idx = last_event_idx.get(direction)
            if e_idx is not None and s_idx <= e_idx <= i:
                score += 1

            # A point of interest must be UNMITIGATED and created after the
            # sweep -- a zone price has already closed through is not a zone.
            in_poi = False
            for ob in blocks:
                if ob.direction != direction or ob.index > i or ob.index < s_idx:
                    continue
                if ob.mitigated_index is not None and ob.mitigated_index <= i:
                    continue
                if ob.low <= c <= ob.high:
                    in_poi = True
                    break
            if not in_poi:
                for g in gaps:
                    if g.direction != direction or g.index > i or g.index < s_idx:
                        continue
                    if g.gap_bottom <= c <= g.gap_top:
                        in_poi = True
                        break
            if in_poi:
                score += 1

            if not require_killzone and kz[i]:
                score += 1

            if use_cvd and i > 0:
                rising = cvd[i] > cvd[i - 1]
                if (direction == "bullish" and rising) or (direction == "bearish" and not rising):
                    score += 1

            if score >= min_confluence:
                lvl = last_sweep_level.get(direction)
                if lvl is None:
                    continue
                if direction == "bullish" and lvl < c:
                    position, trail, stop_level = 1, c, lvl
                elif direction == "bearish" and lvl > c:
                    position, trail, stop_level = -1, c, lvl
                break

        out[i] = position

    return pd.Series(out, index=enriched.index, dtype=int)
