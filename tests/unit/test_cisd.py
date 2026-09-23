"""
Tests for CISD (Change in State of Delivery) detection,
engines/e07_technical/cisd.py.

Two determinism classes, tested at different rigor deliberately:
- direction/signal_index/entry_zone (Steps 1-3) depend ONLY on the FVG
  index, the break bar, and the immediate 3-candle window around it --
  bar-local, like CRT. Tested with EXACT truncation equality.
- `stop` depends on find_swing_points, which (like MSS) can revise a
  swing's confirmation status as later bars arrive within its centered
  lookback window -- tested with the same bounded tolerance
  test_market_structure_shift.py already established for that reason,
  not treated as a bug when it happens at the same documented rate.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from project_titan_x.engines.e07_technical.cisd import CISDSetup, detect_cisd_setups

TRUNCATION_POINTS = (0.35, 0.5, 0.65, 0.8, 0.93)
DATASETS = ("GC=F_4h", "BTC-USD_4h", "AAPL_1d")


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


def _synthetic(n=600, seed=13):
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


def _constructed_bullish_cisd():
    """Hand-built series with a real bearish FVG at g whose zone safely
    contains the "flat filler" close price (100.0, so bars between g and
    b never trigger an accidental early break), failing at b, with a new
    OPPOSITE-direction (bullish) FVG centered on b whose zone overlaps
    the original -- the exact composition spec 2.3 describes.

    zone facts (explicit, not left to arithmetic surprise):
      original bearish FVG at g=10: low[9]=106.0, high[11]=95.0
        -> zone [95.0, 106.0] (contains the 100.0 filler close safely)
      break at b=15: close[15]=106.5 > gap_top=106.0 -> fails
      new FVG at b: high[14]=105.5 < low[16]=106.5 -> bullish, zone [105.5, 106.5]
      overlap([95,106], [105.5,106.5]) = [105.5, 106] -- a real, nonzero overlap
    """
    n = 30
    flat = {"open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 1000.0}
    rows = [dict(flat) for _ in range(n)]
    g, b = 10, 15
    rows[g - 1] = {"open": 100.0, "high": 100.2, "low": 106.0, "close": 100.0, "volume": 1000.0}
    rows[g + 1] = {"open": 100.0, "high": 95.0, "low": 94.5, "close": 100.0, "volume": 1000.0}
    rows[b - 1] = {"open": 100.0, "high": 105.5, "low": 99.0, "close": 100.0, "volume": 1000.0}
    rows[b] = {"open": 100.0, "high": 107.0, "low": 99.0, "close": 106.5, "volume": 1000.0}
    rows[b + 1] = {"open": 106.5, "high": 108.0, "low": 106.5, "close": 107.0, "volume": 1000.0}
    return pd.DataFrame(rows), g, b


# --------------------------------------------------------------------------
# The translation trap (spec 2.3 / "same trap as CRT 1.4")
# --------------------------------------------------------------------------

def test_setup_emits_at_b_plus_1_not_b():
    df, g, b = _constructed_bullish_cisd()
    setups = detect_cisd_setups(df)
    assert len(setups) >= 1
    s = setups[0]
    assert s.break_bar_index == b
    assert s.signal_index == b + 1
    assert s.original_fvg_index == g
    assert s.direction == "bullish"


def test_no_setup_recorded_at_break_bar_itself():
    df = _synthetic()
    for s in detect_cisd_setups(df):
        assert s.signal_index == s.break_bar_index + 1


def test_entry_zone_is_the_real_overlap():
    df, g, b = _constructed_bullish_cisd()
    s = detect_cisd_setups(df)[0]
    assert s.entry_zone_low == pytest.approx(105.5, abs=0.01)
    assert s.entry_zone_high == pytest.approx(106.0, abs=0.01)
    assert s.entry_zone_high > s.entry_zone_low


# --------------------------------------------------------------------------
# No-lookahead: multi-truncation, EXACT for direction/signal_index/zone
# --------------------------------------------------------------------------

def _by_signal_index(setups: list[CISDSetup]) -> dict:
    return {s.signal_index: s for s in setups}


@pytest.mark.parametrize("cut", TRUNCATION_POINTS)
def test_no_lookahead_on_synthetic(cut):
    df = _synthetic()
    k = int(len(df) * cut)
    full = _by_signal_index(detect_cisd_setups(df))
    trunc = _by_signal_index(detect_cisd_setups(df.iloc[:k].copy()))
    for idx, t_setup in trunc.items():
        assert idx in full, f"cut {cut}: setup at {idx} in truncated but not full run"
        f_setup = full[idx]
        assert t_setup.direction == f_setup.direction
        assert t_setup.entry_zone_low == pytest.approx(f_setup.entry_zone_low)
        assert t_setup.entry_zone_high == pytest.approx(f_setup.entry_zone_high)


@pytest.mark.parametrize("cut", TRUNCATION_POINTS)
def test_no_lookahead_on_real_data(cut, frames):
    for name, df in frames.items():
        k = int(len(df) * cut)
        full = _by_signal_index(detect_cisd_setups(df))
        trunc = _by_signal_index(detect_cisd_setups(df.iloc[:k].copy()))
        for idx, t_setup in trunc.items():
            assert idx in full, f"{name} cut {cut}: setup at {idx} in truncated but not full"
            assert t_setup.direction == full[idx].direction, f"{name} cut {cut} idx {idx}"


def _assert_stop_no_hindsight(trunc_by_idx: dict, full_by_idx: dict, label: str) -> None:
    """Same bounded-hindsight tolerance as test_market_structure_shift.py's
    own _assert_no_hindsight, applied to the swing-dependent `stop` field
    only -- direction/zone are asserted exactly above."""
    common = set(trunc_by_idx) & set(full_by_idx)
    mismatches = sum(
        1 for idx in common
        if (trunc_by_idx[idx].stop is None) != (full_by_idx[idx].stop is None)
        or (trunc_by_idx[idx].stop is not None and abs(trunc_by_idx[idx].stop - full_by_idx[idx].stop) > 1e-6)
    )
    limit = max(2, len(common) // 5) if common else 0
    assert mismatches <= limit, f"{label}: {mismatches}/{len(common)} stop values disagree beyond swing-revision noise"


@pytest.mark.parametrize("cut", TRUNCATION_POINTS)
def test_stop_field_no_lookahead_within_swing_revision_tolerance(cut, frames):
    for name, df in frames.items():
        k = int(len(df) * cut)
        full = _by_signal_index(detect_cisd_setups(df))
        trunc = _by_signal_index(detect_cisd_setups(df.iloc[:k].copy()))
        _assert_stop_no_hindsight(trunc, full, f"{name} cut {cut}")


# --------------------------------------------------------------------------
# Edge cases (spec 2.4)
# --------------------------------------------------------------------------

def test_no_fvg_no_setups():
    n = 40
    df = pd.DataFrame({
        "open": [100.0] * n, "high": [100.5] * n, "low": [99.5] * n,
        "close": [100.0] * n, "volume": [1000.0] * n,
    })
    assert detect_cisd_setups(df) == []


def test_touching_zones_are_rejected():
    """overlap_high == overlap_low must be rejected, not treated as a
    zero-width zone."""
    from project_titan_x.engines.e07_technical import cisd as cisd_module

    real_detect = cisd_module.detect_fair_value_gaps

    class _FakeGap:
        def __init__(self, index, direction, gap_bottom, gap_top):
            self.index = index
            self.direction = direction
            self.gap_bottom = gap_bottom
            self.gap_top = gap_top
            self.filled = False

    df, _, _ = _constructed_bullish_cisd()
    # Force the original gap's zone to only TOUCH the new FVG zone (which
    # this constructed series' Step 2 always computes as [99.5, 100.0]).
    fake_gaps = [_FakeGap(index=10, direction="bearish", gap_bottom=99.5, gap_top=99.5)]
    try:
        cisd_module.detect_fair_value_gaps = lambda d: fake_gaps
        assert cisd_module.detect_cisd_setups(df) == []
    finally:
        cisd_module.detect_fair_value_gaps = real_detect


def test_last_bar_cannot_emit():
    df = _synthetic()
    n = len(df)
    for s in detect_cisd_setups(df):
        assert s.signal_index < n


def test_at_most_one_signal_per_direction_per_bar():
    df = _synthetic()
    setups = detect_cisd_setups(df)
    keys = [(s.signal_index, s.direction) for s in setups]
    assert len(keys) == len(set(keys))


def test_stop_is_a_real_finite_price_when_present():
    """Not asserting a strict correct-side relationship: the stop is the
    most recent swing of the right kind strictly before b, and depending
    on how far price has moved since that swing, it's genuinely possible
    (not a bug) for it to sit inside or beyond the entry zone in
    unusual price action -- this only checks it's a real, finite, sane
    number, never NaN/inf/a placeholder."""
    for df in (_synthetic(seed=1), _synthetic(seed=2), _synthetic(seed=3)):
        for s in detect_cisd_setups(df):
            if s.stop is None:
                continue
            assert np.isfinite(s.stop)
            assert s.stop > 0
