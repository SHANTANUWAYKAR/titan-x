"""
Module: engine.py
Description: Engine 10 — Cross-Asset Intelligence (DXY/Gold, Bonds/Stocks,
    Oil/CAD, Yields/USD, VIX/Risk Assets, Copper/Global Growth dependency
    reads + a cross-asset dependency graph).
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-07-16
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
import yfinance as yf
from project_titan_x.core.data_providers.yahoo import ticker_history, ticker_info

from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus
from project_titan_x.engines.e01_knowledge.engine import KnowledgeEngine
from project_titan_x.engines.e12_quant_research.engine import QuantResearchEngine

logger = logging.getLogger(__name__)

_BASELINE_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "e10_cross_asset" / "baseline_correlations.json"

# name -> (ticker_a, label_a, ticker_b, label_b). Pairs and tickers per the
# master prompt's Cross-Asset Intelligence Engine spec: "DXY<->Gold,
# Bonds<->Stocks, Oil<->CAD, Yields<->USD, VIX<->Risk Assets, Copper<->Global
# Growth". No single free "global growth" index exists, so Copper is read
# against ACWI (iShares MSCI ACWI ETF, developed+emerging global equities) as
# an honest, clearly-labeled proxy -- same spirit as e06's TIPS-ETF real-yield
# proxy.
#
# The four "vs" forex pairs below extend the master list with well-known,
# real forex cross-asset relationships (not silently substituting or
# renumbering anything named above): EUR/USD<->GBP/USD as the classic major
# forex-to-forex correlation (shared USD side); USD/JPY<->Yields and
# USD/JPY<->VIX as the standard JPY carry-trade reads (JPY is the classic
# low-yield funding currency, so USD/JPY tracks the US-Japan yield
# differential and unwinds sharply -- USD/JPY down -- when VIX spikes);
# AUD/USD<->Copper as the standard commodity-currency/China-growth read (AUD
# is a textbook growth-sensitive currency, same economic logic as Copper vs
# Global Growth above).
PAIR_DEFINITIONS: list[tuple[str, str, str, str, str]] = [
    ("DXY vs Gold", "DX-Y.NYB", "DXY", "GC=F", "Gold"),
    ("Bonds vs Stocks", "TLT", "Bonds (TLT 20Y+ Treasury)", "^GSPC", "Stocks (S&P 500)"),
    ("Oil vs CAD", "CL=F", "Oil (WTI)", "USDCAD=X", "CAD (USD/CAD)"),
    ("Yields vs USD", "^TNX", "Yields (US 10Y)", "DX-Y.NYB", "USD (DXY)"),
    ("VIX vs Risk Assets", "^VIX", "VIX", "^GSPC", "Risk Assets (S&P 500)"),
    ("Copper vs Global Growth", "HG=F", "Copper", "ACWI", "Global Growth (ACWI proxy)"),
    ("EUR/USD vs GBP/USD", "EURUSD=X", "EUR/USD", "GBPUSD=X", "GBP/USD"),
    ("USD/JPY vs Yields", "USDJPY=X", "USD/JPY", "^TNX", "Yields (US 10Y)"),
    ("USD/JPY vs VIX", "USDJPY=X", "USD/JPY", "^VIX", "VIX"),
    ("AUD/USD vs Copper", "AUDUSD=X", "AUD/USD", "HG=F", "Copper"),
]

ROLLING_WINDOW_DAYS = 60
LIVE_LOOKBACK_PERIOD = "2y"
REGIME_SHIFT_THRESHOLD = 0.3  # |current - baseline| above this => not "intact"
INVERSION_ABS_THRESHOLD = 0.15  # current must be at least this large to call a sign-flip "inverted" rather than noise


@dataclass
class CrossAssetPairResult:
    """One named cross-asset relationship's current read."""

    name: str
    ticker_a: str
    label_a: str
    ticker_b: str
    label_b: str
    current_correlation: float  # ROLLING_WINDOW_DAYS-period correlation, freshly computed
    full_period_correlation: float  # LIVE_LOOKBACK_PERIOD correlation, freshly computed
    baseline_correlation: Optional[float]  # long-run calibrated baseline; None if uncalibrated
    delta_vs_baseline: Optional[float]
    regime: str  # "intact" | "weakening" | "breaking_down" | "inverted" | "uncalibrated"
    # Added 2026-08-02: lead-lag read -- classical intermarket analysis
    # (Murphy) asks not just "how correlated are these two" but "does one
    # tend to lead the other," a genuinely different question than the
    # contemporaneous correlation above. best_lag_days > 0 means asset A
    # leads B (A's move today best predicts B's move `best_lag_days` days
    # later); < 0 means B leads A; 0 means the strongest relationship is
    # contemporaneous, no real lead-lag structure detected.
    best_lag_days: Optional[int] = None
    best_lag_correlation: Optional[float] = None


@dataclass
class CrossAssetSnapshot:
    """Full cross-asset intelligence read: named pairs + dependency graph."""

    timestamp: datetime
    pairs: list[CrossAssetPairResult] = field(default_factory=list)
    dependency_graph: dict[str, Any] = field(default_factory=dict)
    flagged_pairs: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    knowledge_context: Optional[dict] = None


class CrossAssetIntelligenceEngine(BaseEngine):
    """
    Cross-Asset Intelligence Engine (#10) — tracks well-known cross-asset
    relationships (DXY/Gold, Bonds/Stocks, Oil/CAD, Yields/USD, VIX/Risk
    Assets, Copper/Global Growth) and flags when one is breaking down or
    inverting relative to its long-run calibrated baseline. Purely
    descriptive/interpretive -- reads real price history, never places or
    recommends a trade.

    Reuses QuantResearchEngine.rolling_correlation for the actual matrix
    math (recent-window vs full-period correlation across all tracked
    tickers at once) rather than reimplementing correlation computation.
    """

    engine_id = "e10_cross_asset"
    engine_name = "Cross-Asset Intelligence Engine"
    version = "1.0.0"

    def __init__(
        self,
        knowledge_engine: Optional[KnowledgeEngine] = None,
        quant_engine: Optional[QuantResearchEngine] = None,
    ) -> None:
        super().__init__()
        # Optional and None by default: without it, analyze() behaves
        # exactly as before (no knowledge_context). Pass a real instance
        # (as registry.py does) to turn it on.
        self._knowledge_engine = knowledge_engine
        self._quant_engine = quant_engine if quant_engine is not None else QuantResearchEngine()
        self._baseline = self._load_baseline()

    def initialize(self) -> EngineResult:
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Cross-Asset Intelligence Engine initialized")

    def health_check(self) -> EngineResult:
        try:
            hist = ticker_history("^GSPC", "5d", context="e10.spx")
            if hist.empty:
                raise ValueError("S&P 500 data unavailable")
            return EngineResult(success=True, message="Healthy")
        except Exception as e:
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    @staticmethod
    def _load_baseline() -> dict[str, float]:
        """Long-run calibrated baseline correlation per named pair, from
        scripts/training/train_e10_cross_asset.py. Empty (not fabricated)
        if the calibration hasn't been run yet -- see Rule 4, never guess."""
        if not _BASELINE_PATH.exists():
            return {}
        try:
            data = json.loads(_BASELINE_PATH.read_text())
            return {k: float(v["baseline_correlation"]) for k, v in data.get("pairs", {}).items()}
        except Exception as e:
            logger.warning("Failed to load E10 baseline correlations from %s: %s", _BASELINE_PATH, e)
            return {}

    def analyze(
        self,
        lookback_period: str = LIVE_LOOKBACK_PERIOD,
        rolling_window: int = ROLLING_WINDOW_DAYS,
    ) -> EngineResult:
        """Fetch real price history for every tracked ticker, compute
        rolling vs full-period correlation for each named pair, compare
        against the calibrated baseline, and build a dependency graph."""
        try:
            self._set_status(EngineStatus.RUNNING)
            unique_tickers = sorted({t for _, ta, _, tb, _ in PAIR_DEFINITIONS for t in (ta, tb)})

            closes: dict[str, pd.Series] = {}
            for ticker in unique_tickers:
                try:
                    hist = ticker_history(ticker, lookback_period, context="e10")
                    if not hist.empty:
                        series = hist["Close"]
                        # Different tickers (futures/forex/indices) can come back
                        # with different exchange timezones -- normalize each to
                        # tz-naive dates individually before combining, otherwise
                        # pandas can't align a shared index across mismatched tzs.
                        series.index = series.index.tz_localize(None).normalize()
                        closes[ticker] = series
                except Exception as e:
                    logger.warning("Failed to fetch %s: %s", ticker, e)

            missing = set(unique_tickers) - set(closes)
            if missing:
                return EngineResult(
                    success=False,
                    message=f"Could not fetch data for: {', '.join(sorted(missing))}",
                )

            df = pd.DataFrame(closes)
            df = df.dropna()
            if len(df) < rolling_window + 5:
                return EngineResult(
                    success=False,
                    message=f"Need at least {rolling_window + 5} aligned trading days, got {len(df)}",
                )

            returns = df.pct_change().dropna()
            returns_by_symbol = {c: returns[c].to_numpy() for c in returns.columns}

            corr_result = self._quant_engine.rolling_correlation(returns_by_symbol, window=rolling_window)
            if not corr_result.success:
                return EngineResult(success=False, message=f"Correlation computation failed: {corr_result.message}")

            rc = corr_result.data
            symbols = rc.symbols
            recent = np.array(rc.recent_correlation_matrix)
            full = np.array(rc.full_period_correlation_matrix)

            pairs: list[CrossAssetPairResult] = []
            flagged: list[str] = []
            nodes: set = set()
            edges: list[dict[str, Any]] = []
            notes: list[str] = []

            for name, ticker_a, label_a, ticker_b, label_b in PAIR_DEFINITIONS:
                if ticker_a not in symbols or ticker_b not in symbols:
                    continue
                i, j = symbols.index(ticker_a), symbols.index(ticker_b)
                current_corr = float(recent[i, j])
                full_corr = float(full[i, j])
                baseline = self._baseline.get(name)
                regime, delta = self._classify_regime(current_corr, baseline)
                best_lag, best_lag_corr = self._lead_lag_scan(returns, ticker_a, ticker_b)

                pairs.append(
                    CrossAssetPairResult(
                        name=name,
                        ticker_a=ticker_a,
                        label_a=label_a,
                        ticker_b=ticker_b,
                        label_b=label_b,
                        current_correlation=round(current_corr, 3),
                        full_period_correlation=round(full_corr, 3),
                        baseline_correlation=baseline,
                        delta_vs_baseline=delta,
                        regime=regime,
                        best_lag_days=best_lag,
                        best_lag_correlation=best_lag_corr,
                    )
                )
                if regime not in ("intact", "uncalibrated"):
                    flagged.append(name)
                    notes.append(f"{name}: {regime} (current={current_corr:.2f}, baseline={baseline:.2f})")

                nodes.update([label_a, label_b])
                edges.append({"a": label_a, "b": label_b, "weight": round(current_corr, 3), "regime": regime})

            if not self._baseline:
                notes.append(
                    "No calibrated baselines found -- run scripts/training/train_e10_cross_asset.py. "
                    "All pairs report regime='uncalibrated' until then."
                )

            snapshot = CrossAssetSnapshot(
                timestamp=datetime.now(timezone.utc),
                pairs=pairs,
                dependency_graph={"nodes": sorted(nodes), "edges": edges},
                flagged_pairs=flagged,
                notes=notes,
                knowledge_context=self._build_knowledge_context(flagged),
            )

            self._set_status(EngineStatus.IDLE)
            return EngineResult(
                success=True,
                data=snapshot,
                message=f"Cross-asset analysis complete ({len(flagged)} pair(s) flagged)",
                metadata={"flagged_pairs": flagged},
            )
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("Cross-asset analysis failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    @staticmethod
    def _lead_lag_scan(returns: pd.DataFrame, ticker_a: str, ticker_b: str, max_lag: int = 5) -> tuple[int, float]:
        """Scans correlation(A_t, B_{t+lag}) for lag in [-max_lag, max_lag]
        (excluding 0, already known as the contemporaneous correlation)
        and returns the (lag, correlation) pair with the largest absolute
        correlation, only if it clearly exceeds the contemporaneous
        reading -- classical intermarket analysis' lead-lag question,
        distinct from (and previously absent alongside) the pure
        contemporaneous correlation this engine already computes.
        Positive lag: A's move at time t best correlates with B's move
        `lag` periods later (A leads B). Negative: B leads A. Requires the
        lagged correlation to beat the contemporaneous one by a real
        margin (0.05) before reporting a nonzero lag -- otherwise lag=0
        is returned, an honest "no real lead-lag structure" read rather
        than reporting noise as a leading indicator."""
        a = returns[ticker_a]
        contemporaneous = float(a.corr(returns[ticker_b]))
        best_lag, best_corr = 0, contemporaneous
        for lag in range(-max_lag, max_lag + 1):
            if lag == 0:
                continue
            b_shifted = returns[ticker_b].shift(-lag)
            valid = a.notna() & b_shifted.notna()
            if valid.sum() < 30:
                continue
            corr = float(a[valid].corr(b_shifted[valid]))
            if abs(corr) > abs(best_corr):
                best_lag, best_corr = lag, corr
        if abs(best_corr) - abs(contemporaneous) < 0.05:
            return 0, round(contemporaneous, 3)
        return best_lag, round(best_corr, 3)

    @staticmethod
    def _classify_regime(current: float, baseline: Optional[float]) -> tuple[str, Optional[float]]:
        if baseline is None:
            return "uncalibrated", None
        delta = round(current - baseline, 3)
        if abs(delta) <= REGIME_SHIFT_THRESHOLD:
            return "intact", delta
        if (current >= 0) != (baseline >= 0) and abs(current) > INVERSION_ABS_THRESHOLD:
            return "inverted", delta
        return "breaking_down", delta

    def _build_knowledge_context(self, flagged_pairs: list[str]) -> Optional[dict]:
        """Relevant book content for flagged (non-intact) cross-asset
        relationships -- informational only, never changes a pair's
        computed correlation or regime classification. No query is built
        (and no lookup runs) when every tracked pair is intact, since
        there is nothing interpretively notable to explain (same principle
        as e05_economic_calendar: no events in window -> no query)."""
        if self._knowledge_engine is None or not flagged_pairs:
            return None
        try:
            query = "cross-asset correlation breakdown: " + ", ".join(flagged_pairs)
            results = self._knowledge_engine.document_store.hybrid_search(query, limit=3)
        except Exception as e:
            logger.warning("Knowledge context unavailable: %s", e)
            return None
        if not results:
            return None
        return {"query": query, "results": [r.to_dict() for r in results]}
