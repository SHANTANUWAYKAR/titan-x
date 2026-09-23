"""
Module: test_order_flow.py
Description: Unit tests for engines/e07_technical/order_flow.py -- new
    2026-08-21 module (CVD, CVD divergence, absorption). No dedicated
    test file existed before this; covers the CLV-based delta
    approximation's math directly and the two pattern detectors on
    constructed, hand-verifiable OHLCV.
Author: Shantanu Waykar
Version: 1.0.0
"""

import pandas as pd

from project_titan_x.engines.e07_technical.order_flow import (
    AbsorptionEvent,
    CVDDivergenceKind,
    bar_delta_approx,
    compute_cumulative_delta,
    detect_absorption,
    detect_cvd_divergences,
)
from project_titan_x.engines.e07_technical.structure import SwingKind, SwingPoint


def _ohlcv(rows: list[tuple[float, float, float, float, float]]) -> pd.DataFrame:
    """rows: list of (open, high, low, close, volume)."""
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"])


def test_bar_delta_approx_close_at_high_is_fully_positive():
    df = _ohlcv([(100.0, 110.0, 95.0, 110.0, 1000.0)])
    delta = bar_delta_approx(df)
    assert delta.iloc[0] == 1000.0  # closed exactly at the high -> CLV=+1 -> delta=+volume


def test_bar_delta_approx_close_at_low_is_fully_negative():
    df = _ohlcv([(100.0, 110.0, 95.0, 95.0, 1000.0)])
    delta = bar_delta_approx(df)
    assert delta.iloc[0] == -1000.0


def test_bar_delta_approx_close_at_midpoint_is_zero():
    df = _ohlcv([(100.0, 110.0, 90.0, 100.0, 1000.0)])
    delta = bar_delta_approx(df)
    assert delta.iloc[0] == 0.0


def test_bar_delta_approx_flat_bar_is_zero_not_nan():
    df = _ohlcv([(100.0, 100.0, 100.0, 100.0, 1000.0)])
    delta = bar_delta_approx(df)
    assert delta.iloc[0] == 0.0


def test_bar_delta_approx_no_volume_column_returns_all_zero():
    df = pd.DataFrame({"open": [1.0], "high": [2.0], "low": [0.5], "close": [1.8]})
    delta = bar_delta_approx(df)
    assert (delta == 0.0).all()


def test_compute_cumulative_delta_is_running_sum():
    df = _ohlcv([
        (100.0, 110.0, 95.0, 110.0, 1000.0),  # delta = +1000
        (110.0, 115.0, 105.0, 105.0, 500.0),  # delta = -500
    ])
    cvd = compute_cumulative_delta(df)
    assert cvd.iloc[0] == 1000.0
    assert cvd.iloc[1] == 500.0


def test_detect_cvd_divergences_bearish_when_price_higher_high_but_cvd_lower_high():
    # Two swing highs: price makes a HIGHER high at index 5, but CVD is
    # LOWER there than at index 1 -- classic bearish CVD divergence.
    df = pd.DataFrame({"close": [0.0] * 10})
    swings = [
        SwingPoint(index=1, price=100.0, kind=SwingKind.HIGH),
        SwingPoint(index=5, price=105.0, kind=SwingKind.HIGH),
    ]
    cvd = pd.Series([0.0, 500.0, 0, 0, 0, 300.0, 0, 0, 0, 0])
    divs = detect_cvd_divergences(df, swings, cvd=cvd)
    assert len(divs) == 1
    assert divs[0].kind == CVDDivergenceKind.BEARISH
    assert divs[0].first_index == 1 and divs[0].second_index == 5


def test_detect_cvd_divergences_bullish_when_price_lower_low_but_cvd_higher_low():
    df = pd.DataFrame({"close": [0.0] * 10})
    swings = [
        SwingPoint(index=1, price=100.0, kind=SwingKind.LOW),
        SwingPoint(index=5, price=95.0, kind=SwingKind.LOW),
    ]
    cvd = pd.Series([0.0, -500.0, 0, 0, 0, -300.0, 0, 0, 0, 0])
    divs = detect_cvd_divergences(df, swings, cvd=cvd)
    assert len(divs) == 1
    assert divs[0].kind == CVDDivergenceKind.BULLISH


def test_detect_cvd_divergences_no_divergence_when_price_and_cvd_agree():
    df = pd.DataFrame({"close": [0.0] * 10})
    swings = [
        SwingPoint(index=1, price=100.0, kind=SwingKind.HIGH),
        SwingPoint(index=5, price=105.0, kind=SwingKind.HIGH),
    ]
    cvd = pd.Series([0.0, 300.0, 0, 0, 0, 500.0, 0, 0, 0, 0])  # CVD also higher -- no divergence
    divs = detect_cvd_divergences(df, swings, cvd=cvd)
    assert divs == []


def test_detect_absorption_flags_buyers_absorbed_on_high_volume_positive_delta_flat_close():
    rows = [(100.0, 101.0, 99.0, 100.5, 100.0) for _ in range(20)]  # quiet baseline, avg_vol=100
    # Spike bar: deep lower wick (low=90) that gets bought back up to close
    # near the bar's OWN high (close=99 is close to high=101, far from
    # low=90 -> strong positive CLV/delta) -- but close (99) is still
    # BELOW open (100), i.e. zero/negative net bar displacement, with 3x
    # relative volume. Textbook buyers-absorbed: real buying effort
    # (defended the low, pushed price back up within the bar) that still
    # failed to actually close the bar higher.
    rows.append((100.0, 101.0, 90.0, 99.0, 300.0))
    df = _ohlcv(rows)
    events = detect_absorption(df, lookback=20, min_relative_volume=1.5)
    assert len(events) == 1
    assert events[0].direction == "buyers_absorbed"
    assert events[0].index == 20


def test_detect_absorption_ignores_normal_volume_bars():
    rows = [(100.0, 101.0, 99.0, 100.5, 100.0) for _ in range(25)]
    df = _ohlcv(rows)
    events = detect_absorption(df, lookback=20, min_relative_volume=1.5)
    assert events == []


def test_detect_absorption_no_volume_column_returns_empty():
    df = pd.DataFrame({"open": [1.0] * 25, "high": [2.0] * 25, "low": [0.5] * 25, "close": [1.8] * 25})
    events = detect_absorption(df)
    assert events == []
