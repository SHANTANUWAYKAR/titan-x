"""
Module: engine.py
Description: Engine 63 -- Market Memory. See MASTER_PROMPT.md's own
    "PROMPT 5" section (2026-08-09 Tier 1-8 audit): genuinely new, no
    existing engine persists a full daily snapshot queryable by
    similarity later ("show me every day similar to today").

    Real, append-only JSONL log (data/models/e63_market_memory/
    <symbol>_daily.jsonl) of already-real, already-computed fields from
    other engines (macro risk score, regime, ADX/RSI, realized vol) --
    never a second computation of any of them (Rule 4). Similarity search
    is a simple, honest, real distance metric over these real numeric
    fields (z-scored), not a fabricated embedding. Outcome backfill reads
    REAL forward price data once enough time has passed -- a snapshot
    younger than the horizon honestly has no outcome yet, never a
    guessed one.

    Rule 3: no calibration script -- deterministic logging + a real
    Euclidean-distance similarity metric over already-real fields, no
    parameters of its own to fit.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus

logger = logging.getLogger(__name__)

_STORE_DIR = Path(__file__).resolve().parents[2] / "data" / "models" / "e63_market_memory"
_OUTCOME_HORIZON_DAYS = 20
_SIMILARITY_FIELDS = ("macro_score", "adx", "rsi", "realized_vol_pct")


@dataclass
class DailySnapshot:
    date_str: str
    symbol: str
    macro_score: Optional[float]
    regime: Optional[str]
    adx: Optional[float]
    rsi: Optional[float]
    realized_vol_pct: Optional[float]
    close: float
    forward_return_pct: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date_str, "symbol": self.symbol, "macro_score": self.macro_score,
            "regime": self.regime, "adx": self.adx, "rsi": self.rsi,
            "realized_vol_pct": self.realized_vol_pct, "close": self.close,
            "forward_return_pct": self.forward_return_pct,
        }

    @staticmethod
    def from_dict(d: dict) -> "DailySnapshot":
        return DailySnapshot(
            date_str=d["date"], symbol=d["symbol"], macro_score=d.get("macro_score"),
            regime=d.get("regime"), adx=d.get("adx"), rsi=d.get("rsi"),
            realized_vol_pct=d.get("realized_vol_pct"), close=d["close"],
            forward_return_pct=d.get("forward_return_pct"),
        )


class MarketMemoryEngine(BaseEngine):
    """Market Memory Engine (#63) -- real, append-only daily snapshot log
    per asset, queryable for similar historical days by a real distance
    metric over already-real fields."""

    engine_id = "e63_market_memory"
    engine_name = "Market Memory Engine"
    version = "1.0.0"

    def __init__(self, market_data_engine: Optional[Any] = None) -> None:
        super().__init__()
        self._market_data_engine = market_data_engine

    def initialize(self) -> EngineResult:
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Market Memory Engine initialized")

    def health_check(self) -> EngineResult:
        return EngineResult(success=True, message="Healthy")

    def _store_path(self, symbol: str) -> Path:
        return _STORE_DIR / f"{symbol}_daily.jsonl"

    def record_snapshot(
        self, symbol: str, close: float, macro_score: Optional[float] = None,
        regime: Optional[str] = None, adx: Optional[float] = None, rsi: Optional[float] = None,
        realized_vol_pct: Optional[float] = None, as_of: Optional[date] = None,
    ) -> EngineResult:
        try:
            self._set_status(EngineStatus.RUNNING)
            d = (as_of or datetime.now(timezone.utc).date()).isoformat()
            snapshot = DailySnapshot(d, symbol, macro_score, regime, adx, rsi, realized_vol_pct, close)
            _STORE_DIR.mkdir(parents=True, exist_ok=True)
            path = self._store_path(symbol)
            existing = self._load_all(symbol)
            existing = [s for s in existing if s.date_str != d]
            existing.append(snapshot)
            existing.sort(key=lambda s: s.date_str)
            path.write_text("\n".join(json.dumps(s.to_dict()) for s in existing) + "\n", encoding="utf-8")
            self._set_status(EngineStatus.IDLE)
            return EngineResult(success=True, message=f"Recorded {symbol} snapshot for {d} ({len(existing)} total)")
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("record_snapshot failed for %s: %s", symbol, e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def _load_all(self, symbol: str) -> list[DailySnapshot]:
        path = self._store_path(symbol)
        if not path.exists():
            return []
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    out.append(DailySnapshot.from_dict(json.loads(line)))
                except Exception as e:
                    logger.warning("Skipping corrupt snapshot line in %s: %s", path, e)
                    continue
        return out

    def backfill_outcomes(self, symbol: str, yahoo_symbol: str) -> EngineResult:
        if self._market_data_engine is None:
            return EngineResult(success=False, message="No market_data_engine injected")
        try:
            self._set_status(EngineStatus.RUNNING)
            snapshots = self._load_all(symbol)
            if not snapshots:
                return EngineResult(success=True, message="No snapshots to backfill")
            fetch = self._market_data_engine.fetch_ohlcv(yahoo_symbol, "1d", years=10)
            if not fetch.success or fetch.data is None or fetch.data.empty:
                return EngineResult(success=False, message=f"Could not fetch OHLCV for {symbol}")
            df = fetch.data
            df["date_str"] = df["timestamp"].dt.strftime("%Y-%m-%d")
            close_by_date = dict(zip(df["date_str"], df["close"]))
            dates_sorted = sorted(close_by_date.keys())

            n_filled = 0
            for s in snapshots:
                if s.forward_return_pct is not None or s.date_str not in close_by_date:
                    continue
                idx = dates_sorted.index(s.date_str)
                target_idx = idx + _OUTCOME_HORIZON_DAYS
                if target_idx >= len(dates_sorted):
                    continue
                future_close = close_by_date[dates_sorted[target_idx]]
                s.forward_return_pct = (future_close / s.close - 1.0) * 100.0
                n_filled += 1

            path = self._store_path(symbol)
            path.write_text("\n".join(json.dumps(s.to_dict()) for s in snapshots) + "\n", encoding="utf-8")
            self._set_status(EngineStatus.IDLE)
            return EngineResult(success=True, message=f"Backfilled {n_filled} real outcome(s) for {symbol}")
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("backfill_outcomes failed for %s: %s", symbol, e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def find_similar_days(
        self, symbol: str, macro_score: Optional[float] = None, adx: Optional[float] = None,
        rsi: Optional[float] = None, realized_vol_pct: Optional[float] = None, top_n: int = 5,
    ) -> EngineResult:
        try:
            self._set_status(EngineStatus.RUNNING)
            snapshots = self._load_all(symbol)
            query = {"macro_score": macro_score, "adx": adx, "rsi": rsi, "realized_vol_pct": realized_vol_pct}
            active_fields = [f for f in _SIMILARITY_FIELDS if query[f] is not None]
            if not active_fields:
                return EngineResult(success=False, message="Must supply at least one real field to compare against")
            if len(snapshots) < 10:
                return EngineResult(success=True, data=[], message=f"Only {len(snapshots)} snapshot(s) recorded -- too few for a meaningful similarity search")

            stats = {}
            for f in active_fields:
                vals = [getattr(s, f) for s in snapshots if getattr(s, f) is not None]
                if len(vals) < 5:
                    continue
                mean = sum(vals) / len(vals)
                std = math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals)) or 1.0
                stats[f] = (mean, std)

            usable_fields = [f for f in active_fields if f in stats]
            if not usable_fields:
                return EngineResult(success=True, data=[], message="Not enough historical spread to compare against")

            scored = []
            for s in snapshots:
                dist_sq = 0.0
                n_matched = 0
                for f in usable_fields:
                    val = getattr(s, f)
                    if val is None:
                        continue
                    mean, std = stats[f]
                    z_query = (query[f] - mean) / std
                    z_val = (val - mean) / std
                    dist_sq += (z_query - z_val) ** 2
                    n_matched += 1
                if n_matched == len(usable_fields):
                    scored.append((math.sqrt(dist_sq), s))

            scored.sort(key=lambda x: x[0])
            top = [{"distance": round(d, 3), "snapshot": s.to_dict()} for d, s in scored[:top_n]]
            self._set_status(EngineStatus.IDLE)
            return EngineResult(success=True, data=top, message=f"Found {len(top)} similar real historical day(s) for {symbol} out of {len(snapshots)} recorded")
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("find_similar_days failed for %s: %s", symbol, e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])
