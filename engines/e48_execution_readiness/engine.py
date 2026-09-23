"""
Module: engine.py
Description: Engine 48 -- Execution Readiness Intelligence. Master
    prompt scope (line 517, draft item #35 "Execution Cost Analytics" --
    "spread costs, slippage, commission, market impact" -- kept for
    detail per Rule 1; slot #48 in the authoritative MAJOR ENGINES list
    is "Execution Intelligence Engine"). Deliberately scoped as
    INFORMATIONAL-ONLY -- this platform has explicitly decided not to
    build E49 (MetaTrader 5 Integration Layer, real broker connectivity)
    per CLAUDE.md Rule 5's no-live-execution boundary. This engine never
    places an order, never touches a broker API, and exposes no
    place_order/execute_trade/submit_order method (verified live by
    e47_governance's own no_execution_capability check, which would fail
    the whole platform's compliance audit if this engine ever grew one).

    Composes E11 Market Microstructure's own already-real spread/
    liquidity/session read (never a second, duplicate Corwin-Schultz
    computation, Rule 4) with a real, standard square-root market-impact
    model (Almgren et al., a well-established quant convention: impact
    scales with the square root of order size relative to average
    volume, not linearly) to answer "if a human decided to act on this
    signal right now, what would it actually cost, and is now a good
    time" -- the exact "Execution Cost Analytics" scope named above,
    entirely pre-trade estimation, never execution itself.

    Rule 3: no calibration script for the spread/liquidity read itself
    (inherited directly from E11, already real); the market-impact
    model's own square-root FORM is a standard, well-established
    quant-finance convention (not fit to this platform's own data), same
    "static, documented convention" category as e13_derivatives' skew
    thresholds.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from project_titan_x.core.config import get_asset
from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus

logger = logging.getLogger(__name__)

# Sessions E11 itself classifies as "quiet" are poor execution timing for
# FX -- reused directly, never a second classification.
_POOR_TIMING_LIQUIDITY_LABELS = {"quiet"}
_HIGH_RISK_EXECUTION_LABELS = {"high"}


@dataclass
class ExecutionCostEstimate:
    symbol: str
    position_size_usd: float
    estimated_spread_pct: float
    spread_cost_usd: float
    market_impact_pct: Optional[float]
    market_impact_usd: Optional[float]
    total_cost_usd: Optional[float]
    total_cost_pct_of_position: Optional[float]
    execution_risk: str  # from E11, unmodified
    session_liquidity: Optional[str]  # from E11, unmodified (forex only)
    readiness: str  # ready | caution | insufficient_data
    notes: list[str]
    generated_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "position_size_usd": round(self.position_size_usd, 2),
            "estimated_spread_pct": self.estimated_spread_pct,
            "spread_cost_usd": round(self.spread_cost_usd, 2),
            "market_impact_pct": round(self.market_impact_pct, 5) if self.market_impact_pct is not None else None,
            "market_impact_usd": round(self.market_impact_usd, 2) if self.market_impact_usd is not None else None,
            "total_cost_usd": round(self.total_cost_usd, 2) if self.total_cost_usd is not None else None,
            "total_cost_pct_of_position": round(self.total_cost_pct_of_position, 4) if self.total_cost_pct_of_position is not None else None,
            "execution_risk": self.execution_risk,
            "session_liquidity": self.session_liquidity,
            "readiness": self.readiness,
            "notes": self.notes,
            "generated_at": self.generated_at.isoformat(),
        }


class ExecutionReadinessEngine(BaseEngine):
    """Execution Readiness Intelligence Engine (#48) -- pre-trade cost/
    timing estimation ONLY. No order-placement method exists anywhere in
    this class; see this module's own docstring for the governance
    boundary this deliberately stays inside."""

    engine_id = "e48_execution_readiness"
    engine_name = "Execution Readiness Intelligence Engine"
    version = "1.0.0"

    def __init__(self, microstructure_engine: Optional[Any] = None, market_data_engine: Optional[Any] = None) -> None:
        super().__init__()
        self._microstructure_engine = microstructure_engine
        self._market_data_engine = market_data_engine

    def initialize(self) -> EngineResult:
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Execution Readiness Intelligence Engine initialized")

    def health_check(self) -> EngineResult:
        return EngineResult(success=True, message="Healthy")

    def assess_execution_readiness(self, symbol: str, position_size_usd: float, timeframe: str = "1d") -> EngineResult:
        if self._microstructure_engine is None or self._market_data_engine is None:
            return EngineResult(success=False, message="microstructure_engine and market_data_engine both required")
        if position_size_usd <= 0:
            return EngineResult(success=False, message="position_size_usd must be positive")
        try:
            self._set_status(EngineStatus.RUNNING)
            asset = get_asset(symbol)
            if asset is None:
                return EngineResult(success=False, message=f"Unknown asset: {symbol}")

            fetch = self._market_data_engine.fetch_ohlcv(asset.yahoo_symbol, timeframe, years=1)
            if not fetch.success or fetch.data is None or fetch.data.empty:
                return EngineResult(success=False, message=f"Could not fetch OHLCV for {symbol}")
            df = fetch.data

            micro_result = self._microstructure_engine.analyze(df, symbol=asset.symbol, timeframe=timeframe, asset_class=asset.asset_class.value)
            if not micro_result.success or micro_result.data is None:
                return EngineResult(success=False, message=f"E11 microstructure read failed: {micro_result.message}")
            snapshot = micro_result.data

            spread_cost_usd = (snapshot.estimated_spread_pct / 100.0) * position_size_usd

            # Standard square-root market-impact model: impact scales with
            # sqrt(order size / average daily dollar volume), not linearly
            # -- a well-established quant-finance convention (Almgren et
            # al.), not fit to this platform's own data.
            avg_dollar_volume = self._avg_dollar_volume(df)
            market_impact_pct = market_impact_usd = None
            notes = list(snapshot.notes)
            if avg_dollar_volume and avg_dollar_volume > 0:
                participation = position_size_usd / avg_dollar_volume
                market_impact_pct = snapshot.estimated_spread_pct * math.sqrt(participation)
                market_impact_usd = (market_impact_pct / 100.0) * position_size_usd
            else:
                notes.append("Average dollar volume unavailable -- market impact not estimated (honest gap, not a fabricated 0)")

            total_cost_usd = spread_cost_usd + market_impact_usd if market_impact_usd is not None else None
            total_cost_pct = (total_cost_usd / position_size_usd * 100.0) if total_cost_usd is not None else None

            session_liquidity = snapshot.session.get("liquidity") if snapshot.session else None
            readiness = self._determine_readiness(snapshot.execution_risk, session_liquidity)

            estimate = ExecutionCostEstimate(
                symbol=asset.symbol, position_size_usd=position_size_usd,
                estimated_spread_pct=snapshot.estimated_spread_pct, spread_cost_usd=spread_cost_usd,
                market_impact_pct=market_impact_pct, market_impact_usd=market_impact_usd,
                total_cost_usd=total_cost_usd, total_cost_pct_of_position=total_cost_pct,
                execution_risk=snapshot.execution_risk, session_liquidity=session_liquidity,
                readiness=readiness, notes=notes, generated_at=datetime.now(timezone.utc),
            )
            self._set_status(EngineStatus.IDLE)
            return EngineResult(
                success=True, data=estimate,
                message=f"{symbol}: readiness={readiness}, est. total cost={total_cost_pct:.3f}% of position" if total_cost_pct is not None
                else f"{symbol}: readiness={readiness}, total cost unavailable (see notes)",
            )
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("Execution readiness assessment failed for %s: %s", symbol, e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    @staticmethod
    def _avg_dollar_volume(df) -> Optional[float]:
        if "volume" not in df.columns or "close" not in df.columns or df.empty:
            return None
        recent = df.tail(30)
        dollar_volume = (recent["volume"] * recent["close"]).mean()
        if dollar_volume != dollar_volume or dollar_volume <= 0:  # NaN check
            return None
        return float(dollar_volume)

    @staticmethod
    def _determine_readiness(execution_risk: str, session_liquidity: Optional[str]) -> str:
        if execution_risk == "unknown":
            return "insufficient_data"
        if execution_risk in _HIGH_RISK_EXECUTION_LABELS:
            return "caution"
        if session_liquidity in _POOR_TIMING_LIQUIDITY_LABELS:
            return "caution"
        return "ready"
