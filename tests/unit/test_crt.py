"""
Tests for CRT (Candle Range Theory) detection, engines/e07_technical/crt.py.

THE TRANSLATION-TRAP TEST IS THE POINT (docs/ICT_SPEC_PHASE5.md 1.4/1.11
item 1): a setup detected using bars i and i+1 must be EMITTED at i+1,
never at i -- the same defect class as the order-block lookahead bug that
once reported a 94.8% win rate. Multi-truncation at 0.35/0.5/0.65/0.8/0.93
follows Rule 7; a single midpoint cut is documented as insufficient.

CRT's determinism is actually STRONGER than MSS/displacement's: a setup at
range_bar_index=i depends only on bar i, bar i+1, and a trailing ATR window
ending at i -- nothing about any bar beyond i+1 can change whether it
fires. So truncation tests here assert EXACT equality (zero tolerance),
not the hindsight-bounded tolerance MSS's own tests need for its
swing-revision noise.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from project_titan_x.engines.e07_technical.crt import CRTSetup, detect_crt_setups

TRUNCATION_POINTS = (0.35, 0.5, 0.65, 0.8, 0.93)
DATASETS = ("GC=F_4h", "BTC-USD_4h", "AAPL_1d")
PROJECTION_MULT_DEFAULT = 1.0
EXTENSION_LEVEL_DEFAULT = 1.618


@pytest.fixture(scope="module")
def frames():
    root = Path(__file__).resolve().parents[2] / "data" / "processed"
    out = {}
    for name in DATASETS:
        p = root / f"{name}.parquet"
        if p.exists():
            out[name] = pd.read_parquet(p).tail(4000).reset_index(drop=True)
    if not out:
        pytest.skip("no local parquet data available")
    return out


def _synthetic(n=600, seed=11):
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 1.0, n))
    high = close + np.abs(rng.normal(0, 0.6, n))
    low = close - np.abs(rng.normal(0, 0.6, n))
    open_ = close + rng.normal(0, 0.3, n)
    return pd.DataFrame({
        "open": open_, "high": np.maximum.reduce([high, open_, close]),
        "low": np.minimum.reduce([low, open_, close]), "close": close,
        "volume": rng.integers(1_000, 10_000, n).astype(float),
    })


def _flat_then_range_bar(range_atr_mult=1.34, body_ratio=0.6, broke="high", retrace=0.4, n=40):
    """A synthetic series with 30 flat warm-up bars (stable ATR), then a
    qualifying range bar at index 30, then a controlled next bar at index
    31 that breaks exactly one side by a known amount and retraces by a
    known fraction."""
    rows = []
    for _ in range(30):
        rows.append({"open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 1000.0})
    # ATR of a series of 1.0-range bars is ~1.0 once warmed up.
    range_i = range_atr_mult * 1.0
    high_i, low_i = 100.0 + range_i / 2, 100.0 - range_i / 2
    body = body_ratio * range_i
    open_i, close_i = low_i + (range_i - body) / 2, low_i + (range_i - body) / 2 + body
    rows.append({"open": open_i, "high": high_i, "low": low_i, "close": close_i, "volume": 1000.0})
    if broke == "high":
        high_k = high_i + 0.3
        close_k = high_i - retrace * range_i
        rows.append({"open": close_i, "high": high_k, "low": low_i + 0.1, "close": close_k, "volume": 1000.0})
    elif broke == "low":
        low_k = low_i - 0.3
        close_k = low_i + retrace * range_i
        rows.append({"open": close_i, "high": high_i - 0.1, "low": low_k, "close": close_k, "volume": 1000.0})
    elif broke == "both":
        rows.append({"open": close_i, "high": high_i + 0.3, "low": low_i - 0.3, "close": close_i, "volume": 1000.0})
    elif broke == "neither":
        rows.append({"open": close_i, "high": high_i - 0.1, "low": low_i + 0.1, "close": close_i, "volume": 1000.0})
    for _ in range(n - len(rows)):
        rows.append({"open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 1000.0})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# The translation trap (spec 1.4 / 1.11 item 1)
# --------------------------------------------------------------------------

def test_bullish_setup_emits_at_k_not_i():
    df = _flat_then_range_bar(broke="high", retrace=0.4)
    setups = detect_crt_setups(df, require_retrace=True)
    assert len(setups) == 1
    s = setups[0]
    assert s.range_bar_index == 30
    assert s.signal_index == 31
    assert s.signal_index != s.range_bar_index
    assert s.direction == "bullish"


def test_bearish_setup_emits_at_k_not_i():
    df = _flat_then_range_bar(broke="low", retrace=0.4)
    setups = detect_crt_setups(df, require_retrace=True)
    assert len(setups) == 1
    s = setups[0]
    assert s.range_bar_index == 30
    assert s.signal_index == 31
    assert s.direction == "bearish"


def test_no_setup_recorded_at_bar_i_itself():
    """A naive port that emitted at i (rather than i+1) would place a
    setup whose defining information (bar i+1's high/low/close) did not
    exist yet -- assert this never happens for ANY detected setup."""
    df = _synthetic()
    setups = detect_crt_setups(df)
    for s in setups:
        assert s.signal_index == s.range_bar_index + 1


# --------------------------------------------------------------------------
# No-lookahead: multi-truncation, EXACT (CRT has no swing-revision noise)
# --------------------------------------------------------------------------

def _setups_by_signal_index(setups: list[CRTSetup]) -> dict:
    return {s.signal_index: s for s in setups}


@pytest.mark.parametrize("cut", TRUNCATION_POINTS)
def test_no_lookahead_on_synthetic(cut):
    df = _synthetic()
    k = int(len(df) * cut)
    full = _setups_by_signal_index(detect_crt_setups(df))
    trunc = _setups_by_signal_index(detect_crt_setups(df.iloc[:k].copy()))
    for idx, t_setup in trunc.items():
        assert idx in full, f"cut {cut}: setup at {idx} in truncated run but not in full run"
        f_setup = full[idx]
        assert t_setup.direction == f_setup.direction
        assert t_setup.range_bar_index == f_setup.range_bar_index
        assert t_setup.entry == pytest.approx(f_setup.entry)
        assert t_setup.stop == pytest.approx(f_setup.stop)
    # Every setup fully contained in the truncated window (signal_index < k)
    # must also appear in the truncated run -- CRT depends only on i, i+1,
    # and a trailing ATR window, all present once k > i+1.
    for idx, f_setup in full.items():
        if idx < k - 1:
            assert idx in trunc, f"cut {cut}: setup at {idx} missing from truncated run (should be fully determined)"


@pytest.mark.parametrize("cut", TRUNCATION_POINTS)
def test_no_lookahead_on_real_data(cut, frames):
    for name, df in frames.items():
        k = int(len(df) * cut)
        full = _setups_by_signal_index(detect_crt_setups(df))
        trunc = _setups_by_signal_index(detect_crt_setups(df.iloc[:k].copy()))
        for idx, t_setup in trunc.items():
            assert idx in full, f"{name} cut {cut}: setup at {idx} in truncated but not full run"
            f_setup = full[idx]
            assert t_setup.direction == f_setup.direction, f"{name} cut {cut} idx {idx}"
            assert t_setup.entry == pytest.approx(f_setup.entry), f"{name} cut {cut} idx {idx}"


def test_appending_a_bar_never_rewrites_history(frames):
    df = next(iter(frames.values())).tail(800).reset_index(drop=True)
    base = _setups_by_signal_index(detect_crt_setups(df.iloc[:-1].copy()))
    extended = _setups_by_signal_index(detect_crt_setups(df))
    for idx, b_setup in base.items():
        assert idx in extended
        assert b_setup.direction == extended[idx].direction
        assert b_setup.entry == pytest.approx(extended[idx].entry)


# --------------------------------------------------------------------------
# Edge cases (spec 1.8)
# --------------------------------------------------------------------------

def test_both_sides_broken_is_rejected():
    df = _flat_then_range_bar(broke="both")
    assert detect_crt_setups(df) == []


def test_neither_side_broken_is_rejected():
    df = _flat_then_range_bar(broke="neither")
    assert detect_crt_setups(df) == []


def test_zero_range_bar_is_rejected():
    n = 40
    df = pd.DataFrame({
        "open": [100.0] * n, "high": [100.0] * n, "low": [100.0] * n,
        "close": [100.0] * n, "volume": [1000.0] * n,
    })
    assert detect_crt_setups(df) == []


def test_insufficient_history_returns_empty():
    df = _synthetic(n=10)
    assert detect_crt_setups(df, atr_period=14) == []


def test_last_bar_of_series_cannot_emit():
    """No i+1 exists for the final bar -- the loop must stop at len-2, so
    no setup's range_bar_index can equal the last index."""
    df = _synthetic()
    setups = detect_crt_setups(df)
    last_idx = len(df) - 1
    assert all(s.range_bar_index < last_idx for s in setups)


def test_retrace_filter_rejects_below_threshold():
    df = _flat_then_range_bar(broke="high", retrace=0.1)  # below default 0.25
    assert detect_crt_setups(df, require_retrace=True) == []


def test_retrace_filter_can_be_disabled():
    df = _flat_then_range_bar(broke="high", retrace=0.1)
    setups = detect_crt_setups(df, require_retrace=False)
    assert len(setups) == 1


def test_range_atr_outside_band_is_rejected():
    too_small = _flat_then_range_bar(range_atr_mult=0.5, broke="high", retrace=0.4)
    assert detect_crt_setups(too_small) == []
    # The range bar's own true range feeds into its own trailing ATR (a
    # self-inclusive rolling window), so a nominal 3.5x multiplier is
    # diluted down to an actual range_atr of ~2.97 (still inside the 3.0
    # ceiling) -- 5x clears it with margin, verified empirically.
    too_large = _flat_then_range_bar(range_atr_mult=5.0, broke="high", retrace=0.4)
    assert detect_crt_setups(too_large) == []


def test_body_ratio_below_minimum_is_rejected():
    df = _flat_then_range_bar(body_ratio=0.1, broke="high", retrace=0.4)
    assert detect_crt_setups(df) == []


# --------------------------------------------------------------------------
# Levels and quality (spec 1.2)
# --------------------------------------------------------------------------

def test_bullish_levels_match_spec_formulas():
    df = _flat_then_range_bar(broke="high", retrace=0.4)
    s = detect_crt_setups(df)[0]
    range_i = s.range_high - s.range_low
    assert s.entry == pytest.approx((s.range_high + s.range_low) / 2)
    assert s.tp1 == pytest.approx(s.range_high + 0.5 * range_i * PROJECTION_MULT_DEFAULT)
    assert s.tp2 == pytest.approx(s.range_high + range_i * PROJECTION_MULT_DEFAULT)
    assert s.tp3 == pytest.approx(s.range_high + range_i * EXTENSION_LEVEL_DEFAULT)
    assert s.tp2 > s.entry > s.stop  # bullish: target above, stop below


def test_bearish_levels_match_spec_formulas():
    df = _flat_then_range_bar(broke="low", retrace=0.4)
    s = detect_crt_setups(df)[0]
    range_i = s.range_high - s.range_low
    assert s.entry == pytest.approx((s.range_high + s.range_low) / 2)
    assert s.tp1 == pytest.approx(s.range_low - 0.5 * range_i * PROJECTION_MULT_DEFAULT)
    assert s.tp2 == pytest.approx(s.range_low - range_i * PROJECTION_MULT_DEFAULT)
    assert s.tp3 == pytest.approx(s.range_low - range_i * EXTENSION_LEVEL_DEFAULT)
    assert s.stop > s.entry > s.tp2  # bearish: stop above, target below


def test_quality_tier_boundaries():
    from project_titan_x.engines.e07_technical.crt import _quality_tier

    assert _quality_tier(1.5) == "A"
    assert _quality_tier(1.49) == "B"
    assert _quality_tier(1.2) == "B"
    assert _quality_tier(1.19) == "C"
    assert _quality_tier(0.9) == "C"
    assert _quality_tier(0.89) == "D"


def test_body_ratio_field_is_a_body_ratio_not_a_wick_ratio():
    """Spec 1.10 bug 2: STAR-EA's source misnames this 'wickRatio' while
    computing bodySize/candleRange. A high body_ratio here must correspond
    to a LARGE body, small wicks -- not the reverse."""
    df = _flat_then_range_bar(body_ratio=0.9, broke="high", retrace=0.4)
    s = detect_crt_setups(df)[0]
    assert s.body_ratio == pytest.approx(0.9, abs=0.05)
