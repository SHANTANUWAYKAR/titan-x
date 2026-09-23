"""
Module: engine.py
Description: Engine 28 -- Stress Testing. Master prompt scope (draft
    detail, item #25 "Portfolio Stress Lab"): "replay 2008 GFC, 2020 COVID
    crash, 2022 inflation shock, banking crises, commodity shocks against
    every strategy/portfolio."

    The core simulation math for this ALREADY EXISTS -- E26 Backtesting
    Laboratory has had a working stress_test() method and a STRESS_PERIODS
    table (2008_gfc, 2020_covid, 2022_rate_shock, and since 2026-08-02
    2023_banking_crisis -- well-known, widely-documented historical market
    date ranges, not a guessed fact) since before this session, verified
    correct against real GOLD data during this engine's build (23/2/16
    trades, real drawdowns computed). It was simply never called from
    anywhere else in the codebase and had zero test coverage -- the exact
    "dead code" pattern this project has caught before (see CLAUDE.md's
    Signal-table precedent). This engine is the orchestration layer that
    actually calls it: for the EXACT live rule e51_signals.build_strategy_fn
    resolves for an asset, replay every stress period E26 knows about and
    classify each against E45's own real CRO drawdown limit
    (settings.max_drawdown_pct) -- reusing that existing risk threshold
    rather than inventing a new one.

    2023_banking_crisis (SVB/Signature/Credit Suisse/First Republic, real
    dates in E26's own STRESS_PERIODS docstring) closes a real gap: the
    master prompt names "banking crises" as its own distinct stress
    category, and none of the three periods that existed before it were
    one. E28 itself needed no code change for this -- it already iterates
    `self._backtesting_engine.STRESS_PERIODS.items()` generically, so a
    new period in that single shared table flows through automatically
    (same decoupling this module's docstring already describes for the
    other three periods).

    Also relevant to this platform's real asset universe: BTC-USD/ETH-USD
    (and every other real symbol this platform tracks) DO have real 2023
    daily history, unlike 2008_gfc (where crypto has none at all) -- so
    2023_banking_crisis is the first stress period to give every asset on
    this platform a genuine, non-"insufficient_data" read.

    Honest gap: BTCUSD/ETHUSD have no 2008 data (Bitcoin didn't exist until
    2009) -- reported as insufficient_data for that period, not fabricated.

    No calibration script (Rule 3): like E26/E27, this is a deterministic
    validation utility, not a model with parameters to fit.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-07-19
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from project_titan_x.core.config import get_asset, get_settings
from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus
from project_titan_x.engines.e01_knowledge.engine import KnowledgeEngine
from project_titan_x.engines.e02_market_data.engine import MarketDataEngine
from project_titan_x.engines.e07_technical.engine import TechnicalAnalysisEngine
from project_titan_x.engines.e26_backtesting.engine import BacktestingEngine

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class StressPeriodResult:
    period_name: str
    start: str
    end: str
    verdict: str  # "resilient" | "breached_risk_limit" | "insufficient_data"
    total_trades: int = 0
    max_drawdown_pct: float = 0.0
    total_return_pct: float = 0.0
    note: str = ""


@dataclass
class StressTestReport:
    symbol: str
    timeframe: str
    generated_at: datetime
    periods: list[StressPeriodResult] = field(default_factory=list)
    worst_case_dd_pct: Optional[float] = None
    overall_verdict: str = "insufficient_data"  # resilient | breached_risk_limit | insufficient_data
    knowledge_context: Optional[dict] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "generated_at": self.generated_at.isoformat(),
            "periods": [
                {
                    "period_name": p.period_name, "start": p.start, "end": p.end, "verdict": p.verdict,
                    "total_trades": p.total_trades, "max_drawdown_pct": round(p.max_drawdown_pct, 2),
                    "total_return_pct": round(p.total_return_pct, 2), "note": p.note,
                }
                for p in self.periods
            ],
            "worst_case_dd_pct": round(self.worst_case_dd_pct, 2) if self.worst_case_dd_pct is not None else None,
            "overall_verdict": self.overall_verdict,
            "knowledge_context": self.knowledge_context,
        }


class StressTestingEngine(BaseEngine):
    """Stress Testing Engine (#28) -- replays real historical crisis
    windows against the EXACT live rule e51_signals resolves for an asset,
    via E26's own (previously unused) stress_test()."""

    engine_id = "e28_stress_testing"
    engine_name = "Stress Testing Engine"
    version = "1.0.0"

    MIN_STRESS_BARS = 10  # matches E26.stress_test's own internal floor

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
        return EngineResult(success=True, message="Stress Testing Engine initialized")

    def health_check(self) -> EngineResult:
        return EngineResult(success=True, message="Healthy")

    def run_stress_test(self, symbol: str, timeframe: str = "1d") -> EngineResult:
        if self._signal_engine is None:
            return EngineResult(success=False, message="No signal_engine injected -- cannot resolve this asset's live strategy rule")
        try:
            self._set_status(EngineStatus.RUNNING)
            asset = get_asset(symbol)
            if asset is None:
                return EngineResult(success=False, message=f"Unknown asset: {symbol}")

            # Full available history -- STRESS_PERIODS reaches back to
            # 2008, so ask for as much as this source has; fetch_ohlcv caps
            # gracefully at whatever real history actually exists (e.g.
            # BTCUSD only goes back to 2014-ish on Yahoo).
            fetch = self._market_data_engine.fetch_ohlcv(asset.yahoo_symbol, timeframe, years=30)
            if not fetch.success or fetch.data is None or fetch.data.empty:
                return EngineResult(success=False, message=f"Could not fetch OHLCV for {symbol}")
            df = fetch.data

            ta_result = self._technical_engine.analyze(df, symbol=asset.symbol, timeframe=timeframe)
            if not ta_result.success:
                return EngineResult(success=False, message=f"Technical analysis failed: {ta_result.message}")
            enriched = ta_result.data["df"]

            strategy_fn = self._signal_engine.build_strategy_fn(asset.symbol, timeframe, enriched)

            periods: list[StressPeriodResult] = []
            for period_name, (start, end) in self._backtesting_engine.STRESS_PERIODS.items():
                result = self._backtesting_engine.stress_test(enriched, strategy_fn, period_name)
                if not result.success:
                    periods.append(StressPeriodResult(
                        period_name=period_name, start=start, end=end, verdict="insufficient_data",
                        note=result.message,
                    ))
                    continue
                m = result.data.metrics
                breached = m.max_drawdown_pct >= settings.max_drawdown_pct
                periods.append(StressPeriodResult(
                    period_name=period_name, start=start, end=end,
                    verdict="breached_risk_limit" if breached else "resilient",
                    total_trades=m.total_trades, max_drawdown_pct=m.max_drawdown_pct,
                    total_return_pct=m.total_return_pct,
                    note=(
                        f"Max drawdown {m.max_drawdown_pct:.1f}% "
                        f"{'>=' if breached else '<'} CRO limit {settings.max_drawdown_pct:.0f}%"
                    ),
                ))

            report = self._aggregate(asset.symbol, timeframe, periods)
            report.knowledge_context = self._build_knowledge_context(asset.symbol, report.overall_verdict)
            self._set_status(EngineStatus.IDLE)
            return EngineResult(
                success=True, data=report,
                message=f"{symbol}: overall_verdict={report.overall_verdict}, worst-case DD={report.worst_case_dd_pct}%",
            )
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("Stress test failed for %s: %s", symbol, e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    @staticmethod
    def _aggregate(symbol: str, timeframe: str, periods: list[StressPeriodResult]) -> StressTestReport:
        report = StressTestReport(symbol=symbol, timeframe=timeframe, generated_at=datetime.now(timezone.utc), periods=periods)
        valid = [p for p in periods if p.verdict != "insufficient_data"]
        if not valid:
            report.overall_verdict = "insufficient_data"
            return report
        report.worst_case_dd_pct = max(p.max_drawdown_pct for p in valid)
        report.overall_verdict = "breached_risk_limit" if any(p.verdict == "breached_risk_limit" for p in valid) else "resilient"
        return report

    def _build_knowledge_context(self, symbol: str, overall_verdict: str) -> Optional[dict]:
        """Relevant book content on tail risk/crisis behavior -- only
        queried when a real breach was found, same "nothing to explain, no
        query" principle as e05/e10/e13/e14/e15/e16/e17/e27."""
        if self._knowledge_engine is None or overall_verdict != "breached_risk_limit":
            return None
        try:
            query = f"{symbol} strategy tail risk crisis drawdown stress test"
            results = self._knowledge_engine.document_store.hybrid_search(query, limit=3)
        except Exception as e:
            logger.warning("Knowledge context unavailable: %s", e)
            return None
        if not results:
            return None
        return {"query": query, "results": [r.to_dict() for r in results]}
