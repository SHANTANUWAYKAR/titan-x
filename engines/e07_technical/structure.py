"""
Module: structure.py
Description: Shared swing-point detection for e07_technical's structural
    methodologies (Smart Money Concepts, Wyckoff, Harmonics) -- each reads
    the market through the same confirmed swing highs/lows rather than
    re-deriving its own notion of "pivot," so a swing point means the same
    thing everywhere it's used.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd


class SwingKind(str, Enum):
    HIGH = "high"
    LOW = "low"


@dataclass
class SwingPoint:
    index: int  # integer position in the DataFrame (iloc-style, not a label)
    price: float
    kind: SwingKind


def find_swing_points(df: pd.DataFrame, lookback: int = 5) -> list[SwingPoint]:
    """A candle at position i is a confirmed swing high/low if its high/low
    is the max/min within [i-lookback, i+lookback] (a centered window --
    confirmation is necessarily `lookback` bars delayed, the same
    unavoidable lag every swing-based method accepts, including the
    engine's pre-existing _detect_market_structure). Returns points in
    chronological order; a candle can register as both a swing high and
    low (rare, e.g. a single extreme spike candle) and appears twice.
    """
    window = lookback * 2 + 1
    if len(df) < window:
        return []
    highs, lows = df["high"], df["low"]
    is_high = highs == highs.rolling(window, center=True).max()
    is_low = lows == lows.rolling(window, center=True).min()
    points: list[SwingPoint] = []
    for i in range(len(df)):
        if bool(is_high.iloc[i]):
            points.append(SwingPoint(index=i, price=float(highs.iloc[i]), kind=SwingKind.HIGH))
        if bool(is_low.iloc[i]):
            points.append(SwingPoint(index=i, price=float(lows.iloc[i]), kind=SwingKind.LOW))
    points.sort(key=lambda p: p.index)
    return points


def alternate_swings(points: list[SwingPoint]) -> list[SwingPoint]:
    """Collapses consecutive same-kind swing points down to only the most
    extreme one (e.g. two swing highs with no swing low between them ->
    keep only the higher), producing a clean alternating high/low/high/low
    sequence. Harmonic pattern detection specifically requires this
    (X-A-B-C-D must strictly alternate); BOS/CHoCH benefit from it too --
    without it, a minor intermediate pivot could register a spurious
    structure break before the real, more extreme swing is reached."""
    if not points:
        return []
    result: list[SwingPoint] = [points[0]]
    for p in points[1:]:
        if p.kind == result[-1].kind:
            is_more_extreme = (
                p.price > result[-1].price if p.kind == SwingKind.HIGH
                else p.price < result[-1].price
            )
            if is_more_extreme:
                result[-1] = p
        else:
            result.append(p)
    return result
