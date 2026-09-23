"""
Module: engine.py
Description: Engine 27 -- Walk-Forward Validation. Master prompt scope
    ("Walk-forward testing" under BACKTESTING REQUIREMENTS; slot #27 in the
    authoritative MAJOR ENGINES list).

    Today's validation (E26 Backtesting Laboratory's run_backtest, used by
    e51_signals.validate_historical_edge and every research script) is a
    SINGLE static in-sample/out-of-sample split -- real, but only one
    sample of "did this hold up." This engine tests something a single
    split cannot: does the SAME live rule (via e51_signals.build_strategy_fn
    -- not a reimplementation) hold up across SEVERAL different historical
    periods, not just one? A rule that passes one lucky split and fails the
    other four is a materially different, weaker claim than one that passes
    consistently -- this is exactly the distinction a single IS/OOS split
    cannot make.

    Method: split the full available history into `n_folds` contiguous,
    non-overlapping chronological chunks; run E26's own run_backtest (which
    does its own internal 70/30 IS/OOS split) independently on each fold;
    aggregate pass rate and OOS Sharpe stability across folds. No new
    backtesting math -- this is an orchestration layer over E26, same
    decoupling convention as e16/e24 reusing e02/e26 rather than
    reimplementing.

    No calibration script (Rule 3): like E26 itself and E31/E33/E34/E35/E40,
    this is a deterministic validation UTILITY applied at call time, not a
    model with parameters to fit against historical data -- the fold count/
    minimum-bars-per-fold are documented static conventions, not backtested
    thresholds requiring their own held-out validation.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-07-19
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np

from project_titan_x.core.config import get_asset
from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus
from project_titan_x.engines.e01_knowledge.engine import KnowledgeEngine
from project_titan_x.engines.e02_market_data.engine import MarketDataEngine
from project_titan_x.engines.e07_technical.engine import TechnicalAnalysisEngine
from project_titan_x.engines.e26_backtesting.engine import BacktestingEngine

logger = logging.getLogger(__name__)

MIN_BARS_PER_FOLD = 120
DEFAULT_N_FOLDS = 5
PASS_RATE_STABLE_THRESHOLD = 0.6

# Same convention as e24_strategy_research.BARS_PER_YEAR and
# train_e51_signals.PERIODS_PER_YEAR: run_walk_forward accepts a
# `timeframe` argument and fetches real OHLCV at that granularity, but
# previously always called E26.run_backtest with a hardcoded
# periods_per_year=252 regardless of it -- silently mispricing
# Sharpe (and therefore passed_validation/verdict) for any non-daily
# fold by whatever factor separates 252 from the true bar frequency.
BARS_PER_YEAR = {
    "1m": 525_600, "5m": 105_120, "15m": 35_040, "30m": 17_520,
    "1h": 8_760, "4h": 2_190, "1d": 252, "1wk": 52, "1mo": 12,
}


@dataclass
class FoldResult:
    fold_index: int
    n_bars: int
    is_sharpe: float
    is_trades: int
    oos_sharpe: float
    passed_validation: bool
    # Walk-Forward Efficiency (Pardo, "The Evaluation and Optimization of
    # Trading Strategies"): OOS Sharpe / IS Sharpe for this fold -- the
    # standard diagnostic for how much of the in-sample edge survives
    # out-of-sample. None (not 0 or a fabricated ratio) when IS Sharpe
    # wasn't positive -- there's no meaningful in-sample edge to compare
    # OOS against, so a ratio here would be a divide against noise, not a
    # real efficiency figure. This is informational only, deliberately NOT
    # fed into _aggregate's verdict logic (which already distinguishes
    # pass_rate from oos_sharpe_positive_rate for good, documented
    # reasons) -- an additional lens on the same fold data, not a
    # replacement for the existing one.
    walk_forward_efficiency: Optional[float] = None


@dataclass
class WalkForwardReport:
    symbol: str
    timeframe: str
    generated_at: datetime
    n_folds_requested: int
    folds: list[FoldResult] = field(default_factory=list)
    n_folds_evaluated: int = 0
    n_folds_passed: int = 0
    pass_rate: float = 0.0
    oos_sharpe_mean: float = 0.0
    oos_sharpe_std: float = 0.0
    oos_sharpe_positive_rate: float = 0.0
    # Mean of walk_forward_efficiency across folds where it's defined (IS
    # Sharpe > 0). None if no fold had a positive IS Sharpe to measure
    # against. A low mean (well below 1.0) alongside an otherwise decent
    # pass_rate is the classic Pardo overfitting signature: the strategy
    # looks good in-sample but gives most of that edge back out-of-sample.
    mean_walk_forward_efficiency: Optional[float] = None
    # stable_edge | directionally_consistent_low_sample | unstable_edge |
    # no_edge | insufficient_data -- see _aggregate's docstring for why
    # pass_rate alone (E26's full bar, including its 30-trade minimum) is
    # not enough to distinguish "no edge" from "too few trades in this
    # short a window to independently clear a bar calibrated for
    # whole-history testing."
    verdict: str = "insufficient_data"
    knowledge_context: Optional[dict] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "generated_at": self.generated_at.isoformat(),
            "n_folds_requested": self.n_folds_requested,
            "n_folds_evaluated": self.n_folds_evaluated,
            "n_folds_passed": self.n_folds_passed,
            "pass_rate": round(self.pass_rate, 3),
            "oos_sharpe_mean": round(self.oos_sharpe_mean, 4),
            "oos_sharpe_std": round(self.oos_sharpe_std, 4),
            "oos_sharpe_positive_rate": round(self.oos_sharpe_positive_rate, 3),
            "mean_walk_forward_efficiency": (
                round(self.mean_walk_forward_efficiency, 4) if self.mean_walk_forward_efficiency is not None else None
            ),
            "verdict": self.verdict,
            "folds": [
                {
                    "fold_index": f.fold_index, "n_bars": f.n_bars, "is_sharpe": round(f.is_sharpe, 4),
                    "is_trades": f.is_trades, "oos_sharpe": round(f.oos_sharpe, 4), "passed_validation": f.passed_validation,
                    "walk_forward_efficiency": round(f.walk_forward_efficiency, 4) if f.walk_forward_efficiency is not None else None,
                }
                for f in self.folds
            ],
            "knowledge_context": self.knowledge_context,
        }


class WalkForwardValidationEngine(BaseEngine):
    """Walk-Forward Validation Engine (#27) -- multi-fold stability check
    on top of E26's single-split validation, for the EXACT live rule
    e51_signals.build_strategy_fn resolves for a given asset."""

    engine_id = "e27_walk_forward"
    engine_name = "Walk-Forward Validation Engine"
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
        # Typed Any deliberately -- avoids a hard import-time dependency on
        # e51_signals (which itself optionally depends on this engine's
        # sibling collaborators), same decoupling convention used
        # throughout e51_signals' own confluence collaborators.
        self._signal_engine = signal_engine
        self._market_data_engine = market_data_engine if market_data_engine is not None else MarketDataEngine()
        self._technical_engine = technical_engine if technical_engine is not None else TechnicalAnalysisEngine()
        self._backtesting_engine = backtesting_engine if backtesting_engine is not None else BacktestingEngine()
        self._knowledge_engine = knowledge_engine

    def initialize(self) -> EngineResult:
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Walk-Forward Validation Engine initialized")

    def health_check(self) -> EngineResult:
        return EngineResult(success=True, message="Healthy")

    def run_walk_forward(
        self, symbol: str, timeframe: str = "1d", n_folds: int = DEFAULT_N_FOLDS, years: int = 8
    ) -> EngineResult:
        if self._signal_engine is None:
            return EngineResult(success=False, message="No signal_engine injected -- cannot resolve this asset's live strategy rule")
        try:
            self._set_status(EngineStatus.RUNNING)
            asset = get_asset(symbol)
            if asset is None:
                return EngineResult(success=False, message=f"Unknown asset: {symbol}")

            fetch = self._market_data_engine.fetch_ohlcv(asset.yahoo_symbol, timeframe, years=years)
            if not fetch.success or fetch.data is None:
                return EngineResult(success=False, message=f"Could not fetch OHLCV for {symbol}")
            df = fetch.data
            if len(df) < MIN_BARS_PER_FOLD * 2:
                return EngineResult(
                    success=False,
                    message=f"Only {len(df)} bars for {symbol} -- need at least {MIN_BARS_PER_FOLD * 2} for 2+ folds",
                )

            ta_result = self._technical_engine.analyze(df, symbol=asset.symbol, timeframe=timeframe)
            if not ta_result.success:
                return EngineResult(success=False, message=f"Technical analysis failed: {ta_result.message}")
            enriched = ta_result.data["df"]

            strategy_fn = self._signal_engine.build_strategy_fn(asset.symbol, timeframe, enriched)

            fold_bounds = np.array_split(np.arange(len(enriched)), n_folds)
            folds: list[FoldResult] = []
            for i, idx in enumerate(fold_bounds):
                if len(idx) < MIN_BARS_PER_FOLD:
                    logger.info("Fold %d for %s has only %d bars (<%d) -- skipping", i, symbol, len(idx), MIN_BARS_PER_FOLD)
                    continue
                fold_df = enriched.iloc[idx[0]: idx[-1] + 1]
                bt_result = self._backtesting_engine.run_backtest(
                    fold_df, strategy_fn, periods_per_year=BARS_PER_YEAR.get(timeframe, 252)
                )
                if not bt_result.success:
                    logger.warning("Fold %d backtest failed for %s: %s", i, symbol, bt_result.message)
                    continue
                r = bt_result.data
                is_sharpe = float(r.metrics.sharpe_ratio)
                oos_sharpe = float(r.parameters.get("oos_sharpe", 0.0))
                folds.append(FoldResult(
                    fold_index=i,
                    n_bars=len(fold_df),
                    is_sharpe=is_sharpe,
                    is_trades=int(r.metrics.total_trades),
                    oos_sharpe=oos_sharpe,
                    passed_validation=bool(r.passed_validation),
                    walk_forward_efficiency=(oos_sharpe / is_sharpe) if is_sharpe > 0 else None,
                ))

            report = self._aggregate(asset.symbol, timeframe, n_folds, folds)
            report.knowledge_context = self._build_knowledge_context(asset.symbol, report.verdict)
            self._set_status(EngineStatus.IDLE)
            return EngineResult(
                success=True, data=report,
                message=f"{symbol}: {report.n_folds_passed}/{report.n_folds_evaluated} folds passed -- verdict={report.verdict}",
            )
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("Walk-forward validation failed for %s: %s", symbol, e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    @staticmethod
    def _aggregate(symbol: str, timeframe: str, n_folds_requested: int, folds: list[FoldResult]) -> WalkForwardReport:
        """
        pass_rate (fraction of folds clearing E26's FULL bar, including its
        30-trade minimum) and oos_sharpe_positive_rate (fraction of folds
        with merely positive OOS Sharpe) are deliberately tracked
        separately: a low-frequency strategy (e.g. a multi-week Donchian
        breakout) can go 5+ folds with consistently positive OOS Sharpe
        while never accumulating 30 trades WITHIN any single ~1.5-year
        fold -- that fold-level trade-count shortfall is not the same
        claim as "no edge," and conflating them into one pass/fail would
        misreport a real, live example (SP500's validated Donchian
        override: 4/5 folds OOS-Sharpe-positive, mean 0.96, 0/5 individually
        clearing the 30-trade bar per fold) as "no_edge" when the honest
        read is "directionally consistent, too few trades per fold to
        confirm at full statistical strength."
        """
        report = WalkForwardReport(
            symbol=symbol, timeframe=timeframe, generated_at=datetime.now(timezone.utc),
            n_folds_requested=n_folds_requested, folds=folds, n_folds_evaluated=len(folds),
        )
        if len(folds) < 2:
            report.verdict = "insufficient_data"
            return report

        n_passed = sum(1 for f in folds if f.passed_validation)
        oos_sharpes = [f.oos_sharpe for f in folds]
        n_positive = sum(1 for s in oos_sharpes if s > 0)
        report.n_folds_passed = n_passed
        report.pass_rate = n_passed / len(folds)
        report.oos_sharpe_mean = float(np.mean(oos_sharpes))
        report.oos_sharpe_std = float(np.std(oos_sharpes))
        report.oos_sharpe_positive_rate = n_positive / len(folds)

        defined_wfe = [f.walk_forward_efficiency for f in folds if f.walk_forward_efficiency is not None]
        report.mean_walk_forward_efficiency = float(np.mean(defined_wfe)) if defined_wfe else None

        if report.pass_rate >= PASS_RATE_STABLE_THRESHOLD and report.oos_sharpe_mean > 0:
            report.verdict = "stable_edge"
        elif report.oos_sharpe_positive_rate >= PASS_RATE_STABLE_THRESHOLD and report.oos_sharpe_mean > 0:
            report.verdict = "directionally_consistent_low_sample"
        elif report.oos_sharpe_positive_rate > 0:
            report.verdict = "unstable_edge"
        else:
            report.verdict = "no_edge"
        return report

    def _build_knowledge_context(self, symbol: str, verdict: str) -> Optional[dict]:
        """Relevant book content on overfitting/walk-forward instability --
        only queried when there's something to explain (unstable/no edge),
        same "nothing to explain, no query" principle as e05/e10/e13/e14/
        e15/e16/e17."""
        if self._knowledge_engine is None or verdict not in ("unstable_edge", "no_edge", "directionally_consistent_low_sample"):
            return None
        try:
            query = f"{symbol} strategy walk-forward validation overfitting {verdict.replace('_', ' ')}"
            results = self._knowledge_engine.document_store.hybrid_search(query, limit=3)
        except Exception as e:
            logger.warning("Knowledge context unavailable: %s", e)
            return None
        if not results:
            return None
        return {"query": query, "results": [r.to_dict() for r in results]}
