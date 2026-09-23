"""
Module: registry.py
Description: Central engine registry for PROJECT TITAN-X.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-06-28
"""

import logging
from typing import Any

from project_titan_x.core.data_providers.ecb import get_ecb_client
from project_titan_x.core.data_providers.finnhub import get_finnhub_client
from project_titan_x.core.data_providers.fred import get_fred_client
from project_titan_x.engines.base import BaseEngine
from project_titan_x.engines.e00_titan_brain import TitanBrainEngine
from project_titan_x.engines.e01_knowledge import KnowledgeEngine
from project_titan_x.engines.e02_market_data import MarketDataEngine
from project_titan_x.engines.e04_macro import MacroIntelligenceEngine
from project_titan_x.engines.e05_economic_calendar import EconomicCalendarEngine
from project_titan_x.engines.e08_regime import MarketRegimeEngine
from project_titan_x.engines.e10_cross_asset import CrossAssetIntelligenceEngine
from project_titan_x.engines.e13_derivatives import DerivativesIntelligenceEngine
from project_titan_x.engines.e14_fixed_income import FixedIncomeIntelligenceEngine
from project_titan_x.engines.e15_credit import CreditIntelligenceEngine
from project_titan_x.engines.e16_commodity import CommodityIntelligenceEngine
from project_titan_x.engines.e17_crypto import CryptoIntelligenceEngine
from project_titan_x.engines.e19_global_liquidity import GlobalLiquidityEngine
from project_titan_x.engines.e20_factor_research import FactorResearchEngine
from project_titan_x.engines.e24_strategy_research import StrategyResearchEngine
from project_titan_x.engines.e27_walk_forward import WalkForwardValidationEngine
from project_titan_x.engines.e28_stress_testing import StressTestingEngine
from project_titan_x.engines.e06_fundamental import FundamentalAnalysisEngine
from project_titan_x.engines.e07_technical import TechnicalAnalysisEngine
from project_titan_x.engines.e03_news import NewsIntelligenceEngine
from project_titan_x.engines.e12_quant_research import QuantResearchEngine
from project_titan_x.engines.e09_sentiment import SentimentIntelligenceEngine
from project_titan_x.engines.e26_backtesting import BacktestingEngine
from project_titan_x.engines.e11_microstructure import MarketMicrostructureEngine
from project_titan_x.engines.e45_risk import RiskManagementEngine
from project_titan_x.engines.e43_committee import CommitteeEngine
from project_titan_x.engines.e51_signals import SignalIntelligenceEngine
from project_titan_x.engines.e40_data_quality import DataQualityEngine
from project_titan_x.engines.e35_performance_analytics import PerformanceAnalyticsEngine
from project_titan_x.engines.e34_trade_attribution import TradeAttributionEngine
from project_titan_x.engines.e31_portfolio_construction import PortfolioConstructionEngine
from project_titan_x.engines.e33_opportunity_ranking import OpportunityRankingEngine
from project_titan_x.engines.e42_confidence_calibration import ConfidenceCalibrationEngine
from project_titan_x.engines.e38_alpha_decay_monitor import AlphaDecayMonitorEngine
from project_titan_x.engines.e41_explainable_ai import ExplainableAIEngine
from project_titan_x.engines.e21_feature_engineering import FeatureEngineeringEngine
from project_titan_x.engines.e22_alpha_research import AlphaResearchFactoryEngine
from project_titan_x.engines.e23_forecasting import ForecastingEngine
from project_titan_x.engines.e25_strategy_lifecycle import StrategyLifecycleEngine
from project_titan_x.engines.e29_scenario_analysis import ScenarioAnalysisEngine
from project_titan_x.engines.e30_adversarial_testing import AdversarialTestingEngine
from project_titan_x.engines.e32_capital_allocation import CapitalAllocationEngine
from project_titan_x.engines.e36_learning import LearningEngine
from project_titan_x.engines.e37_meta_learning import MetaLearningEngine
from project_titan_x.engines.e39_model_risk import ModelRiskManagementEngine
from project_titan_x.engines.e44_chief_investment_officer import ChiefInvestmentOfficerEngine
from project_titan_x.engines.e46_chief_risk_officer import ChiefRiskOfficerEngine
from project_titan_x.engines.e47_governance import GovernanceEngine
from project_titan_x.engines.e48_execution_readiness import ExecutionReadinessEngine
from project_titan_x.engines.e63_market_memory import MarketMemoryEngine
from project_titan_x.engines.e64_causal_intelligence import CausalIntelligenceEngine
from project_titan_x.engines.e65_world_model import WorldModelEngine
from project_titan_x.engines.e74_conflict_resolution import ConflictResolutionEngine
from project_titan_x.engines.e79_portfolio_simulation import PortfolioSimulationEngine
from project_titan_x.engines.e84_counterfactual import CounterfactualEngine

logger = logging.getLogger(__name__)


class EngineRegistry:
    """Central registry for all Titan-X engines."""

    def __init__(self) -> None:
        self._engines: dict[str, BaseEngine] = {}
        # Constructed before _risk_engine/_register_defaults() so every
        # engine below can receive the SAME KnowledgeEngine instance.
        self._knowledge_engine = KnowledgeEngine()
        self._risk_engine = RiskManagementEngine(knowledge_engine=self._knowledge_engine)
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Register Phase 1 + Phase 2 + Phase 3 (in-progress) engines."""
        knowledge_engine = self._knowledge_engine
        data_quality_engine = DataQualityEngine()
        technical_engine = TechnicalAnalysisEngine(knowledge_engine=knowledge_engine)
        backtesting_engine = BacktestingEngine()
        microstructure_engine = MarketMicrostructureEngine(knowledge_engine=knowledge_engine)
        economic_calendar_engine = EconomicCalendarEngine(knowledge_engine=knowledge_engine, finnhub_client=get_finnhub_client())
        market_data_engine = MarketDataEngine(data_quality_engine=data_quality_engine)
        macro_engine = MacroIntelligenceEngine(knowledge_engine=knowledge_engine)
        cross_asset_engine = CrossAssetIntelligenceEngine(knowledge_engine=knowledge_engine)
        derivatives_engine = DerivativesIntelligenceEngine(knowledge_engine=knowledge_engine)
        commodity_engine = CommodityIntelligenceEngine(knowledge_engine=knowledge_engine, market_data_engine=market_data_engine)
        crypto_engine = CryptoIntelligenceEngine(knowledge_engine=knowledge_engine, market_data_engine=market_data_engine)
        news_engine = NewsIntelligenceEngine()
        sentiment_engine = SentimentIntelligenceEngine(knowledge_engine=knowledge_engine)
        quant_engine = QuantResearchEngine(knowledge_engine=knowledge_engine)
        fixed_income_engine = FixedIncomeIntelligenceEngine(knowledge_engine=knowledge_engine, quant_engine=quant_engine)
        credit_engine = CreditIntelligenceEngine(
            knowledge_engine=knowledge_engine, fixed_income_engine=fixed_income_engine, quant_engine=quant_engine
        )
        performance_engine = PerformanceAnalyticsEngine(market_data_engine=market_data_engine, quant_engine=quant_engine)
        trade_attribution_engine = TradeAttributionEngine(performance_engine=performance_engine)
        portfolio_construction_engine = PortfolioConstructionEngine()
        # OpportunityRankingEngine takes the registry itself (same pattern
        # as TitanBrainEngine below) -- it only calls registry.get(...)
        # lazily inside rank_opportunities(), well after _register_defaults()
        # finishes registering every other engine, so construction order
        # here doesn't matter.
        opportunity_ranking_engine = OpportunityRankingEngine(registry=self)
        confidence_calibration_engine = ConfidenceCalibrationEngine(performance_engine=performance_engine, quant_engine=quant_engine)
        alpha_decay_monitor_engine = AlphaDecayMonitorEngine(performance_engine=performance_engine, quant_engine=quant_engine)
        global_liquidity_engine = GlobalLiquidityEngine(knowledge_engine=knowledge_engine, fred_client=get_fred_client())
        factor_research_engine = FactorResearchEngine(knowledge_engine=knowledge_engine, market_data_engine=market_data_engine)
        strategy_research_engine = StrategyResearchEngine(
            market_data_engine=market_data_engine, technical_engine=technical_engine, backtesting_engine=backtesting_engine,
        )
        # E21/E22/E23 (added 2026-08-05, per MASTER_PROMPT.md slots #21-23
        # -- see each engine's own module docstring for the exact spec
        # line quoted). No knowledge_engine on E21: mechanical assembly of
        # already-computed values, same "no" category as
        # e02_market_data/e40_data_quality (see e21's own docstring).
        feature_engineering_engine = FeatureEngineeringEngine(
            technical_engine=technical_engine, macro_engine=macro_engine,
            derivatives_engine=derivatives_engine, cross_asset_engine=cross_asset_engine,
        )
        alpha_research_engine = AlphaResearchFactoryEngine(market_data_engine=market_data_engine, knowledge_engine=knowledge_engine)
        forecasting_engine = ForecastingEngine(market_data_engine=market_data_engine)
        # E39 has no dependency on signal_engine (pure file scan/
        # provenance check) so it's constructed here, before signal_engine,
        # and passed into its constructor normally -- unlike E37 below,
        # which has a genuine circular dependency with signal_engine.
        model_risk_engine = ModelRiskManagementEngine()
        # signal_engine assigned to a variable (not built inline in
        # `defaults` like every other engine here) specifically so
        # walk_forward_engine/stress_testing_engine below can take it as a
        # collaborator (both need signal_engine.build_strategy_fn to
        # resolve the EXACT live rule for an asset) -- constructed BEFORE
        # them for that reason, registered in its usual `defaults` list
        # position below.
        signal_engine = SignalIntelligenceEngine(
            risk_engine=self._risk_engine,
            technical_engine=technical_engine,
            backtesting_engine=backtesting_engine,
            microstructure_engine=microstructure_engine,
            economic_calendar_engine=economic_calendar_engine,
            knowledge_engine=knowledge_engine,
            cross_asset_engine=cross_asset_engine,
            news_engine=news_engine,
            sentiment_engine=sentiment_engine,
            derivatives_engine=derivatives_engine,
            commodity_engine=commodity_engine,
            crypto_engine=crypto_engine,
            fixed_income_engine=fixed_income_engine,
            credit_engine=credit_engine,
            quant_engine=quant_engine,
            global_liquidity_engine=global_liquidity_engine,
            feature_engineering_engine=feature_engineering_engine,
            alpha_research_engine=alpha_research_engine,
            forecasting_engine=forecasting_engine,
            model_risk_engine=model_risk_engine,
        )
        walk_forward_engine = WalkForwardValidationEngine(
            signal_engine=signal_engine, market_data_engine=market_data_engine,
            technical_engine=technical_engine, backtesting_engine=backtesting_engine, knowledge_engine=knowledge_engine,
        )
        stress_testing_engine = StressTestingEngine(
            signal_engine=signal_engine, market_data_engine=market_data_engine,
            technical_engine=technical_engine, backtesting_engine=backtesting_engine, knowledge_engine=knowledge_engine,
        )
        # E25/E29/E30/E32/E36/E37/E39 (added 2026-08-05, per MASTER_PROMPT.md
        # slots #25/#29/#30/#32/#36/#37/#39 -- see each engine's own module
        # docstring for the exact spec line quoted, and CLAUDE.md's roster
        # entry for the honest scope interpretation E25/E32 needed (no
        # detail section exists for either beyond their one-line master-list
        # name). Every one of these composes ALREADY-real engines' outputs
        # rather than reimplementing anything (Rule 4) -- see each
        # docstring for exactly which collaborator owns which piece of math.
        scenario_analysis_engine = ScenarioAnalysisEngine(
            market_data_engine=market_data_engine, forecasting_engine=forecasting_engine, knowledge_engine=knowledge_engine,
        )
        adversarial_testing_engine = AdversarialTestingEngine(
            signal_engine=signal_engine, market_data_engine=market_data_engine,
            technical_engine=technical_engine, backtesting_engine=backtesting_engine, knowledge_engine=knowledge_engine,
        )
        # Genuine circular dependency: E37's OWN learn_regime_fit() needs
        # signal_engine.build_strategy_fn (to resolve the exact live rule
        # to backtest), while signal_engine's live confluence check needs
        # a reference to E37 (see _confluence_meta_learning). Neither
        # constructor can take the other as a param at the same time --
        # resolved with a direct post-construction attribute set below,
        # the same pattern this exact circularity requires in any
        # constructor-injection design.
        meta_learning_engine = MetaLearningEngine(
            signal_engine=signal_engine, market_data_engine=market_data_engine,
            technical_engine=technical_engine, backtesting_engine=backtesting_engine, knowledge_engine=knowledge_engine,
        )
        signal_engine._meta_learning_engine = meta_learning_engine
        learning_engine = LearningEngine(trade_attribution_engine=trade_attribution_engine, performance_engine=performance_engine)
        strategy_lifecycle_engine = StrategyLifecycleEngine(alpha_decay_monitor_engine=alpha_decay_monitor_engine)
        # CapitalAllocationEngine takes the registry itself (same pattern as
        # OpportunityRankingEngine above) -- it only calls registry.get(...)
        # lazily inside allocate(), well after _register_defaults() finishes.
        capital_allocation_engine = CapitalAllocationEngine(registry=self)
        # E44/E46/E47/E48 (added 2026-08-09, per MASTER_PROMPT.md slots
        # #44/#46/#47/#48 -- see each engine's own module docstring for the
        # exact spec line quoted, including E46's explicit Rule-1 conflict
        # note against E45's own existing "(CRO)" scope, and E48's explicit
        # no-execution-capability boundary per Rule 5).
        chief_investment_officer_engine = ChiefInvestmentOfficerEngine(registry=self)
        chief_risk_officer_engine = ChiefRiskOfficerEngine(risk_engine=self._risk_engine, stress_testing_engine=stress_testing_engine)
        governance_engine = GovernanceEngine(registry=self, model_risk_engine=model_risk_engine)
        execution_readiness_engine = ExecutionReadinessEngine(microstructure_engine=microstructure_engine, market_data_engine=market_data_engine)
        # E63/E64/E65/E74/E79/E84 (added 2026-08-10, per MASTER_PROMPT.md's
        # own "PROMPT 5" Tier 1-8 duplicate audit -- the 6 genuinely-new
        # engines out of the user's 30-engine proposal; see each module's
        # own docstring for the exact real technique used (Granger
        # causality, historical-bootstrap Monte Carlo, real regime-
        # attributed philosophy comparison, real historical episode
        # replay) -- never a fabricated one.
        market_memory_engine = MarketMemoryEngine(market_data_engine=market_data_engine)
        causal_intelligence_engine = CausalIntelligenceEngine(market_data_engine=market_data_engine)
        world_model_engine = WorldModelEngine(
            macro_engine=macro_engine, cross_asset_engine=cross_asset_engine,
            global_liquidity_engine=global_liquidity_engine, causal_engine=causal_intelligence_engine,
        )
        conflict_resolution_engine = ConflictResolutionEngine(
            market_data_engine=market_data_engine, technical_engine=technical_engine, backtesting_engine=backtesting_engine,
        )
        portfolio_simulation_engine = PortfolioSimulationEngine(market_data_engine=market_data_engine)
        counterfactual_engine = CounterfactualEngine(market_data_engine=market_data_engine)
        defaults: list[BaseEngine] = [
            knowledge_engine,
            market_data_engine,
            macro_engine,
            economic_calendar_engine,
            MarketRegimeEngine(knowledge_engine=knowledge_engine),
            cross_asset_engine,
            derivatives_engine,
            fixed_income_engine,
            credit_engine,
            commodity_engine,
            crypto_engine,
            FundamentalAnalysisEngine(knowledge_engine=knowledge_engine, ecb_client=get_ecb_client()),
            data_quality_engine,
            technical_engine,
            news_engine,
            quant_engine,
            sentiment_engine,
            backtesting_engine,
            microstructure_engine,
            performance_engine,
            trade_attribution_engine,
            portfolio_construction_engine,
            opportunity_ranking_engine,
            confidence_calibration_engine,
            alpha_decay_monitor_engine,
            ExplainableAIEngine(),
            global_liquidity_engine,
            factor_research_engine,
            strategy_research_engine,
            feature_engineering_engine,
            alpha_research_engine,
            forecasting_engine,
            walk_forward_engine,
            stress_testing_engine,
            scenario_analysis_engine,
            adversarial_testing_engine,
            meta_learning_engine,
            model_risk_engine,
            learning_engine,
            strategy_lifecycle_engine,
            capital_allocation_engine,
            chief_investment_officer_engine,
            chief_risk_officer_engine,
            market_memory_engine,
            causal_intelligence_engine,
            world_model_engine,
            conflict_resolution_engine,
            portfolio_simulation_engine,
            counterfactual_engine,
            governance_engine,
            execution_readiness_engine,
            self._risk_engine,
            # technical_engine + backtesting_engine wired in turns on the
            # edge gate: a proven-negative-edge backtest result on this
            # engine's own rule vetoes the signal outright (see
            # e51_signals/engine.py validate_historical_edge).
            # microstructure_engine, economic_calendar_engine,
            # cross_asset_engine, news_engine+sentiment_engine,
            # derivatives_engine, commodity_engine, fixed_income_engine, and
            # credit_engine all feed _apply_confluence_adjustments -- these
            # DO nudge confidence (never direction), the same way Command
            # Center's own higher-timeframe/cross-asset confluence
            # multipliers do. quant_engine additionally enriches
            # validate_historical_edge with a Bayesian-calibrated win-rate
            # read (informational, never changes status/confidence).
            # knowledge_engine attaches informational relevant-trader-
            # knowledge context to every signal -- never changes
            # confidence/direction. Every real engine on this platform now
            # has a hand in the ONE signal E51 produces, one way or another.
            signal_engine,
            CommitteeEngine(knowledge_engine=knowledge_engine, market_data_engine=market_data_engine),
        ]
        for engine in defaults:
            self.register(engine)

        # Registered last: Titan Brain holds a live reference to this
        # registry, so it sees every engine registered above (and any
        # registered later via .register()) regardless of construction order.
        self.register(TitanBrainEngine(registry=self))

    def register(self, engine: BaseEngine) -> None:
        """Register an engine instance."""
        self._engines[engine.engine_id] = engine
        logger.info("Registered engine: %s", engine.engine_id)

    def get(self, engine_id: str) -> BaseEngine | None:
        """Get engine by ID."""
        return self._engines.get(engine_id)

    def initialize_all(self) -> dict[str, Any]:
        """Initialize all registered engines."""
        results = {}
        for eid, engine in self._engines.items():
            result = engine.initialize()
            results[eid] = {
                "success": result.success,
                "message": result.message,
            }
        return results

    # Health is polled far more often than it changes -- /health is what
    # monitoring, load balancers and the dashboard all hit. Checking 54 engines
    # serially measured 3.995s, which is past the timeout most pollers use, and
    # recomputing it on every poll is the same answer bought repeatedly.
    _HEALTH_TTL_SECONDS = 10.0

    def health_check_all(self, *, max_age_seconds: float | None = None) -> dict[str, Any]:
        """Health check all engines, cached briefly.

        `max_age_seconds=0` forces a fresh check -- use it when something has
        just been repaired and the answer must not be a stale success.
        """
        import time as _time

        ttl = self._HEALTH_TTL_SECONDS if max_age_seconds is None else max_age_seconds
        cached = getattr(self, "_health_cache", None)
        if cached is not None and ttl > 0:
            ts, payload = cached
            if (_time.monotonic() - ts) < ttl:
                return payload

        # Engine health checks are I/O-bound (feeds, files, db pings), so
        # threads genuinely overlap them; the serial version spent most of its
        # 4s waiting rather than computing.
        from concurrent.futures import ThreadPoolExecutor

        def _one(item):
            eid, engine = item
            try:
                return eid, bool(engine.health_check().success)
            except Exception:  # noqa: BLE001 - one sick engine must not sink /health
                return eid, False

        items = list(self._engines.items())
        if not items:
            result: dict[str, Any] = {}
        else:
            with ThreadPoolExecutor(max_workers=min(16, len(items))) as ex:
                result = dict(ex.map(_one, items))
        self._health_cache = (_time.monotonic(), result)
        return result

    def list_engines(self) -> list[dict[str, Any]]:
        """List all registered engines."""
        return [engine.get_info() for engine in self._engines.values()]


_registry: EngineRegistry | None = None


def get_registry() -> EngineRegistry:
    """Get or create the global engine registry."""
    global _registry
    if _registry is None:
        _registry = EngineRegistry()
    return _registry
