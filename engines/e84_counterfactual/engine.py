"""
Module: engine.py
Description: Engine 84 -- Counterfactual. See MASTER_PROMPT.md's "PROMPT
    5" section: genuinely new -- "if CPI had printed higher, would this
    signal have fired" is a backward-looking ANALOG-REPLAY question,
    distinct from E29 Scenario Analysis's forward-looking worst-case
    replay and E22 Alpha Research's aggregate significance TEST.

    Real technique: given a real condition (e.g. "VIX above 25", "ADX
    trending"), find every REAL individual historical date this exact
    condition actually held for this asset, and report what REALLY
    happened forward from each one (real dates, real forward returns) --
    an honest list of real historical episodes, never a simulated
    alternate history. "Counterfactual" here means "here are the real
    other times this held, replayed individually," not a fabricated
    parallel timeline.

    Rule 3: no calibration script -- deterministic historical episode
    lookup over already-real price/VIX data, no parameters of its own to
    fit.
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

logger = logging.getLogger(__name__)

MIN_EPISODES = 3


def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Identical closed-form ADX to e07/e08/e22/e23/e37/e74 -- reused, not re-derived."""
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
class HistoricalEpisode:
    date_str: str
    close_at_episode: float
    forward_return_pct: Optional[float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date_str, "close_at_episode": round(self.close_at_episode, 4),
            "forward_return_pct": round(self.forward_return_pct, 3) if self.forward_return_pct is not None else None,
        }


@dataclass
class CounterfactualReport:
    symbol: str
    condition: str
    generated_at: datetime
    horizon_days: int
    episodes: list[HistoricalEpisode] = field(default_factory=list)
    median_forward_return_pct: Optional[float] = None
    n_episodes: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol, "condition": self.condition, "generated_at": self.generated_at.isoformat(),
            "horizon_days": self.horizon_days, "n_episodes": self.n_episodes,
            "median_forward_return_pct": round(self.median_forward_return_pct, 3) if self.median_forward_return_pct is not None else None,
            "episodes": [e.to_dict() for e in self.episodes],
        }


class CounterfactualEngine(BaseEngine):
    """Counterfactual Engine (#84) -- "here are the real other times this
    condition held, and what really happened" -- an honest analog-replay,
    never a fabricated alternate history."""

    engine_id = "e84_counterfactual"
    engine_name = "Counterfactual Engine"
    version = "1.0.0"

    def __init__(self, market_data_engine: Optional[Any] = None) -> None:
        super().__init__()
        self._market_data_engine = market_data_engine

    def initialize(self) -> EngineResult:
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Counterfactual Engine initialized")

    def health_check(self) -> EngineResult:
        return EngineResult(success=True, message="Healthy")

    def replay_condition(
        self, symbol: str, condition: str = "vix_elevated", horizon_days: int = 20,
        threshold_multiplier: float = 1.0, years: int = 10,
    ) -> EngineResult:
        """condition: "vix_elevated" (VIX above its own trailing 252-day
        median * threshold_multiplier) or "trending" (this asset's own
        ADX above its trailing 252-day median * threshold_multiplier) --
        same real, reused conventions as e22/e23/e37/e74, never a new
        ad-hoc definition."""
        if self._market_data_engine is None:
            return EngineResult(success=False, message="No market_data_engine injected")
        if condition not in ("vix_elevated", "trending"):
            return EngineResult(success=False, message="condition must be 'vix_elevated' or 'trending'")
        try:
            self._set_status(EngineStatus.RUNNING)
            asset = get_asset(symbol)
            yahoo_symbol = asset.yahoo_symbol if asset else symbol
            price_fetch = self._market_data_engine.fetch_ohlcv(yahoo_symbol, "1d", years=years)
            if not price_fetch.success or price_fetch.data is None or price_fetch.data.empty:
                return EngineResult(success=False, message=f"Could not fetch OHLCV for {symbol}")
            df = price_fetch.data.reset_index(drop=True)

            if condition == "vix_elevated":
                vix_fetch = self._market_data_engine.fetch_ohlcv("^VIX", "1d", years=years)
                if not vix_fetch.success or vix_fetch.data is None:
                    return EngineResult(success=False, message="Could not fetch real VIX history")
                # Merge on DATE only -- same real cross-source hour-of-day
                # mismatch e64_causal_intelligence's own fix documents
                # (VIX closes its trading day at a different UTC hour than
                # commodity/index futures), verified live.
                vix_df = vix_fetch.data[["timestamp", "close"]].rename(columns={"close": "vix"})
                df["date_key"] = df["timestamp"].dt.date
                vix_df["date_key"] = vix_df["timestamp"].dt.date
                df = pd.merge(df, vix_df[["date_key", "vix"]], on="date_key", how="inner")
                series = df["vix"]
            else:
                series = _adx(df)

            median = series.rolling(252, min_periods=60).median()
            condition_mask = series > (median * threshold_multiplier)

            forward_return = (df["close"].shift(-horizon_days) / df["close"] - 1.0) * 100.0
            episode_rows = df[condition_mask.fillna(False)]
            episodes = []
            for idx in episode_rows.index:
                fr = forward_return.iloc[idx] if idx < len(forward_return) else None
                episodes.append(HistoricalEpisode(
                    date_str=str(df["timestamp"].iloc[idx])[:10], close_at_episode=float(df["close"].iloc[idx]),
                    forward_return_pct=float(fr) if fr == fr else None,  # NaN check
                ))

            valid_returns = [e.forward_return_pct for e in episodes if e.forward_return_pct is not None]
            if len(valid_returns) < MIN_EPISODES:
                report = CounterfactualReport(symbol=asset.symbol if asset else symbol, condition=condition, generated_at=datetime.now(timezone.utc), horizon_days=horizon_days, episodes=episodes, n_episodes=len(episodes))
                self._set_status(EngineStatus.IDLE)
                return EngineResult(success=True, data=report, message=f"Only {len(valid_returns)} real historical episode(s) with a known outcome -- too few for a meaningful median")

            median_fr = float(np.median(valid_returns))
            report = CounterfactualReport(
                symbol=asset.symbol if asset else symbol, condition=condition, generated_at=datetime.now(timezone.utc),
                horizon_days=horizon_days, episodes=episodes, median_forward_return_pct=median_fr, n_episodes=len(episodes),
            )
            self._set_status(EngineStatus.IDLE)
            return EngineResult(
                success=True, data=report,
                message=f"{symbol}: {len(episodes)} real historical episode(s) of '{condition}', median {horizon_days}d forward return {median_fr:+.2f}%",
            )
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("replay_condition failed for %s: %s", symbol, e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])
