"""
Module: cisd.py
Description: Engine 07 -- CISD (Change in State of Delivery) detection.

    docs/UPGRADE_ROADMAP.md P2 item 6. Fully specified in
    docs/ICT_SPEC_PHASE5.md section 2, converted from prose (a `## CISD`
    section found in Tradecraft's own SKILL.md, MIT) into a deterministic
    algorithm per Rule 21 -- not from ICT prose directly.

    CONCEPT: "a breakout candle through an FVG simultaneously creates a
    NEW FVG that overlaps the failed (IFVG) zone -- two signals merge
    into one candle" (source's own words). A composition of three
    primitives this platform already has: FVG detection (smart_money.
    detect_fair_value_gaps), an FVG failing (the same close-through-the-
    zone test as research/ict_concepts.inverse_fvg, reimplemented here
    rather than imported since CISD needs the exact break bar `b`, which
    inverse_fvg's own return type -- a ternary Series -- doesn't expose),
    and swing points (structure.find_swing_points, for the stop).

    UNFAVORABLE PRIOR, SPECIFIED ANYWAY (spec 2.5). inverse_fvg (the
    component CISD's Step 1 is built on) measured negative solo on all
    three tested assets (-0.208/-0.569/-0.270, research/ablation_*.json).
    CISD is a STRICTER filter over the same failed-gap population, so a
    thin, possibly-unmeasurable sample is the spec's own stated most
    likely outcome -- built for completeness per the roadmap, not because
    a positive result was expected.

    NOT YET ABLATED AT IMPORT TIME. Same convention as crt.py: exposed on
    TechnicalSnapshot.cisd_setups for inspection only, not wired into
    _generate_advanced_signals or _compute_bullish_score until ablated.
Author: Shantanu Waykar
Version: 1.0.0
"""

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from project_titan_x.engines.e07_technical.smart_money import detect_fair_value_gaps
from project_titan_x.engines.e07_technical.structure import SwingKind, find_swing_points

MAX_AGE = 50  # spec 2.4: "inverse_fvg caps the search at 50 bars; reuse that bound"


@dataclass
class CISDSetup:
    """One CISD setup. `direction` is the direction of the NEW (second)
    FVG -- the source's own "two signals merge into one candle" means the
    tradeable direction is the confirming, opposite-direction imbalance,
    not the original failed one."""

    signal_index: int  # b+1 -- EMITTED here, never at b (spec 2.3: "same trap as CRT 1.4")
    break_bar_index: int  # b -- the bar whose close broke clean through the original FVG
    original_fvg_index: int  # g -- the original (now-failed) FVG's own index
    direction: str  # "bullish" / "bearish"
    entry_zone_low: float
    entry_zone_high: float
    # Beyond the most recent swing LOW (bullish) / HIGH (bearish) strictly
    # before `b`, on the far side (spec 2.3). None if no such swing exists
    # in the available history -- an honest gap, not a guessed level. Like
    # CRT's own entry/stop/tp, this is a specification output, never
    # validated by E26 (which exits on signal flip only).
    stop: Optional[float]


def detect_cisd_setups(df: pd.DataFrame, max_age: int = MAX_AGE) -> list[CISDSetup]:
    """Detect CISD setups per docs/ICT_SPEC_PHASE5.md section 2.3.

    Args:
        df: OHLC data.
        max_age: bars after an FVG forms within which its failure (Step 1)
            must occur, or it's no longer a candidate (default 50, same
            bound research/ict_concepts.inverse_fvg already uses).

    Returns:
        list[CISDSetup], ordered by signal_index ascending.

    Edge cases (spec 2.4), all reject-not-guess:
        - `b` is the last bar: no b+1 exists, cannot evaluate Step 2 -- skipped.
        - `b == g + 1`: allowed; the zones will usually not overlap, and
          the overlap check naturally rejects it when they don't.
        - Multiple FVGs fail on the same bar: each is a separate
          candidate, but at most one signal per (signal_index, direction)
          is emitted -- a set dedups exact duplicates.
        - Zones touch but do not overlap (`overlap_high == overlap_low`):
          rejected -- a zero-width entry zone is not a zone.
    """
    gaps = detect_fair_value_gaps(df)
    if not gaps:
        return []

    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    n = len(df)

    swings = None  # lazy -- only computed if at least one candidate reaches the stop lookup
    setups: list[CISDSetup] = []
    seen: set[tuple[int, str]] = set()

    for g_fvg in gaps:
        g = g_fvg.index
        window_end = min(n, g + max_age + 1)

        # Step 1: the FVG fails -- first bar b in (g, window_end) whose
        # close breaks clean through the original zone.
        b = None
        for i in range(g + 1, window_end):
            if g_fvg.direction == "bullish" and c[i] < g_fvg.gap_bottom:
                b = i
                break
            if g_fvg.direction == "bearish" and c[i] > g_fvg.gap_top:
                b = i
                break
        if b is None or b + 1 >= n or b - 1 < 0:
            continue

        # Step 2: a NEW, opposite-direction FVG centered on b (window b-1/b/b+1).
        if h[b - 1] < l[b + 1]:
            new_direction, new_low, new_high = "bullish", h[b - 1], l[b + 1]
        elif l[b - 1] > h[b + 1]:
            new_direction, new_low, new_high = "bearish", h[b + 1], l[b - 1]
        else:
            continue
        if new_direction == g_fvg.direction:  # require the OPPOSITE direction
            continue

        # Step 3: the two zones overlap (not merely touch).
        overlap_low = max(g_fvg.gap_bottom, new_low)
        overlap_high = min(g_fvg.gap_top, new_high)
        if overlap_high <= overlap_low:
            continue

        signal_index = b + 1
        key = (signal_index, new_direction)
        if key in seen:
            continue
        seen.add(key)

        if swings is None:
            swings = find_swing_points(df)
        wanted_kind = SwingKind.LOW if new_direction == "bullish" else SwingKind.HIGH
        prior_swings = [s for s in swings if s.index < b and s.kind == wanted_kind]
        stop = max(prior_swings, key=lambda s: s.index).price if prior_swings else None

        setups.append(CISDSetup(
            signal_index=signal_index, break_bar_index=b, original_fvg_index=g,
            direction=new_direction,
            entry_zone_low=float(overlap_low), entry_zone_high=float(overlap_high),
            stop=float(stop) if stop is not None else None,
        ))

    setups.sort(key=lambda s: s.signal_index)
    return setups
