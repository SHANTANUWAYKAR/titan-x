"""
Tests for E26's opt-in barrier exits (stop-loss / take-profit).

WHY THIS EXISTS. Until 2026-09-09 the simulator exited on signal flip only.
E51 shows a stop_loss and take_profit on every live signal and nothing ever
tested them, so every Sharpe, win rate and Stage 0 percentile on this
platform described a strategy that holds until the signal reverses -- not
the one a human following the stated levels actually trades.

The most important test here is the FIRST one: barriers are opt-in, and the
default path must stay byte-identical. Every validated default on this
platform was measured without them, and this project has already had to
re-validate everything twice after a simulator change.

Data is constructed, not sampled, so each rule is pinned deterministically
rather than "whatever the market happened to do".
"""

import numpy as np
import pandas as pd
import pytest

from project_titan_x.engines.e26_backtesting.engine import BacktestingEngine


@pytest.fixture
def engine():
    e = BacktestingEngine()
    e.initialize()
    return e


def _frame(rows):
    """rows: list of (open, high, low, close)."""
    o, h, l, c = zip(*rows)
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c,
                         "volume": [1000.0] * len(rows)})


def _flat(n, price=100.0):
    return [(price, price + 0.5, price - 0.5, price)] * n


# run_backtest splits 70/30 and RETURNS THE IN-SAMPLE RESULT. A constructed
# event must therefore land inside the first 70% or the test silently
# inspects a result that never saw it -- which is exactly how the first
# version of this file produced eight vacuous failures.
WARMUP = 40          # > atr_period, so ATR is warm before the event
TAIL = 200           # keeps the event well inside the in-sample portion


def _event_frame(event_rows, price=100.0, after=None):
    """WARMUP flat bars, then the event, then a long flat tail."""
    return _frame(_flat(WARMUP, price) + list(event_rows)
                  + _flat(TAIL, price if after is None else after))


def _always_long(df):
    return pd.Series(1, index=df.index)


def _long_after_warmup(df):
    """Flat until ATR is warm, then long.

    REAL BEHAVIOUR THIS EXISTS FOR: barrier levels are computed once, at
    entry, from the ATR at that bar. A position opened while ATR is still
    NaN (the first `atr_period` bars) gets no levels and stays unbarriered
    for its entire life -- deliberately, since the alternative is inventing
    a level. `_always_long` enters at bar 1 and therefore can NEVER be
    barriered, which is correct behaviour and useless for testing barriers.
    """
    v = np.zeros(len(df), dtype=int)
    v[WARMUP - 2:] = 1
    return pd.Series(v, index=df.index)


def _sig(values):
    def fn(df, _v=values):
        return pd.Series(_v[: len(df)], index=df.index)
    return fn


# --------------------------------------------------------------------------
# 1. Opt-in: the default path must not move
# --------------------------------------------------------------------------

def test_default_is_signal_flip_only(engine):
    df = _frame(_flat(80))
    r = engine.run_backtest(df, _always_long, periods_per_year=252).data
    assert r.parameters["exit_model"] == "signal_flip_only"
    assert all("exit_reason" not in t for t in r.trades)


def test_barriers_off_matches_barriers_absent(engine):
    """Passing None explicitly must equal passing nothing."""
    rows = _flat(30) + [(100 + i * 0.4, 100 + i * 0.4 + 0.6, 100 + i * 0.4 - 0.6, 100 + i * 0.4)
                        for i in range(60)]
    df = _frame(rows)
    a = engine.run_backtest(df, _always_long, periods_per_year=252).data
    b = engine.run_backtest(df, _always_long, periods_per_year=252,
                            stop_atr_mult=None, tp_atr_mult=None).data
    assert a.metrics.sharpe_ratio == b.metrics.sharpe_ratio
    assert a.metrics.total_trades == b.metrics.total_trades
    assert [t["pnl_pct"] for t in a.trades] == [t["pnl_pct"] for t in b.trades]


def test_enabling_barriers_sets_the_exit_model_label(engine):
    df = _frame(_flat(60))
    r = engine.run_backtest(df, _always_long, periods_per_year=252, stop_atr_mult=2.0).data
    assert r.parameters["exit_model"] == "barriers"
    assert r.parameters["stop_atr_mult"] == 2.0


# --------------------------------------------------------------------------
# 2. Barriers actually fire
# --------------------------------------------------------------------------

def test_stop_fires_on_a_long(engine):
    df = _event_frame([(100.0, 100.5, 80.0, 85.0)], after=85.0)
    r = engine.run_backtest(df, _long_after_warmup, periods_per_year=252, stop_atr_mult=1.0).data
    assert any(t.get("exit_reason") == "stop" for t in r.trades)


def test_target_fires_on_a_long(engine):
    df = _event_frame([(100.0, 130.0, 99.5, 129.0)], after=129.0)
    r = engine.run_backtest(df, _long_after_warmup, periods_per_year=252, tp_atr_mult=1.0).data
    assert any(t.get("exit_reason") == "target" for t in r.trades)


def test_stop_fires_on_a_short(engine):
    df = _event_frame([(100.0, 120.0, 99.5, 119.0)], after=119.0)
    r = engine.run_backtest(df, lambda d: -_long_after_warmup(d),
                            periods_per_year=252, stop_atr_mult=1.0).data
    assert any(t.get("exit_reason") == "stop" for t in r.trades)


# --------------------------------------------------------------------------
# 3. The same-bar tie -- the rule that decides whether a backtest flatters itself
# --------------------------------------------------------------------------

def test_same_bar_stop_and_target_resolves_to_the_stop(engine):
    """One bar touches BOTH levels. Bar data cannot say which came first,
    so the stop must win. Assuming the target is exactly how a backtest
    invents performance that never existed."""
    df = _event_frame([(100.0, 140.0, 60.0, 100.0)])
    r = engine.run_backtest(df, _long_after_warmup, periods_per_year=252,
                            stop_atr_mult=1.0, tp_atr_mult=1.0).data
    barrier_trades = [t for t in r.trades if t.get("exit_reason") in ("stop", "target")]
    assert barrier_trades, "no barrier exit occurred; test is vacuous"
    assert barrier_trades[0]["exit_reason"] == "stop"
    assert barrier_trades[0]["pnl_pct"] < 0


# --------------------------------------------------------------------------
# 4. Gaps -- a resting order does not get its level back
# --------------------------------------------------------------------------

def test_gap_through_the_stop_fills_at_the_open_not_the_stop(engine):
    """If the bar OPENED below the stop, the gap already passed it. Filling
    at the stop level would hand back money the trade never had."""
    df = _event_frame([(70.0, 71.0, 69.0, 70.0)], after=70.0)
    r = engine.run_backtest(df, _long_after_warmup, periods_per_year=252, stop_atr_mult=1.0).data
    stops = [t for t in r.trades if t.get("exit_reason") == "stop"]
    assert stops, "no stop exit occurred; test is vacuous"
    # fill must be at/near the gapped-down open, far below any ATR-based stop
    assert stops[0]["exit_price"] <= 71.0
    assert stops[0]["pnl_pct"] < -20


def test_gap_through_the_target_fills_at_the_open(engine):
    df = _event_frame([(160.0, 161.0, 159.0, 160.0)], after=160.0)
    r = engine.run_backtest(df, _long_after_warmup, periods_per_year=252, tp_atr_mult=1.0).data
    tps = [t for t in r.trades if t.get("exit_reason") == "target"]
    assert tps, "no target exit occurred; test is vacuous"
    assert tps[0]["exit_price"] >= 155.0


# --------------------------------------------------------------------------
# 5. Levels are fixed at entry -- not a trailing stop
# --------------------------------------------------------------------------

def test_levels_are_frozen_at_entry(engine):
    """A drift up then back to entry must NOT stop out. If levels tracked
    price each bar this would be a trailing stop -- a different mechanism
    with different behaviour, not a detail."""
    rows = _flat(40)
    rows += [(100 + i, 100 + i + 0.5, 100 + i - 0.5, 100 + i) for i in range(1, 16)]
    rows += [(115 - i, 115 - i + 0.5, 115 - i - 0.5, 115 - i) for i in range(1, 15)]
    df = _frame(rows)
    r = engine.run_backtest(df, _long_after_warmup, periods_per_year=252, stop_atr_mult=3.0).data
    assert not any(t.get("exit_reason") == "stop" for t in r.trades)


# --------------------------------------------------------------------------
# 6. Chronology and warm-up
# --------------------------------------------------------------------------

def test_trade_can_be_stopped_on_its_own_entry_bar(engine):
    """Entry fills at the open; a collapse later in that same bar is a real
    stop-out, not something deferred to the next bar."""
    # signal turns on at WARMUP-1 so it is ACTED ON at bar WARMUP -- the
    # event bar itself (signals are shifted one bar before execution).
    sig = [0] * (WARMUP - 1) + [1] * (TAIL + 4)
    df = _event_frame([(100.0, 100.5, 60.0, 62.0)], after=62.0)
    r = engine.run_backtest(df, _sig(sig), periods_per_year=252, stop_atr_mult=1.0).data
    stops = [t for t in r.trades if t.get("exit_reason") == "stop"]
    assert stops, "expected an entry-bar stop-out"
    assert stops[0]["entry_idx"] == stops[0]["exit_idx"]


def test_no_barrier_before_atr_is_warm(engine):
    """ATR is NaN during warm-up. A trade opened then must run unbarriered
    rather than be given a fabricated level."""
    # event at bar 3, long before ATR(14) is warm; flat afterwards so no
    # later bar can produce a stop once ATR does warm up.
    df = _frame([(100.0, 100.5, 99.5, 100.0)] * 3
                + [(100.0, 100.5, 50.0, 55.0)] + _flat(250, 55.0))
    r = engine.run_backtest(df, _always_long, periods_per_year=252,
                            stop_atr_mult=1.0, atr_period=14).data
    assert not any(t.get("exit_reason") == "stop" for t in r.trades)


def test_flat_series_produces_no_barrier_exits(engine):
    """ATR == 0 must not divide-by-zero or fabricate a level."""
    df = _frame([(100.0, 100.0, 100.0, 100.0)] * 60)
    r = engine.run_backtest(df, _long_after_warmup, periods_per_year=252,
                            stop_atr_mult=1.0, tp_atr_mult=2.0).data
    assert not any(t.get("exit_reason") in ("stop", "target") for t in r.trades)


# --------------------------------------------------------------------------
# 7. Direction and accounting sanity
# --------------------------------------------------------------------------

def test_stop_exit_is_always_a_loss_and_target_always_a_gain(engine):
    """Before costs this is definitional. With costs a stop stays negative;
    a target must not come out negative, which would mean the level was
    computed on the wrong side."""
    rng = np.random.default_rng(3)
    close = 100 + np.cumsum(rng.normal(0, 1.2, 3000))
    rows = [(c, c + abs(rng.normal(0, 0.8)), c - abs(rng.normal(0, 0.8)), c) for c in close]
    df = _frame(rows)
    r = engine.run_backtest(df, _long_after_warmup, periods_per_year=252,
                            stop_atr_mult=2.0, tp_atr_mult=3.0).data
    stops = [t for t in r.trades if t.get("exit_reason") == "stop"]
    tps = [t for t in r.trades if t.get("exit_reason") == "target"]
    assert stops and tps, "need both kinds present for this to mean anything"
    assert all(t["pnl_pct"] < 0 for t in stops)
    assert all(t["pnl_pct"] > 0 for t in tps)


def test_tighter_stop_produces_more_stop_exits(engine):
    rng = np.random.default_rng(11)
    close = 100 + np.cumsum(rng.normal(0, 1.0, 900))
    rows = [(c, c + abs(rng.normal(0, 0.7)), c - abs(rng.normal(0, 0.7)), c) for c in close]
    df = _frame(rows)
    counts = []
    for mult in (5.0, 2.0, 0.5):
        r = engine.run_backtest(df, _long_after_warmup, periods_per_year=252,
                                stop_atr_mult=mult).data
        counts.append(sum(1 for t in r.trades if t.get("exit_reason") == "stop"))
    assert counts[0] <= counts[1] <= counts[2], counts


def test_equity_stays_finite_with_barriers(engine):
    rng = np.random.default_rng(5)
    close = 100 + np.cumsum(rng.normal(0, 2.0, 800))
    rows = [(c, c + abs(rng.normal(0, 1.5)), max(c - abs(rng.normal(0, 1.5)), 1.0), c)
            for c in close]
    df = _frame(rows)
    r = engine.run_backtest(df, _long_after_warmup, periods_per_year=252,
                            stop_atr_mult=1.0, tp_atr_mult=2.0).data
    eq = np.asarray(r.equity_curve, dtype=float)
    assert np.all(np.isfinite(eq))
    assert np.all(eq > 0)
