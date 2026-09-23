"""
Module: engine.py
Description: Engine 46 -- Chief Risk Officer. Master prompt scope (line
    526, draft item #40 "Chief Risk Officer (CRO) Layer", kept for detail
    per Rule 1; slot #46 in the authoritative MAJOR ENGINES list is
    "Chief Risk Officer Engine"): "highest authority... CRO can veto any
    trade."

    Genuine numbering overlap with E45, flagged explicitly per Rule 1
    rather than silently resolved: E45 (Risk Management Engine) is ALREADY
    documented and built as "(CRO)" throughout this codebase, WITH
    absolute per-trade veto authority (see CLAUDE.md Rule 5). Building a
    second engine with its own separate veto would either duplicate E45
    or, worse, create two competing sources of veto truth -- exactly the
    failure mode Rule 5 exists to prevent ("nothing may influence
    E45's verdict").

    Resolution: E46 operates one altitude ABOVE E45's per-trade gate --
    the same "zoom out from one decision to the whole portfolio" relationship
    E44 Chief Investment Officer has to E43 Investment Committee's own
    per-signal CIO vote. E46 is READ-ONLY oversight: it reads E45's real,
    already-tracked PortfolioRiskState (via the new e45_risk.
    get_portfolio_state() getter) and classifies it against the EXACT SAME
    real thresholds E45 itself already vetoes individual trades against
    (settings.max_portfolio_heat_pct/max_risk_of_ruin_pct/
    max_correlation_exposure/max_drawdown_pct -- never a second, invented
    threshold), producing a portfolio-wide risk posture. It NEVER writes
    back into E45's state and NEVER gets its own veto -- verified by
    inspection: this module has no code path that calls
    update_portfolio_state or evaluate_trade, only get_portfolio_state
    (read-only) and E28's own real stress-test method (also read-only).

    Rule 3: no calibration script -- deterministic threshold comparison
    against E45's own already-real, already-configured limits, same "no"
    category as e44/e32/e33.
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

# "elevated" (not yet breached) starts at this fraction of the real hard
# limit -- an early-warning band, not a second hard threshold.
_ELEVATED_FRACTION = 0.75


@dataclass
class RiskDimension:
    name: str
    current: float
    limit: float
    status: str  # ok | elevated | breached

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "current": round(self.current, 3), "limit": self.limit, "status": self.status}


@dataclass
class StressExposure:
    symbol: str
    worst_case_dd_pct: Optional[float]
    verdict: str  # resilient | breached_risk_limit | insufficient_data

    def to_dict(self) -> dict[str, Any]:
        return {"symbol": self.symbol, "worst_case_dd_pct": self.worst_case_dd_pct, "verdict": self.verdict}


@dataclass
class CROVerdict:
    generated_at: datetime
    dimensions: list[RiskDimension] = field(default_factory=list)
    stress_exposures: list[StressExposure] = field(default_factory=list)
    risk_posture: str = "normal"  # low | normal | elevated | critical
    narrative: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "dimensions": [d.to_dict() for d in self.dimensions],
            "stress_exposures": [s.to_dict() for s in self.stress_exposures],
            "risk_posture": self.risk_posture,
            "narrative": self.narrative,
        }


class ChiefRiskOfficerEngine(BaseEngine):
    """Chief Risk Officer Engine (#46) -- read-only, portfolio-wide risk
    oversight above E45's own per-trade veto authority. See this
    module's own docstring for why this never duplicates or influences
    E45's real veto (Rule 5)."""

    engine_id = "e46_chief_risk_officer"
    engine_name = "Chief Risk Officer Engine"
    version = "1.0.0"

    def __init__(self, risk_engine: Optional[Any] = None, stress_testing_engine: Optional[Any] = None) -> None:
        super().__init__()
        self._risk_engine = risk_engine
        self._stress_testing_engine = stress_testing_engine

    def initialize(self) -> EngineResult:
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Chief Risk Officer Engine initialized")

    def health_check(self) -> EngineResult:
        if self._risk_engine is None:
            return EngineResult(success=False, message="No risk_engine injected")
        return EngineResult(success=True, message="Healthy")

    def assess_risk_posture(self, symbols: Optional[list[str]] = None, timeframe: str = "1d") -> EngineResult:
        if self._risk_engine is None:
            return EngineResult(success=False, message="No risk_engine injected -- cannot read E45's real portfolio state")
        try:
            self._set_status(EngineStatus.RUNNING)
            state = self._risk_engine.get_portfolio_state()

            dimensions = [
                self._classify("portfolio_heat_pct", state.portfolio_heat_pct, settings.max_portfolio_heat_pct),
                self._classify("risk_of_ruin_pct", state.risk_of_ruin_pct, settings.max_risk_of_ruin_pct),
                self._classify("correlation_max", state.correlation_max, settings.max_correlation_exposure),
                self._classify("current_drawdown_pct", state.current_drawdown_pct, settings.max_drawdown_pct),
            ]

            stress_exposures: list[StressExposure] = []
            if symbols and self._stress_testing_engine is not None:
                for symbol in symbols:
                    result = self._stress_testing_engine.run_stress_test(symbol, timeframe)
                    if result.success and result.data is not None:
                        stress_exposures.append(StressExposure(symbol, result.data.worst_case_dd_pct, result.data.overall_verdict))
                    else:
                        stress_exposures.append(StressExposure(symbol, None, "insufficient_data"))

            n_breached = sum(1 for d in dimensions if d.status == "breached")
            n_elevated = sum(1 for d in dimensions if d.status == "elevated")
            n_stress_breached = sum(1 for s in stress_exposures if s.verdict == "breached_risk_limit")
            if n_breached > 0 or n_stress_breached > 0:
                posture = "critical" if n_breached > 1 else "elevated"
            elif n_elevated > 0:
                posture = "elevated"
            else:
                posture = "normal" if state.open_positions > 0 else "low"

            narrative = self._build_narrative(dimensions, stress_exposures, posture, state.open_positions)
            verdict = CROVerdict(
                generated_at=datetime.now(timezone.utc), dimensions=dimensions,
                stress_exposures=stress_exposures, risk_posture=posture, narrative=narrative,
            )
            self._set_status(EngineStatus.IDLE)
            return EngineResult(success=True, data=verdict, message=narrative)
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("CRO risk posture assessment failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    @staticmethod
    def _classify(name: str, current: float, limit: float) -> RiskDimension:
        if limit <= 0:
            return RiskDimension(name, current, limit, "ok")
        ratio = current / limit
        if ratio >= 1.0:
            status = "breached"
        elif ratio >= _ELEVATED_FRACTION:
            status = "elevated"
        else:
            status = "ok"
        return RiskDimension(name, current, limit, status)

    @staticmethod
    def _build_narrative(
        dimensions: list[RiskDimension], stress_exposures: list[StressExposure], posture: str, open_positions: int,
    ) -> str:
        flagged = [d for d in dimensions if d.status != "ok"]
        parts = [f"Portfolio risk posture: {posture} ({open_positions} open position(s))."]
        if flagged:
            flags_str = ", ".join(f"{d.name}={d.current:.2f} ({d.status}, limit={d.limit})" for d in flagged)
            parts.append(f"Flagged dimensions: {flags_str}.")
        else:
            parts.append("All tracked risk dimensions within normal range.")
        breached_stress = [s for s in stress_exposures if s.verdict == "breached_risk_limit"]
        if breached_stress:
            parts.append(f"{len(breached_stress)} of {len(stress_exposures)} scanned position(s) would breach the CRO drawdown limit in a historical crisis replay.")
        return " ".join(parts)
