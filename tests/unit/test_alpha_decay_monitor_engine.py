"""
Tests for Engine 38 -- Alpha Decay Monitor.

assess_decay_from_trades is the core comparison logic and is tested
directly against hand-built, already-fetched trade lists (no database
needed -- same "most recent first" ordering E35.list_trades produces).
One real-collaborator test (Rule 4) confirms it against the real E35/E12
engines.
"""

import datetime as dt

import pytest

from project_titan_x.engines.e38_alpha_decay_monitor.engine import (
    AlphaDecayMonitorEngine,
    DecayAssessment,
    assess_decay_from_trades,
)
from project_titan_x.engines.e35_performance_analytics.engine import PerformanceAnalyticsEngine


def _trade(pnl_r, pnl_pct=None):
    return {"pnl_r": pnl_r, "pnl_percent": pnl_pct if pnl_pct is not None else pnl_r * 0.01}


class _StubResult:
    def __init__(self, success=True, data=None):
        self.success = success
        self.data = data


class _StubBayesianResult:
    def __init__(self, mean, ci):
        self.posterior_mean = mean
        self.credible_interval_90pct = ci


class _StubQuantEngine:
    """Returns a caller-supplied CI per call, in order -- lets tests force
    a specific non-overlapping/overlapping scenario deterministically."""

    def __init__(self, cis):
        self._cis = list(cis)

    def bayesian_win_rate_update(self, wins, losses):
        ci = self._cis.pop(0)
        return _StubResult(True, _StubBayesianResult(mean=(ci[0] + ci[1]) / 2, ci=ci))


# ---- assess_decay_from_trades (pure logic) ----

def test_insufficient_data_when_recent_window_too_small():
    trades = [_trade(1.0)] * 5 + [_trade(1.0)] * 15  # 5 recent, 15 baseline; min=10
    result = assess_decay_from_trades(trades, quant_engine=None, recent_window=5, min_trades_per_window=10)
    assert result.status == "insufficient_data"
    assert result.decay_detected is False


def test_insufficient_data_when_baseline_window_too_small():
    trades = [_trade(1.0)] * 15 + [_trade(1.0)] * 5  # 15 recent (window=15), 5 baseline
    result = assess_decay_from_trades(trades, quant_engine=None, recent_window=15, min_trades_per_window=10)
    assert result.status == "insufficient_data"


def test_decay_detected_when_recent_ci_entirely_below_baseline_ci():
    trades = [_trade(-1.0)] * 12 + [_trade(1.0)] * 12  # 12 recent (losing), 12 baseline (winning)
    quant = _StubQuantEngine(cis=[(0.10, 0.30), (0.70, 0.90)])  # recent CI, baseline CI
    result = assess_decay_from_trades(trades, quant_engine=quant, recent_window=12, min_trades_per_window=10)
    assert result.status == "decay_detected"
    assert result.decay_detected is True


def test_improving_when_recent_ci_entirely_above_baseline_ci():
    trades = [_trade(1.0)] * 12 + [_trade(-1.0)] * 12
    quant = _StubQuantEngine(cis=[(0.70, 0.90), (0.10, 0.30)])  # recent CI, baseline CI
    result = assess_decay_from_trades(trades, quant_engine=quant, recent_window=12, min_trades_per_window=10)
    assert result.status == "improving"
    assert result.decay_detected is False


def test_stable_when_credible_intervals_overlap():
    # Real, varying pnl_r within each window (not a repeated constant) --
    # the expectancy Welch's t-test (added 2026-08-02, runs independently
    # of quant_engine) needs genuine within-group variance to be a
    # meaningful test at all; a constant-value fixture makes ANY nonzero
    # between-group difference look "infinitely significant" (zero
    # within-group variance), which is a fixture artifact, not real
    # decay -- exactly why this fixture was changed to look like actual
    # trade data instead of a repeated single number.
    recent = [_trade(r) for r in [0.3, 0.5, 0.7, 0.4, 0.6, 0.5, 0.3, 0.6, 0.4, 0.5, 0.7, 0.4]]
    baseline = [_trade(r) for r in [0.4, 0.6, 0.5, 0.7, 0.3, 0.6, 0.5, 0.4, 0.6, 0.5, 0.3, 0.6]]
    trades = recent + baseline
    quant = _StubQuantEngine(cis=[(0.40, 0.70), (0.45, 0.75)])  # overlapping
    result = assess_decay_from_trades(trades, quant_engine=quant, recent_window=12, min_trades_per_window=10)
    assert result.status == "stable"
    assert result.decay_detected is False
    assert result.expectancy_decay_detected is False


def test_no_quant_engine_still_runs_independent_expectancy_test():
    """quant_engine=None skips ONLY the win-rate Bayesian-CI test (it's
    the one collaborator that specifically needs quant_engine) -- the
    expectancy Welch's t-test is a pure scipy computation with no such
    dependency, so it still runs and must still catch a real, total
    reversal from consistently profitable to consistently losing."""
    trades = [_trade(-1.0)] * 12 + [_trade(1.0)] * 12
    result = assess_decay_from_trades(trades, quant_engine=None, recent_window=12, min_trades_per_window=10)
    assert result.status == "decay_detected"
    assert result.expectancy_decay_detected is True
    assert result.baseline_bayesian_ci is None and result.recent_bayesian_ci is None  # win-rate test genuinely skipped
    assert result.recent_expectancy_r == pytest.approx(-1.0)
    assert result.baseline_expectancy_r == pytest.approx(1.0)


def test_broken_quant_engine_does_not_raise():
    class _BrokenQuantEngine:
        def bayesian_win_rate_update(self, wins, losses):
            raise RuntimeError("boom")

    trades = [_trade(1.0)] * 12 + [_trade(1.0)] * 12
    result = assess_decay_from_trades(trades, quant_engine=_BrokenQuantEngine(), recent_window=12, min_trades_per_window=10)
    assert result.status == "stable"  # falls back gracefully, doesn't crash


def test_result_is_decay_assessment_and_to_dict_serializes():
    trades = [_trade(1.0)] * 12 + [_trade(1.0)] * 12
    result = assess_decay_from_trades(trades, quant_engine=None, recent_window=12, min_trades_per_window=10)
    assert isinstance(result, DecayAssessment)
    d = result.to_dict()
    assert d["status"] == "stable"
    assert d["recent_n_trades"] == 12


# ---- engine-level ----

class _StubPerformanceEngine:
    def __init__(self, trades):
        self._trades = trades

    def list_trades(self, strategy_name=None, limit=20000):
        return _StubResult(True, self._trades)

    def health_check(self):
        return _StubResult(True)


def test_engine_assess_decay_with_stub():
    trades = [_trade(1.0)] * 12 + [_trade(1.0)] * 12
    engine = AlphaDecayMonitorEngine(performance_engine=_StubPerformanceEngine(trades), quant_engine=None)
    result = engine.assess_decay(recent_window=12, min_trades_per_window=10)
    assert result.success
    assert isinstance(result.data, DecayAssessment)


def test_engine_propagates_trade_list_failure():
    class _FailingPerformanceEngine:
        def list_trades(self, strategy_name=None, limit=20000):
            return _StubResult(False, None)

        def health_check(self):
            return _StubResult(False)

    engine = AlphaDecayMonitorEngine(performance_engine=_FailingPerformanceEngine())
    result = engine.assess_decay()
    assert not result.success


# ---- real collaborators (Rule 4) ----

@pytest.mark.network
def test_assess_decay_uses_real_performance_and_quant_engines():
    """Real-collaborator test: logs 24 real trades (12 losing "baseline",
    12 winning "recent") via the real PerformanceAnalyticsEngine, runs the
    real QuantResearchEngine's bayesian_win_rate_update, and confirms a
    real "improving" verdict comes back (recent trades are strictly
    better than baseline here). Cleans up its own rows afterward."""
    from sqlalchemy import delete
    from project_titan_x.core.database.models import Trade
    from project_titan_x.core.database.session import get_db_session
    from project_titan_x.engines.e12_quant_research import QuantResearchEngine

    performance_engine = PerformanceAnalyticsEngine()
    performance_engine.initialize()
    quant_engine = QuantResearchEngine()
    strategy = "test_e38_decay_real_collab_unique_tag"
    try:
        now = dt.datetime.now(dt.timezone.utc)
        # Baseline (older, entered first): all losses.
        for i in range(12):
            performance_engine.log_trade(
                symbol="GOLD", direction="long", entry_price=2000.0, exit_price=1990.0,
                entry_time=now - dt.timedelta(days=30 - i), exit_time=now - dt.timedelta(days=30 - i),
                pnl_r=-1.0, pnl_percent=-0.01, strategy_name=strategy,
            )
        # Recent (newer): all wins.
        for i in range(12):
            performance_engine.log_trade(
                symbol="GOLD", direction="long", entry_price=2000.0, exit_price=2020.0,
                entry_time=now - dt.timedelta(days=i), exit_time=now - dt.timedelta(days=i),
                pnl_r=1.0, pnl_percent=0.01, strategy_name=strategy,
            )
        engine = AlphaDecayMonitorEngine(performance_engine=performance_engine, quant_engine=quant_engine)
        result = engine.assess_decay(strategy_name=strategy, recent_window=12, min_trades_per_window=10)
        assert result.success
        assert result.data.status == "improving"
        assert result.data.recent_win_rate == pytest.approx(1.0)
        assert result.data.baseline_win_rate == pytest.approx(0.0)
    finally:
        with get_db_session() as session:
            session.execute(delete(Trade).where(Trade.strategy_name == strategy))
