"""
Module: engine.py
Description: Engine 47 -- Governance. Master prompt scope (line 473,
    draft item #20 "Governance System", kept for detail per Rule 1; also
    line 619's "Institutional Governance (Compliance Frameworks, Risk
    Committees, Investment Committees, Model Governance, Audit
    Frameworks)" -- slot #47 in the authoritative MAJOR ENGINES list is
    "Governance Engine"): "AI cannot remove stop losses, increase
    leverage beyond limits, modify live strategies, deploy untested
    models, or override risk limits without human approval."

    A real, mechanical compliance CHECKLIST over concrete, verifiable
    platform invariants -- never a policy engine that decides anything
    itself, and never a second veto authority (that stays E45's alone,
    per Rule 5). Each check below inspects REAL, live state:
      - no_execution_capability: verifies no registered engine exposes an
        order-placement method (`place_order`/`execute_trade`/`submit_order`)
        -- a live, mechanical guard against this platform's own Rule 5
        boundary ever being silently crossed by a future engine, not a
        one-time manual promise.
      - risk_limits_sane: the real settings thresholds E45 enforces
        (max_drawdown_pct, max_risk_per_trade_pct, min_risk_reward_ratio,
        max_daily_loss_pct) are configured to real, non-bypassing values
        -- catches a misconfiguration (e.g. a limit accidentally set to 0
        or None) that would silently defeat E45's own real checks.
      - model_provenance: delegates entirely to E39 Model Risk
        Management's own real audit() -- never a second, duplicate
        provenance check (Rule 4).
      - human_approval_required_for_execution: this platform has no
        execution engine at all (E48 is informational-only, E49 was
        explicitly not built -- see CLAUDE.md's own note on that
        decision), so this check is trivially, honestly satisfied by
        architecture rather than a runtime flag that could be flipped.

    Rule 3: no calibration script -- pure mechanical inspection of
    already-real engine/config state, same "no" category as
    e39_model_risk/e40_data_quality.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from project_titan_x.core.config import get_settings
from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus

logger = logging.getLogger(__name__)
settings = get_settings()

# Any engine exposing one of these method names would be a live-execution
# capability -- the exact boundary CLAUDE.md's Rule 5 draws ("No engine may
# execute a live trade... E48/E49 are unimplemented and that line should
# not be crossed casually").
_EXECUTION_METHOD_NAMES = ("place_order", "execute_trade", "submit_order", "send_order")


@dataclass
class GovernanceCheck:
    name: str
    status: str  # pass | fail
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "status": self.status, "detail": self.detail}


@dataclass
class GovernanceReport:
    generated_at: datetime
    checks: list[GovernanceCheck] = field(default_factory=list)
    overall_status: str = "compliant"  # compliant | violations_found

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "checks": [c.to_dict() for c in self.checks],
            "overall_status": self.overall_status,
        }


class GovernanceEngine(BaseEngine):
    """Governance Engine (#47) -- a real, mechanical compliance checklist
    over this platform's own no-execution/risk-limit/model-provenance
    invariants. Never a policy decision-maker and never a second veto
    authority (see this module's own docstring for why, and CLAUDE.md
    Rule 5)."""

    engine_id = "e47_governance"
    engine_name = "Governance Engine"
    version = "1.0.0"

    def __init__(self, registry: Optional[Any] = None, model_risk_engine: Optional[Any] = None) -> None:
        super().__init__()
        self._registry = registry
        self._model_risk_engine = model_risk_engine

    def initialize(self) -> EngineResult:
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Governance Engine initialized")

    def health_check(self) -> EngineResult:
        return EngineResult(success=True, message="Healthy")

    def audit_compliance(self) -> EngineResult:
        try:
            self._set_status(EngineStatus.RUNNING)
            checks = [
                self._check_no_execution_capability(),
                self._check_risk_limits_sane(),
                self._check_model_provenance(),
                self._check_human_approval_architecture(),
            ]
            overall = "compliant" if all(c.status == "pass" for c in checks) else "violations_found"
            report = GovernanceReport(generated_at=datetime.now(timezone.utc), checks=checks, overall_status=overall)
            self._set_status(EngineStatus.IDLE)
            n_fail = sum(1 for c in checks if c.status == "fail")
            return EngineResult(
                success=True, data=report,
                message=f"Governance audit: {overall} ({len(checks)} check(s), {n_fail} failure(s))",
            )
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("Governance audit failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def _check_no_execution_capability(self) -> GovernanceCheck:
        if self._registry is None:
            return GovernanceCheck("no_execution_capability", "fail", "No registry injected -- cannot verify")
        offenders = []
        for engine_id, engine in getattr(self._registry, "_engines", {}).items():
            for method_name in _EXECUTION_METHOD_NAMES:
                if hasattr(engine, method_name):
                    offenders.append(f"{engine_id}.{method_name}")
        if offenders:
            return GovernanceCheck("no_execution_capability", "fail", f"Execution-capable method(s) found: {offenders}")
        return GovernanceCheck("no_execution_capability", "pass", "No registered engine exposes an order-placement method")

    @staticmethod
    def _check_risk_limits_sane() -> GovernanceCheck:
        problems = []
        if not (0 < settings.max_drawdown_pct <= 100):
            problems.append(f"max_drawdown_pct={settings.max_drawdown_pct}")
        if not (0 < settings.max_risk_per_trade_pct <= 100):
            problems.append(f"max_risk_per_trade_pct={settings.max_risk_per_trade_pct}")
        if settings.min_risk_reward_ratio <= 0:
            problems.append(f"min_risk_reward_ratio={settings.min_risk_reward_ratio}")
        if not (0 < settings.max_daily_loss_pct <= 100):
            problems.append(f"max_daily_loss_pct={settings.max_daily_loss_pct}")
        if problems:
            return GovernanceCheck("risk_limits_sane", "fail", f"Non-sane risk limit(s): {problems}")
        return GovernanceCheck(
            "risk_limits_sane", "pass",
            f"max_drawdown_pct={settings.max_drawdown_pct}, max_risk_per_trade_pct={settings.max_risk_per_trade_pct}, "
            f"min_risk_reward_ratio={settings.min_risk_reward_ratio}, max_daily_loss_pct={settings.max_daily_loss_pct} "
            "-- all real, non-bypassing values",
        )

    def _check_model_provenance(self) -> GovernanceCheck:
        if self._model_risk_engine is None:
            return GovernanceCheck("model_provenance", "fail", "No model_risk_engine (E39) injected -- cannot verify")
        result = self._model_risk_engine.audit()
        if not result.success or result.data is None:
            return GovernanceCheck("model_provenance", "fail", f"E39 audit failed: {result.message}")
        if result.data.overall_verdict != "clean":
            return GovernanceCheck(
                "model_provenance", "fail",
                f"E39 flagged: {result.data.unverified_live_models} unverified live model(s), "
                f"{result.data.corrupt_files} corrupt file(s)",
            )
        return GovernanceCheck("model_provenance", "pass", "E39: every live-resolved model traces to real training provenance")

    @staticmethod
    def _check_human_approval_architecture() -> GovernanceCheck:
        return GovernanceCheck(
            "human_approval_required_for_execution", "pass",
            "No execution engine exists on this platform (E48 is informational-only, E49 was deliberately not "
            "built -- see CLAUDE.md) -- every recommendation requires human action to become a real trade, by "
            "architecture, not a runtime flag that could be silently flipped.",
        )
