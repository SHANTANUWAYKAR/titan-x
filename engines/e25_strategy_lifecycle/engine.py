"""
Module: engine.py
Description: Engine 25 -- Strategy Lifecycle. Master prompt scope: slot
    #25 in the authoritative MAJOR ENGINES list is "Strategy Lifecycle
    Engine" with NO further detail section anywhere else in the document
    (confirmed via a full word-for-word read per Rule 1 -- unlike
    E29/E30/E32/E36/E37/E39, which each have a draft-numbered detail
    paragraph elsewhere in the file, E25 has only its one-line master-list
    name). Per Rule 1's "say so explicitly" instruction for exactly this
    situation, this engine's scope is an honest, standard-quant-industry
    interpretation of "strategy lifecycle" -- researched -> validated ->
    live -> decaying/retired -- built entirely from real states FOUR
    already-real engines already compute, never a new concept invented
    from nothing:
      - "researched": a real E24 Strategy Research report file exists
        for this symbol+timeframe (`data/models/e24_strategy_research/
        {symbol}_{timeframe}_report.json`).
      - "live": e51_signals actually resolves a structural override or
        tuned-params file for this symbol+timeframe right now (same
        filename convention/precedence `_load_strategy_override`/
        `_load_tuned_params` themselves use, reused directly).
      - "validated" (a sub-check of "live"): that live file carries the
        same real governance fields E39 Model Risk Management already
        requires (`validated_at`/`trained_at`, `oos_sharpe`,
        `total_trades`) -- proof it actually cleared a real walk-forward
        bar at promotion time, not re-run here a second time (Rule 4;
        E27 Walk-Forward already owns that expensive computation).
      - "decaying": E38 Alpha Decay Monitor's own real verdict against
        the live E35 trade journal for this strategy, when the journal
        has enough data to say so -- never re-implemented here.

    "retired" (added 2026-09-13, docs/UPGRADE_ROADMAP.md P2 item 10):
    closed exactly the way this docstring originally said it should be --
    a real `retired_at` field, written into the override/tuned-params
    file itself, that e51_signals._load_strategy_override and
    e45_risk._load_min_confidence_override BOTH now check and refuse to
    treat as live (checked before, and regardless of, stage0 status --
    retirement is terminal). This engine reads that same field rather
    than inventing separate bookkeeping, exactly as originally planned.

    Rule 3: no calibration script -- pure mechanical state derivation
    from four other engines' already-real outputs, same "no" category as
    e33_opportunity_ranking/e39_model_risk.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus

logger = logging.getLogger(__name__)

_E24_REPORT_DIR = Path(__file__).resolve().parents[2] / "data" / "models" / "e24_strategy_research"
_E51_MODELS_DIR = Path(__file__).resolve().parents[2] / "data" / "models" / "e51_signals"

_OVERRIDE_REQUIRED_FIELDS = ("strategy", "params", "validated_at", "oos_sharpe", "total_trades")
_TUNED_PARAMS_REQUIRED_FIELDS = ("trained_at", "oos_sharpe", "total_trades")

# Ordered so a caller can compare stages ("is X further along than Y")
LIFECYCLE_STAGES = (
    "not_researched",
    "researched_not_promoted",
    "live_unverified_provenance",
    "live_validated",
    "decaying",
    "retired",
)


@dataclass
class StrategyLifecycleStatus:
    symbol: str
    timeframe: str
    researched: bool
    research_report_path: Optional[str]
    live_model_kind: str  # "strategy_override" | "tuned_params" | "none"
    live_model_path: Optional[str]
    provenance_verified: Optional[bool]
    missing_provenance_fields: list[str]
    decay_verdict: Optional[str]  # E38's own verdict string, or None if not checked/insufficient data
    lifecycle_stage: str
    retired_at: Optional[str] = None  # the override/tuned-params file's own retired_at, if present

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "researched": self.researched,
            "research_report_path": self.research_report_path,
            "live_model_kind": self.live_model_kind,
            "live_model_path": self.live_model_path,
            "provenance_verified": self.provenance_verified,
            "missing_provenance_fields": self.missing_provenance_fields,
            "decay_verdict": self.decay_verdict,
            "lifecycle_stage": self.lifecycle_stage,
            "retired_at": self.retired_at,
        }


@dataclass
class StrategyLifecycleReport:
    generated_at: datetime
    statuses: list[StrategyLifecycleStatus] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "statuses": [s.to_dict() for s in self.statuses],
        }


class StrategyLifecycleEngine(BaseEngine):
    """Strategy Lifecycle Engine (#25) -- researched -> validated -> live
    -> decaying, derived entirely from E24/e51_signals' own files and
    E38's own real decay verdict. See this module's docstring for the
    honest "retired" gap (no real mechanism exists anywhere yet)."""

    engine_id = "e25_strategy_lifecycle"
    engine_name = "Strategy Lifecycle Engine"
    version = "1.0.0"

    def __init__(self, alpha_decay_monitor_engine: Optional[Any] = None) -> None:
        super().__init__()
        self._alpha_decay_monitor_engine = alpha_decay_monitor_engine

    def initialize(self) -> EngineResult:
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Strategy Lifecycle Engine initialized")

    def health_check(self) -> EngineResult:
        return EngineResult(success=True, message="Healthy")

    def status_for(self, symbol: str, yahoo_symbol: str, timeframe: str = "1d") -> StrategyLifecycleStatus:
        report_path = _E24_REPORT_DIR / f"{symbol}_{timeframe}_report.json"
        researched = report_path.exists()

        override_path = _E51_MODELS_DIR / f"{yahoo_symbol}_{timeframe}_strategy_override.json"
        tuned_path = _E51_MODELS_DIR / f"{yahoo_symbol}_{timeframe}_tuned_params.json"

        live_kind, live_path, missing = "none", None, []
        provenance_verified: Optional[bool] = None
        strategy_name_for_decay = None
        retired_at: Optional[str] = None
        if override_path.exists():
            live_kind, live_path = "strategy_override", override_path.name
            missing, data = self._missing_fields(override_path, _OVERRIDE_REQUIRED_FIELDS)
            provenance_verified = not missing
            strategy_name_for_decay = data.get("strategy") if data else None
            retired_at = data.get("retired_at") if data else None
        elif tuned_path.exists():
            live_kind, live_path = "tuned_params", tuned_path.name
            missing, data = self._missing_fields(tuned_path, _TUNED_PARAMS_REQUIRED_FIELDS)
            provenance_verified = not missing
            retired_at = data.get("retired_at") if data else None

        decay_verdict = None
        if provenance_verified and not retired_at and self._alpha_decay_monitor_engine is not None:
            try:
                decay_result = self._alpha_decay_monitor_engine.assess_decay(strategy_name=strategy_name_for_decay)
                if decay_result.success and decay_result.data is not None:
                    decay_verdict = getattr(decay_result.data, "status", None)
            except Exception as e:
                logger.warning("Decay check unavailable for %s: %s", symbol, e)

        stage = self._determine_stage(researched, live_kind, provenance_verified, decay_verdict, retired_at)
        return StrategyLifecycleStatus(
            symbol=symbol, timeframe=timeframe, researched=researched,
            research_report_path=report_path.name if researched else None,
            live_model_kind=live_kind, live_model_path=live_path,
            provenance_verified=provenance_verified, missing_provenance_fields=missing,
            decay_verdict=decay_verdict, lifecycle_stage=stage, retired_at=retired_at,
        )

    def audit(self, symbols: Optional[list[tuple[str, str]]] = None, timeframe: str = "1d") -> EngineResult:
        """symbols: list of (symbol, yahoo_symbol) pairs. None (default)
        uses every real supported asset via core.config.list_assets."""
        try:
            self._set_status(EngineStatus.RUNNING)
            if symbols is None:
                from project_titan_x.core.config import list_assets
                symbols = [(a.symbol, a.yahoo_symbol) for a in list_assets()]

            statuses = [self.status_for(sym, yahoo_sym, timeframe) for sym, yahoo_sym in symbols]
            report = StrategyLifecycleReport(generated_at=datetime.now(timezone.utc), statuses=statuses)
            self._set_status(EngineStatus.IDLE)
            stage_counts: dict[str, int] = {}
            for s in statuses:
                stage_counts[s.lifecycle_stage] = stage_counts.get(s.lifecycle_stage, 0) + 1
            return EngineResult(
                success=True, data=report,
                message=f"Lifecycle audit across {len(statuses)} symbol(s): {stage_counts}",
            )
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("Strategy lifecycle audit failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    @staticmethod
    def _missing_fields(path: Path, required: tuple[str, ...]) -> tuple[list[str], Optional[dict]]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            return [f"unreadable: {e}"], None
        return [f for f in required if f not in data], data

    @staticmethod
    def _determine_stage(
        researched: bool, live_kind: str, provenance_verified: Optional[bool], decay_verdict: Optional[str],
        retired_at: Optional[str] = None,
    ) -> str:
        if live_kind == "none":
            return "researched_not_promoted" if researched else "not_researched"
        if retired_at:
            return "retired"
        if not provenance_verified:
            return "live_unverified_provenance"
        if decay_verdict == "decay_detected":
            return "decaying"
        return "live_validated"
