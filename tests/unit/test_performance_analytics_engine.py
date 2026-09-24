"""
Tests for Engine 35 -- Performance Analytics.

Pure math (equity curve, drawdown, win rate, profit factor, expectancy,
average win/loss, summarize) needs no database and is tested directly.
The trade-journal CRUD (log_trade/list_trades/summarize on the engine
itself) touches real Postgres -- marked @pytest.mark.network, same
convention as this codebase's other live-infra-dependent tests (e.g.
test_cftc_client.py), since this project has no existing SQLite/mock
fixture for the ORM layer and Postgres is genuinely running via
docker-compose for local development.
"""

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from project_titan_x.engines.e35_performance_analytics.engine import (
    PerformanceAnalyticsEngine,
    PerformanceSummary,
    average_win_loss_r,
    calmar_ratio_from_journal,
    compute_mae_mfe_r,
    cvar_pct_from_pnl_pct,
    equity_curve_from_pnl_pct,
    expectancy_r,
    max_drawdown_pct,
    profit_factor,
    recovery_factor_from_pnl_pct,
    summarize,
    win_rate,
)
from tests._artifacts import requires_postgres


class _FakeEngineResult:
    def __init__(self, success, data=None, message=""):
        self.success = success
        self.data = data
        self.message = message


class _FakeMarketDataEngine:
    """Duck-typed stand-in for MarketDataEngine.fetch_ohlcv -- MAE/MFE's
    own computation is pure once given a real OHLCV shape, so this avoids
    needing a live network fetch for what these tests actually check."""

    def __init__(self, df):
        self._df = df

    def fetch_ohlcv(self, symbol, timeframe, allow_cache=True):
        return _FakeEngineResult(success=True, data=self._df)


def _ohlcv_window(n=10, start="2026-01-01") -> pd.DataFrame:
    ts = pd.date_range(start, periods=n, freq="h", tz="UTC")
    # A deliberate shape: dips low mid-window, then rallies high late --
    # gives both a real adverse and a real favorable excursion to measure.
    low = [100, 98, 95, 96, 97, 98, 99, 100, 101, 102]
    high = [101, 99, 96, 97, 99, 101, 103, 105, 107, 108]
    return pd.DataFrame({"timestamp": ts, "open": low, "high": high, "low": low, "close": high})


# ---- MAE/MFE ----

def test_mae_mfe_long_measures_real_adverse_and_favorable_excursion():
    df = _ohlcv_window()
    engine = _FakeMarketDataEngine(df)
    mae_r, mfe_r = compute_mae_mfe_r(
        engine, symbol="TEST", timeframe="1h", direction="long", entry_price=100.0,
        entry_time=df["timestamp"].iloc[0], exit_time=df["timestamp"].iloc[-1], stop_loss_price=95.0,
    )
    # risk_amount = 5.0. Worst low in window = 95 -> adverse = 100-95=5 -> mae_r=1.0.
    # Best high = 108 -> favorable = 108-100=8 -> mfe_r=1.6.
    assert mae_r == pytest.approx(1.0)
    assert mfe_r == pytest.approx(1.6)


def test_mae_mfe_short_mirrors_long():
    df = _ohlcv_window()
    engine = _FakeMarketDataEngine(df)
    mae_r, mfe_r = compute_mae_mfe_r(
        engine, symbol="TEST", timeframe="1h", direction="short", entry_price=100.0,
        entry_time=df["timestamp"].iloc[0], exit_time=df["timestamp"].iloc[-1], stop_loss_price=105.0,
    )
    # risk_amount = 5.0. For a short, adverse excursion is the HIGH (108-100=8 -> mae_r=1.6),
    # favorable is the LOW (100-95=5 -> mfe_r=1.0) -- the exact mirror of the long case.
    assert mae_r == pytest.approx(1.6)
    assert mfe_r == pytest.approx(1.0)


def test_mae_mfe_returns_none_without_a_stop_loss_price():
    df = _ohlcv_window()
    engine = _FakeMarketDataEngine(df)
    mae_r, mfe_r = compute_mae_mfe_r(
        engine, symbol="TEST", timeframe="1h", direction="long", entry_price=100.0,
        entry_time=df["timestamp"].iloc[0], exit_time=df["timestamp"].iloc[-1], stop_loss_price=100.0,  # zero risk_amount
    )
    assert (mae_r, mfe_r) == (None, None)


def test_mae_mfe_returns_none_when_fetch_fails():
    class _FailingEngine:
        def fetch_ohlcv(self, symbol, timeframe, allow_cache=True):
            return _FakeEngineResult(success=False, message="no data")

    mae_r, mfe_r = compute_mae_mfe_r(
        _FailingEngine(), symbol="TEST", timeframe="1h", direction="long", entry_price=100.0,
        entry_time=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
        exit_time=dt.datetime(2026, 1, 2, tzinfo=dt.timezone.utc), stop_loss_price=95.0,
    )
    assert (mae_r, mfe_r) == (None, None)


def test_mae_mfe_returns_none_when_window_has_no_overlapping_bars():
    df = _ohlcv_window(start="2026-01-01")
    engine = _FakeMarketDataEngine(df)
    mae_r, mfe_r = compute_mae_mfe_r(
        engine, symbol="TEST", timeframe="1h", direction="long", entry_price=100.0,
        entry_time=dt.datetime(2030, 1, 1, tzinfo=dt.timezone.utc),
        exit_time=dt.datetime(2030, 1, 2, tzinfo=dt.timezone.utc), stop_loss_price=95.0,
    )
    assert (mae_r, mfe_r) == (None, None)


# ---- pure math ----

def test_equity_curve_starts_at_one_and_accumulates():
    curve = equity_curve_from_pnl_pct([0.05, -0.02, 0.03])
    assert curve[0] == 1.0
    assert curve[-1] == pytest.approx(1.06)


def test_max_drawdown_pct_from_a_known_drawdown():
    # +10%, then -20% from the peak (1.10 -> 0.88) -- dd = (0.88-1.10)/1.10
    dd = max_drawdown_pct([0.10, -0.22])
    assert dd == pytest.approx(0.2, abs=0.01)


def test_max_drawdown_pct_empty_is_zero():
    assert max_drawdown_pct([]) == 0.0


def test_win_rate_basic():
    assert win_rate([1.0, -1.0, 2.0, -0.5]) == 0.5


def test_win_rate_empty_is_zero():
    assert win_rate([]) == 0.0


def test_profit_factor_normal_case():
    # gains=3.0, losses=1.0 -> 3.0
    assert profit_factor([2.0, 1.0, -1.0]) == pytest.approx(3.0)


def test_profit_factor_infinite_case_returns_none():
    """All wins, zero losses -- mathematically infinite, represented as
    None since float('inf') isn't valid JSON."""
    assert profit_factor([1.0, 2.0]) is None


def test_profit_factor_no_trades_at_all_is_zero():
    assert profit_factor([]) == 0.0


def test_expectancy_r_is_mean_pnl():
    assert expectancy_r([1.0, -1.0, 2.0]) == pytest.approx(2.0 / 3)


def test_average_win_loss_r():
    stats = average_win_loss_r([2.0, -1.0, 3.0, -2.0])
    assert stats["avg_win_r"] == pytest.approx(2.5)
    assert stats["avg_loss_r"] == pytest.approx(-1.5)
    assert stats["largest_win_r"] == pytest.approx(3.0)
    assert stats["largest_loss_r"] == pytest.approx(-2.0)


def test_summarize_combines_pnl_r_and_pnl_pct_correctly():
    result = summarize([2.0, -1.0, 1.5], [0.02, -0.01, 0.015])
    assert isinstance(result, PerformanceSummary)
    assert result.n_trades == 3
    assert result.total_pnl_r == pytest.approx(2.5)
    assert result.win_rate == pytest.approx(2 / 3)


def test_summarize_mismatched_lengths_raises():
    with pytest.raises(ValueError):
        summarize([1.0, 2.0], [0.01])


def test_recovery_factor_matches_hand_computed_value():
    # equity: 1.0 -> 1.02 -> 0.99 (dd=0.02/1.02≈0.0294) -> 1.05
    pnl_pcts = [0.02, -0.03 * (1.02 / 1.02), 0.06]  # simplified below
    pnl_pcts = [0.02, -0.0294117647, 0.06]
    dd = max_drawdown_pct(pnl_pcts)
    total_return = float(equity_curve_from_pnl_pct(pnl_pcts)[-1] - 1.0)
    expected = total_return / dd
    assert recovery_factor_from_pnl_pct(pnl_pcts) == pytest.approx(expected)


def test_recovery_factor_none_when_no_drawdown():
    assert recovery_factor_from_pnl_pct([0.01, 0.02, 0.03]) is None


def test_cvar_pct_none_below_minimum_trades():
    assert cvar_pct_from_pnl_pct([-0.01] * 5) is None


def test_cvar_pct_real_value_on_a_fat_tailed_series():
    """95 small gains + 5 large losses (exactly the worst 5% at alpha=0.95)
    -- CVaR must equal the mean of exactly those 5 tail losses, not the
    typical small-gain bar."""
    pnl_pcts = [0.005] * 95 + [-0.20] * 5
    result = cvar_pct_from_pnl_pct(pnl_pcts)
    assert result == pytest.approx(20.0, abs=0.5)  # mean of the 5 tail losses, in percent


def test_calmar_ratio_none_without_timestamps():
    assert calmar_ratio_from_journal([0.01, -0.02, 0.03], [None, None, None], [None, None, None]) is None


def test_calmar_ratio_none_with_span_under_a_day():
    t0 = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    t1 = dt.datetime(2026, 1, 1, 1, tzinfo=dt.timezone.utc)
    assert calmar_ratio_from_journal([0.01, -0.02], [t0, t0], [t1, t1]) is None


def test_calmar_ratio_real_value_over_a_real_multi_month_span():
    entries = [dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc), dt.datetime(2026, 3, 1, tzinfo=dt.timezone.utc)]
    exits = [dt.datetime(2026, 1, 5, tzinfo=dt.timezone.utc), dt.datetime(2026, 6, 1, tzinfo=dt.timezone.utc)]
    pnl_pcts = [0.05, -0.02]
    result = calmar_ratio_from_journal(pnl_pcts, entries, exits)
    assert result is not None
    dd = max_drawdown_pct(pnl_pcts)
    total_return = float(equity_curve_from_pnl_pct(pnl_pcts)[-1])
    years = (max(exits) - min(entries)).total_seconds() / 86400.0 / 365.25
    expected_cagr = total_return ** (1 / years) - 1
    assert result == pytest.approx(expected_cagr / dd)


def test_summarize_passes_through_calmar_when_timestamps_given():
    entries = [dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc), dt.datetime(2026, 3, 1, tzinfo=dt.timezone.utc)]
    exits = [dt.datetime(2026, 1, 5, tzinfo=dt.timezone.utc), dt.datetime(2026, 6, 1, tzinfo=dt.timezone.utc)]
    result = summarize([1.0, -0.5], [0.05, -0.02], entry_times=entries, exit_times=exits)
    assert result.calmar_ratio is not None


def test_sharpe_per_trade_matches_manual_mean_over_std():
    from project_titan_x.engines.e35_performance_analytics.engine import sharpe_per_trade

    pnl_pcts = [0.02, -0.01, 0.015, 0.005]
    arr = np.asarray(pnl_pcts)
    expected = arr.mean() / arr.std()
    assert sharpe_per_trade(pnl_pcts) == pytest.approx(expected)


def test_sharpe_per_trade_none_below_two_trades():
    from project_titan_x.engines.e35_performance_analytics.engine import sharpe_per_trade

    assert sharpe_per_trade([0.01]) is None
    assert sharpe_per_trade([]) is None


def test_sortino_per_trade_uses_only_downside_deviation():
    from project_titan_x.engines.e35_performance_analytics.engine import sortino_per_trade

    pnl_pcts = [0.05, 0.03, -0.01, -0.02]
    arr = np.asarray(pnl_pcts)
    downside = arr[arr < 0]
    expected = arr.mean() / downside.std()
    assert sortino_per_trade(pnl_pcts) == pytest.approx(expected)


def test_sortino_per_trade_none_when_no_losing_trades():
    """No downside deviation to divide by -- must be None, not a
    fabricated infinite or zero."""
    from project_titan_x.engines.e35_performance_analytics.engine import sortino_per_trade

    assert sortino_per_trade([0.01, 0.02, 0.03]) is None


def test_summarize_includes_sharpe_and_sortino_per_trade():
    # Two losing trades of different magnitudes -- downside.std() > 0, so
    # sortino_per_trade is actually defined (a single losing trade has
    # zero deviation by definition and would correctly come back None).
    result = summarize([2.0, -1.0, 1.5, -0.5], [0.02, -0.012, 0.015, -0.006])
    assert result.sharpe_per_trade is not None
    assert result.sortino_per_trade is not None
    d = result.to_dict()
    assert "sharpe_per_trade" in d and "sortino_per_trade" in d


def test_performance_summary_to_dict_handles_none_profit_factor():
    """profit_factor=None (infinite) must serialize to JSON-safe None, not
    crash on round(None, 4)."""
    summary = summarize([1.0, 2.0], [0.01, 0.02])
    d = summary.to_dict()
    assert d["profit_factor"] is None


# ---- engine (real Postgres) ----

@pytest.fixture
def performance_engine() -> PerformanceAnalyticsEngine:
    engine = PerformanceAnalyticsEngine()
    engine.initialize()
    return engine


def _delete_trades_by_strategy(strategy_name: str) -> None:
    """Test-hygiene helper: these tests write to the REAL, shared Postgres
    dev database (no per-test transaction rollback in this codebase's
    convention -- see module docstring), so leftover rows from a prior run
    would accumulate and break exact-count assertions on the next run.
    Delete by a unique strategy_name tag, same convention as CLAUDE.md
    Rule 4's "clean up test/exploration residue from real persistent
    stores"."""
    from sqlalchemy import delete
    from project_titan_x.core.database.models import Trade
    from project_titan_x.core.database.session import get_db_session

    with get_db_session() as session:
        session.execute(delete(Trade).where(Trade.strategy_name == strategy_name))


@pytest.mark.network
def test_log_and_list_trade_roundtrip(performance_engine):
    strategy = "test_e51_confluence_roundtrip_unique_tag"
    try:
        now = dt.datetime.now(dt.timezone.utc)
        log_result = performance_engine.log_trade(
            symbol="btcusd", direction="long", entry_price=60000.0, exit_price=62000.0,
            entry_time=now - dt.timedelta(hours=2), exit_time=now,
            pnl_r=1.5, pnl_percent=0.03, strategy_name=strategy,
            regime_at_entry="Trending Up", session_tag="new_york", notes="unit test trade",
        )
        assert log_result.success
        trade_id = log_result.data["trade_id"]

        list_result = performance_engine.list_trades(symbol="BTCUSD", strategy_name=strategy)
        assert list_result.success
        matches = [t for t in list_result.data if t["id"] == trade_id]
        assert len(matches) == 1
        assert matches[0]["symbol"] == "BTCUSD"  # uppercased on write
        assert matches[0]["pnl_r"] == pytest.approx(1.5)
    finally:
        _delete_trades_by_strategy(strategy)


@pytest.mark.network
def test_log_trade_computes_real_mae_mfe_from_live_ohlcv():
    """Real end-to-end check (Rule 4: at least one test per integration
    point uses the real collaborator): a real MarketDataEngine fetching
    real, current BTC-USD OHLCV must produce real, non-None mae_r/mfe_r
    for a recent trade window."""
    from project_titan_x.engines.e02_market_data.engine import MarketDataEngine

    strategy = "test_e35_mae_mfe_live_unique_tag"
    engine = PerformanceAnalyticsEngine(market_data_engine=MarketDataEngine())
    try:
        now = dt.datetime.now(dt.timezone.utc)
        log_result = engine.log_trade(
            symbol="BTC-USD", direction="long", entry_price=60000.0, exit_price=60500.0,
            entry_time=now - dt.timedelta(hours=6), exit_time=now,
            pnl_r=0.5, pnl_percent=0.008, strategy_name=strategy, timeframe="1h",
            stop_loss_price=59000.0,
        )
        assert log_result.success
        trade_id = log_result.data["trade_id"]
        matches = [t for t in engine.list_trades(symbol="BTC-USD", strategy_name=strategy).data if t["id"] == trade_id]
        assert len(matches) == 1
        assert matches[0]["mae_r"] is not None
        assert matches[0]["mfe_r"] is not None
        assert matches[0]["mae_r"] >= 0
        assert matches[0]["mfe_r"] >= 0
    finally:
        _delete_trades_by_strategy(strategy)


@pytest.mark.network
def test_summarize_via_engine_matches_pure_function(performance_engine):
    strategy = "test_e35_summarize_unique_tag"
    try:
        now = dt.datetime.now(dt.timezone.utc)
        for pnl_r, pnl_pct in [(1.0, 0.01), (-1.0, -0.01), (2.0, 0.02)]:
            performance_engine.log_trade(
                symbol="GOLD", direction="long", entry_price=2000.0, exit_price=2010.0,
                entry_time=now, exit_time=now, pnl_r=pnl_r, pnl_percent=pnl_pct,
                strategy_name=strategy,
            )
        result = performance_engine.summarize(strategy_name=strategy)
        assert result.success
        assert result.data.n_trades == 3
        assert result.data.total_pnl_r == pytest.approx(2.0)
    finally:
        _delete_trades_by_strategy(strategy)


@pytest.mark.network
def test_summarize_no_matching_trades_fails_gracefully(performance_engine):
    result = performance_engine.summarize(strategy_name="no_such_strategy_ever_logged_xyz")
    assert not result.success


def test_broken_session_factory_does_not_raise():
    """Best-effort convention: a DB failure returns success=False, never
    propagates an exception up to the caller."""
    def _broken_session_factory():
        raise RuntimeError("db unavailable")

    engine = PerformanceAnalyticsEngine(session_factory=_broken_session_factory)
    result = engine.log_trade(symbol="GOLD", direction="long")
    assert not result.success

    list_result = engine.list_trades()
    assert not list_result.success


# ---- self-improvement mistake tagging (added 2026-08-21) ----
# Same real-Postgres, unique-strategy-tag, delete-in-finally convention
# as the rest of this file's @pytest.mark.network tests above.

@pytest.mark.network
@pytest.mark.network
def test_kelly_sizing_exceeded_fires_with_a_real_quant_engine():
    """Regression test for a real bug found live (2026-09-13):
    average_win_loss_r's own avg_loss_r is NEGATIVE (the mean of signed
    losing pnl_rs), but E12's real kelly_criterion requires avg_loss as a
    POSITIVE magnitude -- passing the raw negative value straight through
    made kelly_criterion's own guard reject every real history, so this
    check silently never fired for ANY strategy. Only caught by this real
    end-to-end test against the actual QuantResearchEngine -- the pure
    check_kelly_sizing_exceeded unit tests construct TradeRecord directly
    and can't see this bug, since it lives in the computation that fills
    kelly_recommended_risk_pct, not in the check itself."""
    from project_titan_x.engines.e12_quant_research.engine import QuantResearchEngine

    strategy = "test_e35_kelly_live_unique_tag"
    engine = PerformanceAnalyticsEngine(quant_engine=QuantResearchEngine())
    try:
        now = dt.datetime.now(dt.timezone.utc)
        for i in range(10):
            pnl_r = 2.0 if i % 2 == 0 else -1.0
            engine.log_trade(
                symbol="EURUSD", direction="long", entry_price=1.1, exit_price=1.1 + 0.001 * pnl_r,
                entry_time=now, exit_time=now, pnl_r=pnl_r, pnl_percent=0.001 * pnl_r, strategy_name=strategy,
            )
        result = engine.log_trade(
            symbol="EURUSD", direction="long", entry_price=1.1, exit_price=1.105,
            entry_time=now + dt.timedelta(hours=2), exit_time=now + dt.timedelta(hours=2),
            pnl_r=1.0, pnl_percent=0.005, strategy_name=strategy, risk_percent_used=50.0,
        )
        tags = [t["tag_key"] for t in result.data["mistake_tags"]]
        assert "kelly_sizing_exceeded" in tags
    finally:
        _delete_trades_by_strategy(strategy)


@requires_postgres
def test_log_trade_auto_computes_mistake_tags(performance_engine):
    """Regression coverage for a real bug caught during live verification
    (not by any prior unit test): aggregate_mistake_costs originally read
    ORM attributes (tag.tag_key, trade.pnl_r) AFTER the session that
    fetched them had already closed, raising a real DetachedInstanceError
    the moment this was hit through the live API -- sqlite-backed pure-
    function tests never exercise a real session lifecycle the way this
    does. This test exercises the full path against real Postgres:
    log_trade -> automatic tag computation -> aggregate_mistake_costs."""
    strategy = "test_e35_mistake_tags_unique_tag"
    try:
        now = dt.datetime.now(dt.timezone.utc)
        log_result = performance_engine.log_trade(
            symbol="EURUSD", direction="long", entry_price=1.10, exit_price=1.09,
            entry_time=now - dt.timedelta(hours=1), exit_time=now,
            pnl_r=-1.0, pnl_percent=-0.5, strategy_name=strategy,
            confidence_at_entry=10,  # well below any reasonable min_confidence
        )
        assert log_result.success
        tag_keys = [t["tag_key"] for t in log_result.data["mistake_tags"]]
        assert "below_confluence_threshold" in tag_keys

        trade_id = log_result.data["trade_id"]
        tags_result = performance_engine.list_trade_tags(trade_id)
        assert tags_result.success
        assert any(t["tag_key"] == "below_confluence_threshold" for t in tags_result.data)

        # The exact call that raised DetachedInstanceError before the fix --
        # must succeed and reflect this trade's real logged pnl_r.
        summary_result = performance_engine.aggregate_mistake_costs(since=now - dt.timedelta(days=1))
        assert summary_result.success
        below_threshold_bucket = next(
            (b for b in summary_result.data["by_tag"] if b["tag_key"] == "below_confluence_threshold"), None,
        )
        assert below_threshold_bucket is not None
        assert trade_id in below_threshold_bucket["trade_ids"]
    finally:
        _delete_trades_by_strategy(strategy)


@pytest.mark.network
def test_log_trade_clean_signal_gets_no_mistake_tags(performance_engine):
    """A high-confidence trade with no risk_percent_used and no prior
    history should compute zero mistake tags -- confirms the automatic
    computation doesn't fabricate a tag when nothing actually fired.
    entry_time is a FIXED, known-inside-a-killzone timestamp (NY Open,
    12:00 UTC in January -- see test_killzones.py), not dt.datetime.now()
    -- outside_killzone depends on real wall-clock time, so a "now"-based
    entry_time would make this test's outcome depend on what moment it
    happened to run at, occasionally failing for a reason that has
    nothing to do with a real bug."""
    strategy = "test_e35_clean_trade_unique_tag"
    try:
        entry = dt.datetime(2026, 1, 15, 12, 0, tzinfo=dt.timezone.utc)
        log_result = performance_engine.log_trade(
            symbol="GOLD", direction="long", entry_price=2000.0, exit_price=2010.0,
            entry_time=entry, exit_time=entry + dt.timedelta(minutes=30), pnl_r=1.0, pnl_percent=0.01,
            strategy_name=strategy, confidence_at_entry=95,
        )
        assert log_result.success
        assert log_result.data["mistake_tags"] == []
    finally:
        _delete_trades_by_strategy(strategy)


@pytest.mark.network
def test_get_and_update_mistake_rules_roundtrip(performance_engine):
    """ensure_default_mistake_rules seeds once (idempotent), and
    update_mistake_rule's change is real and immediately visible via
    get_mistake_rules -- exercises the user-editable-threshold path."""
    seed_result = performance_engine.ensure_default_mistake_rules()
    assert seed_result.success
    seed_again = performance_engine.ensure_default_mistake_rules()
    assert seed_again.success
    assert seed_again.data["inserted"] == 0  # idempotent -- nothing new the second time

    rules_result = performance_engine.get_mistake_rules()
    assert rules_result.success
    rule_keys = [r["rule_key"] for r in rules_result.data]
    assert "below_confluence_threshold" in rule_keys

    original = next(r for r in rules_result.data if r["rule_key"] == "below_confluence_threshold")
    try:
        update_result = performance_engine.update_mistake_rule("below_confluence_threshold", enabled=False, params={"min_confidence": 80})
        assert update_result.success

        after = performance_engine.get_mistake_rules()
        updated_rule = next(r for r in after.data if r["rule_key"] == "below_confluence_threshold")
        assert updated_rule["enabled"] is False
        assert updated_rule["params"]["min_confidence"] == 80
    finally:
        # Restore original state so this test doesn't leak config into others.
        performance_engine.update_mistake_rule("below_confluence_threshold", enabled=original["enabled"], params=original["params"])


@pytest.mark.network
def test_disabled_rule_does_not_fire_via_engine(performance_engine):
    """Disabling below_confluence_threshold end-to-end through the real
    engine/DB path must suppress it even for a trade that would
    otherwise clearly trip it."""
    strategy = "test_e35_disabled_rule_unique_tag"
    performance_engine.ensure_default_mistake_rules()
    original = next(r for r in performance_engine.get_mistake_rules().data if r["rule_key"] == "below_confluence_threshold")
    try:
        performance_engine.update_mistake_rule("below_confluence_threshold", enabled=False)
        now = dt.datetime.now(dt.timezone.utc)
        log_result = performance_engine.log_trade(
            symbol="EURUSD", direction="long", entry_price=1.10, exit_price=1.09,
            entry_time=now, exit_time=now, pnl_r=-1.0, pnl_percent=-0.5,
            strategy_name=strategy, confidence_at_entry=5,
        )
        assert log_result.success
        assert "below_confluence_threshold" not in [t["tag_key"] for t in log_result.data["mistake_tags"]]
    finally:
        _delete_trades_by_strategy(strategy)
        performance_engine.update_mistake_rule("below_confluence_threshold", enabled=original["enabled"], params=original["params"])


@pytest.mark.network
def test_add_manual_psychology_tag(performance_engine):
    """The manual tag path (psychology) is independent of automatic
    rule-computation -- add_trade_tag must persist and list correctly,
    and must NOT be cleared by a later automatic tag recomputation
    (compute_and_persist_mistake_tags only clears rule_adherence/
    behavioral categories, per its own docstring)."""
    strategy = "test_e35_psych_tag_unique_tag"
    try:
        now = dt.datetime.now(dt.timezone.utc)
        log_result = performance_engine.log_trade(
            symbol="GOLD", direction="long", entry_price=2000.0, exit_price=2010.0,
            entry_time=now, exit_time=now, pnl_r=1.0, pnl_percent=0.01,
            strategy_name=strategy, confidence_at_entry=95,
        )
        trade_id = log_result.data["trade_id"]

        add_result = performance_engine.add_trade_tag(trade_id, "psychology", "disciplined", negative=False, detail={"note": "followed the plan"})
        assert add_result.success

        recompute_result = performance_engine.compute_and_persist_mistake_tags(trade_id)
        assert recompute_result.success

        tags_result = performance_engine.list_trade_tags(trade_id)
        tag_keys = [t["tag_key"] for t in tags_result.data]
        assert "disciplined" in tag_keys  # survived the automatic recompute
    finally:
        _delete_trades_by_strategy(strategy)


def test_aggregate_mistake_costs_broken_session_factory_does_not_raise():
    def _broken_session_factory():
        raise RuntimeError("db unavailable")

    engine = PerformanceAnalyticsEngine(session_factory=_broken_session_factory)
    result = engine.aggregate_mistake_costs()
    assert not result.success
