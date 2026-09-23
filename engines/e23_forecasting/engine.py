"""
Module: engine.py
Description: Engine 23 -- Forecasting. Master prompt scope (line 564,
    Prompt 3's own numbering, kept for detail per Rule 1): "Forecasting
    Engine -- probabilistic forecasts, scenario forecasts, confidence
    intervals; avoid deterministic predictions." Slot #23 in the
    authoritative MAJOR ENGINES list is literally "Forecasting Engine."

    The master prompt's own instruction ("avoid deterministic
    predictions") is taken literally: this engine NEVER returns a single
    point price/return prediction. Every forecast is an empirical
    (historical-bootstrap) distribution of real, already-realized
    N-day-forward returns -- percentiles (p5/p25/median/p75/p95), not a
    guess. This is a standard, honest quant technique (historical
    simulation) -- "the future isn't certain, so describe the real
    spread of what has actually happened before, not a fabricated single
    number."

    Scenario forecasts condition that same empirical distribution on a
    real, cheaply-computable regime split (ADX-based trending/ranging,
    same convention as e22_alpha_research's own trending-regime
    hypothesis, so a "scenario" here means the identical thing it means
    there) -- "here is the return distribution specifically when this
    asset was trending vs ranging," not a single conditional guess.

    Rule 3 -- REAL, validated calibration (not just fit): this engine's
    entire honesty claim is "our 90% interval actually contains ~90% of
    real outcomes." scripts/training/validate_e23_forecasting.py checks
    exactly that on a genuine chronological held-out split (build the
    percentiles from an EARLIER window, check coverage against a LATER,
    unseen window) -- the forecasting equivalent of e42_confidence_
    calibration's Brier score, and the honest answer to "prove your
    probabilities mean something" rather than assuming a historical
    distribution generalizes forward without ever checking.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus
from project_titan_x.engines.e02_market_data.engine import MarketDataEngine

logger = logging.getLogger(__name__)

MIN_OBSERVATIONS = 60  # below this, empirical percentiles are too noisy to report honestly
PERCENTILES = (5, 25, 50, 75, 95)


@dataclass
class ProbabilisticForecast:
    symbol: str
    horizon_days: int
    n_observations: int
    current_price: float
    return_percentiles_pct: dict[int, float] = field(default_factory=dict)  # {5: -3.2, 25: -0.8, 50: 1.1, ...}
    price_percentiles: dict[int, float] = field(default_factory=dict)  # same percentiles, converted to price levels
    scenario: Optional[str] = None  # None = unconditional; else e.g. "trending" / "ranging"
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "horizon_days": self.horizon_days,
            "n_observations": self.n_observations,
            "current_price": round(self.current_price, 4),
            "return_percentiles_pct": {k: round(v, 3) for k, v in self.return_percentiles_pct.items()},
            "price_percentiles": {k: round(v, 4) for k, v in self.price_percentiles.items()},
            "scenario": self.scenario,
            "generated_at": self.generated_at.isoformat(),
            "disclaimer": "Empirical historical distribution, not a deterministic prediction -- see this engine's own calibration report before trusting interval width.",
        }


def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Identical closed-form ADX to e07_technical/e22_alpha_research --
    reused, not re-derived, so 'trending' means the same thing everywhere."""
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


def _forward_returns(df: pd.DataFrame, horizon_days: int) -> pd.Series:
    return (df["close"].shift(-horizon_days) / df["close"] - 1.0) * 100.0


class ForecastingEngine(BaseEngine):
    """
    Forecasting Engine (#23) -- probabilistic/scenario forecasts via
    empirical historical-return distributions. Deliberately never
    returns a single point prediction, per the master prompt's own
    explicit instruction.
    """

    engine_id = "e23_forecasting"
    engine_name = "Forecasting Engine"
    version = "1.0.0"

    def __init__(self, market_data_engine: Optional[MarketDataEngine] = None) -> None:
        super().__init__()
        self._market_data_engine = market_data_engine if market_data_engine is not None else MarketDataEngine()

    def initialize(self) -> EngineResult:
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Forecasting Engine initialized")

    def health_check(self) -> EngineResult:
        return EngineResult(success=True, message="Healthy")

    def forecast(
        self, symbol: str, yahoo_symbol: str, horizon_days: int = 20, years: int = 10, scenario: Optional[str] = None,
    ) -> EngineResult:
        """Empirical N-day-forward return distribution for `symbol`.
        scenario=None (default): unconditional, uses every historical
        window. scenario="trending"/"ranging": conditions on this
        asset's OWN ADX history being above/below its trailing median
        (same convention as e22_alpha_research's trending-regime
        hypothesis) -- a real 'scenario forecast', not a label with no
        data behind it."""
        try:
            self._set_status(EngineStatus.RUNNING)
            fetch = self._market_data_engine.fetch_ohlcv(yahoo_symbol, "1d", years=years)
            if not fetch.success or fetch.data is None or fetch.data.empty:
                return EngineResult(success=False, message=f"Could not fetch price data for {symbol} ({yahoo_symbol})")

            df = fetch.data.copy().reset_index(drop=True)
            df["forward_return_pct"] = _forward_returns(df, horizon_days)
            current_price = float(df["close"].iloc[-1])

            if scenario is not None:
                df["adx"] = _adx(df)
                df["adx_median"] = df["adx"].rolling(252, min_periods=60).median()
                is_trending = df["adx"] > df["adx_median"]
                mask = is_trending if scenario == "trending" else ~is_trending
                df = df[mask]

            returns = df["forward_return_pct"].dropna()
            if len(returns) < MIN_OBSERVATIONS:
                return EngineResult(
                    success=False,
                    message=f"Only {len(returns)} historical {horizon_days}-day windows for {symbol}{' (' + scenario + ')' if scenario else ''} -- need >={MIN_OBSERVATIONS} for a meaningful empirical distribution",
                )

            return_pcts = {p: float(np.percentile(returns, p)) for p in PERCENTILES}
            price_levels = {p: current_price * (1 + return_pcts[p] / 100.0) for p in PERCENTILES}

            result = ProbabilisticForecast(
                symbol=symbol, horizon_days=horizon_days, n_observations=len(returns),
                current_price=current_price, return_percentiles_pct=return_pcts,
                price_percentiles=price_levels, scenario=scenario,
            )
            self._set_status(EngineStatus.IDLE)
            median = return_pcts[50]
            spread = return_pcts[95] - return_pcts[5]
            return EngineResult(
                success=True, data=result,
                message=(
                    f"{symbol} {horizon_days}d forecast{' (' + scenario + ')' if scenario else ''}: "
                    f"median {median:+.2f}%, 90% interval spans {spread:.2f}pp (n={len(returns)})"
                ),
            )
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("Forecast failed for %s: %s", symbol, e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    @staticmethod
    def check_coverage(returns: pd.Series, train_frac: float = 0.7) -> dict:
        """REAL calibration check (Rule 3): builds the p5/p95 interval
        from the FIRST train_frac of a return series, then measures what
        fraction of the REMAINING (held-out, chronologically later)
        returns actually fall inside that interval. A well-calibrated
        90% interval should cover close to 90% of held-out outcomes --
        this is the honest, checkable claim, not an assumption. Used by
        scripts/training/validate_e23_forecasting.py; exposed as a
        static method so it can be tested directly against any real
        return series without needing a live network fetch."""
        n = len(returns)
        split = int(n * train_frac)
        train, test = returns.iloc[:split], returns.iloc[split:]
        if len(train) < MIN_OBSERVATIONS or len(test) < 10:
            return {"status": "insufficient_data", "n_train": len(train), "n_test": len(test)}
        p5, p95 = np.percentile(train, 5), np.percentile(train, 95)
        covered = ((test >= p5) & (test <= p95)).mean()
        return {
            "status": "ok", "n_train": len(train), "n_test": len(test),
            "train_p5": float(p5), "train_p95": float(p95),
            "target_coverage_pct": 90.0, "actual_coverage_pct": round(float(covered) * 100, 1),
        }
