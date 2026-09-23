"""
Module: engine.py
Description: Engine 11 — Market Microstructure Analysis.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-07-14
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus
from project_titan_x.engines.e01_knowledge.engine import KnowledgeEngine

logger = logging.getLogger(__name__)

# No order book / Level 2 feed exists for free, so this engine deliberately
# ESTIMATES effective spread and liquidity from OHLCV alone rather than
# fabricating bid/ask quotes or market depth -- inventing quote-level data
# that looks real but isn't would be worse than not having it.
#
# The estimator is Corwin & Schultz (2012, "A Simple Way to Estimate
# Bid-Ask Spreads from Daily High and Low Prices", Journal of Finance): a
# real, peer-reviewed method that separates a bar's high-low range into a
# volatility component and a bid-ask-bounce component by comparing a single
# bar's range against a two-bar range (twice the time, only ~sqrt(2)x the
# volatility, but the SAME bounce contribution). This is the standard
# academic answer to "estimate the spread when you have no quote data" --
# not a heuristic invented for this project.

MIN_BARS_FOR_ESTIMATE = 22
ROLLING_WINDOW = 20
RELATIVE_VOLUME_WINDOW = 20
THIN_VOLUME_RATIO = 0.5
ELEVATED_VOLUME_RATIO = 1.5
WIDE_SPREAD_PERCENTILE = 75.0
NARROW_SPREAD_PERCENTILE = 25.0
HIGH_ILLIQUIDITY_PERCENTILE = 75.0
LOW_ILLIQUIDITY_PERCENTILE = 25.0

_CS_K = 3 - 2 * np.sqrt(2)

# FX trading sessions in UTC hour-of-day. London-New York overlap is the
# deepest liquidity window for FX majors; outside any major session is the
# thinnest. Only meaningful for forex -- crypto is always-on with no
# session structure, and commodities/indices trade on exchange hours, not
# this kind of session-liquidity-wave structure.
FX_LONDON_NY_OVERLAP_HOURS = range(12, 16)
FX_ACTIVE_HOURS = set(range(7, 21))


@dataclass
class MicrostructureSnapshot:
    """Estimated execution-risk read for one instrument's most recent bar."""

    symbol: str
    timeframe: str
    estimated_spread_pct: float
    estimated_spread_percentile: float
    relative_volume: Optional[float]
    volume_label: str  # thin | normal | elevated | unknown
    amihud_illiquidity_x1e6: Optional[float]
    amihud_illiquidity_percentile: Optional[float]
    session: Optional[dict]
    execution_risk: str  # low | medium | high | unknown
    notes: list[str] = field(default_factory=list)
    method: str = (
        "Corwin-Schultz high-low spread estimator (Journal of Finance, 2012) + "
        "Amihud illiquidity ratio (Journal of Financial Markets, 2002); "
        "no order book / bid-ask feed available for free, so these are estimates, not quotes"
    )
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    knowledge_context: Optional[dict] = None


def _corwin_schultz_spread_series(high: np.ndarray, low: np.ndarray) -> np.ndarray:
    """Per-bar effective-spread estimate (fraction of price), aligned so
    index i uses bars i-1 and i. Index 0 and any pair with non-positive or
    inverted (high<low) prices is NaN. Negative raw estimates are floored at
    0 -- standard practice from the paper, since a negative spread has no
    economic meaning and is just estimator noise on quiet bars."""
    n = len(high)
    spreads = np.full(n, np.nan)
    for t in range(n - 1):
        h1, l1, h2, l2 = high[t], low[t], high[t + 1], low[t + 1]
        if h1 <= 0 or l1 <= 0 or h2 <= 0 or l2 <= 0 or h1 < l1 or h2 < l2:
            continue
        beta = np.log(h1 / l1) ** 2 + np.log(h2 / l2) ** 2
        hh, ll = max(h1, h2), min(l1, l2)
        gamma = np.log(hh / ll) ** 2
        alpha = (np.sqrt(2 * beta) - np.sqrt(beta)) / _CS_K - np.sqrt(gamma / _CS_K)
        spread = 2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha))
        spreads[t + 1] = max(spread, 0.0)
    return spreads


def _amihud_illiquidity_series(close: np.ndarray, volume: np.ndarray, asset_class: str = "") -> np.ndarray:
    """Amihud (2002) illiquidity ratio: |return| / dollar volume, per bar --
    how much price moves per dollar traded. A genuinely different liquidity
    dimension than the Corwin-Schultz spread (transaction cost) or relative
    volume (activity level): this is a price-impact proxy, the standard
    OHLCV-only complement to a spread estimate in the market-microstructure
    literature (e.g. paired the same way in Amihud's own and follow-on
    papers). NaN where dollar volume is zero/unusable (e.g. FX, which Yahoo
    reports as 0 volume for).

    Dollar volume = close * volume for instruments where "volume" is a unit
    count (shares, contracts) -- true for equities/commodities/indices here.
    Crypto is the one exception: yfinance's BTC-USD/ETH-USD "volume" field
    is ALREADY quote-currency (USD) turnover, not a coin count (confirmed
    directly: ETH-USD daily volume reads ~1e10, which is impossible as a
    coin count -- total ETH supply is ~1.2e8). Multiplying that by close
    again would double-count price, making the series track close^2 instead
    of real turnover and corrupting its own percentile history as price
    moves over time -- not just a constant scale error, since crypto price
    can swing 10x+ within one instrument's own lookback window."""
    n = len(close)
    illiq = np.full(n, np.nan)
    price_already_in_volume = asset_class == "crypto"
    for t in range(1, n):
        dollar_volume = volume[t] if price_already_in_volume else close[t] * volume[t]
        if dollar_volume <= 0 or close[t - 1] <= 0 or close[t] <= 0:
            continue
        ret = abs(np.log(close[t] / close[t - 1]))
        illiq[t] = ret / dollar_volume
    return illiq


def _relative_volume(volume: np.ndarray, window: int = RELATIVE_VOLUME_WINDOW) -> Optional[float]:
    """Current bar's volume vs. its own trailing average -- >1 means busier
    than usual (better liquidity), <1 means thinner than usual. None (not
    zero) when volume data isn't usable (e.g. forex, which Yahoo reports as
    0), so callers can distinguish 'no data' from 'genuinely thin'."""
    if len(volume) < window + 1:
        return None
    trailing_avg = float(np.mean(volume[-(window + 1):-1]))
    if trailing_avg <= 0:
        return None
    return float(volume[-1]) / trailing_avg


def _volume_label(rel_volume: Optional[float]) -> str:
    if rel_volume is None:
        return "unknown"
    if rel_volume < THIN_VOLUME_RATIO:
        return "thin"
    if rel_volume > ELEVATED_VOLUME_RATIO:
        return "elevated"
    return "normal"


def _classify_fx_session(as_of: datetime) -> dict:
    hour = as_of.astimezone(timezone.utc).hour
    if hour in FX_LONDON_NY_OVERLAP_HOURS:
        return {"session": "london_ny_overlap", "liquidity": "peak"}
    if hour in FX_ACTIVE_HOURS:
        return {"session": "london_or_new_york", "liquidity": "active"}
    return {"session": "asia_pacific_only", "liquidity": "quiet"}


def _percentile_rank(value: float, population: np.ndarray) -> float:
    if len(population) == 0:
        return 50.0
    return float(np.mean(population <= value) * 100)


def _execution_risk(
    spread_percentile: Optional[float],
    rel_volume: Optional[float],
    session: Optional[dict],
    amihud_percentile: Optional[float] = None,
) -> tuple[str, list[str]]:
    notes: list[str] = []
    risk_votes = 0
    total_votes = 0

    if spread_percentile is not None:
        total_votes += 1
        if spread_percentile >= WIDE_SPREAD_PERCENTILE:
            risk_votes += 1
            notes.append(f"estimated spread wider than usual for this instrument ({spread_percentile:.0f}th percentile of its own recent history)")
        elif spread_percentile <= NARROW_SPREAD_PERCENTILE:
            notes.append(f"estimated spread tighter than usual ({spread_percentile:.0f}th percentile)")
        else:
            notes.append(f"estimated spread in its normal range ({spread_percentile:.0f}th percentile)")

    if rel_volume is not None:
        total_votes += 1
        label = _volume_label(rel_volume)
        if label == "thin":
            risk_votes += 1
            notes.append(f"volume thin vs. its own {RELATIVE_VOLUME_WINDOW}-bar average ({rel_volume:.2f}x)")
        elif label == "elevated":
            notes.append(f"volume elevated vs. its own {RELATIVE_VOLUME_WINDOW}-bar average ({rel_volume:.2f}x)")
        else:
            notes.append(f"volume close to its own {RELATIVE_VOLUME_WINDOW}-bar average ({rel_volume:.2f}x)")

    if amihud_percentile is not None:
        total_votes += 1
        if amihud_percentile >= HIGH_ILLIQUIDITY_PERCENTILE:
            risk_votes += 1
            notes.append(f"price impact per dollar traded higher than usual for this instrument (Amihud ratio at its {amihud_percentile:.0f}th percentile)")
        elif amihud_percentile <= LOW_ILLIQUIDITY_PERCENTILE:
            notes.append(f"price impact per dollar traded lower than usual (Amihud ratio at its {amihud_percentile:.0f}th percentile)")
        else:
            notes.append(f"price impact per dollar traded in its normal range ({amihud_percentile:.0f}th percentile)")

    if session is not None:
        total_votes += 1
        if session["liquidity"] == "quiet":
            risk_votes += 1
            notes.append(f"outside London/New York hours ({session['session']}) -- thinner FX liquidity typical")
        elif session["liquidity"] == "peak":
            notes.append("London-New York overlap -- deepest FX liquidity window")
        else:
            notes.append(f"within an active FX session ({session['session']})")

    if total_votes == 0:
        return "unknown", notes
    risk_fraction = risk_votes / total_votes
    if risk_fraction >= 0.66:
        return "high", notes
    if risk_fraction >= 0.33:
        return "medium", notes
    return "low", notes


class MarketMicrostructureEngine(BaseEngine):
    """
    Market Microstructure Engine — estimated execution risk from OHLCV.

    No free order book / Level 2 feed exists, so this does NOT attempt bid/
    ask quotes, market depth, or order-book imbalance -- fabricating those
    would be a worse failure mode than not having them (a fake "spread" that
    looks like real market data but isn't is exactly the silent bad-data
    risk E32 Data Quality exists to catch elsewhere in this platform).

    What IS genuinely computable from free OHLCV, and implemented here:
      - Corwin-Schultz effective bid-ask spread estimate (transaction cost).
      - Amihud illiquidity ratio, |return|/dollar-volume (price impact) --
        a distinct dimension from spread: an instrument can have a tight
        spread but still move a lot per dollar traded, or vice versa.
      - Relative volume (current vs. own trailing average) as a liquidity proxy.
      - FX trading-session classification (forex only).

    Execution risk is read off where the CURRENT spread estimate sits in its
    OWN recent history (percentile), not a fixed cross-asset threshold -- a
    0.02% spread is wide for a major FX pair and tight for gold futures, so
    comparing an instrument to itself is the only honest asset-class-
    agnostic way to do this. Informational only: this engine does not
    change any other engine's confidence or direction, same convention as
    E03 Macro / E05 Fundamental context attached to a signal.
    """

    engine_id = "e11_microstructure"
    engine_name = "Market Microstructure Engine"
    version = "1.0.0"

    def __init__(self, knowledge_engine: Optional[KnowledgeEngine] = None) -> None:
        super().__init__()
        # Optional and None by default: without it, analyze() behaves
        # exactly as before (no knowledge_context). Pass a real instance
        # (as registry.py does) to turn it on.
        self._knowledge_engine = knowledge_engine

    def initialize(self) -> EngineResult:
        """Initialize engine (stateless -- nothing to warm up)."""
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Market Microstructure Engine initialized")

    def health_check(self) -> EngineResult:
        """Health check (always healthy -- no external dependencies)."""
        return EngineResult(success=True, message="Healthy")

    def analyze(
        self,
        df: pd.DataFrame,
        symbol: str = "",
        timeframe: str = "1d",
        asset_class: str = "",
    ) -> EngineResult:
        """
        Estimate execution risk (spread/liquidity) for an instrument's most
        recent bar.

        Args:
            df: OHLCV DataFrame (must have high/low/volume columns).
            symbol: Asset symbol, for labeling only.
            timeframe: Candle timeframe, for labeling only.
            asset_class: One of core.config.assets.AssetClass's values --
                only "forex" gets an FX session read; everything else gets
                spread/volume only (an honest scope limit, not a bug).

        Returns:
            EngineResult with a MicrostructureSnapshot in data, or
            success=False if there isn't enough history for a stable read.
        """
        try:
            self._set_status(EngineStatus.RUNNING)
            if len(df) < MIN_BARS_FOR_ESTIMATE:
                raise ValueError(
                    f"Only {len(df)} bars available for {symbol or 'symbol'} -- "
                    f"need at least {MIN_BARS_FOR_ESTIMATE} for a stable microstructure read"
                )

            high = df["high"].to_numpy()
            low = df["low"].to_numpy()
            close = df["close"].to_numpy()
            volume = df["volume"].to_numpy() if "volume" in df.columns else np.zeros(len(df))
            as_of = pd.Timestamp(df["timestamp"].iloc[-1]).to_pydatetime()

            spread_series = _corwin_schultz_spread_series(high, low)
            window = spread_series[-ROLLING_WINDOW:]
            valid_window = window[~np.isnan(window)]
            if len(valid_window) < 5:
                raise ValueError(f"Not enough valid spread estimates for {symbol or 'symbol'} in the recent window")

            current_spread = float(valid_window[-1])
            spread_percentile = (
                _percentile_rank(current_spread, valid_window[:-1]) if len(valid_window) > 1 else 50.0
            )

            rel_volume = _relative_volume(volume)
            session = _classify_fx_session(as_of) if asset_class == "forex" else None

            illiq_series = _amihud_illiquidity_series(close, volume, asset_class)
            illiq_window = illiq_series[-ROLLING_WINDOW:]
            valid_illiq = illiq_window[~np.isnan(illiq_window)]
            amihud_illiquidity = float(valid_illiq[-1]) if len(valid_illiq) else None
            amihud_percentile = (
                _percentile_rank(amihud_illiquidity, valid_illiq[:-1])
                if amihud_illiquidity is not None and len(valid_illiq) > 1
                else None
            )

            execution_risk, notes = _execution_risk(spread_percentile, rel_volume, session, amihud_percentile)

            snapshot = MicrostructureSnapshot(
                symbol=symbol,
                timeframe=timeframe,
                estimated_spread_pct=round(current_spread * 100, 4),
                estimated_spread_percentile=round(spread_percentile, 1),
                relative_volume=round(rel_volume, 3) if rel_volume is not None else None,
                volume_label=_volume_label(rel_volume),
                amihud_illiquidity_x1e6=round(amihud_illiquidity * 1e6, 6) if amihud_illiquidity is not None else None,
                amihud_illiquidity_percentile=round(amihud_percentile, 1) if amihud_percentile is not None else None,
                session=session,
                execution_risk=execution_risk,
                notes=notes,
                knowledge_context=self._build_knowledge_context(execution_risk, _volume_label(rel_volume)),
            )

            self._set_status(EngineStatus.IDLE)
            return EngineResult(
                success=True,
                data=snapshot,
                message=f"Execution risk: {execution_risk} ({symbol})",
                metadata={"execution_risk": execution_risk},
            )
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.warning("Microstructure analysis failed for %s: %s", symbol, e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def _build_knowledge_context(self, execution_risk: str, volume_label: str) -> Optional[dict]:
        """Relevant market-microstructure/execution book content for the
        current execution-risk read, attached for transparency --
        informational only, never changes execution_risk or any other
        field. Best-effort: only runs if a real KnowledgeEngine instance
        was injected (see __init__ / registry.py)."""
        if self._knowledge_engine is None:
            return None
        try:
            query = f"{execution_risk} execution risk {volume_label} volume liquidity spread"
            results = self._knowledge_engine.document_store.hybrid_search(query, limit=3)
        except Exception as e:
            logger.warning("Knowledge context unavailable: %s", e)
            return None
        if not results:
            return None
        return {"query": query, "results": [r.to_dict() for r in results]}
