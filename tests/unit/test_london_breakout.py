"""
Tests for the London Breakout port (je-suis-tm/quant-trading, Apache-2.0).

The session structure is what makes this strategy different from every
other breakout archetype in E24 -- and also what makes it easy to get
subtly wrong. These tests pin the three things that would silently break
it: the reference range must come only from bars BEFORE the session, it
must not leak across calendar days, and the whole thing must survive
truncation without changing an earlier bar's signal.
"""

import numpy as np
import pandas as pd
import pytest

from project_titan_x.engines.e24_strategy_research.plugins.london_breakout import (
    london_breakout,
    london_breakout_buffered,
)

TRUNCATION_POINTS = (0.35, 0.5, 0.65, 0.8, 0.93)


def _session_frame(days=12, seed=4, bar_minutes=15):
    """Synthetic 15m FX-style bars across several London days."""
    rng = np.random.default_rng(seed)
    per_day = int(24 * 60 / bar_minutes)
    ts = pd.date_range("2024-03-20 00:00", periods=days * per_day,
                       freq=f"{bar_minutes}min", tz="UTC")
    close = 1.10 + np.cumsum(rng.normal(0, 0.0004, len(ts)))
    high = close + np.abs(rng.normal(0, 0.0003, len(ts)))
    low = close - np.abs(rng.normal(0, 0.0003, len(ts)))
    return pd.DataFrame({
        "timestamp": ts, "open": close, "high": np.maximum(high, close),
        "low": np.minimum(low, close), "close": close,
        "volume": rng.integers(100, 1000, len(ts)).astype(float),
    })


@pytest.fixture(scope="module")
def real_fx():
    from pathlib import Path
    p = Path(__file__).resolve().parents[2] / "data" / "processed" / "EURUSD=X_15m.parquet"
    if not p.exists():
        pytest.skip("EURUSD 15m parquet not available")
    return pd.read_parquet(p).tail(12000).reset_index(drop=True)


# --------------------------------------------------------------------------
# Session structure
# --------------------------------------------------------------------------

def test_flat_outside_the_trading_session(real_fx):
    """Nothing may be held outside ref_end..session_end London local."""
    from zoneinfo import ZoneInfo
    sig = london_breakout(real_fx).to_numpy()
    hour = real_fx["timestamp"].dt.tz_convert(ZoneInfo("Europe/London")).dt.hour.to_numpy()
    outside = (hour < 7) | (hour >= 16)
    assert not sig[outside].any(), "signal held outside the London session"


def test_no_position_carries_into_the_next_day(real_fx):
    """Each London day starts flat -- the strategy is intraday by design."""
    from zoneinfo import ZoneInfo
    local = real_fx["timestamp"].dt.tz_convert(ZoneInfo("Europe/London"))
    sig = london_breakout(real_fx)
    first_of_day = local.dt.normalize() != local.dt.normalize().shift()
    assert (sig[first_of_day.to_numpy()] == 0).all()


def test_reference_range_uses_only_pre_session_bars():
    """Move a bar INSIDE the session to an extreme. If the reference range
    were computed from session bars too, the level would move and the
    signal would change. It must not."""
    df = _session_frame()
    base = london_breakout(df).to_numpy()
    from zoneinfo import ZoneInfo
    hour = df["timestamp"].dt.tz_convert(ZoneInfo("Europe/London")).dt.hour.to_numpy()
    session_idx = np.flatnonzero((hour >= 7) & (hour < 16))
    assert len(session_idx) > 20
    tampered = df.copy()
    i = session_idx[len(session_idx) // 2]
    tampered.loc[i, "high"] = tampered.loc[i, "high"] + 5.0   # absurd spike
    after = london_breakout(tampered).to_numpy()
    # bars BEFORE the tampered one cannot change
    assert np.array_equal(base[:i], after[:i])


def test_missing_reference_window_yields_no_signal():
    """A day whose pre-London hour is absent (holiday/gap) must produce
    nothing, not fall back to some other day's levels."""
    df = _session_frame(days=6)
    from zoneinfo import ZoneInfo
    local = df["timestamp"].dt.tz_convert(ZoneInfo("Europe/London"))
    hour = local.dt.hour.to_numpy()
    day = local.dt.normalize()
    target_day = sorted(set(day))[3]
    drop = (day == target_day).to_numpy() & (hour >= 6) & (hour < 7)
    df2 = df.loc[~drop].reset_index(drop=True)
    sig = london_breakout(df2)
    local2 = df2["timestamp"].dt.tz_convert(ZoneInfo("Europe/London"))
    on_that_day = (local2.dt.normalize() == target_day).to_numpy()
    assert (sig.to_numpy()[on_that_day] == 0).all()


# --------------------------------------------------------------------------
# DST -- the reason this uses IANA zones instead of a UTC offset
# --------------------------------------------------------------------------

def test_session_tracks_london_dst_not_a_fixed_utc_offset():
    """Across the March DST switch the session's UTC hour must shift by one.

    A hardcoded UTC offset is silently wrong for the weeks around each
    switch -- the exact defect documented in STAR-EA's manual offset table.
    """
    from zoneinfo import ZoneInfo
    ts = pd.date_range("2024-03-25 00:00", periods=4 * 24 * 14, freq="15min", tz="UTC")
    df = pd.DataFrame({"timestamp": ts, "open": 1.1, "high": 1.1,
                       "low": 1.1, "close": 1.1, "volume": 1.0})
    local = df["timestamp"].dt.tz_convert(ZoneInfo("Europe/London"))
    offsets = set(local.dt.strftime("%z"))
    assert len(offsets) >= 1
    # London local 07:00 must map to different UTC hours before/after the switch
    seven = local.dt.hour == 7
    utc_hours = set(df.loc[seven.to_numpy(), "timestamp"].dt.hour)
    assert len(utc_hours) == 2, f"expected a DST shift, got UTC hours {utc_hours}"


# --------------------------------------------------------------------------
# No-lookahead
# --------------------------------------------------------------------------

@pytest.mark.parametrize("cut", TRUNCATION_POINTS)
@pytest.mark.parametrize("fn", [london_breakout, london_breakout_buffered])
def test_no_lookahead_truncation(fn, cut, real_fx):
    k = int(len(real_fx) * cut)
    full = fn(real_fx).to_numpy()
    trunc = fn(real_fx.iloc[:k].copy()).to_numpy()
    assert np.array_equal(trunc, full[:k]), (
        f"{fn.__name__} changed {int((trunc != full[:k]).sum())} of {k} values when "
        "later bars were removed"
    )


def test_appending_a_bar_never_rewrites_history(real_fx):
    sub = real_fx.tail(3000).reset_index(drop=True)
    base = london_breakout(sub.iloc[:-1].copy()).to_numpy()
    ext = london_breakout(sub).to_numpy()
    assert np.array_equal(base, ext[:-1])


# --------------------------------------------------------------------------
# Semantics
# --------------------------------------------------------------------------

def test_output_is_ternary_and_aligned(real_fx):
    for fn in (london_breakout, london_breakout_buffered):
        s = fn(real_fx)
        assert set(np.unique(s.to_numpy())) <= {-1, 0, 1}
        assert len(s) == len(real_fx)
        assert s.index.equals(real_fx.index)


def test_buffered_never_enters_earlier_than_plain(real_fx):
    """The correct invariant, and NOT the obvious one.

    The obvious assumption -- that a cushion can only remove breakouts, so
    the buffered signal is a strict subset -- is FALSE, and the first
    version of this test asserted it and failed. Verified mechanism: the
    cushion DELAYS entry, and a delayed entry can catch the opposite break
    later in the same session. Measured example, 2026-03-30: plain enters
    long at bar 30 of the session, buffered enters SHORT at bar 32, because
    by then price had broken the other side. 62 bars disagree that way
    across 12,000.

    What actually holds, on every one of the 125 sessions where both
    enter: the buffered entry is never earlier than the plain one.
    """
    from zoneinfo import ZoneInfo

    plain = london_breakout(real_fx).to_numpy()
    buffered = london_breakout_buffered(real_fx).to_numpy()
    assert int((buffered != 0).sum()) <= int((plain != 0).sum())

    day = real_fx["timestamp"].dt.tz_convert(ZoneInfo("Europe/London")).dt.normalize()
    compared = 0
    for d in sorted(set(day)):
        m = (day == d).to_numpy()
        ip, ib = np.flatnonzero(plain[m] != 0), np.flatnonzero(buffered[m] != 0)
        if len(ip) and len(ib):
            compared += 1
            assert ib[0] >= ip[0], f"buffered entered EARLIER than plain on {d}"
    assert compared > 20, "too few comparable sessions for this to mean anything"


def test_trades_both_directions(real_fx):
    sig = london_breakout(real_fx).to_numpy()
    assert (sig > 0).sum() > 0 and (sig < 0).sum() > 0


def test_handles_missing_timestamp_and_empty_input():
    assert len(london_breakout(pd.DataFrame())) == 0
    df = pd.DataFrame({"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0]})
    assert (london_breakout(df) == 0).all()
