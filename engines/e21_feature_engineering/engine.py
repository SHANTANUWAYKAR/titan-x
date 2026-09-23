"""
Module: engine.py
Description: Engine 21 -- Feature Engineering. Master prompt scope (line
    546, "Feature Engineering Factory": "technical/macro/sentiment/
    volatility/cross-asset/time features; reusable feature library" --
    slot #21 in the authoritative MAJOR ENGINES list is literally
    "Feature Engineering Engine").

    Deliberately NOT a second computation of anything another engine
    already computes (Rule 4: "don't compute the same expensive thing
    twice") -- this engine is an ASSEMBLER, not a re-implementer. Every
    technical/macro/derivatives value here is read straight out of the
    already-computed TechnicalSnapshot/MacroSnapshot/DerivativesSnapshot
    a caller passes in (or, if not passed, computed once via this
    engine's own injected collaborators using their real analyze()
    calls -- never a parallel formula). The only things genuinely
    computed here are calendar/time features (pure, deterministic
    arithmetic on a timestamp) and a fallback realized-volatility read
    used only when no DerivativesSnapshot is available.

    HONEST SCOPE BOUNDARY on sentiment: e09_sentiment scores individual
    pieces of TEXT (a headline, a note), not a standing per-asset
    sentiment feature -- there is no single "sentiment score for
    EURUSD" this engine can compute on its own without a text corpus to
    score. Rather than fabricate an aggregate, `sentiment` is caller-
    supplied (e.g. e51_signals already aggregates matched-headline
    sentiment per asset for its own confluence read -- a caller with
    that number can pass it straight through). None when not supplied,
    never a guessed 0.0 standing in for "no data."

    Rule 3: mechanical assembly needs no train/held-out calibration --
    same category as e31_portfolio_construction and e40_data_quality's
    own "no calibration" documentation. The one real convention used
    (30-day annualized realized vol for the fallback path) matches
    e13_derivatives' own existing realized_vol_30d convention exactly,
    not a new arbitrary window. scripts/training/validate_e21_feature_
    engineering.py is a live sanity check (real asset, real data, every
    feature group populates sensibly) per that same category's
    documented pattern (see e20_factor_research's own validate_ script).
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
from scipy import stats as scipy_stats

from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus

logger = logging.getLogger(__name__)

FALLBACK_REALIZED_VOL_WINDOW = 30  # trading days -- matches e13_derivatives.realized_vol_30d exactly
DISTRIBUTIONAL_WINDOW = 20  # bars -- matches this codebase's own common Donchian/lookback convention


@dataclass
class FeatureVector:
    """One asset's assembled feature set at a point in time, grouped by
    the master prompt's own named categories."""

    symbol: str
    timestamp: datetime
    technical: dict[str, float] = field(default_factory=dict)
    macro: dict[str, float] = field(default_factory=dict)
    volatility: dict[str, float] = field(default_factory=dict)
    cross_asset: dict[str, float] = field(default_factory=dict)
    time: dict[str, Any] = field(default_factory=dict)
    sentiment: dict[str, float] = field(default_factory=dict)
    # Added 2026-08-20: rolling statistical/shape descriptors of recent
    # returns (skew/kurtosis/persistence/extremes-location/trend-slope) --
    # see _distributional_features' own docstring for why this is a
    # genuinely distinct feature CATEGORY, not a duplicate of technical.
    distributional: dict[str, float] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)  # per-group: "provided" | "computed" | "unavailable"

    def to_flat_dict(self) -> dict[str, Any]:
        """One flat, prefixed dict -- the actual 'reusable feature
        library' output: ready to hand to a hypothesis test (E22), a
        forecast conditioning step (E23), or any future ML pipeline
        without that caller needing to know this engine's internal
        grouping."""
        flat: dict[str, Any] = {"symbol": self.symbol, "timestamp": self.timestamp.isoformat()}
        for prefix, group in (
            ("tech", self.technical), ("macro", self.macro), ("vol", self.volatility),
            ("xasset", self.cross_asset), ("time", self.time), ("sent", self.sentiment),
            ("dist", self.distributional),
        ):
            for k, v in group.items():
                flat[f"{prefix}_{k}"] = v
        return flat

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "technical": self.technical,
            "macro": self.macro,
            "volatility": self.volatility,
            "cross_asset": self.cross_asset,
            "time": self.time,
            "sentiment": self.sentiment,
            "distributional": self.distributional,
            "sources": self.sources,
        }


def _time_features(ts: datetime) -> dict[str, Any]:
    """Pure calendar arithmetic -- no external data, no calibration,
    always available."""
    return {
        "day_of_week": ts.weekday(),  # 0=Monday
        "day_of_month": ts.day,
        "month": ts.month,
        "quarter": (ts.month - 1) // 3 + 1,
        "is_month_start": ts.day <= 3,
        "is_month_end": ts.day >= 28,
        "is_quarter_end": ts.month in (3, 6, 9, 12) and ts.day >= 28,
    }


def _fallback_realized_vol(df: pd.DataFrame, window: int = FALLBACK_REALIZED_VOL_WINDOW) -> Optional[float]:
    """Annualized realized volatility from close-to-close returns --
    used only when no DerivativesSnapshot was provided/computable. Same
    window and annualization convention as e13_derivatives.
    _compute_realized_vol, so a feature vector's vol reading never
    silently disagrees with what E13 itself would report for the same
    asset."""
    if len(df) < window + 1:
        return None
    returns = df["close"].pct_change().dropna().tail(window)
    if len(returns) < window:
        return None
    return float(returns.std() * np.sqrt(252) * 100)


def _distributional_features(df: pd.DataFrame, window: int = DISTRIBUTIONAL_WINDOW) -> Optional[dict[str, float]]:
    """Rolling statistical/shape descriptors of the most recent `window`
    bars' returns -- the DISTRIBUTIONAL SHAPE of recent price action
    (skew/kurtosis/persistence-below-mean/location-of-extremes/trend-
    slope), genuinely distinct from technical INDICATORS (RSI/MACD/ADX/
    etc., which E07 already computes from price levels/differences) or a
    single realized-vol number (E13/the fallback above, which reduces an
    entire window to one dispersion figure). Real technique found while
    reviewing asavinov/intelligent-trading-bot (cloned read-only for
    reference) -- tsfresh-style generic time-series shape features
    (skew/kurtosis/"longest strike below mean"/location-of-max/area-ratio/
    linear-trend-slope), reimplemented here directly from scipy/numpy
    (not vendored) rather than adding a new heavy dependency for six
    formulas.

    Args:
        df: OHLCV DataFrame with a "close" column.
        window: Lookback in bars -- matches this codebase's own common
            Donchian/lookback convention (e.g. donchian_breakout's
            entry_n=20 default), not an arbitrary new figure.
    """
    if len(df) < window + 1:
        return None
    returns = df["close"].pct_change().dropna().tail(window).to_numpy()
    if len(returns) < window:
        return None

    mean = float(returns.mean())
    below_mean = returns < mean
    longest_strike = 0
    current_strike = 0
    for is_below in below_mean:
        current_strike = current_strike + 1 if is_below else 0
        longest_strike = max(longest_strike, current_strike)

    deviations = returns - mean
    area_above = float(deviations[deviations > 0].sum())
    area_below = float(-deviations[deviations < 0].sum())
    total_area = area_above + area_below
    area_ratio = (area_above - area_below) / total_area if total_area > 0 else 0.0

    slope = float(scipy_stats.linregress(np.arange(window), returns).slope)

    return {
        "skewness": round(float(scipy_stats.skew(returns)), 6),
        "excess_kurtosis": round(float(scipy_stats.kurtosis(returns)), 6),  # Fisher convention: 0 = normal
        "longest_strike_below_mean_frac": round(longest_strike / window, 4),
        "max_return_location_frac": round(float(np.argmax(returns)) / window, 4),
        "area_ratio": round(area_ratio, 4),  # -1 = all deviation below mean, +1 = all above
        "linear_trend_slope": round(slope, 8),
    }


class FeatureEngineeringEngine(BaseEngine):
    """
    Feature Engineering Engine (#21) -- assembles a structured, reusable
    feature vector per asset from already-computed engine outputs
    (technical/macro/volatility/cross-asset) plus real calendar/time
    features. Never recomputes what another engine already computed
    (Rule 4); every injected collaborator is optional so this engine
    degrades gracefully (missing groups reported honestly via `sources`,
    never silently zero-filled) rather than requiring the full engine
    graph to be present.
    """

    engine_id = "e21_feature_engineering"
    engine_name = "Feature Engineering Engine"
    version = "1.0.0"

    def __init__(
        self,
        technical_engine: Optional[Any] = None,
        macro_engine: Optional[Any] = None,
        derivatives_engine: Optional[Any] = None,
        cross_asset_engine: Optional[Any] = None,
    ) -> None:
        super().__init__()
        self._technical_engine = technical_engine
        self._macro_engine = macro_engine
        self._derivatives_engine = derivatives_engine
        self._cross_asset_engine = cross_asset_engine

    def initialize(self) -> EngineResult:
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Feature Engineering Engine initialized")

    def health_check(self) -> EngineResult:
        return EngineResult(success=True, message="Healthy")

    def compute_features(
        self,
        symbol: str,
        df: pd.DataFrame,
        timeframe: str = "1d",
        technical_snapshot: Optional[Any] = None,
        macro_snapshot: Optional[Any] = None,
        derivatives_snapshot: Optional[Any] = None,
        sentiment_score: Optional[float] = None,
        cross_asset_pairs: Optional[dict[str, float]] = None,
    ) -> EngineResult:
        """Assembles one FeatureVector for `symbol` at df's last bar.
        Every *_snapshot param is OPTIONAL -- pass an already-computed
        one (e.g. from the same workflow run that already called E07/
        E04/E13) to avoid a duplicate analyze() call; omit it to let
        this engine compute it fresh via its own injected collaborator
        (best-effort -- a failure there degrades that ONE group to
        'unavailable', never the whole vector)."""
        try:
            self._set_status(EngineStatus.RUNNING)
            if len(df) < 2:
                return EngineResult(success=False, message="Need at least 2 OHLCV bars")

            # Same convention as every other OHLCV consumer in this codebase
            # (e02_market_data.fetch_ohlcv always returns a plain RangeIndex
            # with a tz-aware UTC "timestamp" column, never a datetime
            # index) -- see e20_factor_research's identical
            # pd.to_datetime(df["timestamp"]) usage.
            ts = pd.to_datetime(df["timestamp"].iloc[-1])
            if ts.tzinfo is None:
                ts = ts.tz_localize(timezone.utc)
            sources: dict[str, str] = {}

            technical = self._assemble_technical(df, symbol, timeframe, technical_snapshot, sources)
            macro = self._assemble_macro(macro_snapshot, sources)
            volatility = self._assemble_volatility(df, derivatives_snapshot, symbol, sources)
            cross_asset = dict(cross_asset_pairs) if cross_asset_pairs else {}
            sources["cross_asset"] = "provided" if cross_asset_pairs else "unavailable"
            sentiment = {"score": sentiment_score} if sentiment_score is not None else {}
            sources["sentiment"] = "provided" if sentiment_score is not None else "unavailable"
            time_feats = _time_features(ts.to_pydatetime())
            sources["time"] = "computed"
            distributional = _distributional_features(df)
            sources["distributional"] = "computed" if distributional is not None else "unavailable"

            vector = FeatureVector(
                symbol=symbol, timestamp=ts.to_pydatetime(),
                technical=technical, macro=macro, volatility=volatility,
                cross_asset=cross_asset, time=time_feats, sentiment=sentiment,
                distributional=distributional or {},
                sources=sources,
            )
            self._set_status(EngineStatus.IDLE)
            populated = [k for k, v in sources.items() if v != "unavailable"]
            return EngineResult(
                success=True, data=vector,
                message=f"{symbol}: assembled {len(populated)}/{len(sources)} feature groups ({', '.join(populated)})",
            )
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("Feature assembly failed for %s: %s", symbol, e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def _assemble_technical(
        self, df: pd.DataFrame, symbol: str, timeframe: str, snapshot: Optional[Any], sources: dict
    ) -> dict[str, float]:
        if snapshot is not None:
            sources["technical"] = "provided"
            return dict(snapshot.indicators)
        if self._technical_engine is None:
            sources["technical"] = "unavailable"
            return {}
        try:
            result = self._technical_engine.analyze(df, symbol=symbol, timeframe=timeframe)
            if result.success:
                sources["technical"] = "computed"
                return dict(result.data["snapshot"].indicators)
        except Exception as e:
            logger.warning("Technical feature computation failed for %s: %s", symbol, e)
        sources["technical"] = "unavailable"
        return {}

    def _assemble_macro(self, snapshot: Optional[Any], sources: dict) -> dict[str, float]:
        if snapshot is not None:
            sources["macro"] = "provided"
            return {"risk_on_off_score": snapshot.risk_on_off_score, **snapshot.indicators}
        if self._macro_engine is None:
            sources["macro"] = "unavailable"
            return {}
        try:
            result = self._macro_engine.analyze()
            if result.success:
                sources["macro"] = "computed"
                return {"risk_on_off_score": result.data.risk_on_off_score, **result.data.indicators}
        except Exception as e:
            logger.warning("Macro feature computation failed: %s", e)
        sources["macro"] = "unavailable"
        return {}

    def _assemble_volatility(
        self, df: pd.DataFrame, snapshot: Optional[Any], symbol: str, sources: dict
    ) -> dict[str, float]:
        if snapshot is not None and getattr(snapshot, "realized_vol_30d", None) is not None:
            sources["volatility"] = "provided"
            return {
                "realized_vol_30d": snapshot.realized_vol_30d,
                "realized_vol_regime": snapshot.realized_vol_regime,
            }
        if self._derivatives_engine is not None:
            try:
                result = self._derivatives_engine.analyze(symbol)
                if result.success and result.data is not None and result.data.realized_vol_30d is not None:
                    sources["volatility"] = "computed"
                    return {
                        "realized_vol_30d": result.data.realized_vol_30d,
                        "realized_vol_regime": result.data.realized_vol_regime,
                    }
            except Exception as e:
                logger.warning("Derivatives-based volatility feature failed for %s: %s", symbol, e)
        # Fallback: mechanical realized vol straight from price, no engine needed
        fallback = _fallback_realized_vol(df)
        if fallback is not None:
            sources["volatility"] = "computed_fallback"
            return {"realized_vol_30d": fallback, "realized_vol_regime": "uncalibrated"}
        sources["volatility"] = "unavailable"
        return {}
