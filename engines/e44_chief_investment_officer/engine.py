"""
Module: engine.py
Description: Engine 44 -- Chief Investment Officer. Master prompt scope:
    slot #44 in the authoritative MAJOR ENGINES list is "Chief Investment
    Officer Engine." Distinct from E43 Investment Committee's own
    internal "Chief Investment Officer" AGENT VOTE (one weighted vote
    among ten, scoped to a SINGLE signal's up/down decision, see
    e43_committee.CommitteeEngine.AGENT_WEIGHTS) -- E44 operates one
    level up, across the WHOLE opportunity set at once, the same
    portfolio-level altitude E32/E33 already operate at, never
    re-deciding any single signal's own direction/confidence (that stays
    E51's job, reviewed per-signal by E43, never touched here).

    Composes two already-real engines, never reimplementing either:
      - E33 Opportunity Ranking: the real, per-asset conviction read
        across every supported asset in one shared-input pass --
        "what's out there right now."
      - E32 Capital Allocation (optional, only when a total_capital is
        given): the real, CRO-gated capital deployment plan -- "what
        would we actually DO about it." Skipped honestly (not
        fabricated) when no capital figure is supplied.

    The "CIO verdict" narrative is built entirely from these two engines'
    own already-computed numbers (net long/short tilt among TRADEABLE
    opportunities, average confidence, top conviction ideas) -- no LLM
    anywhere in this platform (see e01_knowledge's own "answer() is
    extractive, not LLM-generated" precedent), so this is a templated
    synthesis of real numbers, never a generated opinion.

    Rule 3: no calibration script -- deterministic composition/
    aggregation over two already-real, already-calibrated engines' own
    outputs, same "no" category as e31_portfolio_construction/
    e32_capital_allocation/e33_opportunity_ranking.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus

logger = logging.getLogger(__name__)

# A tilt needs at least this many tradeable opportunities to be reported
# as a real stance rather than noise from 1-2 signals.
MIN_TRADEABLE_FOR_STANCE = 3


@dataclass
class ConvictionIdea:
    symbol: str
    direction: str
    confidence: int
    regime: Optional[str]

    def to_dict(self) -> dict[str, Any]:
        return {"symbol": self.symbol, "direction": self.direction, "confidence": self.confidence, "regime": self.regime}


@dataclass
class CIOVerdict:
    generated_at: datetime
    timeframe: str
    n_assets_scanned: int
    n_tradeable: int
    n_long: int
    n_short: int
    avg_confidence_tradeable: Optional[float]
    overall_stance: str  # net_long | net_short | mixed | insufficient_data
    top_conviction_ideas: list[ConvictionIdea] = field(default_factory=list)
    capital_plan: Optional[dict] = None  # E32's own CapitalAllocationReport.to_dict(), when requested
    narrative: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "timeframe": self.timeframe,
            "n_assets_scanned": self.n_assets_scanned,
            "n_tradeable": self.n_tradeable,
            "n_long": self.n_long,
            "n_short": self.n_short,
            "avg_confidence_tradeable": round(self.avg_confidence_tradeable, 1) if self.avg_confidence_tradeable is not None else None,
            "overall_stance": self.overall_stance,
            "top_conviction_ideas": [i.to_dict() for i in self.top_conviction_ideas],
            "capital_plan": self.capital_plan,
            "narrative": self.narrative,
        }


class ChiefInvestmentOfficerEngine(BaseEngine):
    """Chief Investment Officer Engine (#44) -- portfolio-level synthesis
    across every real opportunity E33 finds, optionally paired with E32's
    real capital deployment plan. Takes the registry itself (same pattern
    as e32_capital_allocation/e33_opportunity_ranking), since its whole
    job is orchestrating across them, not owning analysis logic itself."""

    engine_id = "e44_chief_investment_officer"
    engine_name = "Chief Investment Officer Engine"
    version = "1.0.0"

    def __init__(self, registry: Optional[Any] = None) -> None:
        super().__init__()
        self._registry = registry

    def initialize(self) -> EngineResult:
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Chief Investment Officer Engine initialized")

    def health_check(self) -> EngineResult:
        if self._registry is None:
            return EngineResult(success=False, message="No registry injected")
        return EngineResult(success=True, message="Healthy")

    def assess_portfolio_stance(
        self, timeframe: str = "1d", total_capital: Optional[float] = None, max_positions: int = 5,
        symbols: Optional[list[str]] = None,
    ) -> EngineResult:
        if self._registry is None:
            return EngineResult(success=False, message="No registry injected -- cannot orchestrate E33/E32")
        try:
            self._set_status(EngineStatus.RUNNING)
            opportunity_ranking_engine = self._registry.get("e33_opportunity_ranking")
            if opportunity_ranking_engine is None:
                return EngineResult(success=False, message="e33_opportunity_ranking not registered")
            rank_result = opportunity_ranking_engine.rank_opportunities(timeframe=timeframe, symbols=symbols)
            if not rank_result.success:
                return EngineResult(success=False, message=f"Opportunity ranking failed: {rank_result.message}")
            rankings = rank_result.data

            tradeable = [r for r in rankings if r.tradeable]
            n_long = sum(1 for r in tradeable if r.direction == "LONG")
            n_short = sum(1 for r in tradeable if r.direction == "SHORT")
            avg_confidence = sum(r.confidence for r in tradeable) / len(tradeable) if tradeable else None

            if len(tradeable) < MIN_TRADEABLE_FOR_STANCE:
                stance = "insufficient_data"
            elif n_long > 0 and n_short == 0:
                stance = "net_long"
            elif n_short > 0 and n_long == 0:
                stance = "net_short"
            elif n_long >= 2 * max(n_short, 1):
                stance = "net_long"
            elif n_short >= 2 * max(n_long, 1):
                stance = "net_short"
            else:
                stance = "mixed"

            top_ideas = [
                ConvictionIdea(r.symbol, r.direction, r.confidence, r.regime)
                for r in sorted(tradeable, key=lambda r: r.confidence, reverse=True)[:5]
            ]

            capital_plan = None
            if total_capital is not None and total_capital > 0:
                capital_allocation_engine = self._registry.get("e32_capital_allocation")
                if capital_allocation_engine is not None:
                    alloc_result = capital_allocation_engine.allocate(
                        total_capital=total_capital, timeframe=timeframe, max_positions=max_positions, symbols=symbols,
                    )
                    if alloc_result.success:
                        capital_plan = alloc_result.data.to_dict()

            narrative = self._build_narrative(len(rankings), len(tradeable), n_long, n_short, avg_confidence, stance, top_ideas, capital_plan)

            verdict = CIOVerdict(
                generated_at=datetime.now(timezone.utc), timeframe=timeframe, n_assets_scanned=len(rankings),
                n_tradeable=len(tradeable), n_long=n_long, n_short=n_short, avg_confidence_tradeable=avg_confidence,
                overall_stance=stance, top_conviction_ideas=top_ideas, capital_plan=capital_plan, narrative=narrative,
            )
            self._set_status(EngineStatus.IDLE)
            return EngineResult(success=True, data=verdict, message=narrative)
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("CIO portfolio stance assessment failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    @staticmethod
    def _build_narrative(
        n_scanned: int, n_tradeable: int, n_long: int, n_short: int,
        avg_confidence: Optional[float], stance: str, top_ideas: list[ConvictionIdea], capital_plan: Optional[dict],
    ) -> str:
        if stance == "insufficient_data":
            return (
                f"Scanned {n_scanned} asset(s), only {n_tradeable} cleared the tradeable bar -- "
                "too few for a real portfolio-level stance right now, not fabricating one."
            )
        parts = [
            f"Scanned {n_scanned} asset(s): {n_tradeable} tradeable ({n_long} LONG, {n_short} SHORT, "
            f"avg confidence {avg_confidence:.0f}%)." if avg_confidence is not None else f"Scanned {n_scanned} asset(s): {n_tradeable} tradeable.",
            f"Overall stance: {stance.replace('_', ' ')}.",
        ]
        if top_ideas:
            ideas_str = ", ".join(f"{i.symbol} {i.direction} ({i.confidence}%)" for i in top_ideas)
            parts.append(f"Top conviction: {ideas_str}.")
        if capital_plan is not None:
            parts.append(
                f"Capital plan: {capital_plan['total_allocated']:.2f} of {capital_plan['total_capital']:.2f} "
                f"allocated across {len(capital_plan['allocations'])} position(s)."
            )
        return " ".join(parts)
