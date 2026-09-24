"""
Module: test_wyckoff.py
Description: Regression tests for e07_technical/wyckoff.py's spring/
    upthrust detection. Added 2026-08-02 after discovering
    detect_springs_and_upthrusts had NEVER found a single real spring or
    upthrust: trading_range.support/resistance are the literal min/max
    low/high over exactly the bars the function scanned, so a bar's low
    could never be below that min (nor a high above that max) by
    construction -- confirmed live across GBPUSD/EURUSD/BTC-USD/AAPL
    (thousands of real detected ranges, zero springs/upthrusts before the
    fix, hundreds after). No test existed for this function at all before
    this file, which is exactly how the bug shipped unnoticed.
Author: Shantanu Waykar
Version: 1.0.0
"""

from pathlib import Path

import pandas as pd
import pytest

from project_titan_x.engines.e07_technical.wyckoff import (
    detect_springs_and_upthrusts,
    detect_trading_range,
)

LOOKBACK = 50
ATR_PERIOD = 14
N_BARS = 70


def _flat_range_df(event_index: int, event_ohlc: tuple[float, float, float, float]) -> pd.DataFrame:
    """N_BARS of a tight, flat consolidation (open=100/high=101/low=99/
    close=100 every bar) except at `event_index`, which gets `event_ohlc`
    instead -- lets a single test bar act as a spring/upthrust candidate
    against an otherwise-uniform established range."""
    rows = []
    for i in range(N_BARS):
        if i == event_index:
            o, h, l, c = event_ohlc
        else:
            o, h, l, c = 100.0, 101.0, 99.0, 100.0
        rows.append({"open": o, "high": h, "low": l, "close": c})
    return pd.DataFrame(rows)


def test_trading_range_found_on_flat_synthetic_data():
    df = _flat_range_df(event_index=-1, event_ohlc=(100.0, 101.0, 99.0, 100.0))
    tr = detect_trading_range(df, lookback=LOOKBACK, atr_period=ATR_PERIOD, max_atr_multiple=6.0)
    assert tr is not None
    assert tr.support == pytest.approx(99.0)
    assert tr.resistance == pytest.approx(101.0)


def test_spring_detected_when_bar_undercuts_established_support_and_recovers():
    """A bar late in the range (within the last grace_bars_after_range
    bars) that wicks below the level established by the EARLIER bars,
    then closes back above it, must register as a spring -- this was
    mathematically impossible before the fix."""
    spring_index = 65  # within the last 10 bars (grace window) of a 70-bar range
    df = _flat_range_df(event_index=spring_index, event_ohlc=(99.5, 100.0, 98.0, 99.6))
    tr = detect_trading_range(df, lookback=LOOKBACK, atr_period=ATR_PERIOD, max_atr_multiple=6.0)
    assert tr is not None

    springs, upthrusts = detect_springs_and_upthrusts(df, tr, grace_bars_after_range=10)
    assert upthrusts == []
    assert len(springs) == 1
    spring = springs[0]
    assert spring.index == spring_index
    assert spring.kind == "spring"
    assert spring.wick_price == pytest.approx(98.0)
    assert spring.level == pytest.approx(99.0)  # established support from the earlier, unpolluted bars
    assert spring.wick_price < spring.level  # the whole point: undercut, then closed back above


def test_upthrust_detected_when_bar_exceeds_established_resistance_and_reverses():
    upthrust_index = 65
    df = _flat_range_df(event_index=upthrust_index, event_ohlc=(100.5, 102.0, 100.0, 100.4))
    tr = detect_trading_range(df, lookback=LOOKBACK, atr_period=ATR_PERIOD, max_atr_multiple=6.0)
    assert tr is not None

    springs, upthrusts = detect_springs_and_upthrusts(df, tr, grace_bars_after_range=10)
    assert springs == []
    assert len(upthrusts) == 1
    upthrust = upthrusts[0]
    assert upthrust.index == upthrust_index
    assert upthrust.kind == "upthrust"
    assert upthrust.wick_price == pytest.approx(102.0)
    assert upthrust.level == pytest.approx(101.0)  # established resistance from the earlier bars
    assert upthrust.wick_price > upthrust.level


def test_no_spring_when_range_is_perfectly_flat():
    """Regression guard for the OLD bug's specific failure mode: a
    perfectly flat range with no genuine outlier bar must report zero
    springs/upthrusts, not silently succeed for the wrong reason."""
    df = _flat_range_df(event_index=-1, event_ohlc=(100.0, 101.0, 99.0, 100.0))
    tr = detect_trading_range(df, lookback=LOOKBACK, atr_period=ATR_PERIOD, max_atr_multiple=6.0)
    assert tr is not None
    springs, upthrusts = detect_springs_and_upthrusts(df, tr, grace_bars_after_range=10)
    assert springs == []
    assert upthrusts == []


@pytest.mark.parametrize("fname", ["GBPUSD=X_1d.parquet", "AAPL_1d.parquet"])
def test_real_data_produces_nonzero_springs_and_upthrusts(fname):
    """The core regression guard: on real market data with hundreds of
    detected trading ranges, springs/upthrusts must NOT come back
    universally empty (the exact, previously-silent failure mode)."""
    # Absolute, not cwd-relative: the old "project_titan_x/data/processed/..."
    # string only resolved correctly when pytest's OS-level cwd happened to
    # be TIS/ (this repo's own parent) -- failed with a FileNotFoundError
    # for the exact same real data when invoked with cwd=project_titan_x
    # itself (a real, encountered case, not hypothetical: scripts/training/
    # *.py in this same repo need that same parent dir on PYTHONPATH for a
    # different reason, so cwd conventions here are already easy to get
    # wrong -- this test shouldn't depend on getting it right).
    data_dir = Path(__file__).resolve().parents[2] / "data" / "processed"
    # Checked per-parameter rather than as a module-level skipif: data/ ships
    # empty in the public repository, and one asset may be fetched without the
    # other, so each case reports its own status honestly.
    if not (data_dir / fname).is_file():
        pytest.skip(
            f"needs data/processed/{fname}, not shipped in this repository "
            "-- regenerate with scripts/fetch_all_data.py"
        )
    df = pd.read_parquet(data_dir / fname).reset_index(drop=True)
    if "timestamp" not in df.columns:
        df = df.rename(columns={df.columns[0]: "timestamp"})

    total_springs = total_upthrusts = total_ranges = 0
    for i in range(70, len(df), 25):
        sub = df.iloc[: i + 1]
        tr = detect_trading_range(sub, lookback=LOOKBACK, atr_period=ATR_PERIOD)
        if tr is None:
            continue
        total_ranges += 1
        springs, upthrusts = detect_springs_and_upthrusts(sub, tr, grace_bars_after_range=10)
        total_springs += len(springs)
        total_upthrusts += len(upthrusts)

    assert total_ranges > 10  # sanity: the ATR-relative filter should find plenty of real ranges
    assert total_springs > 0
    assert total_upthrusts > 0
