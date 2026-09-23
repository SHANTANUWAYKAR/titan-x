"""
Module: engine.py
Description: Engine 37 -- Meta-Learning. Master prompt scope (line 507,
    draft item #30 "Meta-Learning Engine", kept for detail per Rule 1;
    slot #37 in the authoritative MAJOR ENGINES list is "Meta-Learning
    Engine"): "learn which STRATEGIES work in which REGIMES (strategy
    selection), not just individual trade outcomes."

    Attributes each REAL trade from a real E26 backtest of the EXACT live
    rule e51_signals resolves for an asset (same build_strategy_fn
    dependency E27/E28/E30 already use) to the regime its ENTRY bar was
    actually in, then compares win rate/expectancy between regimes.
    Deliberately NOT a second full backtest run per regime subset: slicing
    a discontiguous trending/ranging mask out of the price series and
    re-running E26's sequential bar-by-bar simulation on it would create
    artificial price jumps at every gap boundary (a trending bar
    immediately after a large ranging-regime gap would compute its
    return across the skipped gap) -- a real, considered pitfall, not an
    oversight. Post-hoc grouping of a single continuous backtest's own
    real trades sidesteps this entirely, the same principle E34 Trade
    Attribution already uses for the live journal (group real outcomes by
    regime, don't refabricate them).

    "Regime" here means the identical ADX-based trending/ranging
    definition already shared by e07_technical/e08_regime/
    e22_alpha_research/e23_forecasting (ADX above/below its own trailing
    252-bar median) -- reused directly from e07_technical's own enriched
    `adx` column, not recomputed a second time (Rule 4).

    Rule 3: no calibration script for learn_regime_fit() itself --
    deterministic post-hoc grouping of E26's own real backtest trades,
    same "no" category as e34_trade_attribution/e38_alpha_decay_monitor
    (statistical comparison of another engine's already-real results, no
    parameters of its own to fit).

    Live-pipeline wiring (added 2026-08-05): learn_regime_fit() itself
    runs a full E26 backtest -- too expensive to re-run on every
    e51_signals.generate_signal() call (the exact "don't compute the same
    expensive thing twice" lesson e22_alpha_research's own live-confluence
    method already documents). `scripts/training/train_e37_meta_learning.py`
    runs it ONCE per supported asset and persists the verdict to
    `data/models/e37_meta_learning/regime_fit_database.json` -- the SAME
    precomputed-database pattern e22_alpha_research.lookup_relevant_alpha
    already established. `evaluate_live_confluence` does a CHEAP read of
    that file plus one fresh `fetch_ohlcv` call (same cost E22's own live
    check already pays) to check whether the asset is CURRENTLY in the
    regime its own backtest found best, applying the identical
    (multiplier, evidence) contract as every other `e51_signals.
    _confluence_*` check.
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

import numpy as np
import pandas as pd

from project_titan_x.core.config import get_asset
from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus
from project_titan_x.engines.e01_knowledge.engine import KnowledgeEngine
from project_titan_x.engines.e02_market_data.engine import MarketDataEngine
from project_titan_x.engines.e07_technical.engine import TechnicalAnalysisEngine
from project_titan_x.engines.e26_backtesting.engine import BacktestingEngine
from project_titan_x.engines.e51_signals.engine import _load_strategy_override

logger = logging.getLogger(__name__)

REGIME_FIT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "e37_meta_learning" / "regime_fit_database.json"


def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Identical closed-form ADX to e07_technical/e08_regime/
    e22_alpha_research/e23_forecasting -- reused, not re-derived, so
    'trending' means the same thing everywhere on this platform."""
    high_diff = df["high"].diff()
    low_diff = -df["low"].diff()
    plus_dm = high_diff.where((high_diff > low_diff) & (high_diff > 0), 0.0)
    minus_dm = low_diff.where((low_diff > high_diff) & (low_diff > 0), 0.0)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift()).abs(),
        (df["low"] - df["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(period).mean() / atr)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.rolling(period).mean()

MIN_TRADES_PER_REGIME = 5  # below this, a per-regime win rate is too noisy to report honestly
ADX_ROLLING_WINDOW = 252  # trailing ~1yr, identical convention to e22/e23's own trending-regime split


@dataclass
class RegimePerformance:
    regime: str  # "trending" | "ranging"
    n_trades: int
    win_rate_pct: Optional[float]
    expectancy_r: Optional[float]
    status: str  # "ok" | "insufficient_data"

    def to_dict(self) -> dict[str, Any]:
        return {
            "regime": self.regime,
            "n_trades": self.n_trades,
            "win_rate_pct": round(self.win_rate_pct, 1) if self.win_rate_pct is not None else None,
            "expectancy_r": round(self.expectancy_r, 4) if self.expectancy_r is not None else None,
            "status": self.status,
        }


@dataclass
class MetaLearningReport:
    symbol: str
    timeframe: str
    generated_at: datetime
    strategy_label: str
    regime_performance: list[RegimePerformance] = field(default_factory=list)
    best_regime: Optional[str] = None
    verdict: str = "insufficient_data"  # regime_dependent | regime_consistent | insufficient_data
    knowledge_context: Optional[dict] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "generated_at": self.generated_at.isoformat(),
            "strategy_label": self.strategy_label,
            "regime_performance": [r.to_dict() for r in self.regime_performance],
            "best_regime": self.best_regime,
            "verdict": self.verdict,
            "knowledge_context": self.knowledge_context,
        }


class MetaLearningEngine(BaseEngine):
    """Meta-Learning Engine (#37) -- learns which REGIME the EXACT live
    strategy rule for an asset actually performs in, by attributing real
    E26 backtest trades to their real entry-bar regime."""

    engine_id = "e37_meta_learning"
    engine_name = "Meta-Learning Engine"
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
        return EngineResult(success=True, message="Meta-Learning Engine initialized")

    def health_check(self) -> EngineResult:
        return EngineResult(success=True, message="Healthy")

    def learn_regime_fit(self, symbol: str, timeframe: str = "1d") -> EngineResult:
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

            ta_result = self._technical_engine.analyze(fetch.data, symbol=asset.symbol, timeframe=timeframe)
            if not ta_result.success:
                return EngineResult(success=False, message=f"Technical analysis failed: {ta_result.message}")
            enriched = ta_result.data["df"].reset_index(drop=True)
            if "adx" not in enriched.columns:
                return EngineResult(success=False, message="Technical analysis did not produce an ADX column")

            strategy_fn = self._signal_engine.build_strategy_fn(asset.symbol, timeframe, enriched)
            bt = self._backtesting_engine.run_backtest(enriched, strategy_fn)
            if not bt.success or bt.data is None:
                return EngineResult(success=False, message=f"Backtest failed: {bt.message}")
            trades = bt.data.trades
            override = _load_strategy_override(asset.yahoo_symbol, timeframe)
            strategy_label = override.get("strategy") if override else "baseline_composite_rule"

            adx_median = enriched["adx"].rolling(ADX_ROLLING_WINDOW, min_periods=60).median()

            by_regime: dict[str, list[float]] = {"trending": [], "ranging": []}
            for t in trades:
                idx = t.get("entry_idx")
                if idx is None or idx >= len(enriched):
                    continue
                # Checked on the raw adx/adx_median values, not on
                # `adx > adx_median`: a NaN comparison evaluates to False
                # (never NaN) in pandas/numpy, so testing the comparison
                # result itself for NaN never fires and silently mislabels
                # every not-enough-history bar "ranging".
                adx_at_entry = enriched["adx"].iloc[idx]
                median_at_entry = adx_median.iloc[idx]
                if pd.isna(adx_at_entry) or pd.isna(median_at_entry):
                    continue
                regime = "trending" if adx_at_entry > median_at_entry else "ranging"
                by_regime[regime].append(t["pnl_r"])

            regime_performance: list[RegimePerformance] = []
            for regime, pnls in by_regime.items():
                if len(pnls) < MIN_TRADES_PER_REGIME:
                    regime_performance.append(RegimePerformance(regime, len(pnls), None, None, "insufficient_data"))
                    continue
                wins = [p for p in pnls if p > 0]
                win_rate = len(wins) / len(pnls) * 100.0
                expectancy = sum(pnls) / len(pnls)
                regime_performance.append(RegimePerformance(regime, len(pnls), win_rate, expectancy, "ok"))

            verdict, best_regime = self._determine_verdict(regime_performance)
            report = MetaLearningReport(
                symbol=asset.symbol, timeframe=timeframe, generated_at=datetime.now(timezone.utc),
                strategy_label=strategy_label, regime_performance=regime_performance,
                best_regime=best_regime, verdict=verdict,
            )
            report.knowledge_context = self._build_knowledge_context(asset.symbol, verdict)
            self._set_status(EngineStatus.IDLE)
            return EngineResult(
                success=True, data=report,
                message=f"{symbol}: {verdict}" + (f", best regime={best_regime}" if best_regime else ""),
            )
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("Meta-learning regime-fit failed for %s: %s", symbol, e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def lookup_regime_fit(self, symbol: str) -> Optional[dict]:
        """Fast, cheap read of the already-computed regime-fit database
        (see this module's own docstring) -- never re-runs
        learn_regime_fit's own real backtest on the live signal path."""
        if not REGIME_FIT_DB_PATH.exists():
            return None
        try:
            db = json.loads(REGIME_FIT_DB_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("Regime-fit database unreadable (%s)", e)
            return None
        return db.get(symbol)

    def evaluate_live_confluence(self, symbol: str, direction: str) -> Optional[tuple[float, str]]:
        """Same (multiplier, evidence) contract as every other
        e51_signals._confluence_* check. Only nudges confidence when the
        precomputed database found this asset's live strategy to be
        genuinely regime_dependent (profitable in only ONE regime) --
        never for regime_consistent/insufficient_data assets, same
        "only when validated" discipline e17_crypto's own confluence
        weighting already uses.

        Added 2026-09-13 (closing a gap both PDFs in data/PDF/ flagged --
        "IC-weighted confluence," down-weighting a layer by how much it
        actually predicts, not a hand-picked flat number): pulled
        `regime_fit_database.json` for every regime_dependent asset and
        found the "wrong regime" penalty was a FLAT 0.90 regardless of
        how bad that regime actually was for the asset -- real numbers
        range from BHARTIARTL's worst-regime expectancy of -0.0084R
        (n=97, essentially breakeven -- noise, not a real effect) to
        SILVER's -1.3928R (n=33, a genuinely severe historical loser).
        The flat number was overpenalizing the former and underpenalizing
        the latter using data this engine had already measured and
        validated (real E26 backtest trades, causal trailing-ADX regime
        labels -- see learn_regime_fit's own rolling-median comment).
        `_wrong_regime_multiplier` now scales with the MEASURED
        expectancy_r of the regime the asset is currently in, using
        nothing not already in the database -- no new data, no new
        fabrication, just using the number that was already sitting
        there instead of discarding it for a flat constant. The IN-best-
        regime boost stays flat at 1.05: every regime_dependent verdict's
        best-regime expectancy is positive by construction
        (_determine_verdict requires it), so there's no equivalent
        evidence gap to close on that side."""
        entry = self.lookup_regime_fit(symbol)
        if entry is None or entry.get("verdict") != "regime_dependent":
            return None
        best_regime = entry.get("best_regime")
        if best_regime not in ("trending", "ranging"):
            return None
        try:
            is_trending_now = self._current_trending_state(symbol)
        except Exception as e:
            logger.warning("Live regime check failed for %s: %s", symbol, e)
            return None
        if is_trending_now is None:
            return None
        current_regime = "trending" if is_trending_now else "ranging"
        if current_regime == best_regime:
            return 1.05, f"Meta-learning: {symbol}'s live strategy is validated as regime_dependent and currently IN its best regime ({best_regime}, E37)"
        multiplier = self._wrong_regime_multiplier(entry, current_regime)
        return multiplier, f"Meta-learning: {symbol}'s live strategy is validated as regime_dependent and currently OUTSIDE its best regime (now {current_regime}, needs {best_regime}, E37)"

    # Below this trade count, a specific expectancy_r number is too noisy
    # to scale a penalty from -- fall back to the original flat -10%
    # rather than let a handful of trades drive a large adjustment.
    # MIN_TRADES_PER_REGIME (5) governs whether the verdict/database entry
    # exists AT ALL; this is a separate, stricter bar for trusting the
    # exact MAGNITUDE of that entry's expectancy_r.
    MIN_TRADES_FOR_SCALED_PENALTY = 20
    _FLAT_FALLBACK_MULTIPLIER = 0.90
    _SCALED_PENALTY_FLOOR = 0.60  # never more than a 40% haircut off one metric
    _EXPECTANCY_TO_PENALTY_SCALE = 0.20  # -1R of measured expectancy -> -20% multiplier

    @classmethod
    def _wrong_regime_multiplier(cls, entry: dict, current_regime: str) -> float:
        """Scales the wrong-regime confidence penalty by how bad
        `current_regime` has REALLY been for this asset's live strategy,
        per regime_fit_database.json's own already-validated
        regime_performance entries -- see evaluate_live_confluence's
        docstring for the real numbers that motivated this. Smoothly
        interpolates from ~1.0 (measured expectancy near breakeven --
        the "wrong" regime isn't actually costing anything) down to a
        floor of 0.60 (measured expectancy at or below -2R -- a severe,
        well-evidenced historical loser), clipped so a single outlier
        metric can never swing the multiplier outside [floor, 1.0].
        Falls back to the original flat 0.90 when the sample backing
        that specific number is too thin to trust its magnitude."""
        for perf in entry.get("regime_performance", []):
            if perf.get("regime") != current_regime:
                continue
            expectancy_r = perf.get("expectancy_r")
            n_trades = perf.get("n_trades", 0)
            if expectancy_r is None or n_trades < cls.MIN_TRADES_FOR_SCALED_PENALTY:
                return cls._FLAT_FALLBACK_MULTIPLIER
            raw = 1.0 + max(expectancy_r, -2.0) * cls._EXPECTANCY_TO_PENALTY_SCALE
            return max(cls._SCALED_PENALTY_FLOOR, min(1.0, raw))
        return cls._FLAT_FALLBACK_MULTIPLIER

    def _current_trending_state(self, symbol: str) -> Optional[bool]:
        """True if `symbol` is trending (ADX above its own trailing
        252-day median) right now -- identical convention to
        e22_alpha_research's own live confluence check."""
        asset = get_asset(symbol)
        yahoo_symbol = asset.yahoo_symbol if asset else symbol
        fetch = self._market_data_engine.fetch_ohlcv(yahoo_symbol, "1d", years=2)
        if not fetch.success or fetch.data is None or len(fetch.data) < 260:
            return None
        df = fetch.data.reset_index(drop=True)
        adx = _adx(df)
        median = adx.tail(252).median()
        latest = adx.iloc[-1]
        if pd.isna(latest) or pd.isna(median):
            return None
        return bool(latest > median)

    @staticmethod
    def _determine_verdict(regime_performance: list[RegimePerformance]) -> tuple[str, Optional[str]]:
        valid = [r for r in regime_performance if r.status == "ok"]
        if len(valid) < 2:
            single = valid[0] if valid else None
            return "insufficient_data", (single.regime if single and single.expectancy_r and single.expectancy_r > 0 else None)
        valid.sort(key=lambda r: r.expectancy_r, reverse=True)
        best, worst = valid[0], valid[-1]
        # regime_dependent: the strategy is only profitable in ONE regime
        # (worst regime's expectancy is non-positive while best is
        # clearly positive) -- a genuine, actionable "don't run this
        # strategy in that regime" finding, not just noise.
        if best.expectancy_r > 0 and worst.expectancy_r <= 0:
            return "regime_dependent", best.regime
        return "regime_consistent", best.regime

    def _build_knowledge_context(self, symbol: str, verdict: str) -> Optional[dict]:
        """Only queried when a real regime-dependency was found --
        "nothing to explain, no query" principle, same as
        e05/e10/e13/.../e28/e29/e30."""
        if self._knowledge_engine is None or verdict != "regime_dependent":
            return None
        try:
            query = f"{symbol} strategy regime dependent trend following mean reversion market conditions"
            results = self._knowledge_engine.document_store.hybrid_search(query, limit=3)
        except Exception as e:
            logger.warning("Knowledge context unavailable: %s", e)
            return None
        if not results:
            return None
        return {"query": query, "results": [r.to_dict() for r in results]}
