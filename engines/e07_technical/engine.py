"""
Module: engine.py
Description: Engine 06 — Technical Analysis with full indicator suite.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-06-28
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np
import pandas as pd
import pandas_ta  # noqa: F401 -- registers the .ta accessor on DataFrame
from finta import TA as FintaTA

from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus
from project_titan_x.engines.e01_knowledge.engine import KnowledgeEngine
from project_titan_x.engines.e07_technical.chart_patterns import ChartPattern, detect_chart_patterns
from project_titan_x.engines.e07_technical.cisd import CISDSetup, detect_cisd_setups
from project_titan_x.engines.e07_technical.crt import CRTSetup, detect_crt_setups
from project_titan_x.engines.e07_technical.divergence import DivergenceKind, RSIDivergence, detect_rsi_divergences
from project_titan_x.engines.e07_technical.harmonics import HarmonicPattern, detect_harmonic_patterns
from project_titan_x.engines.e07_technical.structure import alternate_swings, find_swing_points
from project_titan_x.engines.e07_technical.smart_money import (
    FairValueGap,
    LiquiditySweep,
    OrderBlock,
    StructureEvent,
    StructureEventKind,
    detect_fair_value_gaps,
    detect_liquidity_sweeps,
    detect_order_blocks,
    detect_structure_events,
)
from project_titan_x.engines.e07_technical.volume_profile import VolumeProfile, compute_volume_profile
from project_titan_x.engines.e07_technical.wyckoff import (
    TradingRange,
    WyckoffEvent,
    classify_phase,
    detect_springs_and_upthrusts,
    detect_trading_range,
)

logger = logging.getLogger(__name__)


class TrendDirection(str, Enum):
    """Market structure trend direction."""

    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class MarketStructure(str, Enum):
    """Swing structure classification."""

    HH = "higher_high"
    HL = "higher_low"
    LH = "lower_high"
    LL = "lower_low"


@dataclass
class TechnicalSnapshot:
    """Complete technical analysis snapshot for an asset."""

    symbol: str
    timeframe: str
    trend: TrendDirection
    structure: list[str]
    support_levels: list[float]
    resistance_levels: list[float]
    indicators: dict
    signals: list[str]
    score: float  # -100 to +100 bullish/bearish
    knowledge_context: Optional[dict] = None
    # Added 2026-08-01: Smart Money Concepts / ICT, Volume Profile,
    # Wyckoff, and Harmonic pattern coverage -- see smart_money.py,
    # volume_profile.py, wyckoff.py, harmonics.py for each methodology's
    # own detection logic and docs. Populated whenever there's enough
    # data for that specific detector; empty list / None otherwise, never
    # fabricated.
    structure_events: list[StructureEvent] = field(default_factory=list)
    liquidity_sweeps: list[LiquiditySweep] = field(default_factory=list)
    order_blocks: list[OrderBlock] = field(default_factory=list)
    fair_value_gaps: list[FairValueGap] = field(default_factory=list)
    volume_profile: Optional[VolumeProfile] = None
    wyckoff_range: Optional[TradingRange] = None
    wyckoff_phase: str = "undefined"
    wyckoff_springs: list[WyckoffEvent] = field(default_factory=list)
    wyckoff_upthrusts: list[WyckoffEvent] = field(default_factory=list)
    harmonic_patterns: list[HarmonicPattern] = field(default_factory=list)
    # Added 2026-08-03: RSI divergence -- see divergence.py's own
    # docstring for why (real gap found cross-referencing this engine
    # against the YouTube knowledge pipeline's extraction: RSI is the
    # most-taught concept in that corpus with zero prior divergence
    # coverage here despite RSI itself already being computed).
    rsi_divergences: list[RSIDivergence] = field(default_factory=list)
    # Added 2026-09-13 (docs/UPGRADE_ROADMAP.md P1 item 2, crt.py) -- CRT
    # (Candle Range Theory) setups. NOT YET ABLATED: exposed here for
    # inspection/research only, deliberately not fed into
    # _generate_advanced_signals or _compute_bullish_score until
    # research/concept_ablation.py measures real solo expectancy (see
    # crt.py's own module docstring).
    crt_setups: list[CRTSetup] = field(default_factory=list)
    # Added 2026-09-13 (docs/UPGRADE_ROADMAP.md P2 item 6, cisd.py) -- same
    # not-yet-ablated, inspection-only convention as crt_setups above.
    cisd_setups: list[CISDSetup] = field(default_factory=list)
    # Added 2026-09-13 (chart_patterns.py) -- classical Head & Shoulders/
    # Double Top-Bottom/Triangle geometry. Same not-yet-ablated,
    # inspection-only convention as crt_setups/cisd_setups above: exposed
    # here for research, not fed into _generate_advanced_signals or
    # _compute_bullish_score until research/concept_ablation.py measures
    # real solo expectancy.
    chart_patterns: list[ChartPattern] = field(default_factory=list)


class TechnicalAnalysisEngine(BaseEngine):
    """
    Technical Analysis Engine — comprehensive TA indicator suite.

    Implements: market structure, S/R, EMAs, RSI, MACD, ADX, ATR,
    Bollinger Bands, VWAP, Fibonacci, pivot points, volume profile basics.
    """

    engine_id = "e07_technical"
    engine_name = "Technical Analysis Engine"
    version = "1.0.0"

    EMA_PERIODS = [8, 21, 50, 200]
    RSI_PERIOD = 14
    MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
    ADX_PERIOD = 14
    ATR_PERIOD = 14
    BB_PERIOD, BB_STD = 20, 2.0

    def __init__(self, knowledge_engine: Optional[KnowledgeEngine] = None) -> None:
        super().__init__()
        # Optional and None by default: without it, analyze() behaves
        # exactly as before (no knowledge_context). Pass a real instance
        # (as registry.py does) to turn it on.
        self._knowledge_engine = knowledge_engine

    def initialize(self) -> EngineResult:
        """Initialize technical analysis engine."""
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Technical Analysis Engine initialized")

    def health_check(self) -> EngineResult:
        """Health check."""
        return EngineResult(success=True, message="Healthy")

    def analyze(self, df: pd.DataFrame, symbol: str = "", timeframe: str = "1d") -> EngineResult:
        """
        Run full technical analysis on OHLCV data.

        Args:
            df: OHLCV DataFrame.
            symbol: Asset symbol.
            timeframe: Analysis timeframe.

        Returns:
            EngineResult with enriched DataFrame and TechnicalSnapshot.
        """
        try:
            self._set_status(EngineStatus.RUNNING)
            if len(df) < 50:
                raise ValueError("Insufficient data: minimum 50 candles required")

            enriched = df.copy()
            enriched = self._add_emas(enriched)
            enriched = self._add_rsi(enriched)
            enriched = self._add_macd(enriched)
            enriched = self._add_adx(enriched)
            enriched = self._add_atr(enriched)
            enriched = self._add_bollinger(enriched)
            enriched = self._add_vwap(enriched)
            enriched = self._add_pandas_ta_indicators(enriched)
            enriched = self._add_ichimoku(enriched)

            structure = self._detect_market_structure(enriched)
            trend = self._classify_trend(enriched)
            support, resistance = self._find_support_resistance(enriched)
            signals = self._generate_ta_signals(enriched, trend)

            # Added 2026-08-01: Smart Money Concepts / ICT, Volume Profile,
            # Wyckoff, and Harmonic pattern detection -- see each module's
            # own docstring for the concepts and real-data validation
            # behind them. Each call is independently best-effort so one
            # methodology failing (e.g. insufficient data for a given
            # asset) never blocks the rest of the analysis, matching the
            # existing pattern for the pandas-ta/finta supplementary
            # indicators above.
            # Computed ONCE and shared below -- detect_structure_events,
            # detect_liquidity_sweeps, and detect_harmonic_patterns were
            # each independently recomputing find_swing_points/
            # alternate_swings from scratch on this SAME enriched frame
            # with the SAME default lookback=5 (a rolling centered
            # min/max over the whole series, not free), 3x total for an
            # identical result. Best-effort like everything else here --
            # a failure just leaves swings=None, and each downstream
            # detector falls back to computing its own (unchanged
            # original behavior), not a hard failure.
            try:
                swings = alternate_swings(find_swing_points(enriched))
            except Exception as e:
                logger.warning("Shared swing-point computation failed, each detector will compute its own: %s", e)
                swings = None

            structure_events, liquidity_sweeps, order_blocks, fvgs = self._analyze_smart_money(enriched, swings=swings)
            wyckoff_range, wyckoff_phase, springs, upthrusts = self._analyze_wyckoff(enriched)
            try:
                volume_profile = compute_volume_profile(enriched)
            except Exception as e:
                logger.warning("Volume profile computation failed: %s", e)
                volume_profile = None
            try:
                harmonic_patterns = detect_harmonic_patterns(enriched, swings=swings)
            except Exception as e:
                logger.warning("Harmonic pattern detection failed: %s", e)
                harmonic_patterns = []
            try:
                rsi_divergences = detect_rsi_divergences(enriched, swings=swings if swings is not None else [])
            except Exception as e:
                logger.warning("RSI divergence detection failed: %s", e)
                rsi_divergences = []
            try:
                crt_setups = detect_crt_setups(enriched)
            except Exception as e:
                logger.warning("CRT detection failed: %s", e)
                crt_setups = []
            try:
                cisd_setups = detect_cisd_setups(enriched)
            except Exception as e:
                logger.warning("CISD detection failed: %s", e)
                cisd_setups = []
            try:
                chart_patterns = detect_chart_patterns(enriched, swings=swings)
            except Exception as e:
                logger.warning("Chart pattern detection failed: %s", e)
                chart_patterns = []

            signals.extend(self._generate_advanced_signals(
                enriched, structure_events, liquidity_sweeps, wyckoff_phase, springs, upthrusts,
                volume_profile, harmonic_patterns, rsi_divergences,
            ))
            score = self._compute_bullish_score(
                enriched, trend, signals,
                structure_events=structure_events, springs=springs, upthrusts=upthrusts,
                harmonic_patterns=harmonic_patterns, rsi_divergences=rsi_divergences,
            )

            last = enriched.iloc[-1]
            snapshot = TechnicalSnapshot(
                symbol=symbol,
                timeframe=timeframe,
                trend=trend,
                structure=structure,
                support_levels=support,
                resistance_levels=resistance,
                structure_events=structure_events,
                liquidity_sweeps=liquidity_sweeps,
                order_blocks=order_blocks,
                fair_value_gaps=fvgs,
                volume_profile=volume_profile,
                wyckoff_range=wyckoff_range,
                wyckoff_phase=wyckoff_phase,
                wyckoff_springs=springs,
                wyckoff_upthrusts=upthrusts,
                harmonic_patterns=harmonic_patterns,
                rsi_divergences=rsi_divergences,
                crt_setups=crt_setups,
                cisd_setups=cisd_setups,
                chart_patterns=chart_patterns,
                indicators={
                    "rsi": round(float(last.get("rsi", 50)), 2),
                    "macd": round(float(last.get("macd", 0)), 4),
                    "macd_signal": round(float(last.get("macd_signal", 0)), 4),
                    "adx": round(float(last.get("adx", 0)), 2),
                    "atr": round(float(last.get("atr", 0)), 4),
                    "ema_8": round(float(last.get("ema_8", 0)), 4),
                    "ema_21": round(float(last.get("ema_21", 0)), 4),
                    "ema_50": round(float(last.get("ema_50", 0)), 4),
                    "ema_200": round(float(last.get("ema_200", 0)), 4),
                    "bb_upper": round(float(last.get("bb_upper", 0)), 4),
                    "bb_lower": round(float(last.get("bb_lower", 0)), 4),
                    "vwap": round(float(last.get("vwap", 0)), 4),
                    "vwap_upper_1": round(float(last.get("vwap_upper_1", 0)), 4),
                    "vwap_lower_1": round(float(last.get("vwap_lower_1", 0)), 4),
                    "vwap_upper_2": round(float(last.get("vwap_upper_2", 0)), 4),
                    "vwap_lower_2": round(float(last.get("vwap_lower_2", 0)), 4),
                    "close": round(float(last["close"]), 4),
                    "stoch_k": round(self._safe_float(last.get("stoch_k"), 50.0), 2),
                    "stoch_d": round(self._safe_float(last.get("stoch_d"), 50.0), 2),
                    "cci": round(self._safe_float(last.get("cci"), 0.0), 2),
                    "williams_r": round(self._safe_float(last.get("williams_r"), -50.0), 2),
                    "mfi": round(self._safe_float(last.get("mfi"), 50.0), 2),
                    "obv": round(self._safe_float(last.get("obv"), 0.0), 2),
                    "supertrend_direction": self._supertrend_label(last.get("supertrend_direction")),
                    "ichimoku_tenkan": round(self._safe_float(last.get("ichimoku_tenkan"), 0.0), 4),
                    "ichimoku_kijun": round(self._safe_float(last.get("ichimoku_kijun"), 0.0), 4),
                },
                signals=signals,
                score=score,
                knowledge_context=self._build_knowledge_context(trend, signals),
            )

            self._set_status(EngineStatus.IDLE)
            return EngineResult(
                success=True,
                data={"df": enriched, "snapshot": snapshot},
                message=f"Analysis complete: {trend.value}, score={score:.1f}",
                metadata={"trend": trend.value, "score": score},
            )
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("TA analysis failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def _add_emas(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add exponential moving averages."""
        for period in self.EMA_PERIODS:
            df[f"ema_{period}"] = df["close"].ewm(span=period, adjust=False).mean()
        return df

    def _add_rsi(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add Relative Strength Index.

        Uses a SIMPLE rolling mean of gains/losses (Cutler's RSI), not
        Wilder's smoothing. TradingView, MT4/MT5 and most broker platforms
        default to WILDER's, so RSI printed here will not tie out exactly
        against a chart -- documented rather than silently different.
        Every validated strategy parameter in this project was fitted
        against this definition, so changing it would invalidate all of
        them and require a full re-validation sweep.

        Real bug fixed 2026-08-23: `loss.replace(0, np.nan)` made RS NaN
        whenever the lookback window contained NO down-closes, so RSI came
        back NaN exactly during the strongest rallies. Correct RSI with
        zero losses is 100 (maximum overbought), not undefined.

        The consequence was not cosmetic and was asymmetric -- a pure
        downtrend correctly produced 0.0, while a pure uptrend produced
        NaN. Every strategy reads rsi via `.fillna(50)`, so a parabolic
        rally was seen as PERFECTLY NEUTRAL (50) instead of maximally
        overbought (100): rsi_mean_reversion could never take the short,
        and trend_pullback_atr_trail's short entry (rsi > overbought)
        could never fire, in precisely the conditions those rules exist
        to catch. Crypto is the worst affected, since BTC/ETH regularly
        run 14+ consecutive up-closes.
        """
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0.0).rolling(self.RSI_PERIOD).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(self.RSI_PERIOD).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        # Resolve the zero-loss window explicitly instead of leaving it NaN.
        # Both branches are only applied where the window is fully formed
        # (gain/loss non-NaN), so the genuine warm-up NaNs are preserved.
        warm = gain.notna() & loss.notna()
        rsi = rsi.mask(warm & (loss == 0) & (gain > 0), 100.0)
        rsi = rsi.mask(warm & (loss == 0) & (gain == 0), 50.0)   # flat: neither side
        df["rsi"] = rsi
        return df

    def _add_macd(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add MACD indicator."""
        ema_fast = df["close"].ewm(span=self.MACD_FAST, adjust=False).mean()
        ema_slow = df["close"].ewm(span=self.MACD_SLOW, adjust=False).mean()
        df["macd"] = ema_fast - ema_slow
        df["macd_signal"] = df["macd"].ewm(span=self.MACD_SIGNAL, adjust=False).mean()
        df["macd_hist"] = df["macd"] - df["macd_signal"]
        return df

    def _add_adx(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add Average Directional Index."""
        high_diff = df["high"].diff()
        low_diff = -df["low"].diff()
        plus_dm = high_diff.where((high_diff > low_diff) & (high_diff > 0), 0.0)
        minus_dm = low_diff.where((low_diff > high_diff) & (low_diff > 0), 0.0)
        tr = pd.concat([
            df["high"] - df["low"],
            (df["high"] - df["close"].shift()).abs(),
            (df["low"] - df["close"].shift()).abs(),
        ], axis=1).max(axis=1)
        atr = tr.rolling(self.ADX_PERIOD).mean()
        plus_di = 100 * (plus_dm.rolling(self.ADX_PERIOD).mean() / atr)
        minus_di = 100 * (minus_dm.rolling(self.ADX_PERIOD).mean() / atr)
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
        df["adx"] = dx.rolling(self.ADX_PERIOD).mean()
        df["plus_di"] = plus_di
        df["minus_di"] = minus_di
        return df

    def _add_atr(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add Average True Range."""
        tr = pd.concat([
            df["high"] - df["low"],
            (df["high"] - df["close"].shift()).abs(),
            (df["low"] - df["close"].shift()).abs(),
        ], axis=1).max(axis=1)
        df["atr"] = tr.rolling(self.ATR_PERIOD).mean()
        return df

    def _add_bollinger(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add Bollinger Bands."""
        sma = df["close"].rolling(self.BB_PERIOD).mean()
        std = df["close"].rolling(self.BB_PERIOD).std()
        df["bb_middle"] = sma
        df["bb_upper"] = sma + self.BB_STD * std
        df["bb_lower"] = sma - self.BB_STD * std
        df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_middle"]
        return df

    def _add_vwap(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add Volume Weighted Average Price, plus standard-deviation
        bands around it.

        Added 2026-08-03: the bands were entirely missing before --
        cross-referencing this engine against the YouTube knowledge
        pipeline's extraction found VWAP itself is the second-most-taught
        concept in that corpus (615 mentions) with its bands specifically
        called out as essential ("really understanding the standard
        deviation bands is something you cannot do without if you want to
        master the VWAP indicator") and used as the actual pullback-entry
        mechanism ("buy pullbacks to VWAP...or you can use the first
        band"). Bands are volume-weighted std dev of price around the
        cumulative VWAP (the standard TradingView convention, same 1x/2x
        multiple structure as this engine's existing Bollinger Bands --
        BB_STD=2.0 above is the same kind of fixed statistical convention,
        not a fitted parameter)."""
        typical = (df["high"] + df["low"] + df["close"]) / 3
        if "volume" in df.columns and df["volume"].sum() > 0:
            cum_vol = df["volume"].cumsum()
            vwap = (typical * df["volume"]).cumsum() / cum_vol
            df["vwap"] = vwap
            variance = ((typical - vwap) ** 2 * df["volume"]).cumsum() / cum_vol
            std = variance.clip(lower=0) ** 0.5
        else:
            vwap = typical.rolling(20).mean()
            df["vwap"] = vwap
            std = typical.rolling(20).std()
        df["vwap_upper_1"] = vwap + std
        df["vwap_lower_1"] = vwap - std
        df["vwap_upper_2"] = vwap + 2 * std
        df["vwap_lower_2"] = vwap - 2 * std
        return df

    def _add_pandas_ta_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Supplementary oscillators/volume indicators from pandas-ta --
        genuinely new coverage (Stochastic, CCI, Williams %R, OBV, MFI,
        Supertrend) rather than a reimplementation of the EMA/RSI/MACD/ADX
        already hand-rolled above. Each is independently best-effort: a
        failure on one (e.g. insufficient length for a given asset) must
        not block the rest of the analysis."""
        try:
            stoch = df.ta.stoch()
            if stoch is not None:
                df["stoch_k"] = stoch.get("STOCHk_14_3_3")
                df["stoch_d"] = stoch.get("STOCHd_14_3_3")
        except Exception as e:
            logger.warning("pandas-ta stoch failed: %s", e)

        try:
            df["cci"] = self._compute_cci(df)
        except Exception as e:
            logger.warning("CCI computation failed: %s", e)

        try:
            df["williams_r"] = df.ta.willr()
        except Exception as e:
            logger.warning("pandas-ta willr failed: %s", e)

        if "volume" in df.columns and df["volume"].sum() > 0:
            try:
                df["obv"] = df.ta.obv()
                df["mfi"] = df.ta.mfi()
            except Exception as e:
                logger.warning("pandas-ta obv/mfi failed: %s", e)

        try:
            supertrend = df.ta.supertrend()
            if supertrend is not None:
                direction_col = next(
                    (c for c in supertrend.columns if c.startswith("SUPERTd_")), None
                )
                if direction_col:
                    df["supertrend_direction"] = supertrend[direction_col]
        except Exception as e:
            logger.warning("pandas-ta supertrend failed: %s", e)

        return df

    @staticmethod
    def _compute_cci(df: pd.DataFrame, length: int = 14, c: float = 0.015) -> pd.Series:
        """Commodity Channel Index, computed directly rather than via
        pandas-ta's df.ta.cci(): pandas-ta 0.4.71b0's implementation has a
        missing-parenthesis bug --
            cci = typical_price - mean_typical_price / (c * mad_typical_price)
        -- which due to operator precedence computes
        `typical_price - (mean / (c*mad))` instead of
        `(typical_price - mean) / (c*mad)`, producing values off by orders
        of magnitude (observed -42576 on live EURUSD data where a correct
        CCI reading is on the order of tens). Verified directly against
        pandas_ta.momentum.cci's source before writing this workaround.
        """
        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        sma = typical_price.rolling(length).mean()
        mean_abs_dev = (typical_price - sma).abs().rolling(length).mean()
        return (typical_price - sma) / (c * mean_abs_dev)

    def _add_ichimoku(self, df: pd.DataFrame) -> pd.DataFrame:
        """Ichimoku Cloud via finta -- a distinct cloud-based structure read
        (Tenkan/Kijun cross, price-vs-cloud position), not already covered
        by the EMA/Bollinger-based trend logic above."""
        try:
            ichimoku = FintaTA.ICHIMOKU(df)
            df["ichimoku_tenkan"] = ichimoku["TENKAN"]
            df["ichimoku_kijun"] = ichimoku["KIJUN"]
            df["ichimoku_senkou_a"] = ichimoku["senkou_span_a"]
            df["ichimoku_senkou_b"] = ichimoku["SENKOU"]
        except Exception as e:
            logger.warning("finta Ichimoku failed: %s", e)
        return df

    @staticmethod
    def _safe_float(value, default: float = 0.0) -> float:
        """Coerce a possibly-missing/NaN indicator value to a plain float,
        since supplementary indicators are best-effort and may be absent."""
        try:
            v = float(value)
            return v if not np.isnan(v) else default
        except (TypeError, ValueError):
            return default

    @classmethod
    def _supertrend_label(cls, direction) -> str:
        """Map pandas-ta's Supertrend direction (+1/-1) to a readable label."""
        value = cls._safe_float(direction, 0.0)
        if value > 0:
            return "bullish"
        if value < 0:
            return "bearish"
        return "n/a"

    def _detect_market_structure(self, df: pd.DataFrame, lookback: int = 5) -> list[str]:
        """Detect swing highs/lows and market structure."""
        structure: list[str] = []
        highs = df["high"].rolling(lookback * 2 + 1, center=True).max()
        lows = df["low"].rolling(lookback * 2 + 1, center=True).min()

        swing_highs = df[df["high"] == highs]["high"].tail(4).tolist()
        swing_lows = df[df["low"] == lows]["low"].tail(4).tolist()

        if len(swing_highs) >= 2:
            structure.append(
                MarketStructure.HH.value
                if swing_highs[-1] > swing_highs[-2]
                else MarketStructure.LH.value
            )
        if len(swing_lows) >= 2:
            structure.append(
                MarketStructure.HL.value
                if swing_lows[-1] > swing_lows[-2]
                else MarketStructure.LL.value
            )
        return structure

    def _classify_trend(self, df: pd.DataFrame) -> TrendDirection:
        """Classify trend from EMA alignment and ADX."""
        last = df.iloc[-1]
        ema_bullish = (
            last.get("ema_8", 0) > last.get("ema_21", 0) > last.get("ema_50", 0)
        )
        ema_bearish = (
            last.get("ema_8", 0) < last.get("ema_21", 0) < last.get("ema_50", 0)
        )
        adx_strong = last.get("adx", 0) > 25

        if ema_bullish and adx_strong:
            return TrendDirection.BULLISH
        if ema_bearish and adx_strong:
            return TrendDirection.BEARISH
        return TrendDirection.NEUTRAL

    def _find_support_resistance(
        self, df: pd.DataFrame, n_levels: int = 3
    ) -> tuple[list[float], list[float]]:
        """Find key support and resistance levels from recent pivots."""
        recent = df.tail(100)
        pivot_highs = recent.nlargest(n_levels, "high")["high"].unique().tolist()
        pivot_lows = recent.nsmallest(n_levels, "low")["low"].unique().tolist()
        return sorted(pivot_lows), sorted(pivot_highs, reverse=True)

    def _generate_ta_signals(
        self, df: pd.DataFrame, trend: TrendDirection
    ) -> list[str]:
        """Generate human-readable TA signals."""
        signals: list[str] = []
        last = df.iloc[-1]
        prev = df.iloc[-2]

        if last.get("rsi", 50) < 30:
            signals.append("RSI oversold (<30)")
        elif last.get("rsi", 50) > 70:
            signals.append("RSI overbought (>70)")

        if prev.get("macd", 0) < prev.get("macd_signal", 0) and last.get("macd", 0) > last.get("macd_signal", 0):
            signals.append("MACD bullish crossover")
        elif prev.get("macd", 0) > prev.get("macd_signal", 0) and last.get("macd", 0) < last.get("macd_signal", 0):
            signals.append("MACD bearish crossover")

        if last["close"] > last.get("ema_200", 0):
            signals.append("Price above 200 EMA (long-term bullish)")
        else:
            signals.append("Price below 200 EMA (long-term bearish)")

        if last.get("adx", 0) > 25:
            signals.append(f"Strong trend (ADX={last['adx']:.1f})")

        if last["close"] <= last.get("bb_lower", 0):
            signals.append("Price at lower Bollinger Band")
        elif last["close"] >= last.get("bb_upper", 0):
            signals.append("Price at upper Bollinger Band")

        signals.extend(self._generate_supplementary_signals(last, prev))

        return signals

    def _generate_supplementary_signals(self, last: pd.Series, prev: pd.Series) -> list[str]:
        """Signals from the pandas-ta/finta supplementary indicators. Uses
        the same 'bullish'/'bearish'/'oversold'/'overbought' vocabulary as
        the hand-rolled signals above so _compute_bullish_score's generic
        keyword scan picks these up automatically -- no separate scoring
        path needed."""
        signals: list[str] = []

        stoch_k = last.get("stoch_k")
        if stoch_k is not None and pd.notna(stoch_k):
            if stoch_k < 20:
                signals.append("Stochastic oversold (<20)")
            elif stoch_k > 80:
                signals.append("Stochastic overbought (>80)")

        cci = last.get("cci")
        if cci is not None and pd.notna(cci):
            if cci < -100:
                signals.append("CCI oversold (<-100)")
            elif cci > 100:
                signals.append("CCI overbought (>100)")

        williams_r = last.get("williams_r")
        if williams_r is not None and pd.notna(williams_r):
            if williams_r < -80:
                signals.append("Williams %R oversold (<-80)")
            elif williams_r > -20:
                signals.append("Williams %R overbought (>-20)")

        mfi = last.get("mfi")
        if mfi is not None and pd.notna(mfi):
            if mfi < 20:
                signals.append("MFI oversold (<20)")
            elif mfi > 80:
                signals.append("MFI overbought (>80)")

        st_dir, prev_st_dir = last.get("supertrend_direction"), prev.get("supertrend_direction")
        if st_dir is not None and prev_st_dir is not None and pd.notna(st_dir) and pd.notna(prev_st_dir):
            if st_dir != prev_st_dir:
                signals.append("Supertrend flipped bullish" if st_dir > 0 else "Supertrend flipped bearish")

        senkou_a, senkou_b = last.get("ichimoku_senkou_a"), last.get("ichimoku_senkou_b")
        if senkou_a is not None and senkou_b is not None and pd.notna(senkou_a) and pd.notna(senkou_b):
            cloud_top, cloud_bottom = max(senkou_a, senkou_b), min(senkou_a, senkou_b)
            if last["close"] > cloud_top:
                signals.append("Price above Ichimoku cloud (bullish)")
            elif last["close"] < cloud_bottom:
                signals.append("Price below Ichimoku cloud (bearish)")

        return signals

    def _analyze_smart_money(
        self, df: pd.DataFrame, swings: Optional[list] = None
    ) -> tuple[list[StructureEvent], list[LiquiditySweep], list[OrderBlock], list[FairValueGap]]:
        """Runs the ICT/Smart Money Concepts detectors (smart_money.py) --
        independently best-effort per the same pattern as the pandas-ta
        supplementary indicators, since a failure here (e.g. too little
        data for a swing to ever confirm) must not block the rest of the
        analysis. swings: optional pre-computed shared swing points (see
        analyze()'s own comment) -- None falls back to each detector
        computing its own, unchanged from before."""
        try:
            events = detect_structure_events(df, swings=swings)
        except Exception as e:
            logger.warning("Structure event detection failed: %s", e)
            events = []
        try:
            sweeps = detect_liquidity_sweeps(df, swings=swings)
        except Exception as e:
            logger.warning("Liquidity sweep detection failed: %s", e)
            sweeps = []
        try:
            blocks = detect_order_blocks(df, events)
        except Exception as e:
            logger.warning("Order block detection failed: %s", e)
            blocks = []
        try:
            fvgs = detect_fair_value_gaps(df)
        except Exception as e:
            logger.warning("Fair value gap detection failed: %s", e)
            fvgs = []
        return events, sweeps, blocks, fvgs

    def _analyze_wyckoff(
        self, df: pd.DataFrame
    ) -> tuple[Optional[TradingRange], str, list[WyckoffEvent], list[WyckoffEvent]]:
        """Runs the Wyckoff trading-range/spring/upthrust/phase detectors
        (wyckoff.py). Independently best-effort, same reasoning as
        _analyze_smart_money."""
        try:
            trading_range = detect_trading_range(df)
        except Exception as e:
            logger.warning("Wyckoff trading range detection failed: %s", e)
            return None, "undefined", [], []
        if trading_range is None:
            return None, "undefined", [], []
        try:
            springs, upthrusts = detect_springs_and_upthrusts(df, trading_range)
            phase = classify_phase(df, trading_range, springs, upthrusts)
        except Exception as e:
            logger.warning("Wyckoff spring/upthrust/phase detection failed: %s", e)
            return trading_range, "undefined", [], []
        return trading_range, phase, springs, upthrusts

    def _generate_advanced_signals(
        self,
        df: pd.DataFrame,
        structure_events: list[StructureEvent],
        liquidity_sweeps: list[LiquiditySweep],
        wyckoff_phase: str,
        springs: list[WyckoffEvent],
        upthrusts: list[WyckoffEvent],
        volume_profile: Optional[VolumeProfile],
        harmonic_patterns: list[HarmonicPattern],
        rsi_divergences: Optional[list[RSIDivergence]] = None,
    ) -> list[str]:
        """Human-readable signals from the Smart Money/Wyckoff/Volume
        Profile/Harmonics detectors, restricted to events on (or very
        near) the most recent candle -- a structure break from 500 bars
        ago isn't a signal about the CURRENT moment. Uses the same
        'bullish'/'bearish' vocabulary as the rest of the engine's
        signals so _compute_bullish_score's generic keyword scan still
        picks these up for its baseline contribution; the highest-
        conviction ones (CHoCH, springs/upthrusts, a harmonic pattern
        completing at D) additionally get explicit weighted contributions
        in _compute_bullish_score itself, since they're materially higher-
        conviction than a simple oscillator reading."""
        signals: list[str] = []
        last_idx = len(df) - 1
        recency_window = 3  # bars

        for event in structure_events:
            if event.index >= last_idx - recency_window:
                label = {
                    StructureEventKind.BOS_BULLISH: "Bullish break of structure (BOS)",
                    StructureEventKind.BOS_BEARISH: "Bearish break of structure (BOS)",
                    StructureEventKind.CHOCH_BULLISH: "Bullish change of character (CHoCH) -- possible reversal",
                    StructureEventKind.CHOCH_BEARISH: "Bearish change of character (CHoCH) -- possible reversal",
                }[event.kind]
                signals.append(label)

        for sweep in liquidity_sweeps:
            if sweep.index >= last_idx - recency_window:
                signals.append(
                    "Bullish liquidity sweep (stop hunt below support, reversal up expected)" if sweep.direction == "bullish"
                    else "Bearish liquidity sweep (stop hunt above resistance, reversal down expected)"
                )

        for spring in springs:
            if spring.index >= last_idx - recency_window:
                signals.append("Wyckoff spring detected (bullish accumulation signal)")
        for upthrust in upthrusts:
            if upthrust.index >= last_idx - recency_window:
                signals.append("Wyckoff upthrust detected (bearish distribution signal)")
        if wyckoff_phase in ("accumulation", "markup"):
            signals.append(f"Wyckoff phase: {wyckoff_phase} (bullish)")
        elif wyckoff_phase in ("distribution", "markdown"):
            signals.append(f"Wyckoff phase: {wyckoff_phase} (bearish)")

        if volume_profile is not None:
            close = float(df["close"].iloc[-1])
            if close > volume_profile.value_area_high:
                signals.append("Price above Volume Profile value area (bullish acceptance)")
            elif close < volume_profile.value_area_low:
                signals.append("Price below Volume Profile value area (bearish rejection)")

        for pattern in harmonic_patterns:
            if pattern.d_index >= last_idx - recency_window:
                signals.append(
                    f"{pattern.name} harmonic pattern completing (bullish reversal zone)" if pattern.direction == "bullish"
                    else f"{pattern.name} harmonic pattern completing (bearish reversal zone)"
                )

        divergence_labels = {
            DivergenceKind.REGULAR_BULLISH: "Regular bullish RSI divergence (price lower low, RSI higher low -- reversal up)",
            DivergenceKind.REGULAR_BEARISH: "Regular bearish RSI divergence (price higher high, RSI lower high -- reversal down)",
            DivergenceKind.HIDDEN_BULLISH: "Hidden bullish RSI divergence (price higher low, RSI lower low -- uptrend continuation)",
            DivergenceKind.HIDDEN_BEARISH: "Hidden bearish RSI divergence (price lower high, RSI higher high -- downtrend continuation)",
        }
        for div in rsi_divergences or []:
            if div.second_index >= last_idx - recency_window:
                signals.append(divergence_labels[div.kind])

        return signals

    def _compute_bullish_score(
        self,
        df: pd.DataFrame,
        trend: TrendDirection,
        signals: list[str],
        structure_events: Optional[list[StructureEvent]] = None,
        springs: Optional[list[WyckoffEvent]] = None,
        upthrusts: Optional[list[WyckoffEvent]] = None,
        harmonic_patterns: Optional[list[HarmonicPattern]] = None,
        rsi_divergences: Optional[list[RSIDivergence]] = None,
    ) -> float:
        """Compute composite bullish score from -100 to +100."""
        score = 0.0
        last = df.iloc[-1]

        if trend == TrendDirection.BULLISH:
            score += 30
        elif trend == TrendDirection.BEARISH:
            score -= 30

        rsi = last.get("rsi", 50)
        score += (rsi - 50) * 0.5

        if last.get("macd_hist", 0) > 0:
            score += 15
        else:
            score -= 15

        if last["close"] > last.get("ema_50", last["close"]):
            score += 10
        else:
            score -= 10

        bullish_signals = sum(1 for s in signals if "bullish" in s.lower() or "oversold" in s.lower())
        bearish_signals = sum(1 for s in signals if "bearish" in s.lower() or "overbought" in s.lower())
        score += (bullish_signals - bearish_signals) * 5

        # Added 2026-08-01: explicit, heavier-weighted contributions for
        # the highest-conviction new signals -- a CHoCH, a Wyckoff spring/
        # upthrust, or a harmonic pattern reaching its completion point
        # are each meaningfully higher-conviction than a plain oscillator
        # reading, and the generic keyword scan above already gives them
        # only the same flat +/-5 as everything else. Restricted to the
        # last few bars (same recency_window as _generate_advanced_signals)
        # so a break/spring/pattern from deep history doesn't keep moving
        # today's score.
        last_idx = len(df) - 1
        recency_window = 3
        for event in structure_events or []:
            if event.index >= last_idx - recency_window:
                if event.kind == StructureEventKind.CHOCH_BULLISH:
                    score += 12
                elif event.kind == StructureEventKind.CHOCH_BEARISH:
                    score -= 12
        for _ in [s for s in (springs or []) if s.index >= last_idx - recency_window]:
            score += 15
        for _ in [u for u in (upthrusts or []) if u.index >= last_idx - recency_window]:
            score -= 15
        for pattern in harmonic_patterns or []:
            if pattern.d_index >= last_idx - recency_window:
                score += 10 if pattern.direction == "bullish" else -10

        # RSI divergence -- regular divergence is a reversal read (same
        # conviction tier as CHoCH: it's price/momentum actively
        # disagreeing right now, not just a static oscillator level), so
        # it's weighted the same as CHoCH above. Hidden divergence is a
        # continuation read and gets half that weight -- it confirms the
        # prevailing move rather than calling a turn, a lower-conviction
        # claim than a reversal signal firing.
        for div in rsi_divergences or []:
            if div.second_index >= last_idx - recency_window:
                if div.kind == DivergenceKind.REGULAR_BULLISH:
                    score += 12
                elif div.kind == DivergenceKind.REGULAR_BEARISH:
                    score -= 12
                elif div.kind == DivergenceKind.HIDDEN_BULLISH:
                    score += 6
                elif div.kind == DivergenceKind.HIDDEN_BEARISH:
                    score -= 6

        return max(-100.0, min(100.0, score))

    def fibonacci_levels(
        self, high: float, low: float
    ) -> dict[str, float]:
        """
        Calculate Fibonacci retracement levels.

        Args:
            high: Swing high price.
            low: Swing low price.

        Returns:
            Dict of Fibonacci level names to prices.
        """
        diff = high - low
        return {
            "0.0": high,
            "0.236": high - 0.236 * diff,
            "0.382": high - 0.382 * diff,
            "0.5": high - 0.5 * diff,
            "0.618": high - 0.618 * diff,
            "0.786": high - 0.786 * diff,
            "1.0": low,
        }

    def pivot_points(
        self, high: float, low: float, close: float, method: str = "standard"
    ) -> dict[str, float]:
        """
        Calculate pivot point levels.

        Args:
            high: Previous period high.
            low: Previous period low.
            close: Previous period close.
            method: 'standard' or 'camarilla'.

        Returns:
            Dict of pivot level names to prices.
        """
        if method == "camarilla":
            diff = high - low
            return {
                "R4": close + diff * 1.1 / 2,
                "R3": close + diff * 1.1 / 4,
                "R2": close + diff * 1.1 / 6,
                "R1": close + diff * 1.1 / 12,
                "PP": close,
                "S1": close - diff * 1.1 / 12,
                "S2": close - diff * 1.1 / 6,
                "S3": close - diff * 1.1 / 4,
                "S4": close - diff * 1.1 / 2,
            }
        pp = (high + low + close) / 3
        return {
            "R3": high + 2 * (pp - low),
            "R2": pp + (high - low),
            "R1": 2 * pp - low,
            "PP": pp,
            "S1": 2 * pp - high,
            "S2": pp - (high - low),
            "S3": low - 2 * (high - pp),
        }

    def _build_knowledge_context(self, trend: TrendDirection, signals: list[str]) -> Optional[dict]:
        """Relevant technical-analysis book content for the classified
        trend + top signals, attached for transparency -- informational
        only, never changes trend/score. Best-effort: only runs if a real
        KnowledgeEngine instance was injected (see __init__ / registry.py)."""
        if self._knowledge_engine is None:
            return None
        try:
            query = f"{trend.value} trend " + " ".join(signals[:2])
            results = self._knowledge_engine.document_store.hybrid_search(query, limit=3)
        except Exception as e:
            logger.warning("Knowledge context unavailable: %s", e)
            return None
        if not results:
            return None
        return {"query": query, "results": [r.to_dict() for r in results]}
