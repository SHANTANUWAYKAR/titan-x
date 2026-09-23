"""
Module: engine.py
Description: Engine 39 -- Model Risk Management. Master prompt scope
    (line 513, draft item #33 "Model Risk Management", kept for detail
    per Rule 1; slot #39 in the authoritative MAJOR ENGINES list is
    "Model Risk Management Engine"): "track model versions, training
    data, backtest versions, deployment history; prevent an unknown model
    from making live decisions."

    Two real, mechanical jobs, both operating on files this platform's
    OWN training scripts already write to `data/models/` -- never a new
    persisted database of its own, never a fabricated "model version"
    concept:

    1. Inventory: walk `data/models/` recursively, hash every real file
       (sha256), record size/age, and flag any JSON file that fails to
       parse (`corrupt`) -- pure mechanical scan, same "no interpretive
       read" category as e40_data_quality.
    2. Live-decision provenance check: for every REAL supported asset
       (`core.config.list_assets`), resolve the EXACT files
       e51_signals._load_strategy_override/_load_tuned_params would read
       for it (same filename convention those two functions already use,
       reused directly rather than reverse-engineered) and verify each
       one carries the governance fields its own training script always
       writes (`validated_at`/`trained_at`, `oos_sharpe`, `total_trades`,
       plus `strategy`+`params` for an override). A file missing these
       fields did not come from this platform's real train/validate
       pipeline -- exactly the master prompt's "prevent an UNKNOWN model
       from making live decisions" scope, made concrete: not "is this
       model good" (E27/E30 already answer that), but "did this file
       actually go through the pipeline at all."

    Rule 3: no calibration script -- pure mechanical file inventory/
    provenance check, same "no" category as e34_trade_attribution/
    e40_data_quality (deterministic, no parameters to fit).
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from project_titan_x.core.config import list_assets
from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus

logger = logging.getLogger(__name__)

_DATA_MODELS_DIR = Path(__file__).resolve().parents[2] / "data" / "models"
_SIGNALS_MODELS_DIR = _DATA_MODELS_DIR / "e51_signals"

# Governance fields each file type's OWN real training script always
# writes (verified directly against real, already-shipped files --
# BTC-USD_1d_strategy_override.json / BTC-USD_1d_tuned_params.json --
# not guessed).
_OVERRIDE_REQUIRED_FIELDS = ("strategy", "params", "validated_at", "oos_sharpe", "total_trades")
_TUNED_PARAMS_REQUIRED_FIELDS = ("trained_at", "oos_sharpe", "total_trades")

STALE_AFTER_DAYS = 180  # standard quant-ops convention: a model unrefreshed for 6mo needs a governance review


@dataclass
class TrackedModelFile:
    relative_path: str
    engine_dir: str
    sha256: str
    size_bytes: int
    age_days: float
    status: str  # "ok" | "corrupt" | "unreadable"
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "engine_dir": self.engine_dir,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "age_days": round(self.age_days, 1),
            "status": self.status,
            "note": self.note,
        }


@dataclass
class LiveModelProvenance:
    symbol: str
    timeframe: str
    model_kind: str  # "strategy_override" | "tuned_params" | "baseline_composite_rule"
    file_path: Optional[str]
    provenance: str  # "verified" | "unverified" | "not_applicable" | "missing_required_fields"
    missing_fields: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "model_kind": self.model_kind,
            "file_path": self.file_path,
            "provenance": self.provenance,
            "missing_fields": self.missing_fields,
        }


@dataclass
class ModelRiskReport:
    generated_at: datetime
    tracked_files: list[TrackedModelFile] = field(default_factory=list)
    live_provenance: list[LiveModelProvenance] = field(default_factory=list)
    corrupt_files: list[str] = field(default_factory=list)
    unverified_live_models: list[str] = field(default_factory=list)  # symbols with an unknown/unverified model live
    stale_files: list[str] = field(default_factory=list)
    overall_verdict: str = "clean"  # clean | unverified_models_live | corrupt_files_present

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "n_tracked_files": len(self.tracked_files),
            "tracked_files": [f.to_dict() for f in self.tracked_files],
            "live_provenance": [p.to_dict() for p in self.live_provenance],
            "corrupt_files": self.corrupt_files,
            "unverified_live_models": self.unverified_live_models,
            "stale_files": self.stale_files,
            "overall_verdict": self.overall_verdict,
        }


class ModelRiskManagementEngine(BaseEngine):
    """Model Risk Management Engine (#39) -- inventories every real file
    under data/models/ and verifies every asset's LIVE-resolved
    e51_signals model actually carries this platform's own real training
    provenance, so an unknown/hand-dropped file can never silently
    influence a live decision."""

    engine_id = "e39_model_risk"
    engine_name = "Model Risk Management Engine"
    version = "1.0.0"

    def __init__(self, timeframe: str = "1d") -> None:
        super().__init__()
        self._timeframe = timeframe

    def initialize(self) -> EngineResult:
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Model Risk Management Engine initialized")

    def health_check(self) -> EngineResult:
        return EngineResult(success=True, message="Healthy")

    def check_symbol(self, symbol: str, yahoo_symbol: str, timeframe: str = "1d") -> LiveModelProvenance:
        """Cheap, single-symbol provenance check (at most two small file
        reads) -- deliberately NOT the full audit() directory scan, so a
        caller on the live signal-generation hot path (e51_signals, one
        call per symbol per scan) never pays the cost of hashing every
        file under data/models/ just to answer "is THIS asset's live
        model verified." Same underlying check audit() itself uses,
        never a second implementation."""
        return self._check_live_provenance(symbol, yahoo_symbol, timeframe)

    def audit(self) -> EngineResult:
        try:
            self._set_status(EngineStatus.RUNNING)
            now = datetime.now(timezone.utc)

            tracked_files: list[TrackedModelFile] = []
            corrupt_files: list[str] = []
            stale_files: list[str] = []
            if _DATA_MODELS_DIR.exists():
                for path in sorted(_DATA_MODELS_DIR.rglob("*")):
                    if not path.is_file():
                        continue
                    rel = str(path.relative_to(_DATA_MODELS_DIR)).replace("\\", "/")
                    engine_dir = rel.split("/")[0] if "/" in rel else "(root)"
                    try:
                        raw = path.read_bytes()
                    except Exception as e:
                        tracked_files.append(TrackedModelFile(rel, engine_dir, "", 0, 0.0, "unreadable", note=str(e)))
                        continue
                    sha256 = hashlib.sha256(raw).hexdigest()
                    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                    age_days = (now - mtime).total_seconds() / 86400.0
                    status, note = "ok", ""
                    if path.suffix == ".json":
                        try:
                            json.loads(raw.decode("utf-8"))
                        except Exception as e:
                            status, note = "corrupt", f"Invalid JSON: {e}"
                            corrupt_files.append(rel)
                    if age_days > STALE_AFTER_DAYS:
                        stale_files.append(rel)
                    tracked_files.append(TrackedModelFile(rel, engine_dir, sha256, len(raw), age_days, status, note=note))

            live_provenance: list[LiveModelProvenance] = []
            unverified_live_models: list[str] = []
            for asset in list_assets():
                entry = self._check_live_provenance(asset.symbol, asset.yahoo_symbol, self._timeframe)
                live_provenance.append(entry)
                if entry.provenance in ("unverified", "missing_required_fields"):
                    unverified_live_models.append(asset.symbol)

            overall = "clean"
            if corrupt_files:
                overall = "corrupt_files_present"
            elif unverified_live_models:
                overall = "unverified_models_live"

            report = ModelRiskReport(
                generated_at=now, tracked_files=tracked_files, live_provenance=live_provenance,
                corrupt_files=corrupt_files, unverified_live_models=unverified_live_models,
                stale_files=stale_files, overall_verdict=overall,
            )
            self._set_status(EngineStatus.IDLE)
            return EngineResult(
                success=True, data=report,
                message=(
                    f"Model risk audit: {len(tracked_files)} files tracked, "
                    f"overall_verdict={overall} "
                    f"({len(unverified_live_models)} unverified live model(s), {len(corrupt_files)} corrupt file(s))"
                ),
            )
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("Model risk audit failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    @staticmethod
    def _check_live_provenance(symbol: str, yahoo_symbol: str, timeframe: str) -> LiveModelProvenance:
        override_path = _SIGNALS_MODELS_DIR / f"{yahoo_symbol}_{timeframe}_strategy_override.json"
        tuned_path = _SIGNALS_MODELS_DIR / f"{yahoo_symbol}_{timeframe}_tuned_params.json"

        # Same precedence e51_signals.build_strategy_fn/_determine_direction
        # itself uses: structural override > parameter tuning > baseline.
        if override_path.exists():
            return ModelRiskManagementEngine._verify_fields(
                symbol, timeframe, "strategy_override", override_path, _OVERRIDE_REQUIRED_FIELDS,
            )
        if tuned_path.exists():
            return ModelRiskManagementEngine._verify_fields(
                symbol, timeframe, "tuned_params", tuned_path, _TUNED_PARAMS_REQUIRED_FIELDS,
            )
        # No file at all -- the shipped, version-controlled baseline
        # composite rule applies. Code under version control is not a
        # "model" in the sense this engine governs (no separate file to
        # go stale/unverified); not_applicable is the honest label.
        return LiveModelProvenance(symbol, timeframe, "baseline_composite_rule", None, "not_applicable")

    @staticmethod
    def _verify_fields(symbol: str, timeframe: str, kind: str, path: Path, required: tuple[str, ...]) -> LiveModelProvenance:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            return LiveModelProvenance(symbol, timeframe, kind, str(path.name), "unverified", missing_fields=[f"unreadable: {e}"])
        missing = [f for f in required if f not in data]
        if missing:
            return LiveModelProvenance(symbol, timeframe, kind, str(path.name), "missing_required_fields", missing_fields=missing)
        return LiveModelProvenance(symbol, timeframe, kind, str(path.name), "verified")
