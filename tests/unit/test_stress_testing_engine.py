"""
Module: test_stress_testing_engine.py
Description: Unit tests for Engine 28 (Stress Testing).
Author: Shantanu Waykar
Version: 1.0.0
"""

import pytest

from project_titan_x.engines.e28_stress_testing.engine import (
    StressPeriodResult,
    StressTestingEngine,
)


@pytest.fixture
def engine() -> StressTestingEngine:
    e = StressTestingEngine()
    e.initialize()
    return e


def test_health_check(engine):
    assert engine.health_check().success


def test_run_stress_test_without_signal_engine_fails(engine):
    result = engine.run_stress_test("GOLD")
    assert not result.success
    assert "signal_engine" in result.message


def test_run_stress_test_unknown_asset_fails():
    class _FakeSignalEngine:
        def build_strategy_fn(self, *a, **k):
            raise AssertionError("should not be called for an unknown asset")

    engine = StressTestingEngine(signal_engine=_FakeSignalEngine())
    result = engine.run_stress_test("NOT_A_REAL_ASSET")
    assert not result.success


# ---- _aggregate (pure function, no network) ----


def test_aggregate_insufficient_data_when_no_valid_periods(engine):
    periods = [StressPeriodResult(period_name="2008_gfc", start="x", end="y", verdict="insufficient_data")]
    report = engine._aggregate("BTCUSD", "1d", periods)
    assert report.overall_verdict == "insufficient_data"
    assert report.worst_case_dd_pct is None


def test_aggregate_resilient_when_all_periods_within_limit(engine):
    periods = [
        StressPeriodResult(period_name="2008_gfc", start="x", end="y", verdict="resilient", max_drawdown_pct=5.0),
        StressPeriodResult(period_name="2020_covid", start="x", end="y", verdict="resilient", max_drawdown_pct=8.0),
    ]
    report = engine._aggregate("GOLD", "1d", periods)
    assert report.overall_verdict == "resilient"
    assert report.worst_case_dd_pct == 8.0


def test_aggregate_breached_when_any_period_breaches(engine):
    periods = [
        StressPeriodResult(period_name="2008_gfc", start="x", end="y", verdict="resilient", max_drawdown_pct=5.0),
        StressPeriodResult(period_name="2022_rate_shock", start="x", end="y", verdict="breached_risk_limit", max_drawdown_pct=25.0),
    ]
    report = engine._aggregate("GOLD", "1d", periods)
    assert report.overall_verdict == "breached_risk_limit"
    assert report.worst_case_dd_pct == 25.0


def test_aggregate_ignores_insufficient_periods_when_computing_worst_case(engine):
    periods = [
        StressPeriodResult(period_name="2008_gfc", start="x", end="y", verdict="insufficient_data"),
        StressPeriodResult(period_name="2020_covid", start="x", end="y", verdict="resilient", max_drawdown_pct=3.0),
    ]
    report = engine._aggregate("BTCUSD", "1d", periods)
    assert report.worst_case_dd_pct == 3.0
    assert report.overall_verdict == "resilient"


# ---- knowledge_context ----


def test_build_knowledge_context_none_without_engine(engine):
    assert engine._build_knowledge_context("GOLD", "breached_risk_limit") is None


def test_build_knowledge_context_none_when_resilient():
    class _StubKnowledge:
        document_store = None

    engine = StressTestingEngine(knowledge_engine=_StubKnowledge())
    assert engine._build_knowledge_context("GOLD", "resilient") is None


# ---- run_stress_test() against REAL yfinance data + REAL E26 math ----


@pytest.mark.network
def test_run_stress_test_gold_uses_real_stress_periods(engine):
    from project_titan_x.engines.e51_signals.engine import SignalIntelligenceEngine

    engine = StressTestingEngine(signal_engine=SignalIntelligenceEngine())
    result = engine.run_stress_test("GOLD", timeframe="1d")
    assert result.success
    report = result.data
    period_names = {p.period_name for p in report.periods}
    # 2023_banking_crisis added 2026-08-02 (SVB/Signature/Credit Suisse/First
    # Republic) alongside the original three periods, see E26's own
    # STRESS_PERIODS docstring.
    assert period_names == {"2008_gfc", "2020_covid", "2022_rate_shock", "2023_banking_crisis"}
    # GOLD has real data back to 2000 -- every period must resolve to a
    # real, non-fabricated verdict, not an honest gap.
    assert all(p.verdict != "insufficient_data" for p in report.periods)


@pytest.mark.network
def test_run_stress_test_btcusd_honestly_reports_no_2008_data(engine):
    """Bitcoin did not exist in 2008 -- this must be an honest gap, not a
    fabricated result."""
    from project_titan_x.engines.e51_signals.engine import SignalIntelligenceEngine

    engine = StressTestingEngine(signal_engine=SignalIntelligenceEngine())
    result = engine.run_stress_test("BTCUSD", timeframe="1d")
    assert result.success
    gfc = next(p for p in result.data.periods if p.period_name == "2008_gfc")
    assert gfc.verdict == "insufficient_data"
