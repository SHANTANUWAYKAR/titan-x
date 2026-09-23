"""
Module: engine.py
Description: Engine 29 -- Scenario Analysis. Master prompt scope (line
    495, draft item #24 "Scenario Analysis Engine", kept for detail per
    Rule 1 -- slot #29 in the authoritative MAJOR ENGINES list is
    "Scenario Analysis Engine"): "'what happens if I'm wrong?' Simulate
    Fed surprise, geopolitical shock, flash crash, liquidity event, black
    swan. Best/base/worst case."

    Deliberately distinct from E28 Stress Testing, which already covers
    "replay a historical crisis window against a STRATEGY's trade
    history." E29 answers a narrower, more immediate question: given
    TODAY's proposed trade (entry/stop/target from e51_signals, before
    any trade is taken), what does best/base/worst case actually look
    like in R-multiples? "Best" and "base" reuse E23 Forecasting's own
    empirical percentile distribution (p95/median for the trade's
    direction) -- never a second, duplicate return-distribution
    computation (Rule 4). "Worst" replays the SAME real historical shock
    windows E26/E28 already use (STRESS_PERIODS -- 2008 GFC, 2020 COVID,
    2022 rate shock, 2023 banking crisis -- not invented dates) directly
    against this asset's own real price history, measuring the worst
    peak-to-trough move AGAINST the trade's direction that actually
    happened in that window, then applying that real percentage move to
    today's entry price. This is honest position-level tail risk: "if a
    2020-COVID-sized shock hit this exact position today, would the stop
    hold, and by how much would it miss."

    Rule 3: no calibration script -- like E26/E28, this is a deterministic
    replay of real historical price data against a caller-supplied
    entry/stop/target, not a model with parameters to fit.
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
from project_titan_x.engines.e23_forecasting.engine import ForecastingEngine

logger = logging.getLogger(__name__)


@dataclass
class ScenarioOutcome:
    scenario_name: str
    scenario_type: str  # "best" | "base" | "worst"
    shock_return_pct: Optional[float]  # real (historical or forecast-percentile) return applied
    implied_price: Optional[float]
    r_multiple: Optional[float]  # PnL in units of the trade's own risk (entry - stop)
    stop_loss_breached: Optional[bool]
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_name": self.scenario_name,
            "scenario_type": self.scenario_type,
            "shock_return_pct": round(self.shock_return_pct, 3) if self.shock_return_pct is not None else None,
            "implied_price": round(self.implied_price, 5) if self.implied_price is not None else None,
            "r_multiple": round(self.r_multiple, 2) if self.r_multiple is not None else None,
            "stop_loss_breached": self.stop_loss_breached,
            "note": self.note,
        }


@dataclass
class ScenarioAnalysisReport:
    symbol: str
    timeframe: str
    direction: str
    entry: float
    stop_loss: float
    take_profit: Optional[float]
    generated_at: datetime
    outcomes: list[ScenarioOutcome] = field(default_factory=list)
    worst_case_r_multiple: Optional[float] = None
    any_worst_case_breaches_stop: bool = False
    knowledge_context: Optional[dict] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "direction": self.direction,
            "entry": round(self.entry, 5),
            "stop_loss": round(self.stop_loss, 5),
            "take_profit": round(self.take_profit, 5) if self.take_profit is not None else None,
            "generated_at": self.generated_at.isoformat(),
            "outcomes": [o.to_dict() for o in self.outcomes],
            "worst_case_r_multiple": round(self.worst_case_r_multiple, 2) if self.worst_case_r_multiple is not None else None,
            "any_worst_case_breaches_stop": self.any_worst_case_breaches_stop,
            "knowledge_context": self.knowledge_context,
        }


class ScenarioAnalysisEngine(BaseEngine):
    """Scenario Analysis Engine (#29) -- "what happens if I'm wrong?" for
    a specific proposed trade. Best/base case from E23's own empirical
    forecast distribution; worst case from real historical shock windows
    (E26's own STRESS_PERIODS) replayed against this asset's real price
    history."""

    engine_id = "e29_scenario_analysis"
    engine_name = "Scenario Analysis Engine"
    version = "1.0.0"

    # Same table E26/E28 already use -- not reinvented, see this module's
    # own docstring. Imported lazily inside analyze() to avoid a hard
    # dependency on e26_backtesting for callers that only want best/base.
    def __init__(
        self,
        market_data_engine: Optional[MarketDataEngine] = None,
        forecasting_engine: Optional[ForecastingEngine] = None,
        knowledge_engine: Optional[KnowledgeEngine] = None,
    ) -> None:
        super().__init__()
        self._market_data_engine = market_data_engine if market_data_engine is not None else MarketDataEngine()
        self._forecasting_engine = forecasting_engine if forecasting_engine is not None else ForecastingEngine(market_data_engine=self._market_data_engine)
        self._knowledge_engine = knowledge_engine

    def initialize(self) -> EngineResult:
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Scenario Analysis Engine initialized")

    def health_check(self) -> EngineResult:
        return EngineResult(success=True, message="Healthy")

    def analyze_scenarios(
        self,
        symbol: str,
        direction: str,
        entry: float,
        stop_loss: float,
        take_profit: Optional[float] = None,
        timeframe: str = "1d",
        horizon_days: int = 20,
    ) -> EngineResult:
        """direction: "LONG" or "SHORT". entry/stop_loss/take_profit: the
        exact levels e51_signals already computed for this trade -- never
        recomputed here."""
        try:
            self._set_status(EngineStatus.RUNNING)
            asset = get_asset(symbol)
            if asset is None:
                return EngineResult(success=False, message=f"Unknown asset: {symbol}")
            is_long = direction.upper() == "LONG"
            risk_per_unit = abs(entry - stop_loss)
            if risk_per_unit <= 0:
                return EngineResult(success=False, message="stop_loss must differ from entry to define a risk unit")

            outcomes: list[ScenarioOutcome] = []

            # Best/base case: E23's own empirical distribution, never
            # recomputed here (Rule 4).
            fc = self._forecasting_engine.forecast(asset.symbol, asset.yahoo_symbol, horizon_days=horizon_days)
            if fc.success and fc.data is not None:
                pct = fc.data.return_percentiles_pct
                base_pct = pct.get(50)
                best_pct = pct.get(95) if is_long else pct.get(5)
                outcomes.append(self._outcome_from_return_pct(
                    "base_case_median_forecast", "base", base_pct, entry, stop_loss, is_long, risk_per_unit,
                    note=f"E23 median {horizon_days}d forecast (n={fc.data.n_observations})",
                ))
                outcomes.append(self._outcome_from_return_pct(
                    "best_case_forecast_percentile", "best", best_pct, entry, stop_loss, is_long, risk_per_unit,
                    note=f"E23 {'p95' if is_long else 'p5'} {horizon_days}d forecast (n={fc.data.n_observations})",
                ))
            else:
                outcomes.append(ScenarioOutcome(
                    "base_case_median_forecast", "base", None, None, None, None,
                    note=f"E23 forecast unavailable: {fc.message}",
                ))

            # Worst case: real historical shock windows replayed against
            # this asset's own real price history (never a fabricated
            # shock magnitude).
            from project_titan_x.engines.e26_backtesting.engine import BacktestingEngine
            stress_periods = BacktestingEngine.STRESS_PERIODS
            fetch = self._market_data_engine.fetch_ohlcv(asset.yahoo_symbol, timeframe, years=30)
            if fetch.success and fetch.data is not None and not fetch.data.empty:
                df = fetch.data
                for period_name, (start, end) in stress_periods.items():
                    window = df[(df["timestamp"] >= start) & (df["timestamp"] <= end)]
                    worst_pct = self._worst_adverse_move_pct(window, is_long)
                    if worst_pct is None:
                        outcomes.append(ScenarioOutcome(
                            f"worst_case_{period_name}", "worst", None, None, None, None,
                            note=f"Insufficient {symbol} price history for {period_name} ({start} to {end})",
                        ))
                        continue
                    outcomes.append(self._outcome_from_return_pct(
                        f"worst_case_{period_name}", "worst", worst_pct, entry, stop_loss, is_long, risk_per_unit,
                        note=f"Worst real adverse move for {symbol} during {period_name} ({start} to {end})",
                    ))
            else:
                for period_name in stress_periods:
                    outcomes.append(ScenarioOutcome(
                        f"worst_case_{period_name}", "worst", None, None, None, None,
                        note=f"Could not fetch {symbol} price history: {fetch.message}",
                    ))

            worst_outcomes = [o for o in outcomes if o.scenario_type == "worst" and o.r_multiple is not None]
            worst_case_r = min((o.r_multiple for o in worst_outcomes), default=None)
            any_breach = any(o.stop_loss_breached for o in worst_outcomes)

            report = ScenarioAnalysisReport(
                symbol=asset.symbol, timeframe=timeframe, direction=direction.upper(),
                entry=entry, stop_loss=stop_loss, take_profit=take_profit,
                generated_at=datetime.now(timezone.utc), outcomes=outcomes,
                worst_case_r_multiple=worst_case_r, any_worst_case_breaches_stop=any_breach,
            )
            report.knowledge_context = self._build_knowledge_context(asset.symbol, any_breach)
            self._set_status(EngineStatus.IDLE)
            return EngineResult(
                success=True, data=report,
                message=(
                    f"{symbol} scenario analysis: worst-case {worst_case_r:.2f}R"
                    if worst_case_r is not None else f"{symbol} scenario analysis: worst-case unavailable"
                ),
            )
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("Scenario analysis failed for %s: %s", symbol, e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    @staticmethod
    def _worst_adverse_move_pct(window, is_long: bool) -> Optional[float]:
        """Worst REAL raw asset return (price up = positive, price down =
        negative -- same convention E23's own return_percentiles_pct
        uses) that is adverse for the trade's direction within a
        historical window: the largest decline (negative raw return) for
        LONG, the largest rally (positive raw return) for SHORT. None if
        too little data in that window (e.g. BTCUSD has no 2008 history
        -- honest gap, not fabricated)."""
        if window is None or len(window) < 5:
            return None
        closes = window["close"]
        if is_long:
            running_peak = closes.cummax()
            drawdown_pct = (closes - running_peak) / running_peak * 100.0
            worst = drawdown_pct.min()
        else:
            running_trough = closes.cummin()
            rally_pct = (closes - running_trough) / running_trough * 100.0
            worst = rally_pct.max()
        if worst is None or (isinstance(worst, float) and (worst != worst)):  # NaN check, no numpy import needed
            return None
        return float(worst)

    @staticmethod
    def _outcome_from_return_pct(
        name: str, scenario_type: str, return_pct: Optional[float],
        entry: float, stop_loss: float, is_long: bool, risk_per_unit: float, note: str = "",
    ) -> ScenarioOutcome:
        if return_pct is None:
            return ScenarioOutcome(name, scenario_type, None, None, None, None, note=note or "No data")
        # return_pct is always the RAW asset return (positive = price up,
        # negative = price down) -- same convention E23's own
        # return_percentiles_pct uses. Direction only determines how that
        # price move translates into PnL, never the sign of the price
        # move itself.
        implied_price = entry * (1 + return_pct / 100.0)
        pnl_per_unit = (implied_price - entry) if is_long else (entry - implied_price)
        r_multiple = pnl_per_unit / risk_per_unit
        breached = (is_long and implied_price <= stop_loss) or (not is_long and implied_price >= stop_loss)
        return ScenarioOutcome(name, scenario_type, return_pct, implied_price, r_multiple, breached, note=note)

    def _build_knowledge_context(self, symbol: str, any_breach: bool) -> Optional[dict]:
        """Only queried when a real worst-case scenario would have
        breached the stop -- "nothing to explain, no query" principle,
        same as e05/e10/e13/e14/e15/e16/e17/e27/e28."""
        if self._knowledge_engine is None or not any_breach:
            return None
        try:
            query = f"{symbol} gap risk stop loss slippage tail risk black swan"
            results = self._knowledge_engine.document_store.hybrid_search(query, limit=3)
        except Exception as e:
            logger.warning("Knowledge context unavailable: %s", e)
            return None
        if not results:
            return None
        return {"query": query, "results": [r.to_dict() for r in results]}
