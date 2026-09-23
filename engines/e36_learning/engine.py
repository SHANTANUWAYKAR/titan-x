"""
Module: engine.py
Description: Engine 36 -- Learning Engine. Master prompt scope (line
    456, draft item #14 "Learning Engine", kept for detail per Rule 1;
    slot #36 in the authoritative MAJOR ENGINES list is "Learning
    Engine"): "store entry/exit/PnL/screenshots/regime/volatility/news/
    strategy per trade. Generate lessons + improvement hypotheses;
    backtest them; never deploy automatically -- requires research,
    validation, forward testing, human approval."

    The "store per trade" half of this scope is ALREADY E35 Performance
    Analytics' job (the trade journal itself, `core.database.models.
    Trade`, entry/exit/PnL/regime/strategy/session columns) -- not
    reimplemented here (Rule 4). This engine's real, distinct
    contribution is the "generate lessons" half: it depends on E34 Trade
    Attribution's own `attribute_by_field` (already real, already
    computes per-group performance for strategy/regime/session/symbol/
    direction/day_of_week) and turns a statistically meaningful group
    deviation from the overall population into a plain-language "lesson"
    plus a named, testable hypothesis -- never a new grouping computation
    of its own.

    "Backtest them" and "never deploy automatically" are both taken
    literally: this engine has NO capability to change any shipped
    default itself. Every lesson carries a `suggested_validation_engine`
    pointing at whichever REAL engine already exists to test that class
    of hypothesis (E22 Alpha Research Factory for a condition-based
    hypothesis like "this regime helps", E24 Strategy Research/E26
    Backtesting/E27 Walk-Forward for a strategy/parameter hypothesis) --
    the same "propose, never auto-promote" boundary
    e24_strategy_research's own `promote_if_validated` flag already
    enforces for parameter changes, extended here to journal-derived
    lessons.

    Honest gap: "screenshots" (from the master prompt's own list) has no
    real implementation -- `Trade` has a `notes` text field but no image
    storage anywhere in this codebase, and fabricating one would be
    scope creep with no real backing. Documented here rather than
    silently ignored.

    Rule 3: no calibration script -- like E34/E38, this is a statistical
    comparison of another engine's already-real trade-journal output, no
    parameters of its own to fit. If the trade journal is empty (this
    platform has no execution engine, see CLAUDE.md Rule 5 -- every trade
    is a manually-logged, retrospective entry), this engine honestly
    reports `insufficient_data`, the same discipline E38/E42 already use,
    never a fabricated lesson.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus
from project_titan_x.engines.e34_trade_attribution.engine import ALLOWED_ATTRIBUTION_FIELDS, TradeAttributionEngine
from project_titan_x.engines.e35_performance_analytics.engine import PerformanceAnalyticsEngine

logger = logging.getLogger(__name__)

MIN_TRADES_PER_GROUP = 10  # below this, a group's own expectancy is too noisy to draw a lesson from
MIN_EXPECTANCY_GAP_R = 0.25  # a group must beat/trail the overall population by this much to be "notable"

# Which existing, real engine should validate each lesson dimension
# before any promotion -- never this engine itself (see module docstring's
# "never deploy automatically").
_VALIDATION_ENGINE_BY_FIELD = {
    "regime_at_entry": "e22_alpha_research (condition-based hypothesis: does this regime genuinely predict forward edge, Welch's t-test on real price history)",
    "strategy_name": "e24_strategy_research + e26_backtesting (parameter/archetype grid search against a real walk-forward bar)",
    "session_tag": "e22_alpha_research (condition-based hypothesis on session timing)",
    "symbol": "e27_walk_forward (per-asset fold-by-fold stability check)",
    "direction": "e30_adversarial_testing (check whether the directional skew survives parameter/trade-order perturbation)",
    "day_of_week": "e22_alpha_research (condition-based hypothesis on calendar timing)",
}


@dataclass
class Lesson:
    dimension: str
    group_key: str
    n_trades: int
    group_expectancy_r: float
    overall_expectancy_r: float
    direction: str  # "outperforms" | "underperforms"
    statement: str
    suggested_validation_engine: str
    auto_deployed: bool = False
    note: str = "Never deployed automatically -- requires research, validation, forward testing, and human approval."

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "group_key": self.group_key,
            "n_trades": self.n_trades,
            "group_expectancy_r": round(self.group_expectancy_r, 4),
            "overall_expectancy_r": round(self.overall_expectancy_r, 4),
            "direction": self.direction,
            "statement": self.statement,
            "suggested_validation_engine": self.suggested_validation_engine,
            "auto_deployed": self.auto_deployed,
            "note": self.note,
        }


@dataclass
class LearningReport:
    generated_at: datetime
    n_trades_analyzed: int
    overall_expectancy_r: Optional[float]
    lessons: list[Lesson] = field(default_factory=list)
    status: str = "insufficient_data"  # ok | insufficient_data

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "n_trades_analyzed": self.n_trades_analyzed,
            "overall_expectancy_r": round(self.overall_expectancy_r, 4) if self.overall_expectancy_r is not None else None,
            "lessons": [l.to_dict() for l in self.lessons],
            "status": self.status,
        }


class LearningEngine(BaseEngine):
    """Learning Engine (#36) -- turns E34 Trade Attribution's real
    per-group performance breakdown of the E35 trade journal into
    plain-language lessons and named, testable improvement hypotheses.
    Never deploys anything itself."""

    engine_id = "e36_learning"
    engine_name = "Learning Engine"
    version = "1.0.0"

    def __init__(
        self,
        trade_attribution_engine: Optional[TradeAttributionEngine] = None,
        performance_engine: Optional[PerformanceAnalyticsEngine] = None,
    ) -> None:
        super().__init__()
        self._performance_engine = performance_engine if performance_engine is not None else PerformanceAnalyticsEngine()
        self._trade_attribution_engine = (
            trade_attribution_engine if trade_attribution_engine is not None
            else TradeAttributionEngine(performance_engine=self._performance_engine)
        )

    def initialize(self) -> EngineResult:
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Learning Engine initialized")

    def health_check(self) -> EngineResult:
        return self._performance_engine.health_check()

    def generate_lessons(self, limit: int = 5000) -> EngineResult:
        try:
            self._set_status(EngineStatus.RUNNING)
            overall = self._performance_engine.summarize(limit=limit)
            if not overall.success:
                report = LearningReport(
                    generated_at=datetime.now(timezone.utc), n_trades_analyzed=0,
                    overall_expectancy_r=None, status="insufficient_data",
                )
                self._set_status(EngineStatus.IDLE)
                return EngineResult(success=True, data=report, message=f"No lessons: {overall.message}")

            overall_summary = overall.data
            lessons: list[Lesson] = []
            for dimension in sorted(ALLOWED_ATTRIBUTION_FIELDS):
                attr = self._trade_attribution_engine.attribute_by_field(dimension, limit=limit)
                if not attr.success:
                    continue
                for key, group_summary in attr.data["groups"].items():
                    if group_summary.n_trades < MIN_TRADES_PER_GROUP:
                        continue
                    gap = group_summary.expectancy_r - overall_summary.expectancy_r
                    if abs(gap) < MIN_EXPECTANCY_GAP_R:
                        continue
                    outperforms = gap > 0
                    lessons.append(Lesson(
                        dimension=dimension, group_key=str(key), n_trades=group_summary.n_trades,
                        group_expectancy_r=group_summary.expectancy_r, overall_expectancy_r=overall_summary.expectancy_r,
                        direction="outperforms" if outperforms else "underperforms",
                        statement=(
                            f"Trades where {dimension}={key} {'outperform' if outperforms else 'underperform'} "
                            f"the overall population ({group_summary.expectancy_r:+.2f}R vs "
                            f"{overall_summary.expectancy_r:+.2f}R expectancy, n={group_summary.n_trades})."
                        ),
                        suggested_validation_engine=_VALIDATION_ENGINE_BY_FIELD.get(dimension, "e24_strategy_research"),
                    ))

            lessons.sort(key=lambda l: abs(l.group_expectancy_r - l.overall_expectancy_r), reverse=True)
            report = LearningReport(
                generated_at=datetime.now(timezone.utc), n_trades_analyzed=overall_summary.n_trades,
                overall_expectancy_r=overall_summary.expectancy_r, lessons=lessons, status="ok",
            )
            self._set_status(EngineStatus.IDLE)
            return EngineResult(
                success=True, data=report,
                message=f"Generated {len(lessons)} lesson(s) from {overall_summary.n_trades} logged trade(s)",
            )
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("Lesson generation failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])
