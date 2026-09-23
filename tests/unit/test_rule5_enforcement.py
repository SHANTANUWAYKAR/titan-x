"""
Tests for E47 (Governance) and E48 (Execution Readiness) -- the two engines
that ENFORCE Rule 5 ("no execution engine; this system reports, I trade").

WHY THESE EXIST. The Phase 1 audit found that 19 of 55 engines had no test
reference at all, and that these two were among them. That is the sharpest
gap in the suite: E47's `_check_no_execution_capability` is the mechanism
that detects an order-placement method appearing anywhere in the platform,
and nothing verified that the detector itself works. A detector that
silently stopped detecting would look identical to a clean platform.

The most important assertions here are the FAIL-CLOSED ones. A compliance
check that returns "pass" when it cannot actually verify anything is worse
than no check, because it manufactures false assurance -- so the tests below
pin that an uninjected registry or a missing E39 produces `fail`, not `pass`.
"""

from types import SimpleNamespace

import pandas as pd
import pytest

from project_titan_x.engines.e47_governance.engine import (
    _EXECUTION_METHOD_NAMES,
    GovernanceEngine,
)
from project_titan_x.engines.e48_execution_readiness.engine import ExecutionReadinessEngine
from project_titan_x.engines.registry import get_registry


class _CleanEngine:
    engine_id = "e_clean"

    def analyze(self):
        return None


def _registry_with(**engines):
    """Minimal stand-in exposing the `_engines` mapping E47 walks."""
    return SimpleNamespace(_engines=dict(engines))


@pytest.fixture
def gov():
    e = GovernanceEngine(registry=_registry_with(e_clean=_CleanEngine()))
    e.initialize()
    return e


# --------------------------------------------------------------------------
# E47 -- the Rule 5 detector
# --------------------------------------------------------------------------

def test_clean_registry_passes(gov):
    check = gov._check_no_execution_capability()
    assert check.status == "pass"


@pytest.mark.parametrize("method_name", _EXECUTION_METHOD_NAMES)
def test_every_banned_method_name_is_detected(method_name):
    """Each of the four names must trip the check on its own.

    Parametrised deliberately: a refactor that narrowed the tuple, or an
    `any`/`all` inversion, could leave three names detected and one live.
    """
    offender = type("Offender", (), {"engine_id": "e_bad", method_name: lambda self: None})()
    gov = GovernanceEngine(registry=_registry_with(e_bad=offender))
    check = gov._check_no_execution_capability()
    assert check.status == "fail"
    assert method_name in check.detail
    assert "e_bad" in check.detail


def test_offender_is_named_not_just_counted():
    """The report must say WHICH engine and WHICH method, or it is unactionable."""
    offender = type("Offender", (), {"engine_id": "e_broker", "place_order": lambda self: None})()
    gov = GovernanceEngine(registry=_registry_with(e_ok=_CleanEngine(), e_broker=offender))
    detail = gov._check_no_execution_capability().detail
    assert "e_broker.place_order" in detail


def test_missing_registry_fails_closed():
    """No registry means the check CANNOT verify -- it must not report pass."""
    check = GovernanceEngine(registry=None)._check_no_execution_capability()
    assert check.status == "fail"
    assert "cannot verify" in check.detail.lower()


def test_missing_model_risk_engine_fails_closed():
    check = GovernanceEngine(registry=_registry_with())._check_model_provenance()
    assert check.status == "fail"
    assert "cannot verify" in check.detail.lower()


def test_audit_flips_overall_status_on_violation():
    offender = type("Offender", (), {"engine_id": "e_bad", "submit_order": lambda self: None})()
    gov = GovernanceEngine(registry=_registry_with(e_bad=offender))
    gov.initialize()
    result = gov.audit_compliance()
    assert result.success is True          # the audit ran
    assert result.data.overall_status == "violations_found"   # and reported a violation
    assert any(c.name == "no_execution_capability" and c.status == "fail" for c in result.data.checks)


def test_audit_reports_every_check(gov):
    names = {c.name for c in gov.audit_compliance().data.checks}
    assert names == {
        "no_execution_capability",
        "risk_limits_sane",
        "model_provenance",
        "human_approval_required_for_execution",
    }


def test_insane_risk_limits_are_caught(monkeypatch):
    """A risk limit of 0 or >100 is nonsense and must not pass silently."""
    import project_titan_x.engines.e47_governance.engine as mod

    monkeypatch.setattr(mod.settings, "max_drawdown_pct", 0, raising=False)
    check = GovernanceEngine(registry=_registry_with())._check_risk_limits_sane()
    assert check.status == "fail"
    assert "max_drawdown_pct" in check.detail


# --------------------------------------------------------------------------
# THE ACTUAL GUARANTEE -- the real platform, not a stand-in
# --------------------------------------------------------------------------

def test_real_registry_has_no_execution_capability():
    """Rule 5, asserted against the live engine registry.

    This is the test the whole file exists for. Everything above proves the
    detector works; this runs it over every engine actually registered on
    the platform. If someone adds `place_order` to any engine, this fails.
    """
    gov = GovernanceEngine(registry=get_registry())
    gov.initialize()
    check = gov._check_no_execution_capability()
    assert check.status == "pass", check.detail


def test_e48_itself_exposes_no_execution_method():
    """E48 is informational-only by design; its name invites the opposite."""
    engine = ExecutionReadinessEngine()
    for name in _EXECUTION_METHOD_NAMES:
        assert not hasattr(engine, name), f"E48 exposes {name} -- Rule 5 violation"


# --------------------------------------------------------------------------
# E48 -- assessment behaviour
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "execution_risk,session_liquidity,expected",
    [
        ("unknown", "normal", "insufficient_data"),
        ("unknown", None, "insufficient_data"),
        ("high", "normal", "caution"),
        ("low", "quiet", "caution"),
        ("low", "normal", "ready"),
        ("low", None, "ready"),
    ],
)
def test_readiness_truth_table(execution_risk, session_liquidity, expected):
    assert ExecutionReadinessEngine._determine_readiness(execution_risk, session_liquidity) == expected


def test_unknown_risk_never_reports_ready():
    """'insufficient_data' must not degrade to 'ready' -- that would turn an
    absence of information into a green light."""
    for liquidity in ("normal", "quiet", None, "deep"):
        assert ExecutionReadinessEngine._determine_readiness("unknown", liquidity) != "ready"


def test_rejects_non_positive_position_size():
    engine = ExecutionReadinessEngine(
        microstructure_engine=SimpleNamespace(), market_data_engine=SimpleNamespace()
    )
    for size in (0, -1, -1000.0):
        result = engine.assess_execution_readiness("GOLD", size)
        assert result.success is False
        assert "positive" in result.message


def test_requires_both_dependencies():
    for micro, market in ((None, SimpleNamespace()), (SimpleNamespace(), None), (None, None)):
        result = ExecutionReadinessEngine(
            microstructure_engine=micro, market_data_engine=market
        ).assess_execution_readiness("GOLD", 1000.0)
        assert result.success is False
        assert "required" in result.message


@pytest.mark.parametrize(
    "df",
    [
        pd.DataFrame(),                                              # empty
        pd.DataFrame({"close": [1.0, 2.0]}),                         # no volume
        pd.DataFrame({"volume": [1, 2]}),                            # no close
        pd.DataFrame({"volume": [0, 0], "close": [10.0, 10.0]}),     # zero volume
        pd.DataFrame({"volume": [float("nan")], "close": [10.0]}),   # NaN
    ],
)
def test_avg_dollar_volume_returns_none_rather_than_zero(df):
    """An unavailable volume must be None, so the caller records an honest
    gap. A fabricated 0.0 would make sqrt(size/0) blow up or, worse, imply
    infinite market impact was actually measured."""
    assert ExecutionReadinessEngine._avg_dollar_volume(df) is None


def test_avg_dollar_volume_computes_when_available():
    df = pd.DataFrame({"volume": [100, 200], "close": [10.0, 10.0]})
    assert ExecutionReadinessEngine._avg_dollar_volume(df) == pytest.approx(1500.0)
