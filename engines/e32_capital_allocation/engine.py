"""
Module: engine.py
Description: Engine 32 -- Capital Allocation. Master prompt scope (line
    486, draft item #21 "Decision Intelligence Engine", kept for detail
    per Rule 1; slot #32 in the authoritative MAJOR ENGINES list is
    "Capital Allocation Engine"): "should I deploy capital here vs every
    other opportunity in the world? Opportunity cost analysis, capital
    efficiency analysis, relative opportunity ranking, cross-asset
    comparison, expected utility optimization, dynamic capital
    allocation. Every trade competes against all other trades."

    Deliberately a COMPOSITION of five already-real engines, never a
    second implementation of any of their math (Rule 4):
      - E33 Opportunity Ranking: "relative opportunity ranking" and
        "cross-asset comparison" -- ranks every supported asset by E51's
        own real conviction score in one shared-input pass.
      - E51 Signal Intelligence (via the same SignalGenerationWorkflow
        E33 itself already runs): the exact entry/stop/target for the
        small number of TOP-ranked candidates actually competing for
        capital -- re-run only for that small bounded subset (default
        max_positions=5, never the full asset universe a second time),
        an explicit, documented, bounded cost, same class of on-demand
        real compute as e28/e29/e30/e37's own per-asset calls.
      - E26 Backtesting Laboratory (via the same build_strategy_fn
        dependency e27/e28/e30/e37 already use): real win_rate/avg_win_r/
        avg_loss_r for each candidate, feeding...
      - E12 Quant Research's own real `kelly_criterion` -- "capital
        efficiency analysis" and "expected utility optimization" is
        literally what Kelly sizing already answers, not reinvented here.
      - E45 Risk Management (CRO): every candidate's proposed size is
        submitted through the REAL `evaluate_trade()` veto check before
        any capital is allocated -- this engine never invents its own
        risk cap or bypasses the CRO (Rule 5, verified: this module reads
        `RiskCheckResult.approved`/`adjusted_risk_pct` and nothing else,
        never writes into E45's own verdict logic).

    "Opportunity cost analysis" is answered directly and honestly: every
    asset that did NOT receive capital (not tradeable, ranked below
    max_positions, or CRO-vetoed) is reported with the real reason it
    lost out to a higher-conviction alternative -- "every trade competes
    against all other trades" taken literally.

    Rule 3: no calibration script -- deterministic composition/
    normalization over five already-real, already-calibrated engines'
    outputs, same "no" category as e31_portfolio_construction/
    e33_opportunity_ranking.

    Rule 5: no execution. This engine only ever proposes an allocation
    for a human to review -- consistent with this platform having no
    execution engine (E48/E49 unimplemented) anywhere in its pipeline.
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

MIN_TRADES_FOR_KELLY = 15  # below this, a per-symbol win_rate/avg_win/avg_loss read is too noisy to size against


@dataclass
class CapitalAllocation:
    symbol: str
    direction: str
    allocated_capital: float
    risk_percent: float
    kelly_fraction: Optional[float]
    confidence: int
    cro_verdict: str
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "direction": self.direction,
            "allocated_capital": round(self.allocated_capital, 2),
            "risk_percent": round(self.risk_percent, 3),
            "kelly_fraction": round(self.kelly_fraction, 4) if self.kelly_fraction is not None else None,
            "confidence": self.confidence,
            "cro_verdict": self.cro_verdict,
            "note": self.note,
        }


@dataclass
class OpportunityCost:
    symbol: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"symbol": self.symbol, "reason": self.reason}


@dataclass
class CapitalAllocationReport:
    generated_at: datetime
    total_capital: float
    timeframe: str
    max_positions: int
    allocations: list[CapitalAllocation] = field(default_factory=list)
    opportunity_costs: list[OpportunityCost] = field(default_factory=list)
    total_allocated: float = 0.0
    total_unallocated: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "total_capital": round(self.total_capital, 2),
            "timeframe": self.timeframe,
            "max_positions": self.max_positions,
            "allocations": [a.to_dict() for a in self.allocations],
            "opportunity_costs": [o.to_dict() for o in self.opportunity_costs],
            "total_allocated": round(self.total_allocated, 2),
            "total_unallocated": round(self.total_unallocated, 2),
        }


class CapitalAllocationEngine(BaseEngine):
    """Capital Allocation Engine (#32) -- "every trade competes against
    all other trades." Takes the registry itself (same pattern as
    e00_titan_brain/e33_opportunity_ranking) since its whole job is
    orchestrating E33/E51/E26/E12/E45 via the existing workflow/engine
    layer, never owning analysis logic of its own."""

    engine_id = "e32_capital_allocation"
    engine_name = "Capital Allocation Engine"
    version = "1.0.0"

    def __init__(self, registry: Optional[Any] = None) -> None:
        super().__init__()
        self._registry = registry

    def initialize(self) -> EngineResult:
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Capital Allocation Engine initialized")

    def health_check(self) -> EngineResult:
        if self._registry is None:
            return EngineResult(success=False, message="No registry injected")
        return EngineResult(success=True, message="Healthy")

    def allocate(
        self, total_capital: float, timeframe: str = "1d", max_positions: int = 5,
        symbols: Optional[list[str]] = None,
    ) -> EngineResult:
        if self._registry is None:
            return EngineResult(success=False, message="No registry injected -- cannot orchestrate E33/E51/E26/E12/E45")
        if total_capital <= 0:
            return EngineResult(success=False, message="total_capital must be positive")
        try:
            self._set_status(EngineStatus.RUNNING)

            opportunity_ranking_engine = self._registry.get("e33_opportunity_ranking")
            if opportunity_ranking_engine is None:
                return EngineResult(success=False, message="e33_opportunity_ranking not registered")
            rank_result = opportunity_ranking_engine.rank_opportunities(timeframe=timeframe, symbols=symbols)
            if not rank_result.success:
                return EngineResult(success=False, message=f"Opportunity ranking failed: {rank_result.message}")
            rankings = rank_result.data

            tradeable = sorted((r for r in rankings if r.tradeable), key=lambda r: r.confidence, reverse=True)
            not_tradeable = [r for r in rankings if not r.tradeable]
            candidates = tradeable[:max_positions]
            ranked_out = tradeable[max_positions:]

            opportunity_costs: list[OpportunityCost] = [
                OpportunityCost(r.symbol, f"Did not clear E51's tradeable gate: {r.reason}") for r in not_tradeable
            ]
            opportunity_costs.extend(
                OpportunityCost(r.symbol, f"Ranked #{i + max_positions + 1} by confidence ({r.confidence}) -- outside top {max_positions}, capital went to higher-conviction alternatives instead")
                for i, r in enumerate(ranked_out)
            )

            scored: list[tuple[Any, float, float, Optional[float]]] = []  # (ranking, entry_signal, risk_pct, kelly_fraction)
            for opp in candidates:
                sizing = self._size_candidate(opp, timeframe)
                if sizing is None:
                    opportunity_costs.append(OpportunityCost(opp.symbol, "Signal no longer available on re-check (data changed between ranking and sizing) or CRO vetoed the proposal"))
                    continue
                risk_pct, kelly_fraction, direction, cro_note = sizing
                scored.append((opp, direction, risk_pct, kelly_fraction, cro_note))

            allocations: list[CapitalAllocation] = []
            if scored:
                weights = [max(0.0, s[0].confidence) * max(1e-6, s[2]) for s in scored]
                total_weight = sum(weights) or 1.0
                for (opp, direction, risk_pct, kelly_fraction, cro_note), weight in zip(scored, weights):
                    share = weight / total_weight
                    allocations.append(CapitalAllocation(
                        symbol=opp.symbol, direction=direction, allocated_capital=total_capital * share,
                        risk_percent=risk_pct, kelly_fraction=kelly_fraction, confidence=opp.confidence,
                        cro_verdict="approved", note=cro_note,
                    ))

            total_allocated = sum(a.allocated_capital for a in allocations)
            report = CapitalAllocationReport(
                generated_at=datetime.now(timezone.utc), total_capital=total_capital, timeframe=timeframe,
                max_positions=max_positions, allocations=allocations, opportunity_costs=opportunity_costs,
                total_allocated=total_allocated, total_unallocated=total_capital - total_allocated,
            )
            self._set_status(EngineStatus.IDLE)
            return EngineResult(
                success=True, data=report,
                message=f"Allocated {total_allocated:.2f} of {total_capital:.2f} across {len(allocations)} opportunit{'y' if len(allocations) == 1 else 'ies'}",
            )
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("Capital allocation failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def _size_candidate(self, opp: Any, timeframe: str) -> Optional[tuple[float, Optional[float], str, str]]:
        """Returns (risk_percent, kelly_fraction, direction, note) for an
        approved candidate, or None if the signal vanished on re-check or
        the CRO vetoed it. Re-running the workflow for just THIS one
        candidate (never the full universe) is the documented, bounded
        cost this module's own docstring explains."""
        from project_titan_x.engines.e00_titan_brain.workflows import SignalGenerationWorkflow

        wf = SignalGenerationWorkflow(registry=self._registry)
        wf_result = wf.run(opp.symbol, timeframe)
        signal = wf_result.final_data.get("signal") if wf_result.final_data else None
        if signal is None:
            return None

        kelly_fraction = None
        risk_pct = settings.default_risk_per_trade_pct
        kelly_note = "Using CRO default risk-per-trade (insufficient real backtest sample for Kelly sizing)"
        backtest_stats = self._real_backtest_stats(opp.symbol, timeframe)
        if backtest_stats is not None:
            win_rate, avg_win_r, avg_loss_r, n_trades = backtest_stats
            if n_trades >= MIN_TRADES_FOR_KELLY and 0 < win_rate < 1 and avg_win_r > 0 and avg_loss_r > 0:
                quant_engine = self._registry.get("e12_quant_research")
                if quant_engine is not None:
                    kelly_result = quant_engine.kelly_criterion(win_rate, avg_win_r, avg_loss_r)
                    if kelly_result.success and kelly_result.data is not None:
                        kelly_fraction = kelly_result.data.half_kelly_fraction
                        if kelly_fraction > 0:
                            risk_pct = min(kelly_fraction * 100.0, settings.max_risk_per_trade_pct)
                            kelly_note = f"Half-Kelly sizing from {n_trades} real backtest trades (win_rate={win_rate:.1%})"

        risk_engine = self._registry.get("e45_risk")
        if risk_engine is None:
            return None
        from project_titan_x.engines.e45_risk.engine import TradeRiskProposal
        proposal = TradeRiskProposal(
            asset=opp.symbol, direction=signal.direction, entry_price=signal.entry, stop_loss=signal.stop_loss,
            take_profit=signal.take_profit_1, risk_percent=risk_pct, confidence_score=signal.confidence_score,
            regime=signal.regime, timeframe=timeframe,
        )
        risk_check = risk_engine.evaluate_trade(proposal)
        if not risk_check.success or not risk_check.data.approved:
            return None
        final_risk_pct = risk_check.data.adjusted_risk_pct if risk_check.data.adjusted_risk_pct is not None else risk_pct
        return final_risk_pct, kelly_fraction, signal.direction, kelly_note

    def _real_backtest_stats(self, symbol: str, timeframe: str) -> Optional[tuple[float, float, float, int]]:
        """Real win_rate/avg_win_r/avg_loss_r/n_trades for the EXACT live
        rule this symbol resolves to, via the same build_strategy_fn +
        E26.run_backtest pattern e27/e28/e30/e37 already use -- never a
        second reimplementation."""
        signal_engine = self._registry.get("e51_signals")
        market_data_engine = self._registry.get("e02_market_data")
        technical_engine = self._registry.get("e07_technical")
        backtesting_engine = self._registry.get("e26_backtesting")
        if not all((signal_engine, market_data_engine, technical_engine, backtesting_engine)):
            return None
        try:
            from project_titan_x.core.config import get_asset
            asset = get_asset(symbol)
            if asset is None:
                return None
            fetch = market_data_engine.fetch_ohlcv(asset.yahoo_symbol, timeframe, years=10)
            if not fetch.success or fetch.data is None or fetch.data.empty:
                return None
            ta_result = technical_engine.analyze(fetch.data, symbol=asset.symbol, timeframe=timeframe)
            if not ta_result.success:
                return None
            enriched = ta_result.data["df"]
            strategy_fn = signal_engine.build_strategy_fn(asset.symbol, timeframe, enriched)
            bt = backtesting_engine.run_backtest(enriched, strategy_fn)
            if not bt.success or bt.data is None:
                return None
            m = bt.data.metrics
            if m.total_trades == 0:
                return None
            return m.win_rate, abs(m.avg_win_r), abs(m.avg_loss_r), m.total_trades
        except Exception as e:
            logger.warning("Real backtest stats unavailable for %s: %s", symbol, e)
            return None
