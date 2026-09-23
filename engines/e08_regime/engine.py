"""
Module: engine.py
Description: Engine 04 — Market Regime classification.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-06-28
"""

import json
import logging
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
import ruptures as rpt
from hmmlearn.hmm import GaussianHMM

from project_titan_x.core.config.assets import get_asset
from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus
from project_titan_x.engines.e01_knowledge.engine import KnowledgeEngine
from project_titan_x.engines.e04_macro.engine import MacroSnapshot
from project_titan_x.engines.e07_technical.engine import TechnicalSnapshot, TrendDirection

_HMM_CALIBRATION_DIR = Path(__file__).resolve().parents[2] / "data" / "models" / "e08_regime"

logger = logging.getLogger(__name__)


class MarketRegime(str, Enum):
    """Market regime classifications."""

    TRENDING_UP = "Trending Up"
    TRENDING_DOWN = "Trending Down"
    RANGING = "Ranging"
    HIGH_VOLATILITY = "High Volatility"
    LOW_VOLATILITY = "Low Volatility"
    CRISIS = "Crisis"
    RECOVERY = "Recovery"
    RISK_ON = "Risk-On"
    RISK_OFF = "Risk-Off"


# Strategy suitability matrix
STRATEGY_REGIME_MAP: dict[str, dict[str, list[str]]] = {
    "trend_following": {
        "best": [MarketRegime.TRENDING_UP.value, MarketRegime.TRENDING_DOWN.value, MarketRegime.RISK_ON.value],
        "worst": [MarketRegime.RANGING.value, MarketRegime.LOW_VOLATILITY.value],
    },
    "mean_reversion": {
        "best": [MarketRegime.RANGING.value, MarketRegime.LOW_VOLATILITY.value],
        "worst": [MarketRegime.TRENDING_UP.value, MarketRegime.CRISIS.value],
    },
    "breakout": {
        "best": [MarketRegime.LOW_VOLATILITY.value, MarketRegime.RANGING.value],
        "worst": [MarketRegime.HIGH_VOLATILITY.value],
    },
    "scalping": {
        "best": [MarketRegime.RANGING.value, MarketRegime.LOW_VOLATILITY.value],
        "worst": [MarketRegime.CRISIS.value, MarketRegime.HIGH_VOLATILITY.value],
    },
}


@dataclass
class RegimeClassification:
    """Full regime classification result."""

    primary_regime: MarketRegime
    secondary_regime: Optional[MarketRegime]
    confidence: float  # 0-100
    macro_alignment: str
    suitable_strategies: list[str] = field(default_factory=list)
    avoid_strategies: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    evidence: list[str] = field(default_factory=list)
    knowledge_context: Optional[dict] = None


class MarketRegimeEngine(BaseEngine):
    """
    Market Regime Engine — classifies current market environment.

    Combines macro snapshot + technical analysis + volatility metrics.
    """

    engine_id = "e08_regime"
    engine_name = "Market Regime Engine"
    version = "1.0.0"

    VIX_CRISIS_THRESHOLD = 30.0
    VIX_LOW_THRESHOLD = 14.0
    ADX_TREND_THRESHOLD = 25.0
    ADX_RANGE_THRESHOLD = 20.0

    # Statistical regime layer (hmmlearn + ruptures) -- corroborating
    # evidence alongside the rule-based ADX/ATR/VIX classification above,
    # not a replacement for it.
    HMM_MIN_BARS = 60
    CHANGEPOINT_WINDOW = 60
    CHANGEPOINT_RECENT_BARS = 5

    def __init__(self, knowledge_engine: Optional[KnowledgeEngine] = None) -> None:
        super().__init__()
        # Optional and None by default: without it, classify() behaves
        # exactly as before (no knowledge_context). Pass a real instance
        # (as registry.py does) to turn it on.
        self._knowledge_engine = knowledge_engine

    def initialize(self) -> EngineResult:
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Market Regime Engine initialized")

    def health_check(self) -> EngineResult:
        return EngineResult(success=True, message="Healthy")

    def classify(
        self,
        df: pd.DataFrame,
        technical: TechnicalSnapshot,
        macro: Optional[MacroSnapshot] = None,
    ) -> EngineResult:
        """
        Classify market regime from price data, TA, and macro.

        Args:
            df: OHLCV DataFrame.
            technical: Technical analysis snapshot.
            macro: Optional macro snapshot.

        Returns:
            EngineResult with RegimeClassification.
        """
        try:
            self._set_status(EngineStatus.RUNNING)
            evidence: list[str] = []

            adx = technical.indicators.get("adx", 0)
            atr = technical.indicators.get("atr", 0)
            close = technical.indicators.get("close", 0)
            rsi = technical.indicators.get("rsi", 50)

            # Volatility regime from ATR percentile
            if "atr" in df.columns and len(df) >= 50:
                atr_pct = float(df["atr"].iloc[-50:].rank(pct=True).iloc[-1]) if "atr" in df.columns else 0.5
            else:
                atr_series = self._calc_atr(df)
                atr_pct = float(atr_series.iloc[-50:].rank(pct=True).iloc[-1]) if len(atr_series) >= 50 else 0.5

            vix = macro.indicators.get("vix_price", 20) if macro else 20
            risk_score = macro.risk_on_off_score if macro else 0.0

            primary, confidence, evidence = self._determine_primary_regime(
                technical, adx, atr_pct, vix, risk_score, rsi, evidence
            )

            hmm_regime = self._fit_hmm_volatility_regime(df, technical.symbol, technical.timeframe)
            if hmm_regime:
                hmm_high_vol = hmm_regime["label"] == "high_volatility"
                rule_high_vol = primary in (MarketRegime.HIGH_VOLATILITY, MarketRegime.CRISIS)
                if hmm_high_vol == rule_high_vol:
                    evidence.append(
                        f"HMM corroborates: {hmm_regime['label']} state "
                        f"({hmm_regime['confidence']:.0f}% model confidence)"
                    )
                    confidence = min(95.0, confidence + 5.0)
                else:
                    evidence.append(
                        f"HMM diverges from rule-based read: statistical model sees "
                        f"{hmm_regime['label']} state ({hmm_regime['confidence']:.0f}% model confidence)"
                    )

            changepoint_bars_ago = self._detect_recent_changepoint(df)
            if changepoint_bars_ago is not None and changepoint_bars_ago <= self.CHANGEPOINT_RECENT_BARS:
                evidence.append(
                    f"Statistical changepoint detected {changepoint_bars_ago} bar(s) ago -- "
                    "regime may be shifting, treat current classification with caution"
                )
                confidence = max(30.0, confidence - 10.0)

            # Added 2026-08-02: Wyckoff phase corroboration, same pattern
            # as the HMM corroboration above -- e07_technical's Wyckoff
            # detection (added earlier the same day) was never read by
            # this engine before, despite TechnicalSnapshot already
            # carrying it. Wyckoff's own phase read (accumulation/
            # distribution/markup/markdown) is a genuinely independent
            # method (trading-range + spring/upthrust geometry) from both
            # the ADX/ATR/VIX rules and the HMM/changepoint statistical
            # layer, so agreement between them is real corroborating
            # evidence, not double-counting the same signal three ways.
            confidence = self._corroborate_with_wyckoff(technical, primary, evidence, confidence)

            secondary = self._determine_secondary_regime(risk_score, vix, macro)

            suitable, avoid = self._strategy_suitability(primary, secondary)

            macro_alignment = "Aligned"
            if macro:
                if primary in (MarketRegime.RISK_ON, MarketRegime.TRENDING_UP) and risk_score < -0.2:
                    macro_alignment = "Divergent — macro risk-off vs local bullish"
                    evidence.append(macro_alignment)
                elif primary in (MarketRegime.RISK_OFF, MarketRegime.CRISIS) and risk_score > 0.2:
                    macro_alignment = "Divergent — macro risk-on vs local stress"
                    evidence.append(macro_alignment)

            classification = RegimeClassification(
                primary_regime=primary,
                secondary_regime=secondary,
                confidence=confidence,
                macro_alignment=macro_alignment,
                suitable_strategies=suitable,
                avoid_strategies=avoid,
                evidence=evidence,
                knowledge_context=self._build_knowledge_context(primary),
            )

            self._set_status(EngineStatus.IDLE)
            return EngineResult(
                success=True,
                data=classification,
                message=f"Regime: {primary.value} ({confidence:.0f}% confidence)",
                metadata={"regime": primary.value, "confidence": confidence},
            )
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("Regime classification failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def is_strategy_suitable(self, strategy_type: str, regime: MarketRegime) -> bool:
        """Check if a strategy type suits the current regime."""
        mapping = STRATEGY_REGIME_MAP.get(strategy_type, {})
        best = mapping.get("best", [])
        worst = mapping.get("worst", [])
        if regime.value in worst:
            return False
        return regime.value in best

    def _determine_primary_regime(
        self,
        technical: TechnicalSnapshot,
        adx: float,
        atr_pct: float,
        vix: float,
        risk_score: float,
        rsi: float,
        evidence: list[str],
    ) -> tuple[MarketRegime, float, list[str]]:
        """Determine primary regime with confidence."""
        if vix >= self.VIX_CRISIS_THRESHOLD:
            evidence.append(f"VIX crisis level ({vix:.1f})")
            return MarketRegime.CRISIS, 85.0, evidence

        if atr_pct > 0.85 and vix > 22:
            evidence.append(f"High volatility (ATR percentile {atr_pct:.0%})")
            return MarketRegime.HIGH_VOLATILITY, 75.0, evidence

        if atr_pct < 0.20 and vix < self.VIX_LOW_THRESHOLD:
            evidence.append(f"Volatility compression (ATR pct {atr_pct:.0%})")
            return MarketRegime.LOW_VOLATILITY, 70.0, evidence

        if adx >= self.ADX_TREND_THRESHOLD:
            if technical.trend == TrendDirection.BULLISH:
                evidence.append(f"Strong uptrend (ADX={adx:.1f})")
                conf = min(90.0, 60 + adx)
                return MarketRegime.TRENDING_UP, conf, evidence
            if technical.trend == TrendDirection.BEARISH:
                evidence.append(f"Strong downtrend (ADX={adx:.1f})")
                conf = min(90.0, 60 + adx)
                return MarketRegime.TRENDING_DOWN, conf, evidence

        if adx < self.ADX_RANGE_THRESHOLD:
            evidence.append(f"Range-bound (ADX={adx:.1f})")
            return MarketRegime.RANGING, 65.0, evidence

        if risk_score >= 0.35:
            evidence.append(f"Macro risk-on (score={risk_score:.2f})")
            return MarketRegime.RISK_ON, 60.0, evidence

        if risk_score <= -0.35:
            evidence.append(f"Macro risk-off (score={risk_score:.2f})")
            return MarketRegime.RISK_OFF, 60.0, evidence

        evidence.append("Mixed signals — default ranging")
        return MarketRegime.RANGING, 50.0, evidence

    # Wyckoff phase -> the regime(s) it corroborates. "accumulation"/
    # "distribution" describe a range PRECEDING a directional move, so
    # they corroborate RANGING (the range itself) as well as the trend
    # direction that phase classically resolves into -- both are real,
    # not a stretch: Wyckoff accumulation's defining feature IS a trading
    # range, and it's specifically a range that (per the method) tends to
    # resolve upward.
    _WYCKOFF_CORROBORATES: dict[str, tuple[MarketRegime, ...]] = {
        "accumulation": (MarketRegime.RANGING, MarketRegime.TRENDING_UP),
        "distribution": (MarketRegime.RANGING, MarketRegime.TRENDING_DOWN),
        "markup": (MarketRegime.TRENDING_UP,),
        "markdown": (MarketRegime.TRENDING_DOWN,),
    }

    def _corroborate_with_wyckoff(
        self, technical: TechnicalSnapshot, primary: MarketRegime, evidence: list[str], confidence: float
    ) -> float:
        """Checks e07_technical's Wyckoff phase read against the
        rule-based primary regime -- agreement nudges confidence up
        (independent-method corroboration, same +5 magnitude as the HMM
        check above); a real Wyckoff signal (spring/upthrust observed,
        not just "undefined") that actively DISAGREES nudges confidence
        down. "undefined" (no trading range currently detected) adds no
        evidence either way -- it's an honest absence of a read, not
        contradicting evidence."""
        phase = getattr(technical, "wyckoff_phase", "undefined")
        if phase == "undefined":
            return confidence

        corroborated_regimes = self._WYCKOFF_CORROBORATES.get(phase, ())
        if primary in corroborated_regimes:
            evidence.append(f"Wyckoff phase corroborates: {phase} (independent range/spring-upthrust read)")
            return min(95.0, confidence + 5.0)

        evidence.append(f"Wyckoff phase diverges from rule-based read: {phase} vs {primary.value}")
        return max(30.0, confidence - 5.0)

    def _determine_secondary_regime(
        self,
        risk_score: float,
        vix: float,
        macro: Optional[MacroSnapshot],
    ) -> Optional[MarketRegime]:
        if vix > 25 and risk_score < -0.2:
            return MarketRegime.RECOVERY if risk_score > -0.5 else MarketRegime.RISK_OFF
        if risk_score > 0.4:
            return MarketRegime.RISK_ON
        return None

    def _strategy_suitability(
        self, primary: MarketRegime, secondary: Optional[MarketRegime]
    ) -> tuple[list[str], list[str]]:
        suitable: list[str] = []
        avoid: list[str] = []
        for strategy, mapping in STRATEGY_REGIME_MAP.items():
            if primary.value in mapping.get("best", []):
                suitable.append(strategy)
            if primary.value in mapping.get("worst", []):
                avoid.append(strategy)
        if secondary and secondary.value in STRATEGY_REGIME_MAP.get("trend_following", {}).get("best", []):
            if "trend_following" not in suitable:
                suitable.append("trend_following")
        return suitable, avoid

    @staticmethod
    def _load_hmm_calibration(symbol: str, timeframe: str) -> Optional[dict]:
        """scripts/training/train_e08_regime.py grid-searches n_components/
        covariance_type per symbol against real held-out history and
        persists the winner to data/models/e08_regime/{yahoo_symbol}_
        {timeframe}_hmm_meta.json. Returns None (not a fabricated guess)
        when no calibration exists yet for this exact symbol+timeframe --
        callers fall back to the honest, documented default (2, diag)."""
        asset = get_asset(symbol)
        yahoo_symbol = asset.yahoo_symbol if asset else symbol
        path = _HMM_CALIBRATION_DIR / f"{yahoo_symbol}_{timeframe}_hmm_meta.json"
        if not path.exists():
            return None
        try:
            winner = json.loads(path.read_text()).get("winner")
            if not winner or "n_components" not in winner or "covariance_type" not in winner:
                return None
            return winner
        except Exception as e:
            logger.warning("Failed to load E08 HMM calibration from %s: %s", path, e)
            return None

    def _fit_hmm_volatility_regime(
        self, df: pd.DataFrame, symbol: Optional[str] = None, timeframe: Optional[str] = None
    ) -> Optional[dict]:
        """Fit a Gaussian HMM on daily log returns for a genuine statistical
        read on which volatility regime the market is currently in --
        distinct from the ATR-percentile heuristic above, since it's fit on
        the full return distribution (mean + variance) rather than a single
        rolling-window rank. n_components/covariance_type come from this
        exact symbol+timeframe's real held-out-validated calibration when
        one exists (see _load_hmm_calibration); the honest default (2,
        diag) applies otherwise -- never silently ignoring a real
        calibration that was already computed and validated.

        Best-effort: returns None on short/degenerate history so callers
        must always treat this as corroborating evidence, never a hard
        requirement -- the rule-based classification above must keep
        working with zero statistical libraries installed.
        """
        if len(df) < self.HMM_MIN_BARS:
            return None
        try:
            returns = np.log(df["close"]).diff().dropna().to_numpy().reshape(-1, 1)
            if len(returns) < self.HMM_MIN_BARS or not np.isfinite(returns).all() or returns.std() == 0:
                return None

            n_components, covariance_type = 2, "diag"
            if symbol and timeframe:
                calibration = self._load_hmm_calibration(symbol, timeframe)
                if calibration:
                    n_components = calibration["n_components"]
                    covariance_type = calibration["covariance_type"]

            model = GaussianHMM(n_components=n_components, covariance_type=covariance_type, n_iter=100, random_state=42)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                # hmmlearn logs "Model is not converging" via its OWN
                # logger (hmmlearn.base), not Python's warnings module --
                # warnings.simplefilter above never catches it. Verified
                # empirically (not assumed) 2026-07-20: re-fit the same
                # real BTCUSD/EURUSD/GOLD return series at n_iter=100 vs
                # 300 vs 1000 and got IDENTICAL label/confidence every
                # time, all reporting converged=True in isolation -- this
                # message is real but benign log noise for this platform's
                # corroborating-evidence-only use of the model, not a sign
                # the classification is actually unreliable. Suppressed at
                # the logger level (scoped to just this fit call, restored
                # after) so it stops burying genuine errors in server logs.
                hmm_logger = logging.getLogger("hmmlearn.base")
                prev_level = hmm_logger.level
                hmm_logger.setLevel(logging.ERROR)
                try:
                    model.fit(returns)
                finally:
                    hmm_logger.setLevel(prev_level)
            state_sequence = model.predict(returns)
            posteriors = model.predict_proba(returns)

            variances = model.covars_.reshape(model.n_components, -1)[:, 0]
            high_vol_state = int(np.argmax(variances))
            current_state = int(state_sequence[-1])

            return {
                "label": "high_volatility" if current_state == high_vol_state else "low_volatility",
                "confidence": float(posteriors[-1, current_state]) * 100,
            }
        except Exception as e:
            logger.warning("HMM regime fit failed: %s", e)
            return None

    def _detect_recent_changepoint(self, df: pd.DataFrame) -> Optional[int]:
        """Detect how many bars ago the single most significant statistical
        break in recent returns occurred, via ruptures' binary segmentation.

        Best-effort: returns None on failure/insufficient data, same as the
        HMM read above -- corroborating evidence only.
        """
        window = min(len(df), self.CHANGEPOINT_WINDOW)
        if window < 30:
            return None
        try:
            returns = np.log(df["close"]).diff().dropna().to_numpy()[-window:]
            if len(returns) < 30 or not np.isfinite(returns).all() or returns.std() == 0:
                return None
            algo = rpt.Binseg(model="l2").fit(returns.reshape(-1, 1))
            breakpoints = algo.predict(n_bkps=1)
            if not breakpoints or breakpoints[0] >= len(returns):
                return None
            return len(returns) - breakpoints[0]
        except Exception as e:
            logger.warning("Changepoint detection failed: %s", e)
            return None

    def _build_knowledge_context(self, primary: "MarketRegime") -> Optional[dict]:
        """Relevant Wyckoff/market-structure book content for the
        classified regime, attached for transparency -- informational
        only, never changes primary_regime or confidence. Best-effort:
        only runs if a real KnowledgeEngine instance was injected (see
        __init__ / registry.py)."""
        if self._knowledge_engine is None:
            return None
        try:
            query = f"{primary.value} market regime characteristics and trading approach"
            results = self._knowledge_engine.document_store.hybrid_search(query, limit=3)
        except Exception as e:
            logger.warning("Knowledge context unavailable: %s", e)
            return None
        if not results:
            return None
        return {"query": query, "results": [r.to_dict() for r in results]}

    @staticmethod
    def _calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        tr = pd.concat([
            df["high"] - df["low"],
            (df["high"] - df["close"].shift()).abs(),
            (df["low"] - df["close"].shift()).abs(),
        ], axis=1).max(axis=1)
        return tr.rolling(period).mean()
