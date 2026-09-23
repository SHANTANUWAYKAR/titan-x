"""
Module: engine.py
Description: Engine 16 -- Commodity Intelligence. Master prompt scope
    (draft detail, item #51 "Commodity Intelligence"): "gold, silver,
    copper, oil, natural gas, agriculture; seasonality and supply-demand
    dynamics."

    Scoped to this platform's three actually-supported commodities (GOLD,
    SILVER, CRUDE -- core/config/assets.py). Copper, natural gas, and
    agriculture are NOT tradable instruments in this platform's watchlist,
    so no per-asset feature is built for them here -- same principle as
    e06_fundamental limiting real-yield/WTI-Brent context to the assets
    they actually apply to, rather than fabricating relevance.

    Two genuinely real, calibrated components, deliberately NOT
    duplicating other engines' commodity coverage (e04_macro's gold/oil
    price-momentum proxies, e06_fundamental's WTI-Brent spread,
    e10_cross_asset's Copper-vs-Global-Growth/DXY-vs-Gold correlations):

    1. Seasonality: monthly return by calendar month, from real maximum
       available price history, with a one-sample t-test per month
       (scripts/training/train_e16_commodity.py) -- only months with
       p<0.05 are called "significant," not every month with a positive
       average (roughly half would be, from noise alone).
    2. Commercial-positioning read: net commercial (producer/hedger, NOT
       speculator) positioning as %% of open interest, from CFTC's public
       COT dataset (reused via e02_market_data.fetch_cot_report(), not
       re-fetched independently), classified against a REAL historical
       percentile distribution -- CFTC's data genuinely has deep history
       (back to 1986 for GOLD), unlike e14_fixed_income/e15_credit's
       live-only yield spreads, so this is calibrated, not a static
       convention.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-07-16
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

_CALIBRATION_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "e16_commodity" / "calibration.json"

SUPPORTED_COMMODITIES = {"GOLD", "SILVER", "CRUDE"}
COT_LOOKBACK_REPORTS = 12  # ~12 most recent weekly reports -- enough for "today's" positioning read

MONTH_NAMES = {
    1: "January", 2: "February", 3: "March", 4: "April", 5: "May", 6: "June",
    7: "July", 8: "August", 9: "September", 10: "October", 11: "November", 12: "December",
}


@dataclass
class SeasonalityResult:
    """Current calendar month's real historical seasonal read."""

    month: int
    month_name: str
    mean_return_pct: Optional[float]
    p_value: Optional[float]
    n_years: Optional[int]
    significant: bool = False
    direction: str = "neutral"  # "bullish" | "bearish" | "neutral"


@dataclass
class CommercialPositioningResult:
    """Net commercial (producer/hedger) positioning vs. real historical baseline."""

    net_positioning_pct: Optional[float]  # (commercial_long - commercial_short) / open_interest * 100
    percentile_rank: Optional[str]  # "below_10th" | "10th_25th" | "25th_75th" | "75th_90th" | "above_90th" | "unavailable"
    regime: str = "uncalibrated"  # "extreme_short" | "normal" | "extreme_long" | "uncalibrated"


@dataclass
class GoldSilverRatioResult:
    """Gold/Silver ratio (gold spot price / silver spot price) vs. its own
    real historical percentile distribution -- see train_e16_commodity.py's
    _train_gold_silver_ratio. Only ever attached for GOLD/SILVER (a
    cross-commodity read, not meaningful for CRUDE)."""

    ratio: Optional[float]
    percentile_rank: Optional[str]
    regime: str = "uncalibrated"  # "silver_cheap_vs_gold" | "normal" | "gold_cheap_vs_silver" | "uncalibrated"


@dataclass
class CommodityReadResult:
    """Full read for one commodity."""

    symbol: str
    seasonality: Optional[SeasonalityResult] = None
    commercial_positioning: Optional[CommercialPositioningResult] = None
    gold_silver_ratio: Optional[GoldSilverRatioResult] = None


@dataclass
class CommoditySnapshot:
    """Full Commodity Intelligence read across GOLD/SILVER/CRUDE."""

    timestamp: datetime
    commodities: list[CommodityReadResult] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    knowledge_context: Optional[dict] = None


class CommodityIntelligenceEngine(BaseEngine):
    """
    Commodity Intelligence Engine (#16) -- real seasonality (statistically
    tested, not folklore) and commercial-positioning reads for GOLD/SILVER/
    CRUDE. Purely descriptive/interpretive -- reads real price/COT data,
    never places or recommends a trade.
    """

    engine_id = "e16_commodity"
    engine_name = "Commodity Intelligence Engine"
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
        self._gold_silver_ratio_calibration = self._load_gold_silver_ratio_calibration()

    def initialize(self) -> EngineResult:
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Commodity Intelligence Engine initialized")

    def health_check(self) -> EngineResult:
        return EngineResult(success=True, message="Healthy") if self._calibration else EngineResult(
            success=True, message="Healthy (uncalibrated -- run scripts/training/train_e16_commodity.py)"
        )

    @staticmethod
    def _load_calibration() -> dict[str, dict]:
        """Per-commodity seasonality + commercial-positioning calibration
        from scripts/training/train_e16_commodity.py. Empty (not
        fabricated) if the training script hasn't been run yet."""
        if not _CALIBRATION_PATH.exists():
            return {}
        try:
            data = json.loads(_CALIBRATION_PATH.read_text())
            return data.get("commodities", {})
        except Exception as e:
            logger.warning("Failed to load E16 calibration from %s: %s", _CALIBRATION_PATH, e)
            return {}

    @staticmethod
    def _load_gold_silver_ratio_calibration() -> Optional[dict]:
        """Real historical Gold/Silver ratio percentiles from the same
        calibration.json (see train_e16_commodity.py's
        _train_gold_silver_ratio) -- a separate top-level key, not nested
        under a single commodity, since the ratio is a cross-commodity
        read. None (not fabricated) if the training script hasn't been
        run since this feature was added."""
        if not _CALIBRATION_PATH.exists():
            return None
        try:
            data = json.loads(_CALIBRATION_PATH.read_text())
            return data.get("gold_silver_ratio")
        except Exception as e:
            logger.warning("Failed to load Gold/Silver ratio calibration from %s: %s", _CALIBRATION_PATH, e)
            return None

    def analyze(self, symbol: str = "GOLD", reference: Optional[datetime] = None) -> EngineResult:
        """Seasonality + commercial-positioning read for `symbol`. Only
        GOLD/SILVER/CRUDE have real data behind them (see module docstring
        for why); every other supported asset returns an honest gap, not
        fabricated data."""
        asset = get_asset(symbol)
        symbol_key = asset.symbol if asset else symbol.upper()

        if symbol_key not in SUPPORTED_COMMODITIES:
            return EngineResult(
                success=True,
                data=None,
                message=(
                    f"{symbol_key} is not one of this engine's covered commodities (GOLD/SILVER/CRUDE) -- "
                    "copper/natural gas/agriculture aren't tradable instruments in this platform's watchlist."
                ),
            )

        try:
            self._set_status(EngineStatus.RUNNING)
            now = reference or datetime.now(timezone.utc)
            notes: list[str] = []

            seasonality = self._read_seasonality(symbol_key, now.month)
            commercial_positioning = self._read_commercial_positioning(symbol_key)

            if symbol_key not in self._calibration:
                notes.append(f"No calibration found for {symbol_key} -- run scripts/training/train_e16_commodity.py")
            if commercial_positioning is None:
                notes.append(f"Could not fetch live COT data for {symbol_key}")

            # Gold/Silver ratio (added 2026-08-02) only applies to the two
            # precious metals -- not meaningful for CRUDE.
            gold_silver_ratio = None
            if symbol_key in ("GOLD", "SILVER"):
                gold_silver_ratio = self._read_gold_silver_ratio()
                if gold_silver_ratio is None:
                    notes.append("Could not compute live Gold/Silver ratio")

            read = CommodityReadResult(
                symbol=symbol_key, seasonality=seasonality,
                commercial_positioning=commercial_positioning, gold_silver_ratio=gold_silver_ratio,
            )
            snapshot = CommoditySnapshot(
                timestamp=now,
                commodities=[read],
                notes=notes,
                knowledge_context=self._build_knowledge_context(symbol_key, seasonality, commercial_positioning, gold_silver_ratio),
            )
            self._set_status(EngineStatus.IDLE)
            return EngineResult(
                success=True,
                data=snapshot,
                message=(
                    f"{symbol_key}: seasonality={'significant' if seasonality and seasonality.significant else 'not significant'}, "
                    f"positioning={commercial_positioning.regime if commercial_positioning else 'n/a'}"
                ),
            )
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("Commodity intelligence analysis failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def _read_seasonality(self, symbol_key: str, month: int) -> Optional[SeasonalityResult]:
        calibration = self._calibration.get(symbol_key, {}).get("seasonality", {})
        entry = calibration.get(str(month))
        if entry is None:
            return SeasonalityResult(month=month, month_name=MONTH_NAMES[month], mean_return_pct=None, p_value=None, n_years=None)
        return SeasonalityResult(
            month=month,
            month_name=MONTH_NAMES[month],
            mean_return_pct=entry["mean_return_pct"],
            p_value=entry["p_value"],
            n_years=entry["n_years"],
            significant=entry["significant"],
            direction=entry["direction"] if entry["significant"] else "neutral",
        )

    def _read_gold_silver_ratio(self) -> Optional[GoldSilverRatioResult]:
        """Live gold/silver spot ratio, classified against real historical
        percentiles (see _load_gold_silver_ratio_calibration). Fetches
        both legs itself via _market_data_engine.fetch_ohlcv (same data
        source the rest of this engine's live reads use) rather than
        reusing whatever symbol analyze() was originally called for,
        since the ratio always needs BOTH gold and silver regardless of
        which one the caller asked about."""
        try:
            gold_result = self._market_data_engine.fetch_ohlcv("GC=F", timeframe="1d", years=1)
            silver_result = self._market_data_engine.fetch_ohlcv("SI=F", timeframe="1d", years=1)
        except Exception as e:
            logger.warning("Gold/Silver ratio price fetch failed: %s", e)
            return None
        if not gold_result.success or gold_result.data is None or gold_result.data.empty:
            return None
        if not silver_result.success or silver_result.data is None or silver_result.data.empty:
            return None

        gold_close = float(gold_result.data["close"].iloc[-1] if "close" in gold_result.data else gold_result.data["Close"].iloc[-1])
        silver_close = float(silver_result.data["close"].iloc[-1] if "close" in silver_result.data else silver_result.data["Close"].iloc[-1])
        if silver_close <= 0:
            return None
        ratio = round(gold_close / silver_close, 2)

        percentiles = (self._gold_silver_ratio_calibration or {}).get("percentiles")
        if not percentiles:
            return GoldSilverRatioResult(ratio=ratio, percentile_rank="unavailable", regime="uncalibrated")

        percentile_rank, regime = self._classify_gold_silver_ratio(ratio, percentiles)
        return GoldSilverRatioResult(ratio=ratio, percentile_rank=percentile_rank, regime=regime)

    @staticmethod
    def _classify_gold_silver_ratio(ratio: float, percentiles: dict[str, float]) -> tuple[str, str]:
        """A HIGH ratio (top decile historically) means gold is expensive
        relative to silver -- historically a silver-cheap-vs-gold read,
        not the other way round; the classification labels name the
        cheap/expensive relationship directly rather than just "high"/
        "low" to avoid the reader having to invert the ratio direction
        themselves."""
        if ratio < percentiles["10"]:
            return "below_10th", "gold_cheap_vs_silver"
        if ratio < percentiles["25"]:
            return "10th_25th", "normal"
        if ratio <= percentiles["75"]:
            return "25th_75th", "normal"
        if ratio <= percentiles["90"]:
            return "75th_90th", "normal"
        return "above_90th", "silver_cheap_vs_gold"

    def _read_commercial_positioning(self, symbol_key: str) -> Optional[CommercialPositioningResult]:
        try:
            result = self._market_data_engine.fetch_cot_report(symbol_key, limit=COT_LOOKBACK_REPORTS)
        except Exception as e:
            logger.warning("COT fetch failed for %s: %s", symbol_key, e)
            return None
        if not result.success or result.data is None or result.data.empty:
            return None

        latest = result.data.iloc[-1]
        oi = latest.get("open_interest_all")
        if not oi:
            return None
        net_pct = round(float((latest["comm_positions_long_all"] - latest["comm_positions_short_all"]) / oi * 100), 3)

        percentiles = self._calibration.get(symbol_key, {}).get("commercial_positioning", {}).get("percentiles")
        if not percentiles:
            return CommercialPositioningResult(net_positioning_pct=net_pct, percentile_rank="unavailable", regime="uncalibrated")

        percentile_rank, regime = self._classify_positioning(net_pct, percentiles)
        return CommercialPositioningResult(net_positioning_pct=net_pct, percentile_rank=percentile_rank, regime=regime)

    @staticmethod
    def _classify_positioning(net_pct: float, percentiles: dict[str, float]) -> tuple[str, str]:
        if net_pct < percentiles["10"]:
            return "below_10th", "extreme_short"
        if net_pct < percentiles["25"]:
            return "10th_25th", "normal"
        if net_pct <= percentiles["75"]:
            return "25th_75th", "normal"
        if net_pct <= percentiles["90"]:
            return "75th_90th", "normal"
        return "above_90th", "extreme_long"

    def _build_knowledge_context(
        self,
        symbol_key: str,
        seasonality: Optional[SeasonalityResult],
        positioning: Optional[CommercialPositioningResult],
        gold_silver_ratio: Optional[GoldSilverRatioResult] = None,
    ) -> Optional[dict]:
        """Relevant book content on commodity seasonality/positioning,
        attached for transparency -- informational only, never changes
        any computed number. No query when nothing is notable (season not
        significant, positioning not extreme, ratio not extreme) -- same
        "nothing to explain, no query" principle as e05/e10/e13/e14/e15."""
        if self._knowledge_engine is None:
            return None
        season_notable = seasonality is not None and seasonality.significant
        positioning_notable = positioning is not None and positioning.regime in ("extreme_short", "extreme_long")
        ratio_notable = gold_silver_ratio is not None and gold_silver_ratio.regime in ("gold_cheap_vs_silver", "silver_cheap_vs_gold")
        if not (season_notable or positioning_notable or ratio_notable):
            return None
        try:
            terms = [f"{symbol_key} commodity"]
            if season_notable:
                terms.append(f"{seasonality.month_name} seasonality {seasonality.direction}")
            if positioning_notable:
                terms.append(f"commercial hedger positioning {positioning.regime}")
            if ratio_notable:
                terms.append(f"gold silver ratio {gold_silver_ratio.regime}")
            query = " ".join(terms)
            results = self._knowledge_engine.document_store.hybrid_search(query, limit=3)
        except Exception as e:
            logger.warning("Knowledge context unavailable: %s", e)
            return None
        if not results:
            return None
        return {"query": query, "results": [r.to_dict() for r in results]}
