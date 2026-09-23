"""
Module: chart_patterns.py
Description: Classical chart-pattern geometry -- every century-old,
    public-domain multi-swing PRICE STRUCTURE pattern this codebase's
    swing-point primitives can support without curve-fitting: Head &
    Shoulders (+ inverse), Double/Triple Top/Bottom, the three standard
    Triangles (ascending, descending, symmetrical), Rising/Falling
    Wedges, Broadening Formations, Rectangles, Diamond Top/Bottom,
    Bull/Bear Flags and Pennants, and Rounding Top/Bottom + Cup and
    Handle. Distinct from single/multi-candle patterns like doji/
    engulfing (covered elsewhere in this platform) and from Fibonacci-
    ratio harmonic patterns (harmonics.py). Built on the SAME shared
    swing-point primitives (structure.py's find_swing_points/
    alternate_swings) every other structural method in this package
    already uses, so a "swing" means the same thing here as it does in
    Smart Money Concepts, Wyckoff, and Harmonics.

    Original scope (2026-09-13): H&S, double top/bottom, triangles.
    Expanded 2026-09-14 to the full classical set above, per explicit
    instruction to cover "all types of patterns" -- each new family
    reuses the exact same detection style, extended only where the
    pattern's own definition genuinely requires it (see each function's
    own docstring): triple top/bottom mirrors H&S's window with an
    "all equal" instead of "middle taller" classification; wedges/
    broadening formations/rectangles reuse triangles' 4-point window
    with different slope-sign criteria; diamonds chain two such windows
    (broadening then converging); flags/pennants require a genuine
    impulsive move (the flagpole) INTO a small consolidation, so
    direction comes from the pole, not the consolidation shape; rounding
    patterns/cup and handle are an honest discrete-point APPROXIMATION of
    what's really a smooth curve in real chart reading -- no curve-
    fitting, only depth/equality checks on the same swing points.

    Every family is detected the same general way: walk the alternating
    swing sequence looking for a specific count/kind of consecutive
    points whose PRICES satisfy the pattern's defining relationship,
    expressed with an ATR-relative tolerance rather than a fixed price
    band -- same reasoning FVG's own min_gap_atr_multiple already
    documents (a fixed tolerance tuned for one instrument becomes
    trivially loose or tight on another with a very different price
    scale). A pattern is reported as UNCONFIRMED until a later bar's
    CLOSE actually breaks the pattern's own neckline/trendline (a mere
    wick is a test, not a break -- same "close, not wick" precision
    standard detect_liquidity_sweeps and detect_order_blocks already use)
    -- `confirmed=False` patterns are real, currently-forming structures,
    not yet-tradeable setups; `confirmed_index` marks exactly which bar
    closed the break for the ones that are. The one exception is
    Rectangle (see detect_rectangles' own docstring): a range with no
    resolved bias isn't reported at all until it actually breaks one way
    or the other, unlike every reversal/continuation pattern here.

    Strictly causal by construction: every field on a pattern is
    computable from bars up to and including the bar being evaluated
    (swing points are themselves lookback-delayed by construction, same
    unavoidable lag structure.py's own docstring already names, and
    confirmation only ever looks forward from the pattern's last swing
    point to the bar where the break is found, never backward).

    NOT wired into E51's confluence scoring: the original 3 families
    were built, tested, and ablated (research/concept_ablation.py) but
    NOT promoted to a live confluence weight -- the IC measurement showed
    mixed/inconclusive predictive value (see CLAUDE.md's dated entry).
    These 7 new families inherit the same "measure before promoting"
    discipline: they run through the same ablation harness (the
    "chart_pattern" concept there already calls detect_chart_patterns()
    generically, so nothing there needed updating), but wiring any of
    them into a live scored signal requires a fresh, honest IC
    measurement first, not an assumption that more pattern coverage means
    more predictive signal.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import numpy as np
import pandas as pd

from project_titan_x.engines.e07_technical.smart_money import _average_true_range
from project_titan_x.engines.e07_technical.structure import SwingKind, SwingPoint, alternate_swings, find_swing_points


class ChartPatternKind(str, Enum):
    HEAD_AND_SHOULDERS = "head_and_shoulders"
    INVERSE_HEAD_AND_SHOULDERS = "inverse_head_and_shoulders"
    DOUBLE_TOP = "double_top"
    DOUBLE_BOTTOM = "double_bottom"
    TRIPLE_TOP = "triple_top"
    TRIPLE_BOTTOM = "triple_bottom"
    ASCENDING_TRIANGLE = "ascending_triangle"
    DESCENDING_TRIANGLE = "descending_triangle"
    SYMMETRICAL_TRIANGLE = "symmetrical_triangle"
    RISING_WEDGE = "rising_wedge"
    FALLING_WEDGE = "falling_wedge"
    BROADENING_FORMATION = "broadening_formation"
    RECTANGLE_BULLISH = "rectangle_bullish"  # a trading range that broke out UP
    RECTANGLE_BEARISH = "rectangle_bearish"  # a trading range that broke out DOWN
    DIAMOND_TOP = "diamond_top"
    DIAMOND_BOTTOM = "diamond_bottom"
    BULL_FLAG = "bull_flag"
    BEAR_FLAG = "bear_flag"
    BULL_PENNANT = "bull_pennant"
    BEAR_PENNANT = "bear_pennant"
    ROUNDING_BOTTOM = "rounding_bottom"
    ROUNDING_TOP = "rounding_top"
    CUP_AND_HANDLE = "cup_and_handle"


@dataclass
class ChartPattern:
    kind: ChartPatternKind
    direction: str  # "bullish" / "bearish" -- the expected move ONCE confirmed; a triangle's own
                     # direction is left as the prior trend's direction where the pattern itself
                     # doesn't determine it (symmetrical triangle -- see detect_triangles)
    point_indices: list[int]  # the swing points that define the pattern, in chronological order
    point_prices: list[float]
    breakout_level: float  # neckline (H&S) / valley-or-peak (double top/bottom) / trendline price at the last point (triangle)
    target_price: float  # classic measured-move projection from the breakout level
    confirmed: bool
    confirmed_index: Optional[int]  # bar index whose CLOSE broke the level; None if not yet confirmed


# ATR multiple within which two swing prices count as "approximately
# equal" (double top/bottom peaks, or H&S's two shoulders) -- wide enough
# that real price data (which essentially never revisits an exact prior
# level) still registers a match, narrow enough that two swings from
# genuinely different price regimes don't get treated as the same level.
EQUALITY_ATR_MULTIPLE = 0.75
ATR_PERIOD = 14


def _atr_tolerance(atr: np.ndarray, index: int, multiple: float) -> float:
    value = atr[index]
    return float(value) * multiple if value == value else 0.0  # value==value is a NaN check


def _approximately_equal(price_a: float, price_b: float, tolerance: float) -> bool:
    return abs(price_a - price_b) <= tolerance


def _closes_beyond(closes: np.ndarray, from_index: int, level: float, direction: str) -> Optional[int]:
    """First bar AFTER from_index whose CLOSE breaks `level` in `direction`
    ("below" or "above"). Returns None if no such bar exists yet (pattern
    still forming/unconfirmed as of the last available bar)."""
    for i in range(from_index + 1, len(closes)):
        if direction == "below" and closes[i] < level:
            return i
        if direction == "above" and closes[i] > level:
            return i
    return None


def detect_head_and_shoulders(
    df: pd.DataFrame, lookback: int = 5, swings: Optional[list[SwingPoint]] = None, atr_period: int = ATR_PERIOD,
) -> list[ChartPattern]:
    """Bearish Head & Shoulders: high-low-high-low-high where the middle
    high (the head) exceeds both flanking highs (the shoulders), and the
    two shoulders are approximately equal. The neckline connects the two
    intervening lows -- NOT necessarily horizontal (a sloped neckline is
    standard and expected in real data); the breakout level used here is
    the neckline's own price at the second (right) low, which is what
    price actually has to close through after the right shoulder forms.
    Confirmed on a close below that level; target is the neckline level
    at confirmation minus the head's height above the neckline at the
    right low -- the standard "measured move" projection.

    Inverse Head & Shoulders (bullish) is the exact mirror: low-high-low-
    high-low, head below both shoulders, neckline connects the highs,
    confirms on a close above it, target projects upward."""
    if swings is None:
        swings = alternate_swings(find_swing_points(df, lookback))
    closes = df["close"].to_numpy(float)
    atr = _average_true_range(df, atr_period).to_numpy(float)
    patterns: list[ChartPattern] = []

    for i in range(len(swings) - 4):
        window = swings[i:i + 5]
        kinds = [p.kind for p in window]

        if kinds == [SwingKind.HIGH, SwingKind.LOW, SwingKind.HIGH, SwingKind.LOW, SwingKind.HIGH]:
            left_shoulder, left_trough, head, right_trough, right_shoulder = window
            tol = _atr_tolerance(atr, right_shoulder.index, EQUALITY_ATR_MULTIPLE)
            if (
                head.price > left_shoulder.price and head.price > right_shoulder.price
                and _approximately_equal(left_shoulder.price, right_shoulder.price, tol)
            ):
                neckline = right_trough.price
                confirmed_idx = _closes_beyond(closes, right_shoulder.index, neckline, "below")
                target = neckline - (head.price - neckline)
                patterns.append(ChartPattern(
                    kind=ChartPatternKind.HEAD_AND_SHOULDERS, direction="bearish",
                    point_indices=[p.index for p in window], point_prices=[p.price for p in window],
                    breakout_level=neckline, target_price=target,
                    confirmed=confirmed_idx is not None, confirmed_index=confirmed_idx,
                ))

        elif kinds == [SwingKind.LOW, SwingKind.HIGH, SwingKind.LOW, SwingKind.HIGH, SwingKind.LOW]:
            left_shoulder, left_peak, head, right_peak, right_shoulder = window
            tol = _atr_tolerance(atr, right_shoulder.index, EQUALITY_ATR_MULTIPLE)
            if (
                head.price < left_shoulder.price and head.price < right_shoulder.price
                and _approximately_equal(left_shoulder.price, right_shoulder.price, tol)
            ):
                neckline = right_peak.price
                confirmed_idx = _closes_beyond(closes, right_shoulder.index, neckline, "above")
                target = neckline + (neckline - head.price)
                patterns.append(ChartPattern(
                    kind=ChartPatternKind.INVERSE_HEAD_AND_SHOULDERS, direction="bullish",
                    point_indices=[p.index for p in window], point_prices=[p.price for p in window],
                    breakout_level=neckline, target_price=target,
                    confirmed=confirmed_idx is not None, confirmed_index=confirmed_idx,
                ))

    return patterns


def detect_double_top_bottom(
    df: pd.DataFrame, lookback: int = 5, swings: Optional[list[SwingPoint]] = None, atr_period: int = ATR_PERIOD,
) -> list[ChartPattern]:
    """Double Top: two swing highs at approximately the same price,
    separated by exactly one intervening swing low (the "valley").
    Confirms on a close below the valley; target projects the peak-to-
    valley distance downward from the valley. Double Bottom mirrors this
    with two approximately-equal swing lows around one intervening high."""
    if swings is None:
        swings = alternate_swings(find_swing_points(df, lookback))
    closes = df["close"].to_numpy(float)
    atr = _average_true_range(df, atr_period).to_numpy(float)
    patterns: list[ChartPattern] = []

    for i in range(len(swings) - 2):
        first, middle, second = swings[i], swings[i + 1], swings[i + 2]
        tol = _atr_tolerance(atr, second.index, EQUALITY_ATR_MULTIPLE)

        if first.kind == SwingKind.HIGH and middle.kind == SwingKind.LOW and second.kind == SwingKind.HIGH:
            if _approximately_equal(first.price, second.price, tol) and middle.price < first.price and middle.price < second.price:
                valley = middle.price
                confirmed_idx = _closes_beyond(closes, second.index, valley, "below")
                target = valley - (max(first.price, second.price) - valley)
                patterns.append(ChartPattern(
                    kind=ChartPatternKind.DOUBLE_TOP, direction="bearish",
                    point_indices=[first.index, middle.index, second.index],
                    point_prices=[first.price, middle.price, second.price],
                    breakout_level=valley, target_price=target,
                    confirmed=confirmed_idx is not None, confirmed_index=confirmed_idx,
                ))

        elif first.kind == SwingKind.LOW and middle.kind == SwingKind.HIGH and second.kind == SwingKind.LOW:
            if _approximately_equal(first.price, second.price, tol) and middle.price > first.price and middle.price > second.price:
                peak = middle.price
                confirmed_idx = _closes_beyond(closes, second.index, peak, "above")
                target = peak + (peak - min(first.price, second.price))
                patterns.append(ChartPattern(
                    kind=ChartPatternKind.DOUBLE_BOTTOM, direction="bullish",
                    point_indices=[first.index, middle.index, second.index],
                    point_prices=[first.price, middle.price, second.price],
                    breakout_level=peak, target_price=target,
                    confirmed=confirmed_idx is not None, confirmed_index=confirmed_idx,
                ))

    return patterns


# A trendline through 2 points counts as "flat" if its slope, expressed
# in ATR-per-bar, is smaller than this -- i.e. materially indistinguishable
# from horizontal given the instrument's own recent volatility, rather
# than judged against an arbitrary fixed price-per-bar slope that would
# be meaningless across instruments of very different scale.
FLAT_SLOPE_ATR_FRACTION = 0.05


def _slope_atr_per_bar(p1: SwingPoint, p2: SwingPoint, atr: np.ndarray) -> float:
    bars = p2.index - p1.index
    if bars <= 0:
        return 0.0
    segment = atr[p1.index:p2.index + 1]
    if np.isnan(segment).all():
        # Both points sit inside ATR's own warmup window (its first
        # `atr_period` bars are NaN by construction) -- same "not warmed
        # up yet, skip rather than guess" convention detect_fair_value_
        # gaps' own ATR-relative filter already uses. np.nanmean would
        # otherwise emit a RuntimeWarning for an all-NaN slice.
        return 0.0
    mean_atr = np.nanmean(segment)
    if not mean_atr or mean_atr != mean_atr:
        return 0.0
    return (p2.price - p1.price) / bars / mean_atr


def detect_triple_top_bottom(
    df: pd.DataFrame, lookback: int = 5, swings: Optional[list[SwingPoint]] = None, atr_period: int = ATR_PERIOD,
) -> list[ChartPattern]:
    """Triple Top: three swing highs all approximately equal (unlike H&S,
    no single peak needs to stand taller), separated by two intervening
    swing lows -- same high-low-high-low-high shape detect_head_and_
    shoulders scans, but classified by "all three peaks roughly level"
    instead of "middle peak taller than both flanks." A window that
    already qualifies as H&S is NOT also reported as a triple top (the
    two classifications are mutually exclusive by definition -- a taller
    head means the peaks are NOT all equal), so a caller combining both
    detectors' output never sees double-counted, contradictory patterns
    over the same 5 points.

    Confirms on a close below the lower of the two intervening lows (the
    weaker support -- price only needs to break the easier level to
    invalidate the range), target projects the peak-to-support distance
    downward from that level. Triple Bottom mirrors this with three
    approximately-equal lows and two intervening highs."""
    if swings is None:
        swings = alternate_swings(find_swing_points(df, lookback))
    closes = df["close"].to_numpy(float)
    atr = _average_true_range(df, atr_period).to_numpy(float)
    patterns: list[ChartPattern] = []

    for i in range(len(swings) - 4):
        window = swings[i:i + 5]
        kinds = [p.kind for p in window]

        if kinds == [SwingKind.HIGH, SwingKind.LOW, SwingKind.HIGH, SwingKind.LOW, SwingKind.HIGH]:
            p1, t1, p2, t2, p3 = window
            tol = _atr_tolerance(atr, p3.index, EQUALITY_ATR_MULTIPLE)
            all_equal = (
                _approximately_equal(p1.price, p2.price, tol)
                and _approximately_equal(p2.price, p3.price, tol)
                and _approximately_equal(p1.price, p3.price, tol)
            )
            if all_equal and t1.price < min(p1.price, p2.price, p3.price) and t2.price < min(p1.price, p2.price, p3.price):
                support = min(t1.price, t2.price)
                confirmed_idx = _closes_beyond(closes, p3.index, support, "below")
                target = support - (max(p1.price, p2.price, p3.price) - support)
                patterns.append(ChartPattern(
                    kind=ChartPatternKind.TRIPLE_TOP, direction="bearish",
                    point_indices=[p.index for p in window], point_prices=[p.price for p in window],
                    breakout_level=support, target_price=target,
                    confirmed=confirmed_idx is not None, confirmed_index=confirmed_idx,
                ))

        elif kinds == [SwingKind.LOW, SwingKind.HIGH, SwingKind.LOW, SwingKind.HIGH, SwingKind.LOW]:
            t1, p1, t2, p2, t3 = window
            tol = _atr_tolerance(atr, t3.index, EQUALITY_ATR_MULTIPLE)
            all_equal = (
                _approximately_equal(t1.price, t2.price, tol)
                and _approximately_equal(t2.price, t3.price, tol)
                and _approximately_equal(t1.price, t3.price, tol)
            )
            if all_equal and p1.price > max(t1.price, t2.price, t3.price) and p2.price > max(t1.price, t2.price, t3.price):
                resistance = max(p1.price, p2.price)
                confirmed_idx = _closes_beyond(closes, t3.index, resistance, "above")
                target = resistance + (resistance - min(t1.price, t2.price, t3.price))
                patterns.append(ChartPattern(
                    kind=ChartPatternKind.TRIPLE_BOTTOM, direction="bullish",
                    point_indices=[p.index for p in window], point_prices=[p.price for p in window],
                    breakout_level=resistance, target_price=target,
                    confirmed=confirmed_idx is not None, confirmed_index=confirmed_idx,
                ))

    return patterns


def detect_wedges(
    df: pd.DataFrame, lookback: int = 5, swings: Optional[list[SwingPoint]] = None, atr_period: int = ATR_PERIOD,
) -> list[ChartPattern]:
    """Same 4-point (2 highs + 2 lows) structure detect_triangles scans,
    classified differently: a wedge needs BOTH trendlines sloping the
    SAME direction (unlike a triangle, where at least one line is flat or
    they slope opposite ways) while still converging.

    Rising wedge: both lines rise, but the LOWER (support) line rises
    faster than the upper (resistance) line, so the channel still narrows
    even though price is climbing -- the classic "reluctant" climb on
    thinning momentum. Despite the upward slope, this is a BEARISH
    pattern (a well-known TA counterintuition every reference on wedges
    names explicitly) -- it typically resolves with a downside break of
    the (faster-rising) support line.

    Falling wedge mirrors this: both lines fall, but the UPPER
    (resistance) line falls faster than support, narrowing the channel on
    the way down. BULLISH -- typically resolves with an upside break of
    resistance.

    Breakout level and target use the same "measured move from the
    formation's own widest point" convention as detect_triangles."""
    if swings is None:
        swings = alternate_swings(find_swing_points(df, lookback))
    closes = df["close"].to_numpy(float)
    atr = _average_true_range(df, atr_period).to_numpy(float)
    patterns: list[ChartPattern] = []

    for i in range(len(swings) - 3):
        window = swings[i:i + 4]
        kinds = [p.kind for p in window]

        if kinds == [SwingKind.HIGH, SwingKind.LOW, SwingKind.HIGH, SwingKind.LOW]:
            h1, l1, h2, l2 = window
        elif kinds == [SwingKind.LOW, SwingKind.HIGH, SwingKind.LOW, SwingKind.HIGH]:
            l1, h1, l2, h2 = window
        else:
            continue

        high_slope = _slope_atr_per_bar(h1, h2, atr)
        low_slope = _slope_atr_per_bar(l1, l2, atr)
        highs_rising = high_slope > FLAT_SLOPE_ATR_FRACTION
        lows_rising = low_slope > FLAT_SLOPE_ATR_FRACTION
        highs_falling = high_slope < -FLAT_SLOPE_ATR_FRACTION
        lows_falling = low_slope < -FLAT_SLOPE_ATR_FRACTION

        last_index = max(h2.index, l2.index)
        kind: Optional[ChartPatternKind] = None
        direction = ""
        breakout_level = 0.0

        if highs_rising and lows_rising and low_slope > high_slope:
            kind = ChartPatternKind.RISING_WEDGE
            direction = "bearish"
            breakout_level = l2.price
        elif highs_falling and lows_falling and high_slope < low_slope:
            kind = ChartPatternKind.FALLING_WEDGE
            direction = "bullish"
            breakout_level = h2.price

        if kind is None:
            continue

        break_direction = "above" if direction == "bullish" else "below"
        confirmed_idx = _closes_beyond(closes, last_index, breakout_level, break_direction)
        height = abs(h1.price - l1.price)
        target = breakout_level + height if direction == "bullish" else breakout_level - height

        patterns.append(ChartPattern(
            kind=kind, direction=direction,
            point_indices=[p.index for p in window], point_prices=[p.price for p in window],
            breakout_level=breakout_level, target_price=target,
            confirmed=confirmed_idx is not None, confirmed_index=confirmed_idx,
        ))

    return patterns


def detect_broadening_formations(
    df: pd.DataFrame, lookback: int = 5, swings: Optional[list[SwingPoint]] = None, atr_period: int = ATR_PERIOD,
) -> list[ChartPattern]:
    """The mirror image of detect_triangles: same 4-point structure, but
    highs RISING and lows FALLING -- the range widens instead of
    narrowing (a "megaphone"). Reflects genuinely increasing disagreement/
    volatility rather than consolidation, so unlike a triangle it carries
    no directional bias of its own -- `direction` reports the prior
    trend as a weak prior only, same convention detect_triangles already
    uses for the symmetrical case, and confirmation checks BOTH edges
    (whichever the close actually breaks first), not one assumed side."""
    if swings is None:
        swings = alternate_swings(find_swing_points(df, lookback))
    closes = df["close"].to_numpy(float)
    atr = _average_true_range(df, atr_period).to_numpy(float)
    patterns: list[ChartPattern] = []

    for i in range(len(swings) - 3):
        window = swings[i:i + 4]
        kinds = [p.kind for p in window]

        if kinds == [SwingKind.HIGH, SwingKind.LOW, SwingKind.HIGH, SwingKind.LOW]:
            h1, l1, h2, l2 = window
            prior_trend = "bearish"
        elif kinds == [SwingKind.LOW, SwingKind.HIGH, SwingKind.LOW, SwingKind.HIGH]:
            l1, h1, l2, h2 = window
            prior_trend = "bullish"
        else:
            continue

        high_slope = _slope_atr_per_bar(h1, h2, atr)
        low_slope = _slope_atr_per_bar(l1, l2, atr)
        if not (high_slope > FLAT_SLOPE_ATR_FRACTION and low_slope < -FLAT_SLOPE_ATR_FRACTION):
            continue

        last_index = max(h2.index, l2.index)
        upper_break = _closes_beyond(closes, last_index, h2.price, "above")
        lower_break = _closes_beyond(closes, last_index, l2.price, "below")
        if upper_break is not None and (lower_break is None or upper_break <= lower_break):
            confirmed_idx, direction, breakout_level = upper_break, "bullish", h2.price
        elif lower_break is not None:
            confirmed_idx, direction, breakout_level = lower_break, "bearish", l2.price
        else:
            confirmed_idx, direction, breakout_level = None, prior_trend, h2.price

        height = abs(h1.price - l1.price)
        target = breakout_level + height if direction == "bullish" else breakout_level - height
        patterns.append(ChartPattern(
            kind=ChartPatternKind.BROADENING_FORMATION, direction=direction,
            point_indices=[p.index for p in window], point_prices=[p.price for p in window],
            breakout_level=breakout_level, target_price=target,
            confirmed=confirmed_idx is not None, confirmed_index=confirmed_idx,
        ))

    return patterns


def detect_rectangles(
    df: pd.DataFrame, lookback: int = 5, swings: Optional[list[SwingPoint]] = None, atr_period: int = ATR_PERIOD,
) -> list[ChartPattern]:
    """A horizontal trading range: 2 swing highs approximately equal
    (resistance) AND 2 swing lows approximately equal (support), same
    4-point structure as detect_triangles/detect_wedges but with BOTH
    lines flat instead of sloped. A rectangle carries no directional bias
    of its own -- it only reports a pattern once price actually closes
    beyond one of the two flat levels, checking both (RECTANGLE_BULLISH
    on an upside break, RECTANGLE_BEARISH on a downside break), same
    "check whichever edge breaks first" approach detect_broadening_
    formations uses for its own direction-agnostic shape."""
    if swings is None:
        swings = alternate_swings(find_swing_points(df, lookback))
    closes = df["close"].to_numpy(float)
    atr = _average_true_range(df, atr_period).to_numpy(float)
    patterns: list[ChartPattern] = []

    for i in range(len(swings) - 3):
        window = swings[i:i + 4]
        kinds = [p.kind for p in window]

        if kinds == [SwingKind.HIGH, SwingKind.LOW, SwingKind.HIGH, SwingKind.LOW]:
            h1, l1, h2, l2 = window
        elif kinds == [SwingKind.LOW, SwingKind.HIGH, SwingKind.LOW, SwingKind.HIGH]:
            l1, h1, l2, h2 = window
        else:
            continue

        tol = _atr_tolerance(atr, max(h2.index, l2.index), EQUALITY_ATR_MULTIPLE)
        if not (_approximately_equal(h1.price, h2.price, tol) and _approximately_equal(l1.price, l2.price, tol)):
            continue
        resistance, support = max(h1.price, h2.price), min(l1.price, l2.price)
        if resistance <= support:
            continue

        last_index = max(h2.index, l2.index)
        upper_break = _closes_beyond(closes, last_index, resistance, "above")
        lower_break = _closes_beyond(closes, last_index, support, "below")
        height = resistance - support

        if upper_break is not None and (lower_break is None or upper_break <= lower_break):
            patterns.append(ChartPattern(
                kind=ChartPatternKind.RECTANGLE_BULLISH, direction="bullish",
                point_indices=[p.index for p in window], point_prices=[p.price for p in window],
                breakout_level=resistance, target_price=resistance + height,
                confirmed=True, confirmed_index=upper_break,
            ))
        elif lower_break is not None:
            patterns.append(ChartPattern(
                kind=ChartPatternKind.RECTANGLE_BEARISH, direction="bearish",
                point_indices=[p.index for p in window], point_prices=[p.price for p in window],
                breakout_level=support, target_price=support - height,
                confirmed=True, confirmed_index=lower_break,
            ))
        # Still forming (neither level broken yet): deliberately not
        # reported at all, unlike every other pattern here that reports
        # an unconfirmed instance -- a rectangle with no bias of its own
        # is just "price is ranging," not yet a structure worth surfacing
        # until it actually resolves one way or the other.

    return patterns


def detect_diamonds(
    df: pd.DataFrame, lookback: int = 5, swings: Optional[list[SwingPoint]] = None, atr_period: int = ATR_PERIOD,
) -> list[ChartPattern]:
    """A broadening formation immediately followed by a converging one --
    6 consecutive swing points shaped like a diamond on the chart: narrow,
    widening, then narrowing back down before the breakout. Built from
    the SAME slope primitives as detect_broadening_formations/detect_
    triangles, just applied to two adjacent 4-point sub-windows sharing
    their middle 2 points (points 0-3 must broaden, points 2-5 must
    converge).

    Diamond Top (points 0-3 bearish-broadening shape, i.e. starting
    high-low-..., widening then narrowing) is a bearish reversal of a
    prior uptrend, confirming on a close below the final converging low.
    Diamond Bottom mirrors this as a bullish reversal. Target uses the
    diamond's own widest vertical extent (the broadening half's height),
    projected from the breakout level -- the standard measured-move
    convention every other formation in this file already uses."""
    if swings is None:
        swings = alternate_swings(find_swing_points(df, lookback))
    closes = df["close"].to_numpy(float)
    atr = _average_true_range(df, atr_period).to_numpy(float)
    patterns: list[ChartPattern] = []

    for i in range(len(swings) - 5):
        window = swings[i:i + 6]
        kinds = [p.kind for p in window]

        if kinds == [SwingKind.HIGH, SwingKind.LOW, SwingKind.HIGH, SwingKind.LOW, SwingKind.HIGH, SwingKind.LOW]:
            h1, l1, h2, l2, h3, l3 = window
            direction = "bearish"
            kind = ChartPatternKind.DIAMOND_TOP
        elif kinds == [SwingKind.LOW, SwingKind.HIGH, SwingKind.LOW, SwingKind.HIGH, SwingKind.LOW, SwingKind.HIGH]:
            l1, h1, l2, h2, l3, h3 = window
            direction = "bullish"
            kind = ChartPatternKind.DIAMOND_BOTTOM
        else:
            continue

        broadening = _slope_atr_per_bar(h1, h2, atr) > FLAT_SLOPE_ATR_FRACTION and _slope_atr_per_bar(l1, l2, atr) < -FLAT_SLOPE_ATR_FRACTION
        converging = _slope_atr_per_bar(h2, h3, atr) < -FLAT_SLOPE_ATR_FRACTION and _slope_atr_per_bar(l2, l3, atr) > FLAT_SLOPE_ATR_FRACTION
        if not (broadening and converging):
            continue

        last_index = max(h3.index, l3.index)
        breakout_level = l3.price if direction == "bearish" else h3.price
        break_direction = "below" if direction == "bearish" else "above"
        confirmed_idx = _closes_beyond(closes, last_index, breakout_level, break_direction)
        height = max(h1.price, h2.price) - min(l1.price, l2.price)
        target = breakout_level - height if direction == "bearish" else breakout_level + height

        patterns.append(ChartPattern(
            kind=kind, direction=direction,
            point_indices=[p.index for p in window], point_prices=[p.price for p in window],
            breakout_level=breakout_level, target_price=target,
            confirmed=confirmed_idx is not None, confirmed_index=confirmed_idx,
        ))

    return patterns


# A single swing-to-swing leg counts as a "flagpole" (the strong impulsive
# move a flag/pennant consolidates after) if it covers at least this many
# ATRs -- a real, sharp move, not routine chop. Loosely calibrated against
# the same kind of "meaningfully larger than typical noise" reasoning
# EQUALITY_ATR_MULTIPLE already documents, just for magnitude instead of
# equality.
FLAGPOLE_ATR_MULTIPLE = 3.0


def detect_flags_pennants(
    df: pd.DataFrame, lookback: int = 5, swings: Optional[list[SwingPoint]] = None, atr_period: int = ATR_PERIOD,
) -> list[ChartPattern]:
    """Continuation patterns: a sharp impulsive move (the flagpole) into
    the FIRST point of a 4-point consolidation structure, where the
    consolidation itself is either a small channel (flag -- reuses the
    same "both lines slope the same, non-diverging way" shape as
    detect_wedges, but the direction test is against the flagpole, not
    the lines' own slope sign) or a small symmetrical taper (pennant --
    reuses detect_triangles' converging-lines shape). Direction is always
    the FLAGPOLE's direction (continuation, by definition) -- the
    consolidation itself never determines it, unlike every reversal
    pattern above.

    Confirms on a close beyond the consolidation's exit point in the
    flagpole's direction. Target is the classic "flagpole height
    projected from the breakout" measured move -- consolidations are by
    definition small, so (unlike the reversal patterns above) the
    formation's OWN height would understate the real expected move."""
    if swings is None:
        swings = alternate_swings(find_swing_points(df, lookback))
    closes = df["close"].to_numpy(float)
    atr = _average_true_range(df, atr_period).to_numpy(float)
    patterns: list[ChartPattern] = []

    for i in range(len(swings) - 4):
        pole_start, h1_or_l1 = swings[i], swings[i + 1]
        window = swings[i + 1:i + 5]
        kinds = [p.kind for p in window]
        if kinds not in (
            [SwingKind.HIGH, SwingKind.LOW, SwingKind.HIGH, SwingKind.LOW],
            [SwingKind.LOW, SwingKind.HIGH, SwingKind.LOW, SwingKind.HIGH],
        ):
            continue
        if kinds[0] == SwingKind.HIGH:
            h1, l1, h2, l2 = window
        else:
            l1, h1, l2, h2 = window

        pole_bars = h1_or_l1.index - pole_start.index
        pole_tol = _atr_tolerance(atr, h1_or_l1.index, FLAGPOLE_ATR_MULTIPLE)
        pole_move = h1_or_l1.price - pole_start.price
        if pole_bars <= 0 or abs(pole_move) < pole_tol:
            continue
        pole_direction = "bullish" if pole_move > 0 else "bearish"

        high_slope = _slope_atr_per_bar(h1, h2, atr)
        low_slope = _slope_atr_per_bar(l1, l2, atr)
        converging = (
            (high_slope < -FLAT_SLOPE_ATR_FRACTION and low_slope > FLAT_SLOPE_ATR_FRACTION)
            or (abs(high_slope) < FLAT_SLOPE_ATR_FRACTION and abs(low_slope) < FLAT_SLOPE_ATR_FRACTION)
        )
        # A flagpole INTO a consolidation that itself still extends further
        # in the pole's own direction isn't a pause, it's just more trend --
        # a real flag's channel drifts flat-to-slightly-against the pole,
        # never further with it. Only applies to the FLAG (channel) shape,
        # not a converging PENNANT taper: a pennant's own support line
        # rising after a bullish pole (or resistance falling after a
        # bearish one) is normal converging-taper geometry, not "still
        # trending" -- real bug found while constructing this detector's
        # own tests, a textbook bull-pennant construction was silently
        # rejected here before this `not converging` guard was added.
        drifting_with_pole = not converging and (
            (pole_direction == "bullish" and low_slope > FLAT_SLOPE_ATR_FRACTION)
            or (pole_direction == "bearish" and high_slope < -FLAT_SLOPE_ATR_FRACTION)
        )
        if drifting_with_pole:
            continue

        last_index = max(h2.index, l2.index)
        breakout_level = h2.price if pole_direction == "bullish" else l2.price
        break_direction = "above" if pole_direction == "bullish" else "below"
        confirmed_idx = _closes_beyond(closes, last_index, breakout_level, break_direction)
        pole_height = abs(pole_move)
        target = breakout_level + pole_height if pole_direction == "bullish" else breakout_level - pole_height

        if converging and abs(high_slope) < FLAT_SLOPE_ATR_FRACTION * 3 and abs(low_slope) < FLAT_SLOPE_ATR_FRACTION * 3 and high_slope < -FLAT_SLOPE_ATR_FRACTION and low_slope > FLAT_SLOPE_ATR_FRACTION:
            kind = ChartPatternKind.BULL_PENNANT if pole_direction == "bullish" else ChartPatternKind.BEAR_PENNANT
        else:
            kind = ChartPatternKind.BULL_FLAG if pole_direction == "bullish" else ChartPatternKind.BEAR_FLAG

        patterns.append(ChartPattern(
            kind=kind, direction=pole_direction,
            point_indices=[pole_start.index] + [p.index for p in window],
            point_prices=[pole_start.price] + [p.price for p in window],
            breakout_level=breakout_level, target_price=target,
            confirmed=confirmed_idx is not None, confirmed_index=confirmed_idx,
        ))

    return patterns


# How far below/above the two rim swings the trough/peak must sit (in ATR)
# to count as a genuine cup/rounding depth, not just routine noise between
# two similar-priced swings that happens to alternate high-low-high.
ROUNDING_DEPTH_ATR_MULTIPLE = 2.0
# A handle's own pullback must stay shallower than this fraction of the
# cup's full depth -- a real handle is a shallow flag-like dip near the
# rim, not a retest of the cup's own low (which would make it a double
# bottom, not a handle).
HANDLE_MAX_DEPTH_FRACTION = 0.5


def detect_rounding_patterns(
    df: pd.DataFrame, lookback: int = 5, swings: Optional[list[SwingPoint]] = None, atr_period: int = ATR_PERIOD,
) -> list[ChartPattern]:
    """Rounding Bottom / Top and Cup and Handle, built on the discrete
    swing points this whole module uses everywhere else -- an honest
    APPROXIMATION of what is, in real chart reading, a smooth curve
    (there's no curve-fitting here, only the same alternating-swing
    primitive every other detector in this file shares). A rounding
    bottom is reported as a left rim - trough - right rim (high-low-high)
    where the two rims are approximately equal AND the trough sits
    genuinely deep (ROUNDING_DEPTH_ATR_MULTIPLE below both rims) --
    depth is what actually distinguishes this from an ordinary minor
    pullback between two similar highs, since real roundedness (as
    opposed to a sharp V) isn't directly checkable from swing points
    alone without curve-fitting.

    Cup and Handle extends a qualifying rounding bottom with one more
    swing low (the handle) after the right rim, shallower than
    HANDLE_MAX_DEPTH_FRACTION of the cup's own depth -- a real handle is
    a brief shallow dip near the rim, not a retest of the cup low. When a
    handle IS found, only the Cup and Handle instance is reported (not
    also a separate Rounding Bottom for the same left-rim/trough/right-rim
    triple), since the handle is strictly more information about the same
    structure, not a competing interpretation of it.

    Rounding Top mirrors Rounding Bottom exactly (low-high-low, inverted);
    this file does not report an inverse cup and handle -- a real but far
    less common pattern in practice, and out of scope here without
    separately-verified demand for it, per this codebase's standing
    build-only-what-the-evidence-supports discipline."""
    if swings is None:
        swings = alternate_swings(find_swing_points(df, lookback))
    closes = df["close"].to_numpy(float)
    atr = _average_true_range(df, atr_period).to_numpy(float)
    patterns: list[ChartPattern] = []

    for i in range(len(swings) - 2):
        left, trough, right = swings[i], swings[i + 1], swings[i + 2]
        if not (left.kind == SwingKind.HIGH and trough.kind == SwingKind.LOW and right.kind == SwingKind.HIGH):
            continue
        tol = _atr_tolerance(atr, right.index, EQUALITY_ATR_MULTIPLE)
        depth_tol = _atr_tolerance(atr, right.index, ROUNDING_DEPTH_ATR_MULTIPLE)
        if not _approximately_equal(left.price, right.price, tol):
            continue
        rim = max(left.price, right.price)
        depth = rim - trough.price
        if depth < depth_tol:
            continue

        handle = swings[i + 3] if i + 3 < len(swings) else None
        if handle is not None and handle.kind == SwingKind.LOW and (rim - handle.price) < depth * HANDLE_MAX_DEPTH_FRACTION:
            confirmed_idx = _closes_beyond(closes, handle.index, rim, "above")
            target = rim + depth
            patterns.append(ChartPattern(
                kind=ChartPatternKind.CUP_AND_HANDLE, direction="bullish",
                point_indices=[left.index, trough.index, right.index, handle.index],
                point_prices=[left.price, trough.price, right.price, handle.price],
                breakout_level=rim, target_price=target,
                confirmed=confirmed_idx is not None, confirmed_index=confirmed_idx,
            ))
        else:
            confirmed_idx = _closes_beyond(closes, right.index, rim, "above")
            target = rim + depth
            patterns.append(ChartPattern(
                kind=ChartPatternKind.ROUNDING_BOTTOM, direction="bullish",
                point_indices=[left.index, trough.index, right.index],
                point_prices=[left.price, trough.price, right.price],
                breakout_level=rim, target_price=target,
                confirmed=confirmed_idx is not None, confirmed_index=confirmed_idx,
            ))

    for i in range(len(swings) - 2):
        left, peak, right = swings[i], swings[i + 1], swings[i + 2]
        if not (left.kind == SwingKind.LOW and peak.kind == SwingKind.HIGH and right.kind == SwingKind.LOW):
            continue
        tol = _atr_tolerance(atr, right.index, EQUALITY_ATR_MULTIPLE)
        depth_tol = _atr_tolerance(atr, right.index, ROUNDING_DEPTH_ATR_MULTIPLE)
        if not _approximately_equal(left.price, right.price, tol):
            continue
        rim = min(left.price, right.price)
        depth = peak.price - rim
        if depth < depth_tol:
            continue
        confirmed_idx = _closes_beyond(closes, right.index, rim, "below")
        target = rim - depth
        patterns.append(ChartPattern(
            kind=ChartPatternKind.ROUNDING_TOP, direction="bearish",
            point_indices=[left.index, peak.index, right.index],
            point_prices=[left.price, peak.price, right.price],
            breakout_level=rim, target_price=target,
            confirmed=confirmed_idx is not None, confirmed_index=confirmed_idx,
        ))

    return patterns


def detect_triangles(
    df: pd.DataFrame, lookback: int = 5, swings: Optional[list[SwingPoint]] = None, atr_period: int = ATR_PERIOD,
) -> list[ChartPattern]:
    """Needs 2 swing highs and 2 swing lows (4 consecutive alternating
    points, either high-low-high-low or low-high-low-high) to define both
    a resistance and a support trendline. Classified by the SIGN of each
    line's ATR-normalized slope:

    - Ascending triangle: highs flat, lows rising -- bullish continuation,
      breakout level is the flat resistance (the second high).
    - Descending triangle: lows flat, highs falling -- bearish
      continuation, breakout level is the flat support (the second low).
    - Symmetrical triangle: highs falling AND lows rising (genuinely
      converging) -- direction is NOT determined by the pattern itself
      (the classic ambiguity every TA reference on triangles agrees on),
      so `direction` here reports the direction of the trend those 4
      points sit within (up if the earliest point is a low, down if it's
      a high) as a weak prior, not a claim the pattern itself predicts it.
      Breakout level is the resistance trendline's price at the second
      high (an ascending-lows / descending-highs squeeze most often
      resolves near where the two lines would otherwise meet).

    Any other slope combination (both rising, both falling, i.e. a
    plain channel, not a triangle) is not reported."""
    if swings is None:
        swings = alternate_swings(find_swing_points(df, lookback))
    closes = df["close"].to_numpy(float)
    atr = _average_true_range(df, atr_period).to_numpy(float)
    patterns: list[ChartPattern] = []

    for i in range(len(swings) - 3):
        window = swings[i:i + 4]
        kinds = [p.kind for p in window]

        if kinds == [SwingKind.HIGH, SwingKind.LOW, SwingKind.HIGH, SwingKind.LOW]:
            h1, l1, h2, l2 = window
            prior_trend = "bearish"
        elif kinds == [SwingKind.LOW, SwingKind.HIGH, SwingKind.LOW, SwingKind.HIGH]:
            l1, h1, l2, h2 = window
            prior_trend = "bullish"
        else:
            continue

        high_slope = _slope_atr_per_bar(h1, h2, atr)
        low_slope = _slope_atr_per_bar(l1, l2, atr)
        highs_flat = abs(high_slope) < FLAT_SLOPE_ATR_FRACTION
        lows_flat = abs(low_slope) < FLAT_SLOPE_ATR_FRACTION
        highs_falling = high_slope < -FLAT_SLOPE_ATR_FRACTION
        highs_rising = high_slope > FLAT_SLOPE_ATR_FRACTION
        lows_rising = low_slope > FLAT_SLOPE_ATR_FRACTION
        lows_falling = low_slope < -FLAT_SLOPE_ATR_FRACTION

        last_index = max(h2.index, l2.index)
        kind: Optional[ChartPatternKind] = None
        direction = prior_trend
        breakout_level = h2.price

        if highs_flat and lows_rising:
            kind = ChartPatternKind.ASCENDING_TRIANGLE
            direction = "bullish"
            breakout_level = h2.price
        elif lows_flat and highs_falling:
            kind = ChartPatternKind.DESCENDING_TRIANGLE
            direction = "bearish"
            breakout_level = l2.price
        elif highs_falling and lows_rising:
            kind = ChartPatternKind.SYMMETRICAL_TRIANGLE
            breakout_level = h2.price

        if kind is None:
            continue

        break_direction = "above" if direction == "bullish" else "below"
        confirmed_idx = _closes_beyond(closes, last_index, breakout_level, break_direction)
        # Measured move: the triangle's own vertical height at its widest
        # (first) side, projected from the breakout level -- the standard
        # triangle target convention, same "height of the formation"
        # principle H&S and double top/bottom already use above.
        height = abs(h1.price - l1.price)
        target = breakout_level + height if direction == "bullish" else breakout_level - height

        patterns.append(ChartPattern(
            kind=kind, direction=direction,
            point_indices=[p.index for p in window], point_prices=[p.price for p in window],
            breakout_level=breakout_level, target_price=target,
            confirmed=confirmed_idx is not None, confirmed_index=confirmed_idx,
        ))

    return patterns


def detect_chart_patterns(
    df: pd.DataFrame, lookback: int = 5, swings: Optional[list[SwingPoint]] = None,
) -> list[ChartPattern]:
    """Convenience wrapper running every family in this module against the
    SAME shared swing sequence (computed once here if not supplied), same
    "compute once, share across detectors" convention detect_structure_
    events' own docstring already established for this package.

    Expanded 2026-09-14 from the original 3 families (H&S, double top/
    bottom, triangles) to all classical public-domain chart-pattern
    geometry this codebase's swing-point primitives can support: triple
    top/bottom, wedges, broadening formations, rectangles, diamonds,
    flags/pennants, and rounding top/bottom + cup and handle. Some
    detectors above scan overlapping window shapes (e.g. a triangle's and
    a wedge's 4-point window is structurally identical, classified apart
    only by slope sign), so a single swing sequence can legitimately
    produce more than one pattern type anchored at the same points --
    deliberately not de-duplicated here, since each represents a genuinely
    different, separately-defined geometric claim about the same points,
    and a caller (or the confluence layer, if this is ever wired into
    scoring) is free to treat multiple simultaneous classifications as
    corroborating or to prefer one family over another."""
    if swings is None:
        swings = alternate_swings(find_swing_points(df, lookback))
    return (
        detect_head_and_shoulders(df, lookback, swings)
        + detect_double_top_bottom(df, lookback, swings)
        + detect_triple_top_bottom(df, lookback, swings)
        + detect_triangles(df, lookback, swings)
        + detect_wedges(df, lookback, swings)
        + detect_broadening_formations(df, lookback, swings)
        + detect_rectangles(df, lookback, swings)
        + detect_diamonds(df, lookback, swings)
        + detect_flags_pennants(df, lookback, swings)
        + detect_rounding_patterns(df, lookback, swings)
    )
