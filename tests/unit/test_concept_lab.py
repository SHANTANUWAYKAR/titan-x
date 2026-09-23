"""Causality and correctness guards for setups/concept_lab.py.

Every concept here is a claim about what was knowable at bar i. A concept that
peeks does not raise -- it just produces a better number, which is the whole
reason this file exists. The negative control below (truncating the data must
not change an earlier signal) is the test that actually catches that class of
bug; the rest pin arithmetic that would otherwise drift silently.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from project_titan_x.setups.concept_lab import (
    CONCEPTS, LabConfig, _atr, _swings, evaluate,
)


def _ohlcv(n: int = 900, seed: int = 4) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    high = close * (1 + np.abs(rng.normal(0, 0.004, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.004, n)))
    open_ = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame({
        "timestamp": pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC"),
        "open": open_, "high": np.maximum(high, np.maximum(open_, close)),
        "low": np.minimum(low, np.minimum(open_, close)), "close": close,
        "volume": rng.integers(1_000, 9_000, n).astype(float),
    })


# ---------------------------------------------------------------------------
# the negative control -- the only test that catches look-ahead
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(CONCEPTS))
def test_concept_signals_are_causal_under_truncation(name: str) -> None:
    """A signal at bar i must not change when later bars arrive.

    Any concept that reads a future bar -- directly, or through a statistic
    computed over the whole frame -- fails here and nowhere else.
    """
    cfg = LabConfig()
    df = _ohlcv()
    fn = CONCEPTS[name]
    full = fn(df, cfg)
    for cut in (400, 600, 750):
        prefix = fn(df.iloc[:cut].copy(), cfg)
        # the last few bars of a prefix can legitimately differ (a swing needs
        # k more bars to confirm), so compare everything before that margin
        margin = cfg.swing_lookback + 2
        np.testing.assert_array_equal(
            prefix[:cut - margin], full[:cut - margin],
            err_msg=f"{name}: signals before bar {cut - margin} changed when "
                    f"data was extended past {cut} -- it is reading the future")


def test_swings_are_only_marked_after_confirmation() -> None:
    """A pivot at i must not be marked until k more bars have printed.

    Marking it at i is the single most common look-ahead in swing-based code:
    it hands the strategy a turning point the market had not yet confirmed.
    """
    k = 5
    # The pivot must sit at index >= k and <= n-k-1, because _swings only
    # examines range(k, n-k) -- it cannot confirm a pivot that has fewer than
    # k bars on either side. An earlier version of this test put the peak at
    # index 3, which the loop never looks at, and failed for that reason
    # rather than for any defect in the primitive.
    h = np.array([1, 1, 1, 1, 1, 1, 9, 1, 1, 1, 1, 1, 1], dtype=float)
    l = np.ones_like(h)
    sh, _ = _swings(h, l, k)
    peak = int(np.argmax(h))
    assert peak >= k and peak < len(h) - k, "fixture must place the pivot inside the examined range"
    assert not sh[peak], "swing marked on the pivot bar itself -- that is look-ahead"
    assert sh[peak + k], f"swing should be confirmed at bar {peak + k}, not before"
    assert sh.sum() == 1, "exactly one confirmation expected"


# ---------------------------------------------------------------------------
# evaluator arithmetic
# ---------------------------------------------------------------------------

def test_a_bar_containing_both_stop_and_target_is_scored_a_loss() -> None:
    """OHLC cannot order two touches inside one bar.

    Assuming the favourable order is how a backtest flatters itself, so the
    convention must be the pessimistic one. Built as a single long signal
    whose very next bar spans both barriers.
    """
    n = 60
    df = pd.DataFrame({
        "timestamp": pd.date_range("2021-01-01", periods=n, freq="D", tz="UTC"),
        "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
        "volume": 1000.0,
    })
    # a wide bar right after entry that touches stop AND target
    df.loc[31, ["high", "low"]] = [140.0, 60.0]
    sig = np.zeros(n, dtype=int)
    sig[29] = 1
    cfg = LabConfig(min_trades=1, atr_mult=1.0, reward_risk=2.0)
    res = evaluate(df, sig, cfg, "t")
    assert res is not None and res.trades == 1
    assert res.win_rate == 0.0, "a bar spanning both barriers must score a LOSS"


def test_net_equals_gross_minus_cost() -> None:
    """If these drift apart every conclusion built on net R is wrong."""
    df = _ohlcv()
    sig = CONCEPTS["trend_pullback"](df, LabConfig())
    cfg = LabConfig(min_trades=1)
    r = evaluate(df, sig, cfg, "t")
    if r is None:
        pytest.skip("fixture produced too few trades")
    assert r.net_r == pytest.approx(r.gross_r - r.cost_r, abs=1e-9)


def test_zero_cost_makes_net_equal_gross() -> None:
    df = _ohlcv()
    sig = CONCEPTS["trend_pullback"](df, LabConfig())
    r = evaluate(df, sig, LabConfig(min_trades=1, cost_round_trip=0.0), "t")
    if r is None:
        pytest.skip("fixture produced too few trades")
    assert r.cost_r == pytest.approx(0.0, abs=1e-12)
    assert r.net_r == pytest.approx(r.gross_r, abs=1e-12)


def test_wider_stops_pay_strictly_less_cost_per_r() -> None:
    """The whole basis of the stop-width sweep, pinned.

    cost_R = cost / stop_frac, so doubling the stop must roughly halve the
    cost in R. If this ever stops holding, the sweep's conclusion is invalid.
    """
    df = _ohlcv()
    costs = []
    for m in (1.0, 2.0, 4.0):
        cfg = LabConfig(min_trades=1, atr_mult=m)
        r = evaluate(df, CONCEPTS["trend_pullback"](df, cfg), cfg, "t")
        if r is None:
            pytest.skip("fixture produced too few trades")
        costs.append(r.cost_r)
    assert costs[0] > costs[1] > costs[2], f"cost_R did not fall with stop width: {costs}"


def test_too_few_trades_returns_none_rather_than_a_number() -> None:
    """A thin sample must be reported as absent, never as a result."""
    df = _ohlcv(n=400)
    sig = np.zeros(len(df), dtype=int)
    sig[300] = 1
    assert evaluate(df, sig, LabConfig(min_trades=100), "t") is None


def test_no_trade_is_ever_EVALUATED_before_atr_is_valid() -> None:
    """The invariant that actually matters: no TRADE during the warm-up.

    Three concepts (fib_zone, failure_test, fvg_fill) are price-only and
    legitimately emit signals before ATR exists -- requiring them to check an
    indicator they do not use would be cargo-cult. What must never happen is a
    TRADE being scored there, because the stop distance is ATR-derived and
    would be undefined. `evaluate` is the single place that guarantees it, so
    that is where the guarantee is tested.
    """
    cfg = LabConfig(min_trades=1)
    df = _ohlcv()
    atr = _atr(df)
    first_valid = int(np.argmax(np.isfinite(atr)))
    assert first_valid > 0, "fixture should have an ATR warm-up period"
    for name, fn in CONCEPTS.items():
        sig = np.zeros(len(df), dtype=int)
        sig[: first_valid] = 1          # force a signal on every warm-up bar
        assert evaluate(df, sig, cfg, name) is None, (
            f"{name}: a trade was scored during the ATR warm-up")
