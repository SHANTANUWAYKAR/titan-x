"""
Module: engine.py
Description: Engine 30 -- Adversarial Testing. Master prompt scope (line
    524, draft item #39 "Adversarial Testing Engine" -- different draft
    numbering than the authoritative slot, kept for detail per Rule 1;
    slot #30 in the authoritative MAJOR ENGINES list is "Adversarial
    Testing Engine"): "try to break your own strategies: what assumptions
    fail, what data could be wrong, what market changes destroy this
    edge."

    Three real, well-known quant "try to break it" techniques, all
    orchestrating E26 Backtesting Laboratory's OWN existing infrastructure
    against the EXACT live rule e51_signals resolves for an asset (same
    build_strategy_fn dependency E27/E28 already use) -- never a second,
    reimplemented backtest engine:

    1. Parameter fragility: E26.run_backtest() already computes a
       robustness_score via its own (previously internal-only)
       _parameter_sensitivity -- +-10% perturbation of risk/commission and
       measuring Sharpe stability. This was computed and stored on every
       BacktestResult but never read or surfaced by any caller (the exact
       "dead code" pattern this project caught before for E26.stress_test,
       see e28_stress_testing's own docstring) -- E30 is the first caller
       to actually read `robustness_score` and act on it.
    2. Monte Carlo reshuffle risk of ruin: E26.monte_carlo() -- shuffles
       the REAL trade list's order 1000x and measures how often equity
       would have hit a 50% ruin threshold. Defined in E26 since before
       this session, never called from anywhere in the codebase until
       this engine (verified via a full-repo grep before building this).
       Answers "was I just lucky about trade ORDER, not edge."
    3. Single-trade dependency ("cockroach test"): a classic adversarial
       check with no existing engine implementation anywhere in this
       codebase -- remove the single best REAL trade from the backtest's
       own trade list and recompute expectancy by hand (simple mean, no
       new statistical machinery). If expectancy flips from positive to
       non-positive by removing exactly one trade, the "edge" was really
       one lucky outlier, not a repeatable process.

    Deliberately distinct from E27 (fold-by-fold walk-forward stability
    across TIME) and E28 (replay of specific historical crisis WINDOWS) --
    E30 asks "does this edge survive being attacked from angles that have
    nothing to do with time or history: parameter choice, trade sequence,
    and reliance on outliers."

    Rule 3: no calibration script -- like E27/E28, this orchestrates
    E26's own deterministic backtest/Monte Carlo machinery against real
    historical data; the only "thresholds" (robustness_score < 0.5,
    risk_of_ruin > 5%) are standard, widely-used quant conventions
    documented inline, not fit to any dataset.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from project_titan_x.core.config import get_asset
from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus
from project_titan_x.engines.e01_knowledge.engine import KnowledgeEngine
from project_titan_x.engines.e02_market_data.engine import MarketDataEngine
from project_titan_x.engines.e07_technical.engine import TechnicalAnalysisEngine
from project_titan_x.engines.e26_backtesting.engine import BacktestingEngine

logger = logging.getLogger(__name__)

ROBUSTNESS_FRAGILE_THRESHOLD = 0.5  # E26's own robustness_score is already clamped to [0, 1]
RISK_OF_RUIN_FRAGILE_THRESHOLD_PCT = 5.0  # standard quant convention: >5% chance of 50% drawdown is unacceptable
MIN_TRADES_FOR_ADVERSARIAL_TESTS = 10


@dataclass
class AdversarialFinding:
    test_name: str
    verdict: str  # "passed" | "fragile" | "insufficient_data"
    detail: dict[str, Any] = field(default_factory=dict)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"test_name": self.test_name, "verdict": self.verdict, "detail": self.detail, "note": self.note}


@dataclass
class AdversarialTestReport:
    symbol: str
    timeframe: str
    generated_at: datetime
    findings: list[AdversarialFinding] = field(default_factory=list)
    overall_verdict: str = "insufficient_data"  # robust | fragile | insufficient_data
    knowledge_context: Optional[dict] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "generated_at": self.generated_at.isoformat(),
            "findings": [f.to_dict() for f in self.findings],
            "overall_verdict": self.overall_verdict,
            "knowledge_context": self.knowledge_context,
        }


class AdversarialTestingEngine(BaseEngine):
    """Adversarial Testing Engine (#30) -- tries to break the EXACT live
    strategy rule e51_signals resolves for an asset via three real
    "attack" angles (parameter perturbation, trade-order Monte Carlo,
    single-trade dependency), all against E26's own real backtest output
    on real historical data."""

    engine_id = "e30_adversarial_testing"
    engine_name = "Adversarial Testing Engine"
    version = "1.0.0"

    def __init__(
        self,
        signal_engine: Optional[Any] = None,
        market_data_engine: Optional[MarketDataEngine] = None,
        technical_engine: Optional[TechnicalAnalysisEngine] = None,
        backtesting_engine: Optional[BacktestingEngine] = None,
        knowledge_engine: Optional[KnowledgeEngine] = None,
    ) -> None:
        super().__init__()
        self._signal_engine = signal_engine
        self._market_data_engine = market_data_engine if market_data_engine is not None else MarketDataEngine()
        self._technical_engine = technical_engine if technical_engine is not None else TechnicalAnalysisEngine()
        self._backtesting_engine = backtesting_engine if backtesting_engine is not None else BacktestingEngine()
        self._knowledge_engine = knowledge_engine

    def initialize(self) -> EngineResult:
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Adversarial Testing Engine initialized")

    def health_check(self) -> EngineResult:
        return EngineResult(success=True, message="Healthy")

    def stress_assumptions(self, symbol: str, timeframe: str = "1d") -> EngineResult:
        if self._signal_engine is None:
            return EngineResult(success=False, message="No signal_engine injected -- cannot resolve this asset's live strategy rule")
        try:
            self._set_status(EngineStatus.RUNNING)
            asset = get_asset(symbol)
            if asset is None:
                return EngineResult(success=False, message=f"Unknown asset: {symbol}")

            fetch = self._market_data_engine.fetch_ohlcv(asset.yahoo_symbol, timeframe, years=10)
            if not fetch.success or fetch.data is None or fetch.data.empty:
                return EngineResult(success=False, message=f"Could not fetch OHLCV for {symbol}")
            df = fetch.data

            ta_result = self._technical_engine.analyze(df, symbol=asset.symbol, timeframe=timeframe)
            if not ta_result.success:
                return EngineResult(success=False, message=f"Technical analysis failed: {ta_result.message}")
            enriched = ta_result.data["df"]

            strategy_fn = self._signal_engine.build_strategy_fn(asset.symbol, timeframe, enriched)
            bt = self._backtesting_engine.run_backtest(enriched, strategy_fn)
            if not bt.success or bt.data is None:
                return EngineResult(success=False, message=f"Backtest failed: {bt.message}")
            result = bt.data
            trades = result.trades

            findings: list[AdversarialFinding] = []

            if len(trades) < MIN_TRADES_FOR_ADVERSARIAL_TESTS:
                findings.append(AdversarialFinding(
                    "parameter_fragility", "insufficient_data",
                    note=f"Only {len(trades)} real trades, need >={MIN_TRADES_FOR_ADVERSARIAL_TESTS}",
                ))
                findings.append(AdversarialFinding(
                    "monte_carlo_ruin_risk", "insufficient_data",
                    note=f"Only {len(trades)} real trades, need >={MIN_TRADES_FOR_ADVERSARIAL_TESTS}",
                ))
                findings.append(AdversarialFinding(
                    "single_trade_dependency", "insufficient_data",
                    note=f"Only {len(trades)} real trades, need >={MIN_TRADES_FOR_ADVERSARIAL_TESTS}",
                ))
            else:
                findings.append(self._check_parameter_fragility(result.robustness_score))
                findings.append(self._check_monte_carlo(trades))
                findings.append(self._check_single_trade_dependency(trades))

            overall = self._aggregate_verdict(findings)
            report = AdversarialTestReport(
                symbol=asset.symbol, timeframe=timeframe, generated_at=datetime.now(timezone.utc),
                findings=findings, overall_verdict=overall,
            )
            report.knowledge_context = self._build_knowledge_context(asset.symbol, overall)
            self._set_status(EngineStatus.IDLE)
            return EngineResult(
                success=True, data=report,
                message=f"{symbol} adversarial testing: overall_verdict={overall} ({len(trades)} real trades tested)",
            )
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("Adversarial testing failed for %s: %s", symbol, e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    @staticmethod
    def _check_parameter_fragility(robustness_score: float) -> AdversarialFinding:
        fragile = robustness_score < ROBUSTNESS_FRAGILE_THRESHOLD
        return AdversarialFinding(
            "parameter_fragility", "fragile" if fragile else "passed",
            detail={"robustness_score": round(robustness_score, 3), "threshold": ROBUSTNESS_FRAGILE_THRESHOLD},
            note=(
                f"Sharpe stability under +-10% risk/commission perturbation: {robustness_score:.2f} "
                f"({'below' if fragile else 'at or above'} the {ROBUSTNESS_FRAGILE_THRESHOLD} threshold)"
            ),
        )

    def _check_monte_carlo(self, trades: list[dict]) -> AdversarialFinding:
        mc = self._backtesting_engine.monte_carlo(trades)
        if not mc.success or mc.data is None:
            return AdversarialFinding("monte_carlo_ruin_risk", "insufficient_data", note=mc.message)
        ruin_pct = mc.data["risk_of_ruin_pct"]
        fragile = ruin_pct > RISK_OF_RUIN_FRAGILE_THRESHOLD_PCT
        return AdversarialFinding(
            "monte_carlo_ruin_risk", "fragile" if fragile else "passed",
            detail=mc.data,
            note=(
                f"{ruin_pct:.1f}% of 1000 reshuffled trade-order simulations hit 50% ruin "
                f"({'above' if fragile else 'at or below'} the {RISK_OF_RUIN_FRAGILE_THRESHOLD_PCT}% threshold)"
            ),
        )

    @staticmethod
    def _check_single_trade_dependency(trades: list[dict]) -> AdversarialFinding:
        pnls = [t["pnl_r"] for t in trades]
        expectancy_all = sum(pnls) / len(pnls)
        best_idx = max(range(len(pnls)), key=lambda i: pnls[i])
        best_pnl = pnls[best_idx]
        remaining = pnls[:best_idx] + pnls[best_idx + 1:]
        expectancy_excl_best = sum(remaining) / len(remaining) if remaining else 0.0
        fragile = expectancy_all > 0 and expectancy_excl_best <= 0
        return AdversarialFinding(
            "single_trade_dependency", "fragile" if fragile else "passed",
            detail={
                "expectancy_all_trades_r": round(expectancy_all, 4),
                "expectancy_excl_best_trade_r": round(expectancy_excl_best, 4),
                "best_trade_pnl_r": round(best_pnl, 4),
                "n_trades": len(trades),
            },
            note=(
                f"Removing the single best real trade ({best_pnl:+.2f}R) "
                f"{'flips expectancy non-positive' if fragile else 'does not flip expectancy negative'} "
                f"({expectancy_all:+.3f}R -> {expectancy_excl_best:+.3f}R)"
            ),
        )

    @staticmethod
    def _aggregate_verdict(findings: list[AdversarialFinding]) -> str:
        verdicts = {f.verdict for f in findings}
        if "fragile" in verdicts:
            return "fragile"
        if verdicts == {"passed"}:
            return "robust"
        return "insufficient_data"

    def _build_knowledge_context(self, symbol: str, overall_verdict: str) -> Optional[dict]:
        """Only queried when a real fragility was found -- "nothing to
        explain, no query" principle, same as e05/e10/e13/.../e28/e29."""
        if self._knowledge_engine is None or overall_verdict != "fragile":
            return None
        try:
            query = f"{symbol} strategy overfitting curve fitting robustness sample size"
            results = self._knowledge_engine.document_store.hybrid_search(query, limit=3)
        except Exception as e:
            logger.warning("Knowledge context unavailable: %s", e)
            return None
        if not results:
            return None
        return {"query": query, "results": [r.to_dict() for r in results]}
