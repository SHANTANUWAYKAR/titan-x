"""
Module: harmonics.py
Description: Harmonic price pattern detection (Gartley, Bat, Butterfly,
    Crab) for e07_technical -- five-point (X-A-B-C-D) Fibonacci-ratio
    patterns. Built for the Harmonics topic cluster (488K tagged chunks
    in the ingested corpus -- the single largest topic overall, and
    previously entirely unimplemented in this engine), using the
    standard ratio definitions consistent across harmonic-trading
    literature (Scott Carney's framework, which the vast majority of
    harmonic-pattern books in the corpus build on).
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from project_titan_x.engines.e07_technical.structure import SwingKind, SwingPoint, alternate_swings, find_swing_points


@dataclass
class HarmonicPattern:
    name: str  # "Gartley", "Bat", "Butterfly", "Crab"
    direction: str  # "bullish" (D is a swing low -- reversal up expected) / "bearish" (D is a swing high)
    x_index: int
    a_index: int
    b_index: int
    c_index: int
    d_index: int
    x_price: float
    a_price: float
    b_price: float
    c_price: float
    d_price: float
    ab_xa_ratio: float
    bc_ab_ratio: float
    cd_bc_ratio: float
    ad_xa_ratio: float


# Each pattern's defining ratio ranges, per the standard harmonic-trading
# definitions. AB/XA and AD/XA are single target ratios in the classic
# definitions (0.618, 0.786, 0.886, 1.618) but are always applied with a
# tolerance band in practice, since real price data essentially never
# hits a Fibonacci ratio exactly -- TOLERANCE widens each into a small
# range around the target rather than requiring an exact match.
TOLERANCE = 0.06

_PATTERNS: dict[str, dict[str, tuple[float, float]]] = {
    "Gartley": {
        "ab_xa": (0.618 - TOLERANCE, 0.618 + TOLERANCE),
        "bc_ab": (0.382, 0.886),
        "cd_bc": (1.13, 1.618),
        "ad_xa": (0.786 - TOLERANCE, 0.786 + TOLERANCE),
    },
    "Bat": {
        "ab_xa": (0.382, 0.500 + TOLERANCE),
        "bc_ab": (0.382, 0.886),
        "cd_bc": (1.618, 2.618),
        "ad_xa": (0.886 - TOLERANCE, 0.886 + TOLERANCE),
    },
    "Butterfly": {
        "ab_xa": (0.786 - TOLERANCE, 0.786 + TOLERANCE),
        "bc_ab": (0.382, 0.886),
        "cd_bc": (1.618, 2.24),
        "ad_xa": (1.27, 1.618 + TOLERANCE),
    },
    "Crab": {
        "ab_xa": (0.382, 0.618 + TOLERANCE),
        "bc_ab": (0.382, 0.886),
        "cd_bc": (2.24, 3.618),
        "ad_xa": (1.618 - TOLERANCE, 1.618 + TOLERANCE),
    },
}

_BULLISH_KINDS = [SwingKind.LOW, SwingKind.HIGH, SwingKind.LOW, SwingKind.HIGH, SwingKind.LOW]
_BEARISH_KINDS = [SwingKind.HIGH, SwingKind.LOW, SwingKind.HIGH, SwingKind.LOW, SwingKind.HIGH]


def _in_range(value: float, bounds: tuple[float, float]) -> bool:
    return bounds[0] <= value <= bounds[1]


def detect_harmonic_patterns(
    df: pd.DataFrame, lookback: int = 5, swings: Optional[list[SwingPoint]] = None
) -> list[HarmonicPattern]:
    """Scans every consecutive alternating 5-swing sequence (X-A-B-C-D,
    see structure.py) for a match against each of the four standard
    harmonic patterns' ratio definitions. A pattern is bullish if X/B/D
    are swing lows and A/C are swing highs (D is the completion point,
    price expected to reverse UP from there); bearish is the mirror.
    Multiple patterns can match the same 5 points if their ratio ranges
    overlap (a real, known ambiguity in harmonic trading -- reported as
    separate matches rather than picking one arbitrarily).

    swings: OPTIONAL pre-computed alternate_swings(find_swing_points(df,
    lookback)) result, same shared-computation param as
    smart_money.detect_structure_events/detect_liquidity_sweeps -- see
    those functions' docstrings. None (default) computes it here,
    exactly as before."""
    if swings is None:
        swings = alternate_swings(find_swing_points(df, lookback=lookback))
    patterns: list[HarmonicPattern] = []

    for i in range(len(swings) - 4):
        x, a, b, c, d = swings[i:i + 5]
        kinds = [x.kind, a.kind, b.kind, c.kind, d.kind]
        if kinds == _BULLISH_KINDS:
            bullish = True
        elif kinds == _BEARISH_KINDS:
            bullish = False
        else:
            continue

        xa = abs(a.price - x.price)
        ab = abs(b.price - a.price)
        bc = abs(c.price - b.price)
        cd = abs(d.price - c.price)
        # Real bug caught in testing: AD is the leg from point A to point D
        # (same naming convention as AB/BC/CD -- each named for its two
        # endpoints), i.e. abs(a.price - d.price), NOT the distance from X
        # to D. Using abs(d.price - x.price) here originally meant a
        # "0.786 XA retracement" target was actually being checked against
        # a completely different quantity (for a bullish Gartley, D sits
        # at X + 0.214*XA, so |D-X|/XA is ~0.214, not 0.786 -- the
        # abs(d.price - x.price) formula could never match the intended
        # ratio). Confirmed via direct testing: zero pattern matches across
        # ~500K real candles spanning 5 instruments/timeframes, even after
        # sweeping both the match tolerance (0.06 up to 0.12) and the
        # swing-detection lookback (3 to 20) independently -- a clean zero
        # under every configuration was the tell that this was a formula
        # bug, not genuine real-world rarity.
        ad = abs(a.price - d.price)
        if xa == 0 or ab == 0 or bc == 0:
            continue

        ab_xa, bc_ab, cd_bc, ad_xa = ab / xa, bc / ab, cd / bc, ad / xa

        for name, ratios in _PATTERNS.items():
            if (_in_range(ab_xa, ratios["ab_xa"]) and _in_range(bc_ab, ratios["bc_ab"])
                    and _in_range(cd_bc, ratios["cd_bc"]) and _in_range(ad_xa, ratios["ad_xa"])):
                patterns.append(HarmonicPattern(
                    name=name, direction="bullish" if bullish else "bearish",
                    x_index=x.index, a_index=a.index, b_index=b.index, c_index=c.index, d_index=d.index,
                    x_price=x.price, a_price=a.price, b_price=b.price, c_price=c.price, d_price=d.price,
                    ab_xa_ratio=round(ab_xa, 3), bc_ab_ratio=round(bc_ab, 3),
                    cd_bc_ratio=round(cd_bc, 3), ad_xa_ratio=round(ad_xa, 3),
                ))

    return patterns
