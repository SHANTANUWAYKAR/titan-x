"""
Module: engine.py
Description: Engine 5 — Fundamental Analysis (adapted scope -- see class
docstring for why).
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-07-13
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import yfinance as yf
from project_titan_x.core.data_providers.yahoo import ticker_history, ticker_info

from project_titan_x.core.data_providers.ecb import ECBClient
from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus
from project_titan_x.engines.e01_knowledge.engine import KnowledgeEngine

logger = logging.getLogger(__name__)

# US Treasury yield tickers (Yahoo Finance, free, no key) -- CBOE indices
# quoted in percent, e.g. 4.57 means 4.57%.
YIELD_TICKERS = {
    "3m": "^IRX",
    "5y": "^FVX",
    "10y": "^TNX",
    "30y": "^TYX",
}
TIPS_ETF_TICKER = "TIP"  # iShares TIPS Bond ETF -- inverse real-yield proxy
WTI_TICKER = "CL=F"
BRENT_TICKER = "BZ=F"

# Which of this engine's components are genuinely applicable to which
# instruments. A currency pair, an equity index, or a crypto asset has no
# financial relationship to real yields or the WTI-Brent spread -- applying
# those readings to them would be fabricated relevance, not analysis. Only
# the yield curve (a broad macro-regime backdrop, same role as E03 Macro) is
# genuinely relevant across every asset class.
PRECIOUS_METALS_SYMBOLS = {"GOLD", "SILVER"}
CRUDE_OIL_SYMBOLS = {"CRUDE"}


def relevance_for_symbol(symbol: str) -> dict:
    """Which of this engine's fundamental components are genuinely
    applicable to `symbol` -- used to attach fundamental context to EVERY
    instrument's signal/analysis without fabricating a driver relationship
    that doesn't actually exist for that asset class."""
    symbol = (symbol or "").upper()
    return {
        "yield_curve_relevant": True,
        "real_yield_relevant": symbol in PRECIOUS_METALS_SYMBOLS,
        "crude_oil_relevant": symbol in CRUDE_OIL_SYMBOLS,
        # Rate-differential/carry is a genuine EURUSD-specific driver -- a
        # US-EUR 10Y spread has no fabricated relationship to e.g. GOLD or
        # BTCUSD the way the broad US yield curve (a macro-regime backdrop
        # for every asset) does above.
        "eur_yield_curve_relevant": symbol == "EURUSD",
    }


@dataclass
class YieldCurveSnapshot:
    """US Treasury yield curve shape and level."""

    yields_pct: dict = field(default_factory=dict)
    slope_10y_3m_pct: float = 0.0  # the classic recession-predictor spread
    slope_10y_5y_pct: Optional[float] = None
    # Added 2026-08-02: the 30Y yield was already being fetched into
    # yields_pct but never used in any slope calculation. The long end of
    # the curve (10Y-30Y) reflects a genuinely DIFFERENT signal than the
    # 10Y-3M spread above -- near-term growth/recession expectations vs
    # long-run inflation/term-premium expectations. A steepening long end
    # (30Y rising faster than 10Y) with a flat/inverted short end is a
    # real, distinct regime (near-term growth pessimism + long-run
    # inflation concern) that the 10Y-3M spread alone can't show.
    slope_30y_10y_pct: Optional[float] = None
    long_end_inverted: Optional[bool] = None  # True if the 30Y yields less than the 10Y -- a distinct, rarer signal from short-end inversion
    shape: str = "normal"  # "normal" | "flat" | "inverted"
    inverted: bool = False
    notes: list = field(default_factory=list)


@dataclass
class EURYieldCurveSnapshot:
    """Euro-area (AAA-rated) government bond yield curve shape and level --
    added 2026-08-20, closes a previously-documented gap (see this class's
    module docstring for why). Same shape/fields as YieldCurveSnapshot so
    callers already handling one can handle both with the same logic."""

    yields_pct: dict = field(default_factory=dict)
    slope_10y_3m_pct: float = 0.0
    shape: str = "normal"  # "normal" | "flat" | "inverted"
    inverted: bool = False
    us_eur_10y_differential_pct: Optional[float] = None  # US 10Y - EUR 10Y; the real FX carry/rate-differential driver for EURUSD
    notes: list = field(default_factory=list)


@dataclass
class RealYieldSnapshot:
    """Real-yield read via TIPS ETF trend -- the standard fundamental driver
    for gold/silver (real yields falling => bullish precious metals)."""

    tips_etf_price: float = 0.0
    tips_chg_20d_pct: float = 0.0
    tips_chg_60d_pct: float = 0.0
    real_yield_direction: str = "flat"  # "falling" | "rising" | "flat"
    precious_metals_bias: str = "neutral"  # "bullish" | "bearish" | "neutral"
    notes: list = field(default_factory=list)


@dataclass
class CrudeOilFundamentals:
    """WTI-Brent spread -- the standard fundamental indicator for crude oil
    (supply/transport/refining dynamics between the two benchmarks)."""

    wti_price: float = 0.0
    brent_price: float = 0.0
    spread: float = 0.0  # brent - wti
    spread_pct_of_wti: float = 0.0
    regime: str = "normal_brent_premium"  # normal_brent_premium | wide_brent_premium | wti_premium_unusual
    notes: list = field(default_factory=list)


@dataclass
class FundamentalSnapshot:
    """Composite fundamental read across everything this engine covers."""

    timestamp: datetime
    yield_curve: Optional[YieldCurveSnapshot] = None
    eur_yield_curve: Optional[EURYieldCurveSnapshot] = None
    real_yield: Optional[RealYieldSnapshot] = None
    crude_oil: Optional[CrudeOilFundamentals] = None
    coverage_notes: list = field(default_factory=list)
    knowledge_context: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "yield_curve": self.yield_curve.__dict__ if self.yield_curve else None,
            "eur_yield_curve": self.eur_yield_curve.__dict__ if self.eur_yield_curve else None,
            "real_yield": self.real_yield.__dict__ if self.real_yield else None,
            "crude_oil": self.crude_oil.__dict__ if self.crude_oil else None,
            "coverage_notes": self.coverage_notes,
            "knowledge_context": self.knowledge_context,
        }


class FundamentalAnalysisEngine(BaseEngine):
    """
    Fundamental Analysis Engine (E05) -- adapted scope.

    The original spec's "Fundamental Analysis Engine" means company-level
    fundamentals (revenue growth, earnings, cash flow, debt ratios, ROE/ROIC,
    valuation multiples). That has nothing to analyze here: this platform's
    "Small Capital Mode" explicitly excludes equities (core/config/assets.py
    lists forex, crypto, commodities, indices only -- zero individual
    stocks), and none of those asset classes file GAAP financial statements.

    Adapted scope -- genuine macro-fundamental value drivers for what this
    platform actually trades, using only free, no-API-key data already
    reachable via yfinance (same provider e02/e03 already use):
      - US Treasury yield curve shape (3M/5Y/10Y/30Y) -- the classic
        recession/risk-regime signal, relevant to every asset class' macro
        backdrop. NOTE (2026-08-02): e04_macro now ALSO computes a 10Y-3M
        curve-inversion read (added in that engine's own upgrade the same
        day) -- genuinely redundant coverage, not a stale claim left
        uncorrected, but deliberately NOT de-duplicated: e04_macro's
        version comes from Alpha Vantage (requires a configured API key,
        silently absent from that engine's read when unconfigured/quota-
        exhausted) while this engine's comes from Yahoo Finance (^IRX/
        ^TNX, no key required) -- this is real fallback redundancy for a
        signal important enough to want two independent sources for, not
        an oversight.
      - Real-yield proxy via TIPS ETF (TIP) price trend -- the standard,
        well-documented fundamental driver for gold/silver (real yields
        falling is bullish for non-yielding precious metals, and vice versa).
      - WTI-Brent spread -- the standard fundamental indicator for crude oil,
        reflecting US supply/transport/refining dynamics vs the global
        benchmark.
      - Euro-area (AAA-rated) government bond yield curve, and the US-EUR
        10Y differential -- added 2026-08-20, closing what used to be an
        honest gap below. Sourced from data.ecb.europa.eu's public
        data-detail-api (core.data_providers.ecb), which needs no API key
        at all (verified live this session -- see that module's own
        docstring). The rate differential is EURUSD's real, textbook
        interest-rate-parity/carry driver (a widening US-EUR spread in
        the US's favor is dollar-bullish, all else equal), scoped only to
        EURUSD via relevance_for_symbol -- applying it to e.g. GOLD or
        BTCUSD would be a fabricated relationship.

    Explicitly NOT covered in this version, and why:
      - Individual equity fundamentals -- no stocks in the watchlist.
      - Crypto on-chain fundamentals (exchange flows, stablecoin liquidity,
        funding rates) -- needs a dedicated data source (Glassnode/CoinGecko-
        style) not yet integrated in this project; that's Engine 52's scope,
        not this one's.
      - Foreign sovereign bond yields for currencies OTHER than EUR (India,
        Japan, etc.) -- no reliable free, no-key source found yet for those
        specifically; the Eurozone gap above is closed, this narrower one
        isn't. Not fabricated.
    """

    engine_id = "e06_fundamental"
    engine_name = "Fundamental Analysis Engine"
    version = "1.0.0"

    # Rough historical norm for Brent's usual premium over WTI (varies with
    # transport/refining capacity cycles; not a fixed physical constant).
    NORMAL_BRENT_PREMIUM_PCT = 5.0
    FLAT_CURVE_THRESHOLD_PCT = 0.25
    REAL_YIELD_MOVE_THRESHOLD_PCT = 1.0

    def __init__(
        self,
        knowledge_engine: Optional[KnowledgeEngine] = None,
        ecb_client: Optional[ECBClient] = None,
    ) -> None:
        super().__init__()
        # Optional and None by default: without it, analyze() behaves
        # exactly as before (no knowledge_context). Pass a real instance
        # (as registry.py does) to turn it on.
        self._knowledge_engine = knowledge_engine
        # Same Optional-collaborator convention as every other cross-engine
        # dependency here, even though ECB needs no key/is_configured gate
        # (see core.data_providers.ecb's own docstring) -- keeps this
        # engine trivially testable without a real network call when the
        # caller doesn't inject one, same as knowledge_engine above.
        self._ecb_client = ecb_client

    def initialize(self) -> EngineResult:
        """Initialize fundamental analysis engine."""
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Fundamental Analysis Engine initialized")

    def health_check(self) -> EngineResult:
        """Verify at least the yield curve data source is reachable."""
        try:
            hist = ticker_history(YIELD_TICKERS["10y"], "5d", context="e06.yield_10y")
            if hist.empty:
                raise ValueError("Treasury yield data unavailable")
            return EngineResult(success=True, message="Healthy")
        except Exception as e:
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def analyze(self) -> EngineResult:
        """
        Run full fundamental analysis across all covered domains.

        Returns:
            EngineResult with a FundamentalSnapshot in data.
        """
        try:
            self._set_status(EngineStatus.RUNNING)
            coverage_notes = [
                "Company/equity fundamentals not covered -- no stocks in this "
                "platform's watchlist (Small Capital Mode excludes equities)",
                "Crypto on-chain fundamentals not covered -- needs a dedicated "
                "data source not yet integrated (see Engine 52's future scope)",
                "Foreign sovereign bond yields for currencies other than EUR "
                "(India, Japan, etc.) not covered -- no reliable free, no-key "
                "source found yet for those specifically; EUR is covered "
                "(see eur_yield_curve).",
            ]

            yield_curve = self._analyze_yield_curve()
            eur_yield_curve = self._analyze_eur_yield_curve(yield_curve)
            real_yield = self._analyze_real_yield()
            crude = self._analyze_crude_oil()

            if yield_curve is None and eur_yield_curve is None and real_yield is None and crude is None:
                raise ValueError("No fundamental data sources available")

            snapshot = FundamentalSnapshot(
                timestamp=datetime.now(timezone.utc),
                yield_curve=yield_curve,
                eur_yield_curve=eur_yield_curve,
                real_yield=real_yield,
                crude_oil=crude,
                coverage_notes=coverage_notes,
                knowledge_context=self._build_knowledge_context(yield_curve, real_yield, crude, eur_yield_curve),
            )
            self._set_status(EngineStatus.IDLE)
            return EngineResult(success=True, data=snapshot, message="Fundamental analysis complete")
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("Fundamental analysis failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def _analyze_yield_curve(self) -> Optional[YieldCurveSnapshot]:
        """US Treasury curve shape -- inversion is one of the most reliable
        macro-fundamental recession/risk-off signals available, historically
        leading actual downturns by 6-18 months."""
        try:
            yields: dict[str, float] = {}
            for tenor, ticker in YIELD_TICKERS.items():
                hist = ticker_history(ticker, "5d", context="e06")
                if hist.empty:
                    continue
                yields[tenor] = float(hist["Close"].iloc[-1])

            if "3m" not in yields or "10y" not in yields:
                return None

            slope_10y_3m = yields["10y"] - yields["3m"]
            slope_10y_5y = (yields["10y"] - yields["5y"]) if "5y" in yields else None

            notes = []
            if slope_10y_3m < 0:
                shape, inverted = "inverted", True
                notes.append(
                    f"10Y-3M spread inverted ({slope_10y_3m:+.2f}pp) -- historically a "
                    "recession-risk signal with a 6-18 month typical lead time"
                )
            elif slope_10y_3m < self.FLAT_CURVE_THRESHOLD_PCT:
                shape, inverted = "flat", False
                notes.append(f"10Y-3M spread flat ({slope_10y_3m:+.2f}pp) -- often a late-cycle signal")
            else:
                shape, inverted = "normal", False
                notes.append(f"10Y-3M spread normal/upward-sloping ({slope_10y_3m:+.2f}pp) -- no inversion signal")

            # Added 2026-08-02: the long end (10Y-30Y) -- a distinct signal
            # from the 10Y-3M short-end spread above. The 30Y yield was
            # already being fetched into `yields` but never used in any
            # slope calculation before this. Long-end inversion (30Y
            # yielding less than 10Y) is rarer than short-end inversion
            # and reflects long-run growth/inflation pessimism specifically,
            # not the same near-term recession-timing signal as 10Y-3M.
            #
            # Real bug caught in testing: first version computed this as
            # yields["10y"] - yields["30y"] (mirroring slope_10y_3m's own
            # "yields[10y] - yields[3m]" formula), but that formula's
            # sign convention is LONG-minus-SHORT, and for THIS pair 30Y
            # is the longer maturity, not 10Y -- computing it 10y-minus-30y
            # is backwards (short-minus-long), which flips the sign. Caught
            # directly on live data: 30Y=5.275%, 10Y=4.745% (30Y genuinely
            # higher, the NORMAL upward-sloping relationship) was being
            # reported as "long_end_inverted=True", exactly backwards.
            slope_30y_10y = (yields["30y"] - yields["10y"]) if "30y" in yields else None
            long_end_inverted = (slope_30y_10y < 0) if slope_30y_10y is not None else None
            if long_end_inverted:
                notes.append(
                    f"10Y-30Y spread also inverted ({slope_30y_10y:+.2f}pp) -- the rarer, "
                    "longer-horizon growth/inflation-pessimism signal, distinct from the "
                    "near-term-focused 10Y-3M spread above"
                )

            return YieldCurveSnapshot(
                yields_pct={k: round(v, 3) for k, v in yields.items()},
                slope_10y_3m_pct=round(slope_10y_3m, 3),
                slope_10y_5y_pct=round(slope_10y_5y, 3) if slope_10y_5y is not None else None,
                slope_30y_10y_pct=round(slope_30y_10y, 3) if slope_30y_10y is not None else None,
                long_end_inverted=long_end_inverted,
                shape=shape,
                inverted=inverted,
                notes=notes,
            )
        except Exception as e:
            logger.warning("Yield curve analysis failed: %s", e)
            return None

    def _analyze_eur_yield_curve(self, us_yield_curve: Optional[YieldCurveSnapshot]) -> Optional[EURYieldCurveSnapshot]:
        """Euro-area (AAA-rated) yield curve shape via ECB's free, no-key
        data-detail-api (core.data_providers.ecb) -- added 2026-08-20, see
        this class's own docstring for why. Degrades to None (not a
        fabricated snapshot) if no ecb_client was injected or ECB is
        unreachable -- same graceful-collaborator-absence pattern as every
        other Optional dependency in this codebase."""
        if self._ecb_client is None:
            return None
        try:
            yields: dict[str, float] = {}
            for tenor in ("3m", "2y", "5y", "10y"):
                value = self._ecb_client.latest_yield(tenor)
                if value is not None:
                    yields[tenor] = value

            if "3m" not in yields or "10y" not in yields:
                return None

            slope_10y_3m = yields["10y"] - yields["3m"]

            notes = []
            if slope_10y_3m < 0:
                shape, inverted = "inverted", True
                notes.append(
                    f"EUR 10Y-3M spread inverted ({slope_10y_3m:+.2f}pp) -- historically a "
                    "euro-area recession-risk signal"
                )
            elif slope_10y_3m < self.FLAT_CURVE_THRESHOLD_PCT:
                shape, inverted = "flat", False
                notes.append(f"EUR 10Y-3M spread flat ({slope_10y_3m:+.2f}pp) -- often a late-cycle signal")
            else:
                shape, inverted = "normal", False
                notes.append(f"EUR 10Y-3M spread normal/upward-sloping ({slope_10y_3m:+.2f}pp) -- no inversion signal")

            differential = None
            if us_yield_curve is not None and "10y" in us_yield_curve.yields_pct:
                differential = us_yield_curve.yields_pct["10y"] - yields["10y"]
                notes.append(
                    f"US-EUR 10Y differential {differential:+.2f}pp -- "
                    f"{'US' if differential > 0 else 'EUR'} yields the more; the real "
                    "interest-rate-parity/carry driver for EURUSD, all else equal"
                )

            return EURYieldCurveSnapshot(
                yields_pct={k: round(v, 3) for k, v in yields.items()},
                slope_10y_3m_pct=round(slope_10y_3m, 3),
                shape=shape,
                inverted=inverted,
                us_eur_10y_differential_pct=round(differential, 3) if differential is not None else None,
                notes=notes,
            )
        except Exception as e:
            logger.warning("EUR yield curve analysis failed: %s", e)
            return None

    def _analyze_real_yield(self) -> Optional[RealYieldSnapshot]:
        """TIPS ETF price trend as an inverse real-yield proxy -- when real
        yields fall, inflation-protected bonds rise in price (their fixed
        coupon becomes relatively more attractive), and non-yielding precious
        metals typically benefit from the same falling-real-yield backdrop."""
        try:
            hist = ticker_history(TIPS_ETF_TICKER, "6mo", context="e06.tips")
            if hist.empty or len(hist) < 21:
                return None
            close = hist["Close"]
            current = float(close.iloc[-1])
            chg_20d = (current / float(close.iloc[-21]) - 1) * 100 if len(close) >= 21 else 0.0
            chg_60d = (current / float(close.iloc[-61]) - 1) * 100 if len(close) >= 61 else chg_20d

            notes = []
            threshold = self.REAL_YIELD_MOVE_THRESHOLD_PCT
            if chg_20d > threshold:
                direction, bias = "falling", "bullish"
                notes.append(
                    f"TIPS ETF up {chg_20d:.1f}% over 20d -- real yields falling, a "
                    "fundamental tailwind for gold/silver"
                )
            elif chg_20d < -threshold:
                direction, bias = "rising", "bearish"
                notes.append(
                    f"TIPS ETF down {chg_20d:.1f}% over 20d -- real yields rising, a "
                    "fundamental headwind for gold/silver"
                )
            else:
                direction, bias = "flat", "neutral"
                notes.append("Real yields roughly flat over 20d -- no strong fundamental bias for precious metals from this driver")

            return RealYieldSnapshot(
                tips_etf_price=round(current, 2),
                tips_chg_20d_pct=round(chg_20d, 2),
                tips_chg_60d_pct=round(chg_60d, 2),
                real_yield_direction=direction,
                precious_metals_bias=bias,
                notes=notes,
            )
        except Exception as e:
            logger.warning("Real yield analysis failed: %s", e)
            return None

    def _analyze_crude_oil(self) -> Optional[CrudeOilFundamentals]:
        """WTI-Brent spread -- Brent normally trades at a premium to WTI
        (global benchmark vs a landlocked-ish US grade); the spread widening
        or inverting reflects real supply/transport/refining fundamentals."""
        try:
            wti_hist = ticker_history(WTI_TICKER, "5d", context="e06.wti")
            brent_hist = ticker_history(BRENT_TICKER, "5d", context="e06.brent")
            if wti_hist.empty or brent_hist.empty:
                return None

            wti = float(wti_hist["Close"].iloc[-1])
            brent = float(brent_hist["Close"].iloc[-1])
            spread = brent - wti
            spread_pct = (spread / wti) * 100 if wti > 0 else 0.0

            notes = []
            if spread < 0:
                regime = "wti_premium_unusual"
                notes.append(
                    f"WTI trading ABOVE Brent ({spread:+.2f}) -- unusual, often signals a "
                    "US supply squeeze or transport/pipeline bottleneck"
                )
            elif spread_pct > self.NORMAL_BRENT_PREMIUM_PCT:
                regime = "wide_brent_premium"
                notes.append(
                    f"Brent premium wide ({spread_pct:.1f}%, rough norm ~{self.NORMAL_BRENT_PREMIUM_PCT:.0f}%) -- "
                    "often reflects US oversupply/export capacity limits or tighter global supply"
                )
            else:
                regime = "normal_brent_premium"
                notes.append(f"Brent premium near its rough historical norm ({spread_pct:.1f}%)")

            return CrudeOilFundamentals(
                wti_price=round(wti, 2),
                brent_price=round(brent, 2),
                spread=round(spread, 2),
                spread_pct_of_wti=round(spread_pct, 2),
                regime=regime,
                notes=notes,
            )
        except Exception as e:
            logger.warning("Crude oil fundamentals analysis failed: %s", e)
            return None

    def _build_knowledge_context(
        self,
        yield_curve: Optional[YieldCurveSnapshot],
        real_yield: Optional[RealYieldSnapshot],
        crude: Optional[CrudeOilFundamentals],
        eur_yield_curve: Optional[EURYieldCurveSnapshot] = None,
    ) -> Optional[dict]:
        """Relevant macro-fundamental book content for whichever reads
        came back (yield curve shape / real-yield precious-metals bias /
        WTI-Brent regime / EUR yield curve), attached for transparency --
        informational only, never changes any of the computed snapshots.
        Best-effort: only runs if a real KnowledgeEngine instance was
        injected."""
        if self._knowledge_engine is None:
            return None
        terms = []
        if yield_curve:
            terms.append(f"{yield_curve.shape} yield curve")
        if real_yield:
            terms.append(f"{real_yield.precious_metals_bias} precious metals real yield")
        if crude:
            terms.append(f"{crude.regime} crude oil")
        if eur_yield_curve:
            terms.append(f"{eur_yield_curve.shape} euro area yield curve interest rate differential")
        if not terms:
            return None
        try:
            query = " ".join(terms) + " fundamental analysis"
            results = self._knowledge_engine.document_store.hybrid_search(query, limit=3)
        except Exception as e:
            logger.warning("Knowledge context unavailable: %s", e)
            return None
        if not results:
            return None
        return {"query": query, "results": [r.to_dict() for r in results]}
