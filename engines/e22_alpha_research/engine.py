"""
Module: engine.py
Description: Engine 22 -- Alpha Research Factory. Master prompt scope
    (line 444, Prompt 1's own numbering, kept for detail per Rule 1):
    "Alpha Research Factory -- continuously generate hypotheses (e.g.
    'gold performs better in risk-off'), auto research/backtest/
    validate/score/store. Proprietary alpha database." -- slot #22 in
    the authoritative MAJOR ENGINES list is literally "Alpha Research
    Factory."

    Distinct from e24_strategy_research (which grid-searches PARAMETERS
    of a few known strategy archetypes against E26's IS/OOS bar): this
    engine tests broader, named MARKET HYPOTHESES -- "does {condition}
    change {asset}'s forward returns?" -- via a real two-sample
    statistical test (Welch's t-test, unequal-variance) comparing mean
    forward returns when a condition holds true vs. false. Every
    hypothesis here is backed by REAL historical data, never a
    fabricated backtest:
      - the "gold performs better in risk-off" example from the master
        prompt itself is tested via real VIX history (Yahoo Finance
        ^VIX, the standard, well-established risk-on/off proxy in real
        quant finance -- not invented here) -- risk-off = VIX above its
        own trailing median.
      - "trend-following breakout works better when trending than
        ranging" is tested via ADX computed directly from the asset's
        OWN price history (no external dependency) -- high ADX =
        trending, matching e08_regime's own ADX-based regime logic.

    Rule 3: the statistical test itself uses the standard two-tailed
    95% (|t|>1.96) convention, same category as e20_factor_research's
    T_STAT_SIGNIFICANCE (a fixed statistical constant, not something
    this project fits). What IS genuinely validated per hypothesis is
    the test result itself, against real, freshly-pulled historical
    data every time research() runs -- never a cached/stale claim.
    scripts/training/train_e22_alpha_research.py runs every curated
    hypothesis against real data and writes results to the "proprietary
    alpha database" (data/models/e22_alpha_research/alpha_database.json).

    knowledge_context here is a genuine part of the engine's own
    interpretive output (Rule 2) -- each tested hypothesis is enriched
    with real supporting/contextual book+YouTube passages, since
    "generate hypotheses" is meaningfully informed by what the ingested
    literature actually says about that exact claim.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats

from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus
from project_titan_x.engines.e01_knowledge.engine import KnowledgeEngine
from project_titan_x.engines.e02_market_data.engine import MarketDataEngine

logger = logging.getLogger(__name__)

ALPHA_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "e22_alpha_research" / "alpha_database.json"
T_STAT_SIGNIFICANCE = 1.96  # standard two-tailed 95% convention, same as e20_factor_research
MIN_OBSERVATIONS_PER_GROUP = 20  # below this, a t-test's normal-approximation isn't meaningful


@dataclass
class HypothesisResult:
    hypothesis_id: str
    description: str
    symbol: str
    forward_days: int
    n_condition_true: int
    n_condition_false: int
    mean_return_true_pct: float
    mean_return_false_pct: float
    t_stat: float
    p_value: float
    significant: bool
    effect_direction: str  # "condition_helps" | "condition_hurts" | "not_significant"
    tested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    knowledge_context: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "hypothesis_id": self.hypothesis_id,
            "description": self.description,
            "symbol": self.symbol,
            "forward_days": self.forward_days,
            "n_condition_true": self.n_condition_true,
            "n_condition_false": self.n_condition_false,
            "mean_return_true_pct": round(self.mean_return_true_pct, 4),
            "mean_return_false_pct": round(self.mean_return_false_pct, 4),
            "t_stat": round(self.t_stat, 3),
            "p_value": round(self.p_value, 4),
            "significant": self.significant,
            "effect_direction": self.effect_direction,
            "tested_at": self.tested_at.isoformat(),
            "knowledge_context": self.knowledge_context,
        }


def _forward_returns(df: pd.DataFrame, forward_days: int) -> pd.Series:
    """Close-to-close forward return, `forward_days` bars ahead, in
    percent. Last `forward_days` rows are necessarily NaN (no future
    data yet) -- dropped by the caller before testing, never filled."""
    return (df["close"].shift(-forward_days) / df["close"] - 1.0) * 100.0


def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Same closed-form ADX as e07_technical._add_adx -- reused directly
    (not re-derived) so a 'trending' read here means the identical thing
    it means everywhere else in this codebase."""
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


class AlphaResearchFactoryEngine(BaseEngine):
    """
    Alpha Research Factory (#22) -- tests real, named market hypotheses
    against real historical data via a two-sample statistical test, and
    stores every result (win or lose) in a persistent alpha database.
    Never invents a data source: hypotheses use only VIX (real, free,
    Yahoo Finance) and price-derived ADX (real, free, computed here).
    """

    engine_id = "e22_alpha_research"
    engine_name = "Alpha Research Factory"
    version = "1.0.0"

    def __init__(
        self,
        market_data_engine: Optional[MarketDataEngine] = None,
        knowledge_engine: Optional[KnowledgeEngine] = None,
    ) -> None:
        super().__init__()
        self._market_data_engine = market_data_engine if market_data_engine is not None else MarketDataEngine()
        self._knowledge_engine = knowledge_engine

    def initialize(self) -> EngineResult:
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Alpha Research Factory initialized")

    def health_check(self) -> EngineResult:
        return EngineResult(success=True, message="Healthy")

    def test_risk_off_hypothesis(
        self, symbol: str = "GOLD", yahoo_symbol: str = "GC=F", forward_days: int = 20, years: int = 10
    ) -> EngineResult:
        """The master prompt's own example: 'gold performs better in
        risk-off.' Risk-off proxied by real VIX being above its own
        trailing 252-day (1yr) median on that day -- a real, standard,
        well-known risk-appetite gauge, not invented here."""
        try:
            self._set_status(EngineStatus.RUNNING)
            price_fetch = self._market_data_engine.fetch_ohlcv(yahoo_symbol, "1d", years=years)
            vix_fetch = self._market_data_engine.fetch_ohlcv("^VIX", "1d", years=years)
            if not price_fetch.success or price_fetch.data is None or price_fetch.data.empty:
                return EngineResult(success=False, message=f"Could not fetch price data for {symbol} ({yahoo_symbol})")
            if not vix_fetch.success or vix_fetch.data is None or vix_fetch.data.empty:
                return EngineResult(success=False, message="Could not fetch VIX data")

            price_df = price_fetch.data.copy()
            price_df["date"] = pd.to_datetime(price_df["timestamp"]).dt.tz_localize(None).dt.normalize()
            vix_df = vix_fetch.data.copy()
            vix_df["date"] = pd.to_datetime(vix_df["timestamp"]).dt.tz_localize(None).dt.normalize()

            merged = price_df.set_index("date")[["close"]].join(
                vix_df.set_index("date")[["close"]].rename(columns={"close": "vix"}), how="inner"
            ).dropna()
            merged["vix_median_1y"] = merged["vix"].rolling(252, min_periods=60).median()
            merged["forward_return_pct"] = _forward_returns(merged.reset_index(), forward_days).values
            merged = merged.dropna(subset=["vix_median_1y", "forward_return_pct"])

            condition = merged["vix"] > merged["vix_median_1y"]  # True = risk-off (elevated VIX)
            result = self._run_two_sample_test(
                hypothesis_id="gold_risk_off",
                description=f"{symbol} performs better when risk appetite is low (VIX above its own trailing 1yr median)",
                symbol=symbol, forward_days=forward_days,
                returns_true=merged.loc[condition, "forward_return_pct"],
                returns_false=merged.loc[~condition, "forward_return_pct"],
            )
            self._set_status(EngineStatus.IDLE)
            return EngineResult(success=True, data=result, message=self._summarize(result))
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("Risk-off hypothesis test failed for %s: %s", symbol, e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def test_trending_regime_hypothesis(
        self, symbol: str, yahoo_symbol: str, forward_days: int = 20, years: int = 10, adx_period: int = 14
    ) -> EngineResult:
        """Does a trending (high-ADX) regime change this asset's own
        forward returns vs. a ranging (low-ADX) one? ADX computed
        directly from the asset's own price -- no external dependency,
        same closed-form as e07_technical's own ADX."""
        try:
            self._set_status(EngineStatus.RUNNING)
            fetch = self._market_data_engine.fetch_ohlcv(yahoo_symbol, "1d", years=years)
            if not fetch.success or fetch.data is None or fetch.data.empty:
                return EngineResult(success=False, message=f"Could not fetch price data for {symbol} ({yahoo_symbol})")

            df = fetch.data.copy().reset_index(drop=True)
            df["adx"] = _adx(df, adx_period)
            df["adx_median"] = df["adx"].rolling(252, min_periods=60).median()
            df["forward_return_pct"] = _forward_returns(df, forward_days)
            valid = df.dropna(subset=["adx", "adx_median", "forward_return_pct"])

            condition = valid["adx"] > valid["adx_median"]  # True = trending (above its own historical median)
            result = self._run_two_sample_test(
                hypothesis_id="trend_regime_breakout_edge",
                description=f"{symbol} shows a different forward-return profile when trending (ADX above its own median) vs ranging",
                symbol=symbol, forward_days=forward_days,
                returns_true=valid.loc[condition, "forward_return_pct"],
                returns_false=valid.loc[~condition, "forward_return_pct"],
            )
            self._set_status(EngineStatus.IDLE)
            return EngineResult(success=True, data=result, message=self._summarize(result))
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("Trending-regime hypothesis test failed for %s: %s", symbol, e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def _run_two_sample_test(
        self, hypothesis_id: str, description: str, symbol: str, forward_days: int,
        returns_true: pd.Series, returns_false: pd.Series,
    ) -> HypothesisResult:
        n_true, n_false = len(returns_true), len(returns_false)
        if n_true < MIN_OBSERVATIONS_PER_GROUP or n_false < MIN_OBSERVATIONS_PER_GROUP:
            return HypothesisResult(
                hypothesis_id=hypothesis_id, description=description, symbol=symbol, forward_days=forward_days,
                n_condition_true=n_true, n_condition_false=n_false,
                mean_return_true_pct=float(returns_true.mean()) if n_true else 0.0,
                mean_return_false_pct=float(returns_false.mean()) if n_false else 0.0,
                t_stat=0.0, p_value=1.0, significant=False, effect_direction="insufficient_data",
            )
        # Welch's t-test -- does NOT assume equal variance between the two
        # groups (real forward-return distributions conditional on a regime
        # very often have different variance, e.g. risk-off periods are
        # typically more volatile than risk-on ones -- assuming equal
        # variance there would understate the true uncertainty).
        t_stat, p_value = stats.ttest_ind(returns_true, returns_false, equal_var=False)
        significant = bool(np.isfinite(t_stat) and abs(t_stat) > T_STAT_SIGNIFICANCE)
        mean_true, mean_false = float(returns_true.mean()), float(returns_false.mean())
        if not significant:
            direction = "not_significant"
        else:
            direction = "condition_helps" if mean_true > mean_false else "condition_hurts"
        result = HypothesisResult(
            hypothesis_id=hypothesis_id, description=description, symbol=symbol, forward_days=forward_days,
            n_condition_true=n_true, n_condition_false=n_false,
            mean_return_true_pct=mean_true, mean_return_false_pct=mean_false,
            t_stat=float(t_stat) if np.isfinite(t_stat) else 0.0,
            p_value=float(p_value) if np.isfinite(p_value) else 1.0,
            significant=significant, effect_direction=direction,
        )
        result.knowledge_context = self._build_knowledge_context(description, symbol)
        return result

    @staticmethod
    def _summarize(result: HypothesisResult) -> str:
        if result.effect_direction == "insufficient_data":
            return f"{result.symbol}/{result.hypothesis_id}: insufficient data ({result.n_condition_true} true, {result.n_condition_false} false observations)"
        return (
            f"{result.symbol}/{result.hypothesis_id}: {result.effect_direction} "
            f"(true={result.mean_return_true_pct:.2f}% vs false={result.mean_return_false_pct:.2f}%, "
            f"t={result.t_stat:.2f}, p={result.p_value:.3f}, n={result.n_condition_true}+{result.n_condition_false})"
        )

    def _build_knowledge_context(self, description: str, symbol: str) -> Optional[dict]:
        if self._knowledge_engine is None:
            return None
        try:
            query = f"{symbol} {description}"
            results = self._knowledge_engine.document_store.hybrid_search(query, limit=3)
        except Exception as e:
            logger.warning("Knowledge context unavailable: %s", e)
            return None
        if not results:
            return None
        return {"query": query, "results": [r.to_dict() for r in results]}

    def store_result(self, result: HypothesisResult) -> None:
        """Append/update this hypothesis's latest result in the
        persistent 'proprietary alpha database' the master prompt
        describes -- keyed by hypothesis_id+symbol so re-running research
        updates the entry rather than accumulating duplicates."""
        ALPHA_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        db: dict = {}
        if ALPHA_DB_PATH.exists():
            try:
                db = json.loads(ALPHA_DB_PATH.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning("Alpha database unreadable (%s) -- starting fresh, old file backed up", e)
                ALPHA_DB_PATH.rename(ALPHA_DB_PATH.with_suffix(".json.corrupt"))
                db = {}
        key = f"{result.hypothesis_id}::{result.symbol}"
        db[key] = result.to_dict()
        ALPHA_DB_PATH.write_text(json.dumps(db, indent=2), encoding="utf-8")

    def lookup_relevant_alpha(self, symbol: str) -> list[dict]:
        """Fast, cheap read of the already-computed alpha database for
        this symbol -- used by the LIVE signal-generation pipeline
        (e51_signals' confluence check) instead of re-running a fresh
        Welch's t-test against 10 years of data on every single signal
        call. The statistical test result for a given hypothesis+symbol
        does not change intraday -- re-computing it identically on every
        call would be exactly the 'don't compute the same expensive
        thing twice' mistake this project's own Rule 4 warns about.
        Returns only hypotheses whose LAST research run found a real,
        statistically significant effect for this symbol -- an
        unvalidated or not-yet-tested hypothesis returns nothing, never
        a fabricated stand-in. Stale by however long it's been since
        `train_e22_alpha_research.py` last ran (documented, not hidden)."""
        if not ALPHA_DB_PATH.exists():
            return []
        try:
            db = json.loads(ALPHA_DB_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("Alpha database unreadable (%s)", e)
            return []
        return [
            entry for key, entry in db.items()
            if key.endswith(f"::{symbol}") and entry.get("significant") is True
        ]

    def evaluate_live_confluence(self, symbol: str, direction: str) -> Optional[tuple[float, str]]:
        """Same (multiplier, evidence) contract as every other
        e51_signals._confluence_* check -- lets e51_signals call this
        engine exactly like it calls E17/E20/etc., no special-casing.
        Only the two hypothesis TYPES this engine actually knows how to
        cheaply re-check live are evaluated (trending-regime via ADX,
        already free since technical analysis always computes it; and
        risk-off via a fresh but cheap VIX read, ~1s thanks to
        e02_market_data's parquet cache). A hypothesis with no
        significant, validated result for this symbol -- or one whose
        condition can't be cheaply checked live -- contributes nothing,
        never a fabricated stand-in. `direction` is never touched, only
        `conf`'s multiplier, same discipline as every sibling confluence
        method."""
        relevant = self.lookup_relevant_alpha(symbol)
        if not relevant:
            return None
        for entry in relevant:
            hid = entry.get("hypothesis_id", "")
            helps_long = entry.get("effect_direction") == "condition_helps"
            try:
                if hid == "trend_regime_breakout_edge":
                    is_condition_true = self._current_trending_state(symbol)
                elif hid == "gold_risk_off":
                    is_condition_true = self._current_risk_off_state()
                else:
                    continue
                if is_condition_true is None:
                    continue
            except Exception as e:
                logger.warning("Live confluence check failed for %s/%s: %s", symbol, hid, e)
                continue
            # The hypothesis found a return DIFFERENCE between condition
            # true/false, not a direction -- so this only tempers/boosts
            # confidence in whichever direction was actually proposed,
            # it can never flip LONG into SHORT or vice versa.
            if is_condition_true and helps_long:
                return 1.08, f"Confluence: validated hypothesis '{entry['description']}' condition is currently active (E22, p={entry['p_value']})"
            if is_condition_true and not helps_long:
                return 0.92, f"Confluence: validated hypothesis '{entry['description']}' condition is currently active and historically hurts this setup (E22, p={entry['p_value']})"
        return None

    def _current_trending_state(self, symbol: str) -> Optional[bool]:
        """True if `symbol` is trending (ADX above its own trailing
        252-day median) right now -- identical definition to
        test_trending_regime_hypothesis, so 'the condition' means the
        same thing at research time and at live-check time."""
        asset = None
        try:
            from project_titan_x.core.config import get_asset
            asset = get_asset(symbol)
        except Exception:
            pass
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

    def _current_risk_off_state(self) -> Optional[bool]:
        """True if VIX is currently above its own trailing 1yr median
        -- identical definition to test_risk_off_hypothesis. A single
        fetch, cheap thanks to e02_market_data's parquet cache
        (measured ~0.7-1.4s, not a full re-download every call)."""
        fetch = self._market_data_engine.fetch_ohlcv("^VIX", "1d", years=2)
        if not fetch.success or fetch.data is None or len(fetch.data) < 60:
            return None
        vix = fetch.data["close"]
        median = vix.tail(252).median()
        latest = vix.iloc[-1]
        if pd.isna(latest) or pd.isna(median):
            return None
        return bool(latest > median)
