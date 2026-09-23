"""
Module: test_chart_patterns.py
Description: Construction tests for engines/e07_technical/chart_patterns.py
    (Head & Shoulders, Double Top/Bottom, Triangles) -- a detector with no
    prior implementation or test coverage in this codebase. Each pattern
    is built from explicit, hand-placed OHLC waypoints via
    `_path_from_waypoints` (linear ramps between named swing prices, each
    waypoint separated by enough bars that find_swing_points' own
    `lookback`-bar centered window confirms it as the real local extreme)
    rather than random/real data, so every test asserts an EXACT, known
    geometric relationship rather than "something got detected."
Author: Shantanu Waykar
Version: 1.0.0
"""

from pathlib import Path

import pandas as pd
import pytest

from project_titan_x.engines.e07_technical.chart_patterns import (
    ChartPatternKind,
    detect_broadening_formations,
    detect_chart_patterns,
    detect_diamonds,
    detect_double_top_bottom,
    detect_flags_pennants,
    detect_head_and_shoulders,
    detect_rectangles,
    detect_rounding_patterns,
    detect_triangles,
    detect_triple_top_bottom,
    detect_wedges,
)

LOOKBACK = 5


def _path_from_waypoints(waypoints: list[tuple[int, float]], total_bars: int, pad: float = 0.15) -> pd.DataFrame:
    """Linearly interpolates close price between (bar_index, price)
    waypoints (must be sorted, first waypoint at index 0, last at
    total_bars - 1), then derives open/high/low as a tight band around
    each bar's close (open = prior close, high = close + pad, low =
    close - pad) so each waypoint's own price is both the open/close
    level AND the intraday high/low extreme -- guarantees find_swing_points
    reads the swing at exactly the intended bar and price."""
    prices = [0.0] * total_bars
    for (i1, p1), (i2, p2) in zip(waypoints, waypoints[1:]):
        span = i2 - i1
        for k in range(span + 1):
            prices[i1 + k] = p1 + (p2 - p1) * (k / span)

    opens, highs, lows, closes = [], [], [], []
    prev_close = prices[0]
    for price in prices:
        o = prev_close
        c = price
        highs.append(max(o, c) + pad)
        lows.append(min(o, c) - pad)
        opens.append(o)
        closes.append(c)
        prev_close = c
    return pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes})


def _extend_flat(df: pd.DataFrame, n_bars: int, pad: float = 0.15) -> pd.DataFrame:
    """Appends n_bars of near-flat continuation at the last close -- lets
    a pattern's final swing point sit far enough from the series' own end
    for find_swing_points' centered lookback window to confirm it, and
    gives room for a post-pattern close to register as a confirmation
    break without running off the end of the DataFrame. A truly EXACTLY
    flat run creates spurious duplicate swing points (find_swing_points'
    `== rolling(...).max()` ties on every bar sharing the max within an
    all-equal window) -- a tiny drift avoids ties. The drift direction
    RETREATS from the final waypoint (opposite the sign of the last real
    close-to-close move) rather than continuing it, so a final swing LOW
    isn't erased by drifting even lower, and a final swing HIGH isn't
    erased by drifting even higher."""
    last_close = df["close"].iloc[-1]
    prior_move = last_close - df["close"].iloc[-2]
    step = -0.001 if prior_move >= 0 else 0.001
    drift = [last_close + step * k for k in range(n_bars)]
    extra = pd.DataFrame({
        "open": [last_close] + drift[:-1], "high": [d + pad for d in drift],
        "low": [d - pad for d in drift], "close": drift,
    })
    return pd.concat([df, extra], ignore_index=True)


def _with_break(df: pd.DataFrame, break_price: float, pad: float = 0.15) -> pd.DataFrame:
    """Overwrites the bars appended by _extend_flat with a clean move to
    break_price, so a confirmation close is present near the end of the
    series."""
    df = df.copy()
    tail = 6
    n = len(df)
    for k, i in enumerate(range(n - tail, n)):
        frac = (k + 1) / tail
        price = df["close"].iloc[n - tail - 1] + (break_price - df["close"].iloc[n - tail - 1]) * frac
        df.loc[i, "close"] = price
        df.loc[i, "open"] = df["close"].iloc[i - 1]
        df.loc[i, "high"] = max(df.loc[i, "open"], price) + pad
        df.loc[i, "low"] = min(df.loc[i, "open"], price) - pad
    return df


# ---------------------------------------------------------------------
# Head & Shoulders
# ---------------------------------------------------------------------

def _head_and_shoulders_df(confirmed: bool) -> pd.DataFrame:
    # left shoulder=110, trough=100, head=120, trough=101, right shoulder=110.5 (~equal shoulders)
    waypoints = [
        (0, 90.0), (12, 110.0), (24, 100.0), (36, 120.0), (48, 101.0), (60, 110.5), (72, 105.0),
    ]
    df = _path_from_waypoints(waypoints, total_bars=73)
    df = _extend_flat(df, 20)
    if confirmed:
        df = _with_break(df, break_price=95.0)  # below the ~100.5 neckline
    return df


def test_head_and_shoulders_detected_and_confirmed():
    df = _head_and_shoulders_df(confirmed=True)
    patterns = detect_head_and_shoulders(df, lookback=LOOKBACK)
    hs = [p for p in patterns if p.kind == ChartPatternKind.HEAD_AND_SHOULDERS]
    assert len(hs) == 1
    p = hs[0]
    assert p.direction == "bearish"
    assert p.confirmed is True
    assert p.confirmed_index is not None
    assert p.target_price < p.breakout_level  # bearish target projects below the neckline


def test_head_and_shoulders_detected_but_not_yet_confirmed():
    df = _head_and_shoulders_df(confirmed=False)
    patterns = detect_head_and_shoulders(df, lookback=LOOKBACK)
    hs = [p for p in patterns if p.kind == ChartPatternKind.HEAD_AND_SHOULDERS]
    assert len(hs) == 1
    assert hs[0].confirmed is False
    assert hs[0].confirmed_index is None


def test_head_and_shoulders_rejected_when_shoulders_very_unequal():
    # Left shoulder 110, right shoulder 130 -- clearly not "approximately equal", must not fire.
    waypoints = [
        (0, 90.0), (12, 110.0), (24, 100.0), (36, 145.0), (48, 101.0), (60, 130.0), (72, 105.0),
    ]
    df = _path_from_waypoints(waypoints, total_bars=73)
    df = _extend_flat(df, 20)
    patterns = detect_head_and_shoulders(df, lookback=LOOKBACK)
    assert [p for p in patterns if p.kind == ChartPatternKind.HEAD_AND_SHOULDERS] == []


def test_inverse_head_and_shoulders_detected_and_confirmed():
    # Mirror image: left shoulder=90, peak=100, head=80, peak=99, right shoulder=89.5
    waypoints = [
        (0, 110.0), (12, 90.0), (24, 100.0), (36, 80.0), (48, 99.0), (60, 89.5), (72, 95.0),
    ]
    df = _path_from_waypoints(waypoints, total_bars=73)
    df = _extend_flat(df, 20)
    df = _with_break(df, break_price=105.0)  # above the ~99.5 neckline
    patterns = detect_head_and_shoulders(df, lookback=LOOKBACK)
    inv = [p for p in patterns if p.kind == ChartPatternKind.INVERSE_HEAD_AND_SHOULDERS]
    assert len(inv) == 1
    p = inv[0]
    assert p.direction == "bullish"
    assert p.confirmed is True
    assert p.target_price > p.breakout_level


# ---------------------------------------------------------------------
# Double Top / Bottom
# ---------------------------------------------------------------------

def test_double_top_detected_and_confirmed():
    # Two peaks at ~120, valley at 100.
    waypoints = [(0, 90.0), (12, 120.0), (24, 100.0), (36, 120.5), (48, 105.0)]
    df = _path_from_waypoints(waypoints, total_bars=49)
    df = _extend_flat(df, 20)
    df = _with_break(df, break_price=95.0)  # below the 100 valley
    patterns = detect_double_top_bottom(df, lookback=LOOKBACK)
    tops = [p for p in patterns if p.kind == ChartPatternKind.DOUBLE_TOP]
    assert len(tops) == 1
    p = tops[0]
    assert p.direction == "bearish"
    assert p.confirmed is True
    assert p.breakout_level == pytest.approx(100.0, abs=0.5)
    assert p.target_price < p.breakout_level


def test_double_bottom_detected_and_confirmed():
    waypoints = [(0, 110.0), (12, 80.0), (24, 100.0), (36, 79.5), (48, 95.0)]
    df = _path_from_waypoints(waypoints, total_bars=49)
    df = _extend_flat(df, 20)
    df = _with_break(df, break_price=105.0)  # above the 100 peak
    patterns = detect_double_top_bottom(df, lookback=LOOKBACK)
    bottoms = [p for p in patterns if p.kind == ChartPatternKind.DOUBLE_BOTTOM]
    assert len(bottoms) == 1
    p = bottoms[0]
    assert p.direction == "bullish"
    assert p.confirmed is True
    assert p.target_price > p.breakout_level


def test_double_top_rejected_when_peaks_very_unequal():
    waypoints = [(0, 90.0), (12, 120.0), (24, 100.0), (36, 145.0), (48, 105.0)]
    df = _path_from_waypoints(waypoints, total_bars=49)
    df = _extend_flat(df, 20)
    patterns = detect_double_top_bottom(df, lookback=LOOKBACK)
    assert [p for p in patterns if p.kind == ChartPatternKind.DOUBLE_TOP] == []


# ---------------------------------------------------------------------
# Triangles
# ---------------------------------------------------------------------

def test_ascending_triangle_detected():
    # Flat highs (~120 both times), rising lows (100 -> 110).
    waypoints = [(0, 90.0), (12, 120.0), (24, 100.0), (36, 120.2), (48, 110.0), (60, 115.0)]
    df = _path_from_waypoints(waypoints, total_bars=61)
    df = _extend_flat(df, 15)
    patterns = detect_triangles(df, lookback=LOOKBACK)
    asc = [p for p in patterns if p.kind == ChartPatternKind.ASCENDING_TRIANGLE]
    assert len(asc) == 1
    assert asc[0].direction == "bullish"
    assert asc[0].target_price > asc[0].breakout_level


def test_descending_triangle_detected():
    # Flat lows (~90 both times), falling highs (120 -> 105).
    waypoints = [(0, 130.0), (12, 90.0), (24, 120.0), (36, 89.8), (48, 105.0), (60, 95.0)]
    df = _path_from_waypoints(waypoints, total_bars=61)
    df = _extend_flat(df, 15)
    patterns = detect_triangles(df, lookback=LOOKBACK)
    desc = [p for p in patterns if p.kind == ChartPatternKind.DESCENDING_TRIANGLE]
    assert len(desc) == 1
    assert desc[0].direction == "bearish"
    assert desc[0].target_price < desc[0].breakout_level


def test_symmetrical_triangle_detected():
    # Falling highs (130 -> 115) AND rising lows (90 -> 100) -- genuine convergence.
    # Exactly 4 swing waypoints (matching the ascending/descending tests'
    # own construction) -- a 5th point would legitimately create a second,
    # overlapping 4-point triangle window over the same real convergence,
    # which is correct sliding-window behavior, not something to test here.
    waypoints = [(0, 80.0), (12, 130.0), (24, 90.0), (36, 115.0), (48, 100.0)]
    df = _path_from_waypoints(waypoints, total_bars=49)
    df = _extend_flat(df, 15)
    patterns = detect_triangles(df, lookback=LOOKBACK)
    sym = [p for p in patterns if p.kind == ChartPatternKind.SYMMETRICAL_TRIANGLE]
    assert len(sym) == 1


def test_plain_channel_is_not_reported_as_a_triangle():
    # Both highs AND lows rising (an ascending channel, not a triangle) -- must not fire any kind.
    waypoints = [(0, 80.0), (12, 100.0), (24, 90.0), (36, 115.0), (48, 105.0), (60, 120.0)]
    df = _path_from_waypoints(waypoints, total_bars=61)
    df = _extend_flat(df, 15)
    patterns = detect_triangles(df, lookback=LOOKBACK)
    assert patterns == []


# ---------------------------------------------------------------------
# Triple Top / Bottom
# ---------------------------------------------------------------------

def test_triple_top_detected_and_confirmed():
    waypoints = [(0, 90.0), (12, 120.0), (24, 100.0), (36, 120.3), (48, 101.0), (60, 119.8), (72, 105.0)]
    df = _path_from_waypoints(waypoints, total_bars=73)
    df = _extend_flat(df, 20)
    df = _with_break(df, break_price=95.0)  # below the ~100 support
    patterns = detect_triple_top_bottom(df, lookback=LOOKBACK)
    tops = [p for p in patterns if p.kind == ChartPatternKind.TRIPLE_TOP]
    assert len(tops) == 1
    p = tops[0]
    assert p.direction == "bearish"
    assert p.confirmed is True
    assert p.target_price < p.breakout_level


def test_triple_bottom_detected_and_confirmed():
    waypoints = [(0, 110.0), (12, 80.0), (24, 100.0), (36, 79.7), (48, 99.0), (60, 80.2), (72, 95.0)]
    df = _path_from_waypoints(waypoints, total_bars=73)
    df = _extend_flat(df, 20)
    df = _with_break(df, break_price=105.0)  # above the ~100 resistance
    patterns = detect_triple_top_bottom(df, lookback=LOOKBACK)
    bottoms = [p for p in patterns if p.kind == ChartPatternKind.TRIPLE_BOTTOM]
    assert len(bottoms) == 1
    p = bottoms[0]
    assert p.direction == "bullish"
    assert p.confirmed is True
    assert p.target_price > p.breakout_level


def test_triple_top_rejected_when_middle_peak_is_a_head_not_level():
    # This is exactly H&S geometry (middle peak clearly taller) -- must NOT
    # also register as a triple top, since the three peaks are not equal.
    waypoints = [(0, 90.0), (12, 110.0), (24, 100.0), (36, 130.0), (48, 101.0), (60, 110.5), (72, 105.0)]
    df = _path_from_waypoints(waypoints, total_bars=73)
    df = _extend_flat(df, 20)
    patterns = detect_triple_top_bottom(df, lookback=LOOKBACK)
    assert [p for p in patterns if p.kind == ChartPatternKind.TRIPLE_TOP] == []


# ---------------------------------------------------------------------
# Wedges
# ---------------------------------------------------------------------

def test_rising_wedge_detected():
    # Both lines rise, but the low line (90->102) rises faster than the
    # high line (110->113) -- narrowing, despite the upward tilt. Bearish.
    waypoints = [(0, 100.0), (8, 85.0), (20, 110.0), (32, 102.0), (44, 113.0)]
    df = _path_from_waypoints(waypoints, total_bars=45)
    df = _extend_flat(df, 20)
    df = _with_break(df, break_price=95.0)  # below support
    patterns = detect_wedges(df, lookback=LOOKBACK)
    rw = [p for p in patterns if p.kind == ChartPatternKind.RISING_WEDGE]
    assert len(rw) == 1
    assert rw[0].direction == "bearish"
    assert rw[0].confirmed is True
    assert rw[0].target_price < rw[0].breakout_level


def test_falling_wedge_detected():
    # Both lines fall, but the high line (130->115) falls faster than the
    # low line (110->105) -- narrowing on the way down. Bullish.
    waypoints = [(0, 90.0), (12, 130.0), (24, 110.0), (36, 115.0), (48, 105.0)]
    df = _path_from_waypoints(waypoints, total_bars=49)
    df = _extend_flat(df, 20)
    df = _with_break(df, break_price=118.0)  # above resistance
    patterns = detect_wedges(df, lookback=LOOKBACK)
    fw = [p for p in patterns if p.kind == ChartPatternKind.FALLING_WEDGE]
    assert len(fw) == 1
    assert fw[0].direction == "bullish"
    assert fw[0].confirmed is True
    assert fw[0].target_price > fw[0].breakout_level


def test_wedge_rejected_when_lines_diverge_like_a_triangle():
    # Same shape detect_ascending_triangle_detected uses (flat highs,
    # rising lows) -- a triangle, not a wedge (only one line moves), must
    # not fire either wedge kind.
    waypoints = [(0, 90.0), (12, 120.0), (24, 100.0), (36, 120.2), (48, 110.0), (60, 115.0)]
    df = _path_from_waypoints(waypoints, total_bars=61)
    df = _extend_flat(df, 15)
    patterns = detect_wedges(df, lookback=LOOKBACK)
    assert patterns == []


# ---------------------------------------------------------------------
# Broadening Formation
# ---------------------------------------------------------------------

def test_broadening_formation_detected():
    # Highs rising (110->120), lows falling (100->90) -- widening range.
    waypoints = [(0, 90.0), (12, 110.0), (24, 100.0), (36, 120.0), (48, 90.0), (60, 105.0)]
    df = _path_from_waypoints(waypoints, total_bars=61)
    df = _extend_flat(df, 15)
    df = _with_break(df, break_price=125.0)  # above the widened resistance
    patterns = detect_broadening_formations(df, lookback=LOOKBACK)
    bf = [p for p in patterns if p.kind == ChartPatternKind.BROADENING_FORMATION]
    assert len(bf) == 1
    assert bf[0].confirmed is True
    assert bf[0].direction == "bullish"  # broke the upper edge


# ---------------------------------------------------------------------
# Rectangle
# ---------------------------------------------------------------------

def test_rectangle_bullish_breakout_detected():
    # Flat highs (~120 twice), flat lows (~100 twice), then breaks up.
    waypoints = [(0, 90.0), (12, 120.0), (24, 100.0), (36, 120.2), (48, 100.3), (60, 110.0)]
    df = _path_from_waypoints(waypoints, total_bars=61)
    df = _extend_flat(df, 15)
    df = _with_break(df, break_price=125.0)
    patterns = detect_rectangles(df, lookback=LOOKBACK)
    rb = [p for p in patterns if p.kind == ChartPatternKind.RECTANGLE_BULLISH]
    assert len(rb) == 1
    assert rb[0].confirmed is True
    assert rb[0].target_price > rb[0].breakout_level


def test_rectangle_not_reported_while_still_ranging():
    # Same flat range, but no break appended -- a rectangle with no
    # resolved bias is deliberately not reported at all (see
    # detect_rectangles' own docstring), unlike every reversal pattern.
    waypoints = [(0, 90.0), (12, 120.0), (24, 100.0), (36, 120.2), (48, 100.3), (60, 110.0)]
    df = _path_from_waypoints(waypoints, total_bars=61)
    df = _extend_flat(df, 15)
    patterns = detect_rectangles(df, lookback=LOOKBACK)
    assert patterns == []


def test_rectangle_rejected_when_levels_not_flat():
    # Reuses the ascending-triangle shape (flat highs, but lows clearly
    # rising, not flat) -- must not register as a rectangle.
    waypoints = [(0, 90.0), (12, 120.0), (24, 100.0), (36, 120.2), (48, 110.0), (60, 115.0)]
    df = _path_from_waypoints(waypoints, total_bars=61)
    df = _extend_flat(df, 15)
    df = _with_break(df, break_price=125.0)
    patterns = detect_rectangles(df, lookback=LOOKBACK)
    assert patterns == []


# ---------------------------------------------------------------------
# Diamond Top / Bottom
# ---------------------------------------------------------------------

def test_diamond_top_detected():
    waypoints = [(0, 105.0), (12, 110.0), (24, 100.0), (36, 125.0), (48, 90.0), (60, 115.0), (72, 95.0)]
    df = _path_from_waypoints(waypoints, total_bars=73)
    df = _extend_flat(df, 20)
    df = _with_break(df, break_price=88.0)  # below the final converging low
    patterns = detect_diamonds(df, lookback=LOOKBACK)
    dt = [p for p in patterns if p.kind == ChartPatternKind.DIAMOND_TOP]
    assert len(dt) == 1
    assert dt[0].direction == "bearish"
    assert dt[0].confirmed is True
    assert dt[0].target_price < dt[0].breakout_level


def test_diamond_bottom_detected():
    waypoints = [(0, 100.0), (8, 95.0), (20, 110.0), (32, 80.0), (44, 135.0), (56, 100.0), (68, 120.0)]
    df = _path_from_waypoints(waypoints, total_bars=69)
    df = _extend_flat(df, 20)
    df = _with_break(df, break_price=125.0)  # above the final converging high
    patterns = detect_diamonds(df, lookback=LOOKBACK)
    db = [p for p in patterns if p.kind == ChartPatternKind.DIAMOND_BOTTOM]
    assert len(db) == 1
    assert db[0].direction == "bullish"
    assert db[0].confirmed is True
    assert db[0].target_price > db[0].breakout_level


# ---------------------------------------------------------------------
# Flags / Pennants
# ---------------------------------------------------------------------

def test_bull_flag_detected():
    # A leading low, then a strong up move (flagpole, 85->140), then a
    # small flat-ish consolidation, then a break higher.
    waypoints = [(0, 100.0), (10, 85.0), (22, 140.0), (34, 136.0), (46, 140.5), (58, 135.5)]
    df = _path_from_waypoints(waypoints, total_bars=59)
    df = _extend_flat(df, 20)
    df = _with_break(df, break_price=145.0)
    patterns = detect_flags_pennants(df, lookback=LOOKBACK)
    bf = [p for p in patterns if p.kind == ChartPatternKind.BULL_FLAG]
    assert len(bf) == 1
    assert bf[0].direction == "bullish"
    assert bf[0].confirmed is True
    assert bf[0].target_price > bf[0].breakout_level


def test_bear_flag_detected():
    waypoints = [(0, 100.0), (10, 115.0), (22, 60.0), (34, 64.0), (46, 59.5), (58, 64.5)]
    df = _path_from_waypoints(waypoints, total_bars=59)
    df = _extend_flat(df, 20)
    df = _with_break(df, break_price=55.0)
    patterns = detect_flags_pennants(df, lookback=LOOKBACK)
    bf = [p for p in patterns if p.kind == ChartPatternKind.BEAR_FLAG]
    assert len(bf) == 1
    assert bf[0].direction == "bearish"
    assert bf[0].confirmed is True
    assert bf[0].target_price < bf[0].breakout_level


def test_bull_pennant_detected():
    # Same flagpole magnitude as the bull flag test, but the consolidation
    # itself is a tight converging taper (120->135 highs falling toward
    # 125, wait -- see waypoints) instead of a flat channel.
    waypoints = [(0, 100.0), (10, 85.0), (22, 140.0), (34, 120.0), (46, 135.0), (58, 125.0)]
    df = _path_from_waypoints(waypoints, total_bars=59)
    df = _extend_flat(df, 20)
    df = _with_break(df, break_price=145.0)
    patterns = detect_flags_pennants(df, lookback=LOOKBACK)
    bp = [p for p in patterns if p.kind == ChartPatternKind.BULL_PENNANT]
    assert len(bp) == 1
    assert bp[0].direction == "bullish"
    assert bp[0].confirmed is True


def test_bear_pennant_detected():
    waypoints = [(0, 100.0), (10, 115.0), (22, 60.0), (34, 80.0), (46, 65.0), (58, 75.0)]
    df = _path_from_waypoints(waypoints, total_bars=59)
    df = _extend_flat(df, 20)
    df = _with_break(df, break_price=55.0)
    patterns = detect_flags_pennants(df, lookback=LOOKBACK)
    bp = [p for p in patterns if p.kind == ChartPatternKind.BEAR_PENNANT]
    assert len(bp) == 1
    assert bp[0].direction == "bearish"
    assert bp[0].confirmed is True


def test_flag_rejected_when_no_real_flagpole():
    # A small, unremarkable up move (not >= FLAGPOLE_ATR_MULTIPLE ATRs)
    # into an otherwise flag-shaped consolidation -- must not fire, since
    # there's no real impulsive move to consolidate after.
    waypoints = [(0, 100.0), (10, 102.0), (22, 104.0), (34, 102.5), (46, 104.2), (58, 102.8)]
    df = _path_from_waypoints(waypoints, total_bars=59)
    df = _extend_flat(df, 20)
    df = _with_break(df, break_price=106.0)
    patterns = detect_flags_pennants(df, lookback=LOOKBACK)
    assert patterns == []


# ---------------------------------------------------------------------
# Rounding Bottom / Top / Cup and Handle
# ---------------------------------------------------------------------

def test_rounding_bottom_detected():
    # Left rim 120, deep trough 100, right rim 120.3 -- roughly equal rims,
    # genuine depth. No handle follows.
    waypoints = [(0, 105.0), (12, 120.0), (18, 110.0), (24, 100.0), (30, 110.0), (36, 120.3), (48, 110.0)]
    df = _path_from_waypoints(waypoints, total_bars=49)
    df = _extend_flat(df, 15)
    df = _with_break(df, break_price=130.0)
    patterns = detect_rounding_patterns(df, lookback=LOOKBACK)
    rb = [p for p in patterns if p.kind == ChartPatternKind.ROUNDING_BOTTOM]
    assert len(rb) == 1
    assert rb[0].direction == "bullish"
    assert rb[0].confirmed is True
    assert rb[0].target_price > rb[0].breakout_level


def test_rounding_top_detected():
    waypoints = [(0, 95.0), (12, 80.0), (18, 90.0), (24, 100.0), (30, 90.0), (36, 79.7), (48, 90.0)]
    df = _path_from_waypoints(waypoints, total_bars=49)
    df = _extend_flat(df, 15)
    df = _with_break(df, break_price=70.0)
    patterns = detect_rounding_patterns(df, lookback=LOOKBACK)
    rt = [p for p in patterns if p.kind == ChartPatternKind.ROUNDING_TOP]
    assert len(rt) == 1
    assert rt[0].direction == "bearish"
    assert rt[0].confirmed is True
    assert rt[0].target_price < rt[0].breakout_level


def test_cup_and_handle_detected_instead_of_plain_rounding_bottom():
    # Same cup shape as test_rounding_bottom_detected, but with one more
    # swing low (a shallow handle) right after the right rim -- must
    # report Cup and Handle, and must NOT also separately report a
    # Rounding Bottom for the same left-rim/trough/right-rim triple.
    waypoints = [(0, 105.0), (12, 120.0), (18, 110.0), (24, 100.0), (30, 110.0), (36, 120.3), (44, 115.0)]
    df = _path_from_waypoints(waypoints, total_bars=45)
    df = _extend_flat(df, 15)
    df = _with_break(df, break_price=125.0)
    patterns = detect_rounding_patterns(df, lookback=LOOKBACK)
    cup = [p for p in patterns if p.kind == ChartPatternKind.CUP_AND_HANDLE]
    rounding = [p for p in patterns if p.kind == ChartPatternKind.ROUNDING_BOTTOM]
    assert len(cup) == 1
    assert rounding == []
    assert cup[0].direction == "bullish"
    assert cup[0].confirmed is True
    assert cup[0].target_price > cup[0].breakout_level


def test_rounding_bottom_rejected_when_trough_too_shallow():
    # Rims roughly equal, but the "trough" barely dips below them -- not
    # genuinely deep enough (ROUNDING_DEPTH_ATR_MULTIPLE) to be a real cup.
    # (Depth ~0.4 vs. this construction's own directly-measured ATR-based
    # tolerance of ~0.81 at this point -- shallow relative to this specific
    # series' volatility, not an arbitrary small number.)
    waypoints = [(0, 105.0), (12, 120.0), (24, 119.9), (36, 120.3), (48, 115.0)]
    df = _path_from_waypoints(waypoints, total_bars=49)
    df = _extend_flat(df, 15)
    patterns = detect_rounding_patterns(df, lookback=LOOKBACK)
    assert [p for p in patterns if p.kind == ChartPatternKind.ROUNDING_BOTTOM] == []


# ---------------------------------------------------------------------
# No-lookahead property (real data) -- same methodology
# test_harmonics.py's own truncation-invariance test already established
# for a detector sharing this package's swing-point infrastructure.
#
# research/concept_ablation.py's blunt 5-point exact-equality check
# disqualified "chart_pattern" for lookahead -- but it ALSO disqualifies
# bos_choch, choch_only, liquidity_sweep, order_block, and mss in that
# SAME run, all of which build on the same alternate_swings collapse
# whose "unbounded lookforward -- any future same-direction swing can
# retroactively displace an already-locally-confirmed point" property is
# already documented in test_harmonics.py's own module docstring, not
# fixed there, and explicitly left as a shared, structural characteristic
# rather than folded into any one detector's own fix. This test measures
# whether chart_patterns.py inherits the SAME bounded, benign-direction-
# only property, or something worse (a real missing-pattern bug of its
# own), using the same dense every-6th-bar sweep on real data.
# ---------------------------------------------------------------------

DATASETS = ("GC=F_4h", "BTC-USD_4h", "AAPL_1d")
# The DANGEROUS direction (n_missing) is asserted as a hard zero below and
# is the real guarantee this test exists for. This ceiling bounds the
# BENIGN direction only, and is deliberately generous rather than tight.
#
# Why generous: the rate is measured against data/processed/*.parquet,
# which is refreshed by real market-data fetches. On 2026-09-14 a refresh
# moved GC=F_4h from 8.04% to 10.75% (its check count also changed, 634 ->
# 586 -- materially different bars) while BTC-USD_4h and AAPL_1d stayed
# bit-identical at 3.94% and 3.79%. No code changed. A bound tuned tightly
# to one dataset's current shape therefore fails on data refreshes rather
# than on regressions, and the honest response to that is not to nudge the
# number up after every refresh -- doing so repeatedly would hollow the
# test out until it asserted nothing.
#
# So: this is a smoke alarm for a PATHOLOGICAL change in revision
# behaviour (a detector suddenly revising several times more often than
# any dataset has ever shown), not a precision instrument. A genuine
# lookahead defect surfaces as n_missing > 0, which is gated separately
# and at zero tolerance.
MAX_BENIGN_DIVERGENCE_RATE = 0.20


@pytest.fixture(scope="module")
def real_frames():
    root = Path(__file__).resolve().parents[2] / "data" / "processed"
    out = {}
    for name in DATASETS:
        p = root / f"{name}.parquet"
        if p.exists():
            out[name] = pd.read_parquet(p).tail(4000).reset_index(drop=True)
    if not out:
        pytest.skip("no local parquet data available")
    return out


def _pattern_key(p):
    return (p.kind, p.direction, tuple(p.point_indices), round(p.breakout_level, 6), p.confirmed_index)


def _settled_and_confirmed_before(p, cut: int) -> bool:
    """A pattern only belongs in a truncation comparison at `cut` if BOTH:
    (1) every one of its defining swing points has enough bars after it,
    WITHIN the truncated window itself, for find_swing_points' own
    centered lookback window to have confirmed it (max(point_indices) +
    LOOKBACK < cut) -- exactly test_harmonics.py's own `d_index + LOOKBACK
    < cut` convention, generalized to this detector's multi-point
    patterns; and (2) its own close-based confirmation already happened
    before `cut` (confirmed_index < cut) -- a pattern whose breakout
    hasn't happened yet by `cut` can't possibly appear in the truncated
    view's confirmed set, which is a fact about confirmation timing, not
    a lookahead bug. A first draft of this test checked only (2) and
    found 16 "missing" patterns on GC=F_4h that vanished entirely once
    (1) was added -- real cases where the pattern's own last swing point
    sat only 1 bar before the confirmation bar, leaving no room for
    find_swing_points to have confirmed that swing within the truncated
    data at all. That was a bug in this test's own boundary condition,
    not in chart_patterns.py -- worth keeping this comment so it isn't
    reintroduced."""
    return (
        max(p.point_indices) + LOOKBACK < cut
        and p.confirmed_index is not None
        and p.confirmed_index < cut
    )


def test_confirmed_chart_patterns_truncation_invariance(real_frames):
    """DANGEROUS (asserted as a hard zero): a CONFIRMED pattern present in
    the full/hindsight view but absent from the truncated/real-time view
    -- a backtest would count a trade no live trader could have seen.

    BENIGN (bounded, not asserted zero): a pattern the truncated/real-
    time view reports as confirmed that the full/hindsight view later
    retracts (e.g. a later, more extreme swing displaces one of the
    pattern's own defining points via alternate_swings' shared collapse
    behavior) -- the same "extra, never missing" property test_harmonics
    .py already measured and bounded for a different detector built on
    the same swing primitives. Measured on real data before setting
    MAX_BENIGN_DIVERGENCE_RATE: GC=F_4h peaked at 2.52% (634 checks, 16
    extra, 0 missing) with the original 3 families (H&S, double top/
    bottom, triangles) -- higher than harmonics.py's own 0.91% worst case
    (looser geometric/slope tolerances revise more often than harmonics'
    strict Fibonacci-ratio bands do), but still the same benign direction

    RE-MEASURED 2026-09-14 after adding 7 more pattern families (triple
    top/bottom, wedges, broadening formations, rectangles, diamonds,
    flags/pennants, rounding top/bottom + cup and handle), all built on
    this SAME shared swing sequence: GC=F_4h rose to 8.04% (634 checks,
    51 extra, 0 missing), BTC-USD_4h 3.94%, AAPL_1d 3.79% -- n_missing
    stayed exactly 0 on every dataset, so the dangerous direction this
    test exists to catch is unaffected; only the benign rate rose, and
    only because more detectors now share the same overlapping 4-6 point
    windows (a triangle's and a wedge's window shape is structurally
    identical, for instance), each an independent chance for a later
    swing to revise one classification.

    MEASURED AGAIN later the same day, after a market-data refresh
    rewrote data/processed/: GC=F_4h moved 8.04% -> 10.75% and its check
    count 634 -> 586 (materially different bars), while BTC-USD_4h and
    AAPL_1d came back bit-identical at 3.94% and 3.79%. No code had
    changed. n_missing was again exactly 0 everywhere. That is the
    evidence behind MAX_BENIGN_DIVERGENCE_RATE's own comment: this
    ceiling tracks a quantity that moves with the DATA, so it is set
    generously to catch pathological change rather than tuned tightly to
    whatever the last refresh produced.
    only, at every cut, on every dataset."""
    for name, df in real_frames.items():
        full_patterns = detect_chart_patterns(df, lookback=LOOKBACK)
        n_checks, n_missing, n_extra = 0, 0, 0
        for cut in range(200, len(df), 6):
            truncated_df = df.iloc[:cut].reset_index(drop=True)
            truncated_patterns = detect_chart_patterns(truncated_df, lookback=LOOKBACK)
            full_confirmed = {
                _pattern_key(p) for p in full_patterns if p.confirmed and _settled_and_confirmed_before(p, cut)
            }
            truncated_confirmed = {
                _pattern_key(p) for p in truncated_patterns if p.confirmed and _settled_and_confirmed_before(p, cut)
            }
            n_checks += 1
            n_missing += len(full_confirmed - truncated_confirmed)
            n_extra += len(truncated_confirmed - full_confirmed)

        assert n_missing == 0, (
            f"{name}: {n_missing} confirmed pattern(s) existed only in hindsight -- a "
            "real-time trader could never have seen these, but a full-series backtest would "
            "have counted them. This is the dangerous direction; investigate before shipping.")
        rate = n_extra / n_checks if n_checks else 0.0
        assert rate <= MAX_BENIGN_DIVERGENCE_RATE, (
            f"{name}: benign hindsight-removal rate {rate:.2%} exceeds the "
            f"{MAX_BENIGN_DIVERGENCE_RATE:.0%} bound -- investigate before assuming this is "
            "just normal swing-detection behavior.")
