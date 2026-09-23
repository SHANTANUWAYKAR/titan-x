"""
Module: engine.py
Description: Engine 65 -- World Model. See MASTER_PROMPT.md's "PROMPT 5"
    section: a cross-engine causal-chain SYNTHESIS layer (Fed -> Liquidity
    -> Dollar -> Treasuries -> Stocks -> Gold -> Crypto), never a fourth
    reimplementation of what E04 Macro, E10 Cross-Asset, E19 Global
    Liquidity, and E64 Causal Intelligence already compute (Rule 4). Pure
    composition: reads each collaborator's own real output and assembles
    one coherent world-state snapshot, with each link's real confirmed/
    not-confirmed status from E64 attached so the "chain" is never
    presented as more certain than what was actually tested.

    Rule 3: no calibration script -- deterministic composition over four
    already-real engines' outputs, same "no" category as
    e32_capital_allocation/e44_chief_investment_officer.
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


@dataclass
class WorldViewReport:
    generated_at: datetime
    macro_risk_score: Optional[float]
    macro_regime: Optional[str]
    liquidity_regime: Optional[str]
    cross_asset_flags: list[str]
    causal_links_tested: list[dict]
    world_narrative: str
    data_gaps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "macro_risk_score": self.macro_risk_score, "macro_regime": self.macro_regime,
            "liquidity_regime": self.liquidity_regime, "cross_asset_flags": self.cross_asset_flags,
            "causal_links_tested": self.causal_links_tested, "world_narrative": self.world_narrative,
            "data_gaps": self.data_gaps,
        }


class WorldModelEngine(BaseEngine):
    """World Model Engine (#65) -- synthesizes E04/E10/E19/E64's own real
    outputs into one coherent global market-state narrative. Owns no
    analysis logic of its own."""

    engine_id = "e65_world_model"
    engine_name = "World Model Engine"
    version = "1.0.0"

    def __init__(
        self, macro_engine: Optional[Any] = None, cross_asset_engine: Optional[Any] = None,
        global_liquidity_engine: Optional[Any] = None, causal_engine: Optional[Any] = None,
    ) -> None:
        super().__init__()
        self._macro_engine = macro_engine
        self._cross_asset_engine = cross_asset_engine
        self._global_liquidity_engine = global_liquidity_engine
        self._causal_engine = causal_engine

    def initialize(self) -> EngineResult:
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="World Model Engine initialized")

    def health_check(self) -> EngineResult:
        return EngineResult(success=True, message="Healthy")

    def build_world_view(self) -> EngineResult:
        try:
            self._set_status(EngineStatus.RUNNING)
            gaps: list[str] = []

            macro_risk_score, macro_regime = None, None
            if self._macro_engine is not None:
                r = self._macro_engine.analyze()
                if r.success and r.data is not None:
                    macro_risk_score = r.data.risk_on_off_score
                    # MacroSnapshot's real field is regime_label, not regime --
                    # getattr(..., "regime", None) always missed it and silently
                    # fell through to a locally reimplemented (and inconsistent,
                    # different thresholds/casing) regime classification.
                    macro_regime = getattr(r.data, "regime_label", None)
                else:
                    gaps.append(f"macro: {r.message}")
            else:
                gaps.append("macro: no engine injected")

            liquidity_regime = None
            if self._global_liquidity_engine is not None:
                r = self._global_liquidity_engine.analyze()
                if r.success and r.data is not None:
                    # GlobalLiquiditySnapshot's real field is overall_regime, not
                    # regime -- this silently returned None every time.
                    liquidity_regime = getattr(r.data, "overall_regime", None)
                else:
                    gaps.append(f"liquidity: {r.message}")
            else:
                gaps.append("liquidity: no engine injected")

            cross_asset_flags: list[str] = []
            if self._cross_asset_engine is not None:
                r = self._cross_asset_engine.analyze()
                if r.success and r.data is not None:
                    # CrossAssetSnapshot has no "relationships"/"status" fields
                    # (real ones are "pairs"/"regime") -- getattr(...) always
                    # returned [] here, so no breakdown was ever surfaced. Reuse
                    # e10's own already-computed flagged_pairs (Rule 4) instead
                    # of re-deriving the breakdown classification.
                    regime_by_name = {p.name: p.regime for p in getattr(r.data, "pairs", [])}
                    for name in getattr(r.data, "flagged_pairs", []) or []:
                        cross_asset_flags.append(f"{name}: {regime_by_name.get(name, '?')}")
                else:
                    gaps.append(f"cross_asset: {r.message}")
            else:
                gaps.append("cross_asset: no engine injected")

            causal_links: list[dict] = []
            if self._causal_engine is not None:
                r = self._causal_engine.trace_causal_chain()
                if r.success and r.data is not None:
                    causal_links = [l.to_dict() for l in r.data.links]
                else:
                    gaps.append(f"causal: {r.message}")
            else:
                gaps.append("causal: no engine injected")

            narrative_parts = []
            if macro_regime:
                narrative_parts.append(f"Macro regime: {macro_regime} (score={macro_risk_score})")
            if liquidity_regime:
                narrative_parts.append(f"Liquidity regime: {liquidity_regime}")
            if cross_asset_flags:
                narrative_parts.append(f"Cross-asset flags: {'; '.join(cross_asset_flags)}")
            else:
                narrative_parts.append("Cross-asset relationships: no flagged breakdowns")
            confirmed = [l for l in causal_links if l.get("significant")]
            if confirmed:
                narrative_parts.append(f"Confirmed causal links right now: {'; '.join(l['hypothesis'] for l in confirmed)}")
            narrative = " | ".join(narrative_parts) if narrative_parts else "Insufficient real data to build a world view"

            report = WorldViewReport(
                generated_at=datetime.now(timezone.utc), macro_risk_score=macro_risk_score,
                macro_regime=macro_regime, liquidity_regime=liquidity_regime,
                cross_asset_flags=cross_asset_flags, causal_links_tested=causal_links,
                world_narrative=narrative, data_gaps=gaps,
            )
            self._set_status(EngineStatus.IDLE)
            return EngineResult(success=True, data=report, message=narrative)
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("build_world_view failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])
