"""
Module: engine.py
Description: Engine 74 -- Conflict Resolution. See MASTER_PROMPT.md's
    "PROMPT 5" section: genuinely new -- "Buffett vs Soros: when Buffett
    wins, when Soros wins" taken literally as "compare two rival trading
    PHILOSOPHIES' regime-conditional real performance," grounded in this
    platform's own real, already-backtestable strategy archetypes
    (`e24_strategy_research.strategies`) rather than anything fabricated
    about a specific named individual's actual (private, unknown) rules.
    Directly useful now that the multi-channel YouTube knowledge base
    spans trend-followers (Al Brooks, Adam Grimes) and mean-reversion/
    contrarian voices side by side -- this engine answers "whose style
    would have actually worked, and when" with real backtested numbers,
    never a fabricated verdict about a real person's track record.

    Reuses e37_meta_learning's own real ADX-trending/ranging regime split
    (identical convention, so "regime" means the same thing everywhere on
    this platform) and E26's own real backtest engine -- never a second
    implementation of either.

    Rule 3: no calibration script -- deterministic backtest + regime
    attribution over two already-real strategy functions, same "no"
    category as e37_meta_learning.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np
import pandas as pd

from project_titan_x.core.config import get_asset
from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus
from project_titan_x.engines.e24_strategy_research import strategies as strat_lib
from project_titan_x.engines.e26_backtesting.engine import BacktestingEngine

logger = logging.getLogger(__name__)

MIN_TRADES_PER_REGIME = 5
ADX_ROLLING_WINDOW = 252

# Real, already-backtestable archetypes from e24_strategy_research.strategies --
# never a fabricated rule attributed to a specific real trader.
PHILOSOPHY_LIBRARY: dict[str, Any] = {
    "trend_following_donchian": strat_lib.donchian_breakout,
    "trend_following_ma_cross": strat_lib.ma_cross_50_200,
    "mean_reversion_rsi": strat_lib.rsi_mean_reversion,
    "mean_reversion_bollinger": strat_lib.bollinger_reversion,
    "regime_adaptive": strat_lib.regime_adaptive,
}


def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Identical closed-form ADX to e07/e08/e22/e23/e37 -- reused, not re-derived."""
    high_diff = df["high"].diff()
    low_diff = -df["low"].diff()
    plus_dm = high_diff.where((high_diff > low_diff) & (high_diff > 0), 0.0)
    minus_dm = low_diff.where((low_diff > high_diff) & (low_diff > 0), 0.0)
    tr = pd.concat([
        df["high"] - df["low"], (df["high"] - df["close"].shift()).abs(), (df["low"] - df["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(period).mean() / atr)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.rolling(period).mean()


@dataclass
class PhilosophyRegimePerformance:
    philosophy: str
    regime: str
    n_trades: int
    win_rate_pct: Optional[float]
    expectancy_r: Optional[float]
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "philosophy": self.philosophy, "regime": self.regime, "n_trades": self.n_trades,
            "win_rate_pct": round(self.win_rate_pct, 1) if self.win_rate_pct is not None else None,
            "expectancy_r": round(self.expectancy_r, 4) if self.expectancy_r is not None else None,
            "status": self.status,
        }


@dataclass
class ConflictResolutionReport:
    symbol: str
    timeframe: str
    generated_at: datetime
    philosophy_a: str
    philosophy_b: str
    performance: list[PhilosophyRegimePerformance] = field(default_factory=list)
    verdict: str = "insufficient_data"

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol, "timeframe": self.timeframe, "generated_at": self.generated_at.isoformat(),
            "philosophy_a": self.philosophy_a, "philosophy_b": self.philosophy_b,
            "performance": [p.to_dict() for p in self.performance], "verdict": self.verdict,
        }


class ConflictResolutionEngine(BaseEngine):
    """Conflict Resolution Engine (#74) -- "when Philosophy A wins, when
    Philosophy B wins," grounded in real backtested archetype strategies
    and real regime attribution, never a fabricated verdict about a real
    trader's actual track record."""

    engine_id = "e74_conflict_resolution"
    engine_name = "Conflict Resolution Engine"
    version = "1.0.0"

    def __init__(
        self, market_data_engine: Optional[Any] = None, technical_engine: Optional[Any] = None,
        backtesting_engine: Optional[BacktestingEngine] = None,
    ) -> None:
        super().__init__()
        self._market_data_engine = market_data_engine
        self._technical_engine = technical_engine
        self._backtesting_engine = backtesting_engine if backtesting_engine is not None else BacktestingEngine()

    def initialize(self) -> EngineResult:
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Conflict Resolution Engine initialized")

    def health_check(self) -> EngineResult:
        return EngineResult(success=True, message="Healthy")

    def compare_philosophies(
        self, symbol: str, philosophy_a: str, philosophy_b: str, timeframe: str = "1d",
    ) -> EngineResult:
        if philosophy_a not in PHILOSOPHY_LIBRARY or philosophy_b not in PHILOSOPHY_LIBRARY:
            return EngineResult(success=False, message=f"philosophy must be one of {sorted(PHILOSOPHY_LIBRARY)}")
        if self._market_data_engine is None or self._technical_engine is None:
            return EngineResult(success=False, message="market_data_engine and technical_engine required")
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
                return EngineResult(success=False, message="No ADX column available for regime split")

            adx_median = enriched["adx"].rolling(ADX_ROLLING_WINDOW, min_periods=60).median()
            is_trending = enriched["adx"] > adx_median

            performance: list[PhilosophyRegimePerformance] = []
            for name in (philosophy_a, philosophy_b):
                fn = PHILOSOPHY_LIBRARY[name]
                bt = self._backtesting_engine.run_backtest(enriched, fn)
                if not bt.success or bt.data is None:
                    performance.append(PhilosophyRegimePerformance(name, "trending", 0, None, None, "backtest_failed"))
                    performance.append(PhilosophyRegimePerformance(name, "ranging", 0, None, None, "backtest_failed"))
                    continue
                by_regime: dict[str, list[float]] = {"trending": [], "ranging": []}
                for t in bt.data.trades:
                    idx = t.get("entry_idx")
                    if idx is None or idx >= len(is_trending):
                        continue
                    flag = is_trending.iloc[idx]
                    if flag != flag:
                        continue
                    by_regime["trending" if bool(flag) else "ranging"].append(t["pnl_r"])
                for regime, pnls in by_regime.items():
                    if len(pnls) < MIN_TRADES_PER_REGIME:
                        performance.append(PhilosophyRegimePerformance(name, regime, len(pnls), None, None, "insufficient_data"))
                        continue
                    wins = [p for p in pnls if p > 0]
                    performance.append(PhilosophyRegimePerformance(
                        name, regime, len(pnls), len(wins) / len(pnls) * 100.0, sum(pnls) / len(pnls), "ok",
                    ))

            verdict = self._determine_verdict(performance, philosophy_a, philosophy_b)
            report = ConflictResolutionReport(
                symbol=asset.symbol, timeframe=timeframe, generated_at=datetime.now(timezone.utc),
                philosophy_a=philosophy_a, philosophy_b=philosophy_b, performance=performance, verdict=verdict,
            )
            self._set_status(EngineStatus.IDLE)
            return EngineResult(success=True, data=report, message=f"{symbol}: {verdict}")
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("compare_philosophies failed for %s: %s", symbol, e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    @staticmethod
    def _determine_verdict(performance: list[PhilosophyRegimePerformance], a: str, b: str) -> str:
        ok = [p for p in performance if p.status == "ok"]
        if len(ok) < 2:
            return "insufficient_data"
        by_key = {(p.philosophy, p.regime): p.expectancy_r for p in ok}
        notes = []
        for regime in ("trending", "ranging"):
            ea, eb = by_key.get((a, regime)), by_key.get((b, regime))
            if ea is not None and eb is not None:
                winner = a if ea > eb else b if eb > ea else "tie"
                notes.append(f"{regime}:{winner}")
        return ", ".join(notes) if notes else "insufficient_data"
