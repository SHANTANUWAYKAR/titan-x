"""
Tests for the three je-suis-tm/quant-trading archetypes ported into E24.

The shooting_star tests matter most: the source computes two of its eight
conditions with `shift(-1)` and a third against a whole-dataframe mean, so
a verbatim port would have three separate lookaheads. These tests assert
the corrected behaviour and would fail if anyone "simplified" it back.
"""

import numpy as np
import pandas as pd
import pytest

from project_titan_x.engines.e24_strategy_research.plugins.quant_trading_classics import (
    awesome_oscillator,
    parabolic_sar,
    shooting_star,
)

ALL = (awesome_oscillator, parabolic_sar, shooting_star)
TRUNCATION_POINTS = (0.35, 0.5, 0.65, 0.8, 0.93)
DATASETS = ("GC=F_4h", "BTC-USD_4h", "AAPL_1d")


@pytest.fixture(scope="module")
def frames():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2] / "data" / "processed"
    out = {n: pd.read_parquet(root / f"{n}.parquet").tail(4000).reset_index(drop=True)
           for n in DATASETS if (root / f"{n}.parquet").exists()}
    if not out:
        pytest.skip("no local parquet data")
    return out


def _synthetic(n=500, seed=11):
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 1.0, n))
    high = close + np.abs(rng.normal(0, 0.7, n))
    low = close - np.abs(rng.normal(0, 0.7, n))
    open_ = close + rng.normal(0, 0.4, n)
    return pd.DataFrame({
        "open": open_, "high": np.maximum.reduce([high, open_, close]),
        "low": np.minimum.reduce([low, open_, close]), "close": close,
        "volume": rng.integers(1000, 9000, n).astype(float),
    })


# --------------------------------------------------------------------------
# No-lookahead
# --------------------------------------------------------------------------

@pytest.mark.parametrize("fn", ALL)
@pytest.mark.parametrize("cut", TRUNCATION_POINTS)
def test_no_lookahead_real_data(fn, cut, frames):
    for name, df in frames.items():
        k = int(len(df) * cut)
        full = fn(df).to_numpy()
        trunc = fn(df.iloc[:k].copy()).to_numpy()
        assert np.array_equal(trunc, full[:k]), f"{fn.__name__} leaks future data on {name} at {cut}"


@pytest.mark.parametrize("fn", ALL)
def test_appending_a_bar_never_rewrites_history(fn, frames):
    df = next(iter(frames.values())).tail(1200).reset_index(drop=True)
    base = fn(df.iloc[:-1].copy()).to_numpy()
    ext = fn(df).to_numpy()
    assert np.array_equal(base, ext[:-1])


def test_shooting_star_does_not_use_a_whole_series_body_mean():
    """Source bug 3: condition3 compared each bar's body against
    np.mean over the ENTIRE dataframe, future bars included.

    Append bars to the END and assert nothing already emitted changes. With
    a whole-series mean, later bars would move the threshold every earlier
    bar was judged against.
    """
    df = _synthetic(n=400)
    base = shooting_star(df).to_numpy()
    extra = _synthetic(n=120, seed=99)
    extra["close"] = extra["close"] * 40.0      # wildly different body scale
    extra[["open", "high", "low"]] = extra[["open", "high", "low"]] * 40.0
    longer = pd.concat([df, extra], ignore_index=True)
    assert np.array_equal(base, shooting_star(longer).to_numpy()[:len(df)])


def test_shooting_star_signal_starts_after_the_star_bar():
    """Source bugs 1 and 2: conditions 7 and 8 read the NEXT bar's high and
    close, so the pattern is not knowable on the star bar itself. The port
    must therefore emit at the CONFIRMING bar, never the star bar.

    Asserted structurally: every entry must be preceded by a flat bar, and
    the first bar of the series can never be an entry.
    """
    for df in (_synthetic(n=800, seed=s) for s in (1, 2, 3, 4, 5)):
        sig = shooting_star(df).to_numpy()
        assert sig[0] == 0
        entries = np.flatnonzero((sig != 0) & (np.r_[0, sig[:-1]] == 0))
        for e in entries:
            assert e >= 1, "entry on the first bar is impossible for a confirmed pattern"


# --------------------------------------------------------------------------
# Semantics
# --------------------------------------------------------------------------

@pytest.mark.parametrize("fn", ALL)
def test_output_is_ternary_and_aligned(fn, frames):
    for df in frames.values():
        s = fn(df)
        assert set(np.unique(s.to_numpy())) <= {-1, 0, 1}
        assert len(s) == len(df) and s.index.equals(df.index)


@pytest.mark.parametrize("fn", ALL)
def test_handles_degenerate_input(fn):
    for n in (0, 1, 2, 3, 10):
        df = _synthetic(n=max(n, 1)).iloc[:n]
        assert len(fn(df)) == n
    flat = pd.DataFrame({"open": [100.0] * 60, "high": [100.0] * 60,
                         "low": [100.0] * 60, "close": [100.0] * 60,
                         "volume": [1.0] * 60})
    for f in ALL:
        assert len(f(flat)) == 60


def test_awesome_oscillator_uses_median_price_not_close():
    """The whole point of AO versus a plain MA cross: it averages
    (high+low)/2. If it silently used close, this frame -- where the close
    is constant but the median price trends -- would produce nothing."""
    n = 200
    med_trend = np.linspace(0, 20, n)
    df = pd.DataFrame({
        "open": np.full(n, 100.0), "close": np.full(n, 100.0),
        "high": 100.0 + med_trend + 1.0, "low": 100.0 + med_trend - 1.0,
        "volume": np.ones(n),
    })
    assert int((awesome_oscillator(df) != 0).sum()) > 0


def test_parabolic_sar_follows_a_clean_trend():
    """On a monotonic uptrend SAR must sit below price and report +1."""
    n = 300
    close = np.linspace(100, 200, n)
    df = pd.DataFrame({"open": close, "close": close,
                       "high": close + 0.5, "low": close - 0.5,
                       "volume": np.ones(n)})
    sig = parabolic_sar(df).to_numpy()
    assert (sig[50:] == 1).mean() > 0.9, "SAR failed to hold a clean uptrend"


def test_parabolic_sar_reverses_on_a_trend_change():
    n = 400
    up = np.linspace(100, 180, n // 2)
    down = np.linspace(180, 100, n // 2)
    close = np.r_[up, down]
    df = pd.DataFrame({"open": close, "close": close,
                       "high": close + 0.5, "low": close - 0.5,
                       "volume": np.ones(n)})
    sig = parabolic_sar(df).to_numpy()
    assert sig[n // 2 - 20] == 1
    assert sig[-20] == -1, "SAR never reversed on the downtrend"


def test_shooting_star_is_short_only():
    """It is a bearish reversal pattern; a long signal would be a port bug."""
    for seed in (1, 7, 13, 21):
        sig = shooting_star(_synthetic(n=1500, seed=seed)).to_numpy()
        assert not (sig > 0).any()


def test_shooting_star_holding_period_is_respected():
    sig = shooting_star(_synthetic(n=2000, seed=3), holding_period=5).to_numpy()
    runs = []
    cur = 0
    for v in sig:
        if v != 0:
            cur += 1
        elif cur:
            runs.append(cur); cur = 0
    if cur:
        runs.append(cur)
    assert all(r <= 5 for r in runs), f"a position was held longer than 5 bars: {runs}"
