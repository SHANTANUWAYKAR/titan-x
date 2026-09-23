"""
Module: engine.py
Description: Engine 17 -- Crypto Intelligence. Master prompt scope (draft
    detail, item #52 "Crypto Intelligence"): "on-chain metrics, exchange
    flows, stablecoin liquidity, funding rates, open interest."

    Scoped to this platform's two actually-supported crypto assets (BTCUSD,
    ETHUSD -- core/config/assets.py), and to the two data points genuinely
    free and no-auth: perpetual-futures funding rate and open interest
    (Binance, via e02_market_data/ccxt). On-chain metrics, exchange flows,
    and stablecoin liquidity are an HONEST GAP -- e02_market_data's own
    module docstring already documents that Glassnode's on-chain tiers are
    paid and not integrated; this engine does not fabricate a substitute.

    Two components:
    1. Funding-rate positioning-crowding regime (crowded_short / normal /
       crowded_long), from real percentile calibration
       (scripts/training/train_e17_crypto.py) against Binance's own funding
       rate history -- same percentile-classification pattern as
       e16_commodity's commercial-positioning read. The classic contrarian
       hypothesis (crowded_long precedes weaker forward returns -- everyone
       already long is paying funding to stay there) is TESTED on a
       chronological held-out split, not assumed: BTCUSD's calibration
       confirmed it, ETHUSD's did not (too few held-out crowded_long
       observations to confirm either way) -- see calibration.json's
       `contrarian_effect_validated` per asset. Confluence weight (see
       e51_signals._apply_confluence_adjustments) is only applied at full
       strength when that asset's own calibration validated the effect.
    2. Open interest trend (rising/falling/flat vs. its own trailing
       average) -- purely INFORMATIONAL. Unlike funding rate, no forward-
       return relationship has been backtested for raw OI trend, so it is
       never used to adjust confidence, only attached as descriptive
       evidence, per this project's honesty discipline: don't imply a
       validated edge that was never tested.

    Fear & Greed Index (alternative.me) is deliberately NOT duplicated here
    -- it is market-wide (not crypto-specific in the sense of BTCUSD vs.
    ETHUSD positioning), already has its own real published classification
    bands, and belongs to e51_signals' own sentiment confluence rather than
    a per-asset engine. See e51_signals._apply_confluence_adjustments for
    where it's actually read.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-07-19
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from project_titan_x.core.config import get_asset
from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus
from project_titan_x.engines.e01_knowledge.engine import KnowledgeEngine
from project_titan_x.engines.e02_market_data.engine import MarketDataEngine

logger = logging.getLogger(__name__)

_CALIBRATION_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "e17_crypto" / "calibration.json"

SUPPORTED_CRYPTO = {"BTCUSD", "ETHUSD"}

# OI trend read is descriptive only (see module docstring) -- these are
# static, documented conventions, not backtested thresholds.
OI_TREND_RISING_THRESHOLD = 1.02
OI_TREND_FALLING_THRESHOLD = 0.98


FUNDING_PERIODS_PER_YEAR = 3 * 365  # Binance settles funding every 8 hours


@dataclass
class FundingRatePositioning:
    """Perpetual-futures funding-rate positioning-crowding read."""

    funding_rate: Optional[float]
    # Added 2026-08-02: the standard annualized convention
    # (funding_rate * 3 settlements/day * 365 days) -- how crypto traders
    # actually communicate this number in practice (a raw per-8h rate like
    # 0.01% reads as negligible; the same rate annualized to ~10.95% reads
    # as the real, meaningful cost/signal it represents). Trivial to
    # compute from data already fetched, previously never surfaced.
    funding_rate_annualized_pct: Optional[float] = None
    regime: str = "uncalibrated"  # "crowded_short" | "normal" | "crowded_long" | "uncalibrated" | "unavailable"
    contrarian_effect_validated: bool = False


@dataclass
class OpenInterestTrend:
    """Descriptive-only open interest trend vs. its own trailing average."""

    open_interest: Optional[float]
    trend: str = "unavailable"  # "rising" | "falling" | "flat" | "unavailable"


@dataclass
class CryptoReadResult:
    """Full read for one crypto asset."""

    symbol: str
    timestamp: datetime
    funding_positioning: Optional[FundingRatePositioning] = None
    open_interest_trend: Optional[OpenInterestTrend] = None
    notes: list[str] = field(default_factory=list)
    knowledge_context: Optional[dict] = None


class CryptoIntelligenceEngine(BaseEngine):
    """
    Crypto Intelligence Engine (#17) -- real funding-rate positioning-
    crowding read (percentile-calibrated, contrarian hypothesis held-out-
    tested per asset) and a purely descriptive open-interest trend for
    BTCUSD/ETHUSD. On-chain metrics/exchange flows/stablecoin liquidity are
    an honest, documented gap (see module docstring), not fabricated.
    """

    engine_id = "e17_crypto"
    engine_name = "Crypto Intelligence Engine"
    version = "1.0.0"

    def __init__(
        self,
        knowledge_engine: Optional[KnowledgeEngine] = None,
        market_data_engine: Optional[MarketDataEngine] = None,
    ) -> None:
        super().__init__()
        self._knowledge_engine = knowledge_engine
        self._market_data_engine = market_data_engine if market_data_engine is not None else MarketDataEngine()
        self._calibration = self._load_calibration()

    def initialize(self) -> EngineResult:
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Crypto Intelligence Engine initialized")

    def health_check(self) -> EngineResult:
        return EngineResult(success=True, message="Healthy") if self._calibration else EngineResult(
            success=True, message="Healthy (uncalibrated -- run scripts/training/train_e17_crypto.py)"
        )

    @staticmethod
    def _load_calibration() -> dict[str, dict]:
        """Per-asset funding-rate percentile calibration from
        scripts/training/train_e17_crypto.py. Empty (not fabricated) if the
        training script hasn't been run yet."""
        if not _CALIBRATION_PATH.exists():
            return {}
        try:
            data = json.loads(_CALIBRATION_PATH.read_text())
            return data.get("assets", {})
        except Exception as e:
            logger.warning("Failed to load E17 calibration from %s: %s", _CALIBRATION_PATH, e)
            return {}

    def analyze(self, symbol: str = "BTCUSD", reference: Optional[datetime] = None) -> EngineResult:
        """Funding-rate positioning + open-interest trend read for `symbol`.
        Only BTCUSD/ETHUSD have real data behind them -- every other asset
        returns an honest gap, not fabricated data."""
        asset = get_asset(symbol)
        symbol_key = asset.symbol if asset else symbol.upper()

        if symbol_key not in SUPPORTED_CRYPTO:
            return EngineResult(
                success=True,
                data=None,
                message=f"{symbol_key} is not one of this engine's covered crypto assets (BTCUSD/ETHUSD).",
            )

        try:
            self._set_status(EngineStatus.RUNNING)
            now = reference or datetime.now(timezone.utc)
            notes: list[str] = []

            funding_positioning = self._read_funding_positioning(symbol_key)
            oi_trend = self._read_oi_trend(symbol_key)

            if symbol_key not in self._calibration or "error" in self._calibration.get(symbol_key, {}):
                notes.append(f"No valid calibration for {symbol_key} -- run scripts/training/train_e17_crypto.py")

            read = CryptoReadResult(
                symbol=symbol_key,
                timestamp=now,
                funding_positioning=funding_positioning,
                open_interest_trend=oi_trend,
                notes=notes,
                knowledge_context=self._build_knowledge_context(symbol_key, funding_positioning),
            )
            self._set_status(EngineStatus.IDLE)
            return EngineResult(
                success=True,
                data=read,
                message=(
                    f"{symbol_key}: funding regime={funding_positioning.regime if funding_positioning else 'n/a'}, "
                    f"OI trend={oi_trend.trend if oi_trend else 'n/a'}"
                ),
            )
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("Crypto intelligence analysis failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def _read_funding_positioning(self, symbol_key: str) -> Optional[FundingRatePositioning]:
        try:
            result = self._market_data_engine.fetch_funding_rate(symbol_key)
        except Exception as e:
            logger.warning("Funding rate fetch failed for %s: %s", symbol_key, e)
            return None
        if not result.success or result.data is None:
            return FundingRatePositioning(funding_rate=None, regime="unavailable")

        funding_rate = result.data.get("funding_rate")
        if funding_rate is None:
            return FundingRatePositioning(funding_rate=None, regime="unavailable")
        annualized_pct = round(funding_rate * FUNDING_PERIODS_PER_YEAR * 100, 2)

        asset_cal = self._calibration.get(symbol_key, {})
        percentiles = asset_cal.get("percentiles")
        if not percentiles:
            return FundingRatePositioning(funding_rate=funding_rate, funding_rate_annualized_pct=annualized_pct, regime="uncalibrated")

        regime = self._classify_funding(funding_rate, percentiles)
        validated = bool(asset_cal.get("contrarian_effect_validated", False))
        return FundingRatePositioning(
            funding_rate=funding_rate, funding_rate_annualized_pct=annualized_pct,
            regime=regime, contrarian_effect_validated=validated,
        )

    @staticmethod
    def _classify_funding(value: float, percentiles: dict[str, float]) -> str:
        if value < percentiles["10"]:
            return "crowded_short"
        if value > percentiles["90"]:
            return "crowded_long"
        return "normal"

    def _read_oi_trend(self, symbol_key: str) -> Optional[OpenInterestTrend]:
        try:
            result = self._market_data_engine.fetch_open_interest_history(symbol_key, days=14)
        except Exception as e:
            logger.warning("Open interest history fetch failed for %s: %s", symbol_key, e)
            return None
        if not result.success or result.data is None or result.data.empty:
            return OpenInterestTrend(open_interest=None, trend="unavailable")

        df = result.data
        latest = float(df["open_interest"].iloc[-1])
        trailing_mean = float(df["open_interest"].iloc[:-1].mean()) if len(df) > 1 else latest
        if trailing_mean <= 0:
            return OpenInterestTrend(open_interest=latest, trend="unavailable")

        ratio = latest / trailing_mean
        if ratio >= OI_TREND_RISING_THRESHOLD:
            trend = "rising"
        elif ratio <= OI_TREND_FALLING_THRESHOLD:
            trend = "falling"
        else:
            trend = "flat"
        return OpenInterestTrend(open_interest=latest, trend=trend)

    def _build_knowledge_context(
        self, symbol_key: str, funding_positioning: Optional[FundingRatePositioning]
    ) -> Optional[dict]:
        """Relevant book content on crypto positioning/funding-rate
        crowding, attached for transparency -- informational only, never
        changes any computed number. No query when nothing is notable (not
        a crowded regime), same "nothing to explain, no query" principle as
        e05/e10/e13/e14/e15/e16."""
        if self._knowledge_engine is None:
            return None
        notable = funding_positioning is not None and funding_positioning.regime in ("crowded_short", "crowded_long")
        if not notable:
            return None
        try:
            query = f"{symbol_key} crypto perpetual futures funding rate {funding_positioning.regime} positioning"
            results = self._knowledge_engine.document_store.hybrid_search(query, limit=3)
        except Exception as e:
            logger.warning("Knowledge context unavailable: %s", e)
            return None
        if not results:
            return None
        return {"query": query, "results": [r.to_dict() for r in results]}
