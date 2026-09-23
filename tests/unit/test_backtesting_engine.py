"""
Module: test_backtesting_engine.py
Description: Unit tests for Engine 26 (Backtesting Laboratory) -- there was
    previously NO dedicated test file for this engine at all, despite it
    being the validation gate every strategy/parameter change on the
    platform must clear (train_e51_thresholds.py, train_e51_signals.py,
    e51_signals.validate_historical_edge's LIVE edge-gate all depend on
    it). That gap let a real position-sizing bug ship undetected: the
    `risk_per_trade` parameter was a complete no-op (see
    test_risk_per_trade_actually_bounds_position_size below).
Author: Shantanu Waykar
Version: 1.0.0
"""

import numpy as np
import pandas as pd
import pytest

from project_titan_x.engines.e26_backtesting.engine import BacktestingEngine


@pytest.fixture
def engine() -> BacktestingEngine:
    e = BacktestingEngine()
    e.initialize()
    return e


def _trending_df(n: int = 400, seed: int = 3) -> pd.DataFrame:
    rng = np.random.RandomState(seed)
    drift = np.linspace(0, 0.4, n)
    noise = rng.normal(0, 0.01, n).cumsum()
    close = 100 * (1 + drift + noise * 0.1)
    close = np.clip(close, 1, None)
    return pd.DataFrame({
        "timestamp": pd.date_range("2015-01-01", periods=n, freq="D", tz="UTC"),
        "open": close, "high": close * 1.01, "low": close * 0.99, "close": close,
        "volume": [1000] * n,
    })


def _alternating_strategy(df: pd.DataFrame) -> pd.Series:
    """Flips long/short every 10 bars -- guarantees real trades regardless
    of the underlying price path, without depending on TA indicators."""
    idx = np.arange(len(df))
    return pd.Series(np.where((idx // 10) % 2 == 0, 1, -1), index=df.index)


def test_risk_per_trade_actually_bounds_position_size(engine):
    """Real regression test for a real bug: `risk_per_trade` must change
    the equity curve's volatility. The old formula
    `equity * risk_pct * (pnl_pct / risk_pct)` algebraically cancels to
    `equity * pnl_pct` for ANY risk_pct > 0 -- a 1% risk setting and a
    100% risk setting produced IDENTICAL equity curves. A genuine
    fractional-risk sizing must make the low-risk run's drawdown clearly
    smaller than the high-risk run's."""
    df = _trending_df()

    low_risk = engine.run_backtest(df, _alternating_strategy, risk_per_trade=0.01)
    high_risk = engine.run_backtest(df, _alternating_strategy, risk_per_trade=0.5)
    assert low_risk.success and high_risk.success

    low_dd = low_risk.data.metrics.max_drawdown_pct
    high_dd = high_risk.data.metrics.max_drawdown_pct
    assert low_dd < high_dd, (
        f"risk_per_trade had no effect on drawdown (low={low_dd}, high={high_dd}) "
        "-- position sizing is a no-op"
    )

    low_curve = low_risk.data.equity_curve
    high_curve = high_risk.data.equity_curve
    assert not low_curve.equals(high_curve)


def test_commission_scales_with_position_size_not_total_equity(engine):
    """Real regression test for a bug adjacent to the position-sizing fix:
    commission was charged as a flat % of TOTAL equity regardless of how
    much was actually risked. With genuine fractional-risk sizing (e.g.
    risk_per_trade=0.01), an unscaled commission on full equity would
    swamp the properly-scaled-down real edge of every trade -- a 0.1%
    flat commission would dwarf a trade that only ever risked 1% of
    equity. A break-even (zero net price movement) round trip must cost
    approximately risk_per_trade * commission_pct * 2 of equity, not
    commission_pct * 2."""
    n = 40
    close = np.full(n, 100.0)
    df = pd.DataFrame({
        "timestamp": pd.date_range("2021-01-01", periods=n, freq="D", tz="UTC"),
        "open": close, "high": close, "low": close, "close": close,
        "volume": [1000] * n,
    })

    def one_round_trip(_df: pd.DataFrame) -> pd.Series:
        s = pd.Series(0, index=_df.index)
        if len(_df) > 10:
            s.iloc[2] = 1
            s.iloc[10] = 0
        return s

    risk_pct = 0.01
    commission_pct = 0.01
    result = engine.run_backtest(
        df, one_round_trip, risk_per_trade=risk_pct, commission_pct=commission_pct,
        slippage_pct=0.0, oos_split=0.99,
    )
    assert result.success
    final_equity = result.data.equity_curve.iloc[-1]
    initial_equity = 10_000.0
    cost_fraction = 1 - final_equity / initial_equity
    # Price never moved, so the only equity change is the two commission
    # deductions, each risk_pct * commission_pct of equity.
    expected = 1 - (1 - risk_pct * commission_pct) ** 2
    assert cost_fraction == pytest.approx(expected, rel=1e-6)
    # And it must be far smaller than what an UNSCALED commission
    # (commission_pct of full equity per leg) would have cost.
    unscaled = 1 - (1 - commission_pct) ** 2
    assert cost_fraction < unscaled / 10


def test_equity_never_goes_negative_under_extreme_adverse_move(engine):
    """Real regression test: a catastrophic single-bar adverse move (e.g.
    the real 2020-04-20 negative WTI crude price event) must not be able
    to drive simulated equity negative when risk_per_trade reflects a
    genuinely bounded position size. Negative equity previously produced
    max_drawdown_pct > 100% and a NaN CAGR (invalid value encountered in
    scalar power) for CL=F in a real training run."""
    n = 60
    close = np.full(n, 100.0)
    close[30] = -40.0  # a real, extreme, negative-price single-bar event
    close[31:] = 20.0
    df = pd.DataFrame({
        "timestamp": pd.date_range("2020-04-01", periods=n, freq="D", tz="UTC"),
        "open": close, "high": np.abs(close) + 1, "low": close - 1, "close": close,
        "volume": [1000] * n,
    })

    def long_from_start(_df: pd.DataFrame) -> pd.Series:
        return pd.Series(1, index=_df.index)

    result = engine.run_backtest(df, long_from_start, risk_per_trade=0.01, oos_split=0.5)
    assert result.success
    metrics = result.data.metrics
    assert (result.data.equity_curve > 0).all()
    assert metrics.max_drawdown_pct <= 100.0
    assert np.isfinite(metrics.cagr)


def test_run_backtest_passes_validation_for_a_genuinely_strong_trend(engine):
    """Smoke test: a strong, clean uptrend with a strategy that actually
    round-trips (enters and exits repeatedly, generating >= MIN_TRADES
    realized trades) should clear IS/OOS validation -- confirms the gate
    isn't permanently broken in the other direction (impossible to ever
    pass). A pure always-long/never-exit signal deliberately isn't used
    here: this engine only records a trade on exit, so a position that's
    never closed contributes zero realized trades."""
    n = 800
    # Exponential (constant %-per-bar) growth, not linear-in-price -- a
    # linear-in-price trend's PERCENTAGE gain per fixed-length hold shrinks
    # as price rises, which can let fixed transaction costs flip later
    # out-of-sample trades net-negative even though the trend never
    # reverses. Constant %/bar keeps every window's edge identical.
    close = 100 * np.exp(np.linspace(0, 1.0, n))
    df = pd.DataFrame({
        "timestamp": pd.date_range("2010-01-01", periods=n, freq="D", tz="UTC"),
        "open": close, "high": close * 1.001, "low": close * 0.999, "close": close,
        "volume": [1000] * n,
    })

    def long_5_flat_5(_df: pd.DataFrame) -> pd.Series:
        idx = np.arange(len(_df))
        return pd.Series(np.where((idx // 5) % 2 == 0, 1, 0), index=_df.index)

    result = engine.run_backtest(df, long_5_flat_5, risk_per_trade=0.5)
    assert result.success
    assert result.data.metrics.total_trades >= engine.MIN_TRADES
    # passed_validation is a numpy bool_ (from a numpy/pandas-typed
    # comparison chain, not a native Python bool) -- compare by value,
    # not identity.
    assert bool(result.data.passed_validation)


def test_intra_trade_drawdown_is_captured_while_position_is_held():
    """Real regression test: before this fix, `equity` (and therefore
    equity_curve/Sharpe/drawdown) only updated on trade entry/exit bars --
    frozen flat for every bar a position stayed open, so any intra-trade
    excursion that recovered before exit was completely invisible to
    max_drawdown_pct. Here a single held position drops 50% then recovers
    past its entry price before finally exiting: the trade nets positive
    (1 realized winning trade), but a real trader was genuinely down 50%
    at one point. The old code could only see the entry and exit prices
    (equity frozen in between), reporting ~0% drawdown for a trade that
    round-tripped through -50%; the fix must report ~50%.

    Updated 2026-08-20 for the fill-timing fix: entry now executes one bar
    later than the signal (bar 6's open, not bar 5's own close -- see
    _simulate's own docstring), so the entry price is ~96.43 rather than
    exactly 100, making the real intra-trade drawdown ~48.1% rather than
    exactly 50% -- still clearly nonzero and still the same qualitative
    regression check (intra-trade dip genuinely captured, not frozen)."""
    n = 50
    close = np.full(n, 100.0)
    close[5:20] = np.linspace(100, 50, 15)   # sharp intra-trade drawdown while held
    close[20:40] = np.linspace(50, 110, 20)  # recovers past entry before the position exits
    close[40:] = 110.0
    df = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC"),
        "open": close, "high": close, "low": close, "close": close,
        "volume": [1000] * n,
    })

    def hold_then_exit(_df: pd.DataFrame) -> pd.Series:
        s = pd.Series(0, index=_df.index)
        s.iloc[5:40] = 1  # one long position, held through the dip and the recovery
        return s

    engine = BacktestingEngine()
    engine.initialize()
    result = engine._simulate(df, hold_then_exit, capital=10_000.0, risk_pct=1.0, commission=0.0, slippage=0.0)

    assert result.metrics.total_trades == 1
    assert result.trades[0]["pnl_pct"] > 0  # nets a real winning trade (110 > 100 entry)
    assert result.metrics.max_drawdown_pct == pytest.approx(48.15, abs=1.0)  # the real intra-trade dip
    assert result.equity_curve.nunique() > n * 0.5  # was ~3 distinct values (flat between trade events) before


def test_run_backtest_fails_min_trades_with_too_few_signals(engine):
    df = _trending_df(n=100)

    def one_trade_only(_df: pd.DataFrame) -> pd.Series:
        s = pd.Series(0, index=_df.index)
        if len(_df) > 6:
            s.iloc[5] = 1
            s.iloc[6] = 0
        return s

    result = engine.run_backtest(df, one_trade_only)
    assert result.success
    assert not bool(result.data.passed_validation)
    assert result.data.metrics.total_trades < engine.MIN_TRADES


# ---- fill-timing fix (added 2026-08-20) ----


def test_entry_fills_at_next_bars_open_not_signal_bars_own_close():
    """The real point of the fix: a signal confirmed at bar i's close must
    fill at bar (i+1)'s OPEN, never at bar i's own close (which no real
    order could ever reach) and never at bar (i+1)'s close either (that
    would just move the same optimism one bar later)."""
    n = 20
    close = np.full(n, 100.0)
    open_ = np.full(n, 100.0)
    # A large, distinct jump on bar 6's open vs bar 5's close vs bar 6's
    # close -- three different candidate fill prices a bug could produce.
    close[5] = 100.0   # the bar the signal is confirmed on
    open_[6] = 105.0   # the ONLY correct fill price
    close[6] = 110.0
    df = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC"),
        "open": open_, "high": np.maximum(open_, close) + 1, "low": np.minimum(open_, close) - 1,
        "close": close, "volume": [1000] * n,
    })

    def single_entry(_df: pd.DataFrame) -> pd.Series:
        s = pd.Series(0, index=_df.index)
        s.iloc[5] = 1  # signal confirmed at bar 5's close
        s.iloc[15] = 0  # exit later, well past the entry bar, so the fill is isolated and checkable
        return s

    engine = BacktestingEngine()
    engine.initialize()
    result = engine._simulate(df, single_entry, capital=10_000.0, risk_pct=1.0, commission=0.0, slippage=0.0)
    assert result.metrics.total_trades == 1
    assert result.trades[0]["entry_price"] == pytest.approx(105.0)
    assert result.trades[0]["entry_idx"] == 6


def test_holding_mark_to_market_still_uses_close_not_open():
    """The fix must NOT change how an already-open position is valued day
    to day -- only the transaction price for NEW entries/exits. Equity
    while holding must still track CLOSE (the standard EOD equity-curve
    convention), confirmed by making open and close diverge sharply on a
    held bar and checking the reported unrealized move matches the CLOSE
    delta, not the OPEN delta."""
    n = 15
    open_ = np.full(n, 100.0)
    close = np.full(n, 100.0)
    close[10] = 150.0  # a big move visible only in CLOSE while bar 10 is held
    open_[10] = 100.0
    df = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC"),
        "open": open_, "high": np.maximum(open_, close) + 1, "low": np.minimum(open_, close) - 1,
        "close": close, "volume": [1000] * n,
    })

    def hold_from_bar_2(_df: pd.DataFrame) -> pd.Series:
        s = pd.Series(0, index=_df.index)
        s.iloc[2:] = 1  # enter early, never exit -- stays "held" through bar 10
        return s

    engine = BacktestingEngine()
    engine.initialize()
    result = engine._simulate(df, hold_from_bar_2, capital=10_000.0, risk_pct=1.0, commission=0.0, slippage=0.0)
    # Entry fills at bar 3's open (bar 2's signal, one bar later) = 100.
    # At bar 10, equity should reflect the CLOSE (150) move, not open (100, no move).
    equity_at_bar_10 = result.equity_curve.iloc[10]
    assert equity_at_bar_10 > 10_000.0 * 1.3  # a real ~50% unrealized gain shows up, proving CLOSE is used


def test_signal_on_last_bar_produces_no_trade():
    """A signal confirmed on the very last bar has no next bar to fill
    at -- must simply produce no trade, never an index error or a
    fabricated fill."""
    n = 10
    close = np.full(n, 100.0)
    df = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC"),
        "open": close, "high": close, "low": close, "close": close, "volume": [1000] * n,
    })

    def signal_on_final_bar(_df: pd.DataFrame) -> pd.Series:
        s = pd.Series(0, index=_df.index)
        s.iloc[-1] = 1
        return s

    engine = BacktestingEngine()
    engine.initialize()
    result = engine._simulate(df, signal_on_final_bar, capital=10_000.0, risk_pct=1.0, commission=0.0, slippage=0.0)
    assert result.metrics.total_trades == 0


# ---- monte_carlo_sequencing_test (added 2026-08-21) ----


def test_monte_carlo_sequencing_test_too_few_trades_returns_error_dict(engine):
    result = engine.monte_carlo_sequencing_test(
        trades=[{"pnl_pct": 1.0}, {"pnl_pct": -0.5}], initial_capital=10_000.0,
    )
    assert "error" in result
    assert result["p_value_sharpe"] == 1.0


def test_monte_carlo_sequencing_test_detects_a_favorable_trade_order():
    """25 small wins followed by 5 larger losses: because dollar PnL is
    cumsum'd into equity and returns are computed against the PRIOR
    equity level, this order lets the wins build a buffer BEFORE the
    losses land, diluting their % impact -- a real sequence-of-returns
    effect. A random reshuffle just as often front-loads a loss onto the
    smaller starting base, hurting Sharpe -- so the actual order should
    beat the vast majority of random permutations (p_value_sharpe low,
    significant_at_5pct True). Empirically confirmed this exact
    construction (seed=42, the method's own default) lands p_value=0.0
    before asserting a threshold here, so the bound below has real margin,
    not a hand-tuned coin-flip."""
    engine = BacktestingEngine()
    engine.initialize()
    trades = [{"pnl_pct": 1.0} for _ in range(25)] + [{"pnl_pct": -1.5} for _ in range(5)]
    result = engine.monte_carlo_sequencing_test(trades, initial_capital=10_000.0, n_simulations=1000)
    assert result["n_trades"] == 30
    assert result["p_value_sharpe"] < 0.05
    assert result["significant_at_5pct"] is True


def test_run_backtest_monte_carlo_is_opt_in_and_does_not_change_default_behavior(engine):
    """run_monte_carlo defaults to False -- must not attach anything (and
    must not change runtime-observable behavior) unless explicitly asked
    for, since every existing caller (train_e51_signals.py,
    e51_signals.validate_historical_edge, etc.) calls run_backtest()
    without this param and must see byte-identical results to before."""
    df = _trending_df()
    default_result = engine.run_backtest(df, _alternating_strategy)
    assert default_result.data.monte_carlo_sequencing is None

    mc_result = engine.run_backtest(df, _alternating_strategy, run_monte_carlo_sequencing=True)
    assert mc_result.data.monte_carlo_sequencing is not None
    assert "p_value_sharpe" in mc_result.data.monte_carlo_sequencing
    # Opting in must not change the actual backtest numbers themselves.
    assert mc_result.data.metrics.sharpe_ratio == default_result.data.metrics.sharpe_ratio
    assert mc_result.data.passed_validation == default_result.data.passed_validation


def test_expectancy_is_price_move_percent_not_r_multiple():
    """Locks the UNITS of expectancy/avg_win_r/avg_loss_r.

    Despite the `_r` suffix these are not R-multiples: pnl_r is
    pnl_pct/risk_pct, and pnl_pct is the raw price-move fraction, so at the
    default risk_pct=0.01 they equal the price move in PERCENT. Verified on
    real ETHUSD 1d data: reported expectancy 22.280 vs measured mean trade
    pnl_pct 22.280%.

    Reading them as R-multiples overstates returns by ~100x, so this test
    exists to make any future change to that relationship fail loudly
    rather than silently re-scale every stored override and report."""
    import numpy as np
    import pandas as pd

    from project_titan_x.engines.e26_backtesting.engine import BacktestingEngine

    engine = BacktestingEngine()
    engine.initialize()
    n = 400
    rng = np.random.RandomState(5)
    close = 100 + np.cumsum(rng.randn(n) * 0.9)
    df = pd.DataFrame({
        "timestamp": pd.date_range("2022-01-01", periods=n, freq="D", tz="UTC"),
        "open": close, "high": close + 1, "low": close - 1, "close": close,
        "volume": np.full(n, 1000),
    })
    # Alternating blocks so real round-trips are booked. The signal MUST be
    # derived from the frame it is handed, not captured: run_backtest slices
    # the data for its IS/OOS split, and a fixed-length series would fail
    # the length check and be silently replaced with zeros.
    def alternating(d):
        return pd.Series(np.where((np.arange(len(d)) // 9) % 2 == 0, 1, -1), index=d.index)

    result = engine.run_backtest(df, alternating)
    metrics, trades = result.data.metrics, result.data.trades
    assert len(trades) >= 10

    mean_pnl_pct = float(np.mean([t["pnl_pct"] for t in trades]))
    assert metrics.expectancy == pytest.approx(mean_pnl_pct, abs=0.01), (
        "expectancy must equal the mean trade price move in percent"
    )
    wins = [t["pnl_pct"] for t in trades if t["pnl_pct"] > 0]
    if wins:
        assert metrics.avg_win_r == pytest.approx(float(np.mean(wins)), abs=0.01)
