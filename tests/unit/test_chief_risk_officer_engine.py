"""
Module: test_chief_risk_officer_engine.py
Description: Unit tests for Engine 46 (Chief Risk Officer) -- another
    engine the Phase 1 audit found had zero test reference. E46's own
    module docstring makes a specific, load-bearing claim: it is
    READ-ONLY oversight above E45's per-trade veto and "NEVER writes back
    into E45's state" -- "verified by inspection" there, but never
    actually pinned by an automated test until this file. The most
    important test below (test_never_writes_back_into_e45) makes that an
    executable guarantee instead of a comment a future edit could quietly
    invalidate.

    Also exercises the real, direct consequence of this session's own
    E45 fix (RiskManagementEngine now computes current_drawdown_pct from
    a tracked peak instead of trusting a caller-supplied number, see
    engines/e45_risk/engine.py's GENERIC_ZONE_YELLOW_START_PCT docstring)
    -- E46 reads that SAME field via get_portfolio_state(), so a real E45
    instance wired into a real E46 proves the fix actually reaches the
    portfolio-level oversight layer, not just E45's own per-trade gate.
Author: Shantanu Waykar
Version: 1.0.0
"""

from types import SimpleNamespace

import pytest

from project_titan_x.engines.e45_risk import PortfolioRiskState, RiskManagementEngine
from project_titan_x.engines.e46_chief_risk_officer.engine import ChiefRiskOfficerEngine


def _state(**overrides) -> PortfolioRiskState:
    defaults = dict(
        total_capital=10_000.0, daily_pnl_pct=0.0, weekly_pnl_pct=0.0, monthly_pnl_pct=0.0,
        current_drawdown_pct=0.0, portfolio_heat_pct=0.0, open_positions=0,
        risk_of_ruin_pct=0.0, correlation_max=0.0,
    )
    defaults.update(overrides)
    return PortfolioRiskState(**defaults)


def _mock_risk_engine(state: PortfolioRiskState):
    return SimpleNamespace(get_portfolio_state=lambda: state)


@pytest.fixture
def cro() -> ChiefRiskOfficerEngine:
    e = ChiefRiskOfficerEngine(risk_engine=_mock_risk_engine(_state()))
    e.initialize()
    return e


# --------------------------------------------------------------------------
# Fail-closed without a risk_engine
# --------------------------------------------------------------------------

def test_health_check_fails_without_risk_engine():
    e = ChiefRiskOfficerEngine()
    e.initialize()
    result = e.health_check()
    assert result.success is False


def test_assess_risk_posture_fails_without_risk_engine():
    e = ChiefRiskOfficerEngine()
    e.initialize()
    result = e.assess_risk_posture()
    assert result.success is False
    assert "no risk_engine" in result.message.lower()


# --------------------------------------------------------------------------
# _classify -- ok / elevated / breached bands
# --------------------------------------------------------------------------

def test_classify_ok_below_elevated_fraction():
    d = ChiefRiskOfficerEngine._classify("heat", current=50.0, limit=100.0)  # 50% of limit
    assert d.status == "ok"


def test_classify_elevated_at_exactly_the_threshold():
    d = ChiefRiskOfficerEngine._classify("heat", current=75.0, limit=100.0)  # exactly 75%
    assert d.status == "elevated"


def test_classify_breached_at_or_above_limit():
    d = ChiefRiskOfficerEngine._classify("heat", current=100.0, limit=100.0)
    assert d.status == "breached"
    d2 = ChiefRiskOfficerEngine._classify("heat", current=150.0, limit=100.0)
    assert d2.status == "breached"


def test_classify_zero_limit_is_ok_not_a_crash():
    """A misconfigured/disabled limit (0) must not divide-by-zero or flag
    a false breach -- honest 'ok', same defensive convention as E45's own
    settings-sanity checks in e47_governance."""
    d = ChiefRiskOfficerEngine._classify("heat", current=5.0, limit=0.0)
    assert d.status == "ok"


# --------------------------------------------------------------------------
# assess_risk_posture -- posture derivation
# --------------------------------------------------------------------------

def test_posture_low_when_no_open_positions_and_all_ok():
    cro = ChiefRiskOfficerEngine(risk_engine=_mock_risk_engine(_state(open_positions=0)))
    cro.initialize()
    result = cro.assess_risk_posture()
    assert result.data.risk_posture == "low"


def test_posture_normal_when_positions_open_and_all_ok():
    cro = ChiefRiskOfficerEngine(risk_engine=_mock_risk_engine(_state(open_positions=2)))
    cro.initialize()
    result = cro.assess_risk_posture()
    assert result.data.risk_posture == "normal"


def test_posture_elevated_when_one_dimension_elevated():
    from project_titan_x.core.config import get_settings
    settings = get_settings()
    state = _state(open_positions=1, portfolio_heat_pct=0.76 * settings.max_portfolio_heat_pct)
    cro = ChiefRiskOfficerEngine(risk_engine=_mock_risk_engine(state))
    cro.initialize()
    result = cro.assess_risk_posture()
    assert result.data.risk_posture == "elevated"


def test_posture_elevated_not_critical_on_a_single_breach():
    """Pins a real, non-obvious rule in the current implementation:
    posture only escalates to 'critical' when MORE THAN ONE dimension is
    breached -- a single breach is 'elevated'. Worth an explicit test so
    a future change to this threshold is a deliberate, visible decision,
    not an accidental one-line slip."""
    from project_titan_x.core.config import get_settings
    settings = get_settings()
    state = _state(open_positions=1, portfolio_heat_pct=settings.max_portfolio_heat_pct * 1.5)
    cro = ChiefRiskOfficerEngine(risk_engine=_mock_risk_engine(state))
    cro.initialize()
    result = cro.assess_risk_posture()
    assert result.data.risk_posture == "elevated"


def test_posture_critical_when_two_or_more_dimensions_breached():
    from project_titan_x.core.config import get_settings
    settings = get_settings()
    state = _state(
        open_positions=1,
        portfolio_heat_pct=settings.max_portfolio_heat_pct * 1.5,
        risk_of_ruin_pct=settings.max_risk_of_ruin_pct * 1.5,
    )
    cro = ChiefRiskOfficerEngine(risk_engine=_mock_risk_engine(state))
    cro.initialize()
    result = cro.assess_risk_posture()
    assert result.data.risk_posture == "critical"


def test_all_four_dimensions_are_classified():
    """A regression here (a dropped dimension) would silently narrow the
    CRO's own oversight scope -- pin the exact set by name."""
    cro = ChiefRiskOfficerEngine(risk_engine=_mock_risk_engine(_state()))
    cro.initialize()
    result = cro.assess_risk_posture()
    names = {d.name for d in result.data.dimensions}
    assert names == {"portfolio_heat_pct", "risk_of_ruin_pct", "correlation_max", "current_drawdown_pct"}


# --------------------------------------------------------------------------
# Stress exposures
# --------------------------------------------------------------------------

def test_no_stress_exposures_without_stress_engine(cro):
    result = cro.assess_risk_posture(symbols=["BTCUSD"])
    assert result.data.stress_exposures == []


def test_stress_exposure_recorded_when_available():
    stress_data = SimpleNamespace(worst_case_dd_pct=-12.5, overall_verdict="resilient")
    stress_engine = SimpleNamespace(run_stress_test=lambda symbol, tf: SimpleNamespace(success=True, data=stress_data))
    cro = ChiefRiskOfficerEngine(risk_engine=_mock_risk_engine(_state()), stress_testing_engine=stress_engine)
    cro.initialize()
    result = cro.assess_risk_posture(symbols=["BTCUSD"])
    assert len(result.data.stress_exposures) == 1
    assert result.data.stress_exposures[0].symbol == "BTCUSD"
    assert result.data.stress_exposures[0].verdict == "resilient"


def test_stress_test_failure_reported_as_insufficient_data():
    stress_engine = SimpleNamespace(run_stress_test=lambda symbol, tf: SimpleNamespace(success=False, data=None))
    cro = ChiefRiskOfficerEngine(risk_engine=_mock_risk_engine(_state()), stress_testing_engine=stress_engine)
    cro.initialize()
    result = cro.assess_risk_posture(symbols=["BTCUSD"])
    assert result.data.stress_exposures[0].verdict == "insufficient_data"
    assert result.data.stress_exposures[0].worst_case_dd_pct is None


def test_stress_breach_alone_yields_elevated_not_critical():
    """Pins the current implementation's real coupling: risk_posture only
    reaches 'critical' via n_breached > 1 -- a stress-test breach with
    zero dimension breaches stays 'elevated', not 'critical'. Same
    "document the actual behavior, don't assume" discipline as the
    single-dimension-breach test above."""
    stress_data = SimpleNamespace(worst_case_dd_pct=-40.0, overall_verdict="breached_risk_limit")
    stress_engine = SimpleNamespace(run_stress_test=lambda symbol, tf: SimpleNamespace(success=True, data=stress_data))
    cro = ChiefRiskOfficerEngine(risk_engine=_mock_risk_engine(_state(open_positions=1)), stress_testing_engine=stress_engine)
    cro.initialize()
    result = cro.assess_risk_posture(symbols=["BTCUSD"])
    assert result.data.risk_posture == "elevated"


# --------------------------------------------------------------------------
# Narrative
# --------------------------------------------------------------------------

def test_narrative_mentions_flagged_dimensions():
    from project_titan_x.core.config import get_settings
    settings = get_settings()
    state = _state(open_positions=1, portfolio_heat_pct=settings.max_portfolio_heat_pct * 1.5)
    cro = ChiefRiskOfficerEngine(risk_engine=_mock_risk_engine(state))
    cro.initialize()
    result = cro.assess_risk_posture()
    assert "portfolio_heat_pct" in result.data.narrative


def test_narrative_says_all_normal_when_nothing_flagged(cro):
    result = cro.assess_risk_posture()
    assert "normal range" in result.data.narrative.lower()


# --------------------------------------------------------------------------
# THE ACTUAL GUARANTEE -- read-only, never writes back into E45
# --------------------------------------------------------------------------

def test_never_writes_back_into_e45():
    """The module docstring claims this is 'verified by inspection' --
    make it an executable guarantee instead. A risk_engine stand-in whose
    update_portfolio_state/evaluate_trade would raise if ever called
    proves E46 genuinely never calls either, across a normal call
    (assess_risk_posture with symbols + a stress engine) exercising every
    real code path in the method."""
    def _forbidden(*a, **k):
        raise AssertionError("E46 must never write back into E45's state")

    guarded = SimpleNamespace(
        get_portfolio_state=lambda: _state(open_positions=1),
        update_portfolio_state=_forbidden,
        evaluate_trade=_forbidden,
    )
    stress_data = SimpleNamespace(worst_case_dd_pct=-5.0, overall_verdict="resilient")
    stress_engine = SimpleNamespace(run_stress_test=lambda symbol, tf: SimpleNamespace(success=True, data=stress_data))
    cro = ChiefRiskOfficerEngine(risk_engine=guarded, stress_testing_engine=stress_engine)
    cro.initialize()
    result = cro.assess_risk_posture(symbols=["BTCUSD", "ETHUSD"])
    assert result.success is True  # completed without ever tripping _forbidden


# --------------------------------------------------------------------------
# Real integration with E45 -- proves the fix reaches this layer too
# --------------------------------------------------------------------------

def test_real_e45_drawdown_fix_is_visible_through_e46():
    """A real RiskManagementEngine (not a mock) reports a real capital
    loss from a real peak; E46 must classify E45's OWN authoritative,
    peak-derived current_drawdown_pct -- proving engines/e45_risk's
    trailing high-water-mark fix (this same session) reaches the
    portfolio-level oversight layer with zero E46-side code changes,
    exactly as that fix's own CLAUDE.md entry claims."""
    from project_titan_x.core.config import get_settings
    settings = get_settings()

    risk_engine = RiskManagementEngine()
    risk_engine.initialize()
    risk_engine.update_portfolio_state(PortfolioRiskState(total_capital=10_000.0))  # peak
    # A caller-supplied current_drawdown_pct of 0 here would be WRONG and
    # is exactly what the old behavior would have trusted -- E45 now
    # overwrites it with the real, peak-derived figure regardless.
    risk_engine.update_portfolio_state(
        PortfolioRiskState(total_capital=10_000.0 * (1 - 0.9 * settings.max_drawdown_pct / 100), current_drawdown_pct=0.0)
    )

    cro = ChiefRiskOfficerEngine(risk_engine=risk_engine)
    cro.initialize()
    result = cro.assess_risk_posture()
    dd_dimension = next(d for d in result.data.dimensions if d.name == "current_drawdown_pct")
    assert dd_dimension.status == "elevated"  # 90% of the limit -- real, not the fabricated 0.0
    assert dd_dimension.current == pytest.approx(0.9 * settings.max_drawdown_pct, abs=0.01)
