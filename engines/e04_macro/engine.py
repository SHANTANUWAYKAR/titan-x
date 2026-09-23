"""
Module: engine.py
Description: Engine 03 — Macro Intelligence (risk-on/off, liquidity, currency strength).
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-06-28
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import yfinance as yf
from project_titan_x.core.data_providers.yahoo import ticker_history, ticker_info

from project_titan_x.core.data_providers import get_alpha_vantage_client
from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus
from project_titan_x.engines.e01_knowledge.engine import KnowledgeEngine

logger = logging.getLogger(__name__)

# FRED "Real M2 Money Stock" (M2REAL), monthly, seasonally adjusted,
# inflation-adjusted -- a genuinely direct liquidity-QUANTITY measure
# (not a policy-rate proxy like Fed Funds Rate), with real history back to
# 1959 and no API key/rate limit. Static local file (FRED refreshes this
# monthly with a real-world reporting lag anyway) -- re-download from
# https://fred.stlouisfed.org/series/M2REAL periodically to extend it;
# stale data here degrades gracefully to "indicator unavailable", same as
# every other best-effort source in this method, never a hard failure.
_M2REAL_PATH = Path(__file__).resolve().parents[2] / "data" / "macro" / "m2real.csv"

# Macro proxy tickers via Yahoo Finance
MACRO_TICKERS = {
    "vix": "^VIX",
    "dxy": "DX-Y.NYB",
    "us10y": "^TNX",
    "gold": "GC=F",
    "oil": "CL=F",
    "btc": "BTC-USD",
    "nifty": "^NSEI",
    "india_vix": "^INDIAVIX",
    "sp500": "^GSPC",  # macro indicator only, not traded
}


@dataclass
class MacroSnapshot:
    """Current macro intelligence snapshot."""

    timestamp: datetime
    risk_on_off_score: float  # -1.0 (risk-off) to +1.0 (risk-on)
    regime_label: str  # Risk-On, Risk-Off, Neutral
    liquidity_signal: str  # Expansion, Contraction, Neutral
    # Added 2026-08-02: classical Growth-Inflation quadrant (Reflation /
    # Stagflation Risk / Disinflationary Growth / Deflationary Contraction)
    # -- see _classify_growth_inflation_quadrant. None when there isn't
    # enough CPI/GDP history to classify, never a guessed label.
    growth_inflation_quadrant: Optional[str] = None
    currency_strength: dict[str, float] = field(default_factory=dict)
    indicators: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    knowledge_context: Optional[dict] = None


class MacroIntelligenceEngine(BaseEngine):
    """
    Macro Intelligence Engine — monitors global macro conditions.

    Tracks: VIX, DXY, yields, gold, oil, India VIX, BTC.
    Outputs: risk-on/off score, liquidity signal, currency strength.
    """

    engine_id = "e04_macro"
    engine_name = "Macro Intelligence Engine"
    version = "1.0.0"

    def __init__(self, knowledge_engine: Optional[KnowledgeEngine] = None) -> None:
        super().__init__()
        # Optional and None by default: without it, analyze() behaves
        # exactly as before (no knowledge_context). Pass a real instance
        # (as registry.py does) to turn it on.
        self._knowledge_engine = knowledge_engine

    def initialize(self) -> EngineResult:
        """Initialize macro engine."""
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Macro Intelligence Engine initialized")

    def health_check(self) -> EngineResult:
        """Verify macro data sources."""
        try:
            vix = ticker_history(MACRO_TICKERS["vix"], "5d", context="e04_macro.vix")
            if vix.empty:
                raise ValueError("VIX data unavailable")
            return EngineResult(success=True, message="Healthy")
        except Exception as e:
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def analyze(self) -> EngineResult:
        """
        Run full macro analysis from live market proxies.

        Returns:
            EngineResult with MacroSnapshot.
        """
        try:
            self._set_status(EngineStatus.RUNNING)
            indicators: dict[str, float] = {}
            notes: list[str] = []

            for name, ticker in MACRO_TICKERS.items():
                try:
                    hist = ticker_history(ticker, "3mo", context="e04_macro")
                    if hist.empty or len(hist) < 5:
                        continue
                    close = hist["Close"]
                    current = float(close.iloc[-1])
                    prev_5d = float(close.iloc[-6]) if len(close) >= 6 else float(close.iloc[0])
                    prev_20d = float(close.iloc[-21]) if len(close) >= 21 else float(close.iloc[0])
                    indicators[f"{name}_price"] = round(current, 4)
                    indicators[f"{name}_chg_5d_pct"] = round((current / prev_5d - 1) * 100, 3)
                    indicators[f"{name}_chg_20d_pct"] = round((current / prev_20d - 1) * 100, 3)
                except Exception as e:
                    logger.warning("Failed to fetch %s (%s): %s", name, ticker, e)

            if not indicators:
                raise ValueError("No macro indicators could be fetched")

            av_indicators, av_notes, growth_inflation_quadrant = self._fetch_alpha_vantage_indicators()
            indicators.update(av_indicators)
            notes.extend(av_notes)

            m2_indicators, m2_notes = self._load_m2_liquidity_indicator()
            indicators.update(m2_indicators)
            notes.extend(m2_notes)

            wb_indicators, wb_notes = self._fetch_worldbank_indicators()
            indicators.update(wb_indicators)
            notes.extend(wb_notes)

            risk_score = self._compute_risk_on_off(indicators, notes)
            liquidity = self._compute_liquidity_signal(indicators, notes, risk_score)
            currency_strength = self._compute_currency_strength(indicators)
            regime_label = self._label_regime(risk_score)

            snapshot = MacroSnapshot(
                timestamp=datetime.now(timezone.utc),
                risk_on_off_score=round(risk_score, 3),
                regime_label=regime_label,
                liquidity_signal=liquidity,
                currency_strength=currency_strength,
                growth_inflation_quadrant=growth_inflation_quadrant,
                indicators=indicators,
                notes=notes,
                knowledge_context=self._build_knowledge_context(regime_label, liquidity),
            )

            self._set_status(EngineStatus.IDLE)
            return EngineResult(
                success=True,
                data=snapshot,
                message=f"Macro: {regime_label}, score={risk_score:.2f}",
                metadata={"regime": regime_label, "risk_score": risk_score},
            )
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("Macro analysis failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def _compute_risk_on_off(self, indicators: dict[str, float], notes: list[str]) -> float:
        """Compute risk-on/off score from -1 to +1."""
        score = 0.0
        weight_total = 0.0

        # VIX: low = risk-on, high = risk-off
        vix = indicators.get("vix_price")
        if vix is not None:
            w = 0.25
            if vix < 15:
                score += w * 1.0
                notes.append(f"VIX low ({vix:.1f}) — complacent/risk-on")
            elif vix < 20:
                score += w * 0.3
            elif vix < 30:
                score -= w * 0.3
            else:
                score -= w * 1.0
                notes.append(f"VIX elevated ({vix:.1f}) — fear/risk-off")
            weight_total += w

        # India VIX
        ivix = indicators.get("india_vix_price")
        if ivix is not None:
            w = 0.15
            if ivix < 14:
                score += w * 0.8
            elif ivix > 20:
                score -= w * 0.8
                notes.append(f"India VIX high ({ivix:.1f}) — caution for NIFTY")
            weight_total += w

        # DXY: strong dollar often risk-off for EM/commodities
        dxy_chg = indicators.get("dxy_chg_20d_pct", 0)
        w = 0.15
        if dxy_chg > 2:
            score -= w * 0.7
            notes.append("USD strengthening — headwind for gold/EM")
        elif dxy_chg < -2:
            score += w * 0.7
        weight_total += w

        # BTC as risk appetite proxy
        btc_chg = indicators.get("btc_chg_20d_pct", 0)
        w = 0.15
        if btc_chg > 5:
            score += w * 0.8
        elif btc_chg < -10:
            score -= w * 0.8
            notes.append("BTC weak — risk appetite fading")
        weight_total += w

        # Yields rising fast = tightening
        us10y_chg = indicators.get("us10y_chg_20d_pct", 0)
        w = 0.15
        if us10y_chg > 5:
            score -= w * 0.6
            notes.append("US yields rising — tightening conditions")
        elif us10y_chg < -5:
            score += w * 0.4
        weight_total += w

        # Gold spike = fear
        gold_chg = indicators.get("gold_chg_5d_pct", 0)
        w = 0.15
        if gold_chg > 3:
            score -= w * 0.5
            notes.append("Gold rallying — safe-haven demand")
        weight_total += w

        # Added 2026-08-02: yield curve inversion and the Sahm Rule --
        # both well-established, high-conviction recession indicators
        # (see _compute_yield_curve_signal / _compute_sahm_rule), weighted
        # comparably to VIX since each has a strong historical track
        # record as a standalone recession predictor, not just a minor
        # contributing factor.
        curve_spread = indicators.get("av_yield_curve_10y_3m_spread_pct")
        if curve_spread is not None:
            w = 0.20
            if curve_spread < 0:
                score -= w * 1.0
                notes.append(f"Yield curve inverted ({curve_spread:+.2f}pp) — recession-risk headwind")
            elif curve_spread < 0.5:
                score -= w * 0.3
            else:
                score += w * 0.3
            weight_total += w

        sahm_delta = indicators.get("av_sahm_rule_delta_pp")
        if sahm_delta is not None:
            w = 0.20
            if sahm_delta >= 0.50:
                score -= w * 1.0
                notes.append(f"Sahm Rule triggered ({sahm_delta:+.2f}pp) — recession-risk headwind")
            elif sahm_delta >= 0.30:
                score -= w * 0.4
            weight_total += w

        if weight_total == 0:
            return 0.0
        # Real bug fixed 2026-08-02: the previous formula
        # (score / weight_total * (weight_total / 0.85)) algebraically
        # reduces to score / 0.85 regardless of weight_total's actual
        # value -- confirmed directly (identical score with weight_total
        # of 0.25 vs 1.0 produced the exact same output). That made the
        # "weighted average" framing dead code: a sparse-data read (only
        # one or two indicators available) got the same treatment as a
        # full-data read with the same raw score sum, when it should have
        # been scaled differently since fewer indicators contributed to
        # that sum. A genuine weighted average (score / weight_total)
        # fixes this and is naturally bounded in [-1, 1] since every
        # individual contribution is at most its own weight in magnitude.
        return max(-1.0, min(1.0, score / weight_total))

    def _compute_liquidity_signal(
        self, indicators: dict[str, float], notes: list[str], risk_score: Optional[float] = None
    ) -> str:
        """Classify liquidity expansion vs contraction.

        Three tiers, each used only when the one before it doesn't give a
        decisive read:
        1. Fed Funds Rate trend (Alpha Vantage) -- the actual monetary
           POLICY stance; rate cuts/hikes are the most direct forward-
           looking signal, when available.
        2. Real M2 money supply YoY growth (local FRED data, see
           _load_m2_liquidity_indicator) -- a direct QUANTITY-of-money
           read, always available (no API key/quota) even when Alpha
           Vantage's free tier is exhausted, but slower-moving/more
           lagging than the policy rate.
        3. VIX/risk-score price-derived proxy -- the original fallback,
           used only when neither official source is decisive.

        `risk_score` should be the value analyze() already computed via
        _compute_risk_on_off -- pass it through instead of recomputing the
        same score a second time. Left optional (recomputed if omitted)
        only so this method still works standalone.
        """
        if risk_score is None:
            risk_score = self._compute_risk_on_off(indicators, [])
        vix = indicators.get("vix_price", 20)
        ffr_chg_3mo = indicators.get("av_fed_funds_rate_chg_3mo_pct")

        if ffr_chg_3mo is not None:
            if ffr_chg_3mo <= -0.1:
                return "Expansion"
            if ffr_chg_3mo >= 0.1:
                notes.append(
                    f"Fed Funds Rate up {ffr_chg_3mo:+.2f}pp over 3mo -- monetary tightening drives liquidity contraction"
                )
                return "Contraction"
            # Rate roughly on hold -- defer to M2, then the price-based proxy.

        m2_yoy = indicators.get("fred_m2real_yoy_pct")
        if m2_yoy is not None:
            if m2_yoy > 3.0:
                return "Expansion"
            if m2_yoy < -1.5:
                return "Contraction"
            # M2 growth roughly flat -- defer to the price-based proxy below.

        if risk_score > 0.3 and vix < 18:
            return "Expansion"
        if risk_score < -0.3 or vix > 25:
            notes.append("Liquidity contraction signals detected")
            return "Contraction"
        return "Neutral"

    def _fetch_alpha_vantage_indicators(self) -> tuple[dict[str, float], list[str], Optional[str]]:
        """Official US macro data (CPI, Fed Funds Rate, 10Y+3M Treasury
        Yield, Real GDP, Unemployment) from Alpha Vantage's Economic
        Indicators API -- genuine government-published data, not a
        price-derived proxy like the yfinance tickers above. Returns
        (indicators, notes, growth_inflation_quadrant) -- the quadrant is
        a label, not a number, so it's kept separate from the
        dict[str, float] indicators (see _classify_growth_inflation_
        quadrant's docstring).

        Best-effort and additive: this engine's macro read must keep working
        from yfinance proxies alone when no Alpha Vantage key is configured,
        the free-tier daily quota is already spent, or any single indicator
        call fails.
        """
        indicators: dict[str, float] = {}
        notes: list[str] = []
        client = get_alpha_vantage_client()
        if not client.is_configured:
            return indicators, notes, None

        cpi_series: Optional[pd.DataFrame] = None
        try:
            cpi = client.cpi(interval="monthly")
            cpi_series = cpi
            if len(cpi) >= 13:
                latest, year_ago = float(cpi["value"].iloc[-1]), float(cpi["value"].iloc[-13])
                yoy = (latest / year_ago - 1) * 100 if year_ago else 0.0
                indicators["av_cpi_yoy_pct"] = round(yoy, 3)
                if yoy > 4:
                    notes.append(f"US CPI YoY elevated ({yoy:.1f}%) -- inflation pressure, tightening bias")
        except Exception as e:
            logger.warning("Alpha Vantage CPI fetch failed: %s", e)

        try:
            ffr = client.federal_funds_rate(interval="monthly")
            if len(ffr) >= 1:
                current = float(ffr["value"].iloc[-1])
                indicators["av_fed_funds_rate_pct"] = round(current, 3)
                if len(ffr) >= 4:
                    chg_3mo = current - float(ffr["value"].iloc[-4])
                    indicators["av_fed_funds_rate_chg_3mo_pct"] = round(chg_3mo, 3)
                    if chg_3mo > 0.1:
                        notes.append(f"Fed Funds Rate rising ({chg_3mo:+.2f}pp/3mo) -- monetary tightening")
                    elif chg_3mo < -0.1:
                        notes.append(f"Fed Funds Rate falling ({chg_3mo:+.2f}pp/3mo) -- monetary easing")
        except Exception as e:
            logger.warning("Alpha Vantage Federal Funds Rate fetch failed: %s", e)

        try:
            ty = client.treasury_yield(interval="monthly", maturity="10year")
            if len(ty) >= 1:
                indicators["av_treasury_10y_yield_pct"] = round(float(ty["value"].iloc[-1]), 3)
        except Exception as e:
            logger.warning("Alpha Vantage Treasury Yield fetch failed: %s", e)

        # Added 2026-08-02: short-maturity yield, specifically to compute a
        # 10Y-3M curve spread below -- an inverted yield curve (short rates
        # above long rates) is one of the most-studied real-time recession
        # predictors in macro literature (the 10Y-3M spread specifically
        # preceded every US recession since 1955 with a single false
        # positive in the mid-1960s). One extra Alpha Vantage call/day
        # against the 25/day free-tier quota -- affordable alongside the
        # 5 calls this method already makes.
        try:
            ty_3m = client.treasury_yield(interval="monthly", maturity="3month")
            if len(ty_3m) >= 1:
                indicators["av_treasury_3m_yield_pct"] = round(float(ty_3m["value"].iloc[-1]), 3)
        except Exception as e:
            logger.warning("Alpha Vantage 3-Month Treasury Yield fetch failed: %s", e)

        gdp_series: Optional[pd.DataFrame] = None
        try:
            gdp = client.real_gdp(interval="quarterly")
            gdp_series = gdp
            if len(gdp) >= 5:
                latest, year_ago = float(gdp["value"].iloc[-1]), float(gdp["value"].iloc[-5])
                yoy = (latest / year_ago - 1) * 100 if year_ago else 0.0
                indicators["av_real_gdp_yoy_pct"] = round(yoy, 3)
                if yoy < 0:
                    notes.append(f"US real GDP YoY contracting ({yoy:.1f}%) -- recession-risk signal")
        except Exception as e:
            logger.warning("Alpha Vantage Real GDP fetch failed: %s", e)

        unemployment_series: Optional[pd.DataFrame] = None
        try:
            unemployment = client.unemployment()
            unemployment_series = unemployment
            if len(unemployment) >= 1:
                indicators["av_unemployment_rate_pct"] = round(float(unemployment["value"].iloc[-1]), 3)
        except Exception as e:
            logger.warning("Alpha Vantage Unemployment fetch failed: %s", e)

        # Added 2026-08-02: real interest rate, yield curve inversion, the
        # Sahm Rule recession indicator, and a Growth-Inflation regime
        # quadrant -- classical macro concepts absent before despite this
        # method already fetching all the raw data they need (real rate
        # and the quadrant use only CPI/GDP already fetched above; the
        # Sahm Rule uses more of the SAME unemployment series already
        # fetched, not a new call).
        indicators.update(self._compute_real_rate(indicators))
        curve_indicators, curve_notes = self._compute_yield_curve_signal(indicators)
        indicators.update(curve_indicators)
        notes.extend(curve_notes)
        sahm_indicators, sahm_notes = self._compute_sahm_rule(unemployment_series)
        indicators.update(sahm_indicators)
        notes.extend(sahm_notes)
        quadrant, quadrant_notes = self._classify_growth_inflation_quadrant(cpi_series, gdp_series)
        notes.extend(quadrant_notes)

        if indicators:
            notes.append(
                "Official US macro data (CPI, Fed Funds Rate, Treasury Yield, GDP, "
                "Unemployment) sourced from Alpha Vantage -- supplements the "
                "price-derived proxies above"
            )

        return indicators, notes, quadrant

    @staticmethod
    def _compute_real_rate(indicators: dict[str, float]) -> dict[str, float]:
        """Real interest rate = nominal 10Y yield - CPI YoY inflation -- the
        rate that actually matters for real economic decisions (borrowing,
        investment), not the headline nominal figure. A fundamental macro
        concept, trivial to compute from data this method already fetches,
        previously never calculated despite both inputs being present in
        `indicators` all along."""
        nominal = indicators.get("av_treasury_10y_yield_pct")
        cpi_yoy = indicators.get("av_cpi_yoy_pct")
        if nominal is None or cpi_yoy is None:
            return {}
        return {"av_real_10y_rate_pct": round(nominal - cpi_yoy, 3)}

    @staticmethod
    def _compute_yield_curve_signal(indicators: dict[str, float]) -> tuple[dict[str, float], list[str]]:
        """10Y-3M Treasury spread -- negative (short rates above long rates)
        is the classic yield-curve-inversion recession signal. Requires
        both the 10Y and 3M yields to already be present in `indicators`."""
        y10 = indicators.get("av_treasury_10y_yield_pct")
        y3m = indicators.get("av_treasury_3m_yield_pct")
        if y10 is None or y3m is None:
            return {}, []
        spread = round(y10 - y3m, 3)
        notes: list[str] = []
        if spread < 0:
            notes.append(
                f"10Y-3M Treasury yield curve INVERTED ({spread:+.2f}pp) -- historically "
                "one of the most reliable recession-risk signals, preceded every US "
                "recession since 1955"
            )
        return {"av_yield_curve_10y_3m_spread_pct": spread}, notes

    @staticmethod
    def _compute_sahm_rule(unemployment_series: Optional[pd.DataFrame]) -> tuple[dict[str, float], list[str]]:
        """The Sahm Rule (Claudia Sahm, real-time recession indicator with
        a strong empirical track record): triggered when the 3-month
        moving average of the unemployment rate rises 0.50 percentage
        points or more above its own minimum over the trailing 12 months.
        Uses the FULL unemployment series Alpha Vantage already returns
        (the engine previously only ever read its most recent value) --
        no additional API call."""
        if unemployment_series is None or len(unemployment_series) < 13:
            return {}, []
        try:
            values = unemployment_series["value"].astype(float)
        except (KeyError, ValueError):
            return {}, []
        recent_3mo_avg = float(values.tail(3).mean())
        trailing_12mo_min = float(values.tail(13).min())
        delta = round(recent_3mo_avg - trailing_12mo_min, 3)
        indicators = {"av_sahm_rule_delta_pp": delta}
        notes: list[str] = []
        if delta >= 0.50:
            notes.append(
                f"Sahm Rule TRIGGERED (3mo avg unemployment {delta:+.2f}pp above its trailing "
                "12mo low) -- historically a real-time recession indicator"
            )
        return indicators, notes

    @staticmethod
    def _classify_growth_inflation_quadrant(
        cpi_series: Optional[pd.DataFrame], gdp_series: Optional[pd.DataFrame]
    ) -> tuple[Optional[str], list[str]]:
        """Classical institutional-macro Growth-Inflation quadrant: rising
        vs falling growth crossed with rising vs falling inflation gives
        four regimes each with a distinct asset-allocation implication --
        Reflation (growth up, inflation up: early-cycle, risk-on),
        Stagflation Risk (growth down, inflation up: late-cycle,
        defensive), Disinflationary Growth / "Goldilocks" (growth up,
        inflation down: equities-favorable), Deflationary Contraction
        (growth down, inflation down: recession, bonds-favorable). Needs
        at least two readings of each series (already fetched above) to
        tell rising from falling -- returns None rather than guessing if
        there isn't enough history. Kept as a separate return value (not
        merged into the indicators dict) since MacroSnapshot.indicators is
        typed dict[str, float] and this is a label, not a number -- same
        reasoning as regime_label/liquidity_signal already being their own
        fields rather than crammed into indicators."""
        if cpi_series is None or gdp_series is None or len(cpi_series) < 2 or len(gdp_series) < 2:
            return None, []
        try:
            cpi_rising = float(cpi_series["value"].iloc[-1]) > float(cpi_series["value"].iloc[-2])
            gdp_rising = float(gdp_series["value"].iloc[-1]) > float(gdp_series["value"].iloc[-2])
        except (KeyError, ValueError):
            return None, []

        if gdp_rising and cpi_rising:
            quadrant = "Reflation"
        elif gdp_rising and not cpi_rising:
            quadrant = "Disinflationary Growth"
        elif not gdp_rising and cpi_rising:
            quadrant = "Stagflation Risk"
        else:
            quadrant = "Deflationary Contraction"

        notes = [f"Growth-Inflation regime: {quadrant} (growth {'rising' if gdp_rising else 'falling'}, inflation {'rising' if cpi_rising else 'falling'})"]
        return quadrant, notes

    def _load_m2_liquidity_indicator(self) -> tuple[dict[str, float], list[str]]:
        """Real M2 Money Stock YoY growth from the local FRED CSV (see
        _M2REAL_PATH) -- a direct quantity-of-money liquidity read,
        complementing (not replacing) the Fed Funds Rate policy-stance
        signal above. Best-effort and additive, same convention as the
        other _fetch_* methods: returns empty on any failure (file
        missing, too few rows, bad data), never raises."""
        indicators: dict[str, float] = {}
        notes: list[str] = []
        if not _M2REAL_PATH.exists():
            return indicators, notes
        try:
            df = pd.read_csv(_M2REAL_PATH, parse_dates=["observation_date"])
            df = df.dropna(subset=["M2REAL"]).sort_values("observation_date")
            if len(df) < 13:
                return indicators, notes
            latest = float(df["M2REAL"].iloc[-1])
            year_ago = float(df["M2REAL"].iloc[-13])
            yoy = (latest / year_ago - 1) * 100 if year_ago else 0.0
            indicators["fred_m2real_yoy_pct"] = round(yoy, 3)
            indicators["fred_m2real_as_of"] = df["observation_date"].iloc[-1].year * 100 + df["observation_date"].iloc[-1].month
            if yoy < -1.5:
                notes.append(f"Real M2 money supply contracting YoY ({yoy:.1f}%) -- genuine liquidity drain, not just a rate-policy proxy")
            elif yoy > 3.0:
                notes.append(f"Real M2 money supply expanding YoY ({yoy:.1f}%) -- genuine liquidity tailwind")
        except Exception as e:
            logger.warning("Local M2REAL liquidity indicator load failed: %s", e)
        return indicators, notes

    def _fetch_worldbank_indicators(self) -> tuple[dict[str, float], list[str]]:
        """India macro data (GDP growth, CPI inflation, unemployment) from
        the World Bank's free, no-API-key API -- genuinely new coverage,
        since the Alpha Vantage indicators above are US-only and this
        platform trades USDINR/NIFTY50/BANKNIFTY, where Indian (not just
        US) macro conditions are the relevant backdrop.

        World Bank indicators are annual and published with a lag (often
        1-2 years), so this is a slow-moving structural backdrop signal,
        not a timing signal -- same role as the yield curve above, not a
        substitute for the higher-frequency price-derived indicators.

        Best-effort and additive, like the Alpha Vantage indicators: this
        engine's macro read must keep working from yfinance proxies alone
        if the World Bank API is unreachable or wbdata isn't installed.
        """
        indicators: dict[str, float] = {}
        notes: list[str] = []
        try:
            import wbdata

            df = wbdata.get_dataframe(
                {
                    "NY.GDP.MKTP.KD.ZG": "gdp_growth",
                    "FP.CPI.TOTL.ZG": "cpi_inflation",
                    "SL.UEM.TOTL.ZS": "unemployment",
                },
                country="IND",
            )
            df = df.dropna(how="all").sort_index()
            if df.empty:
                return indicators, notes

            latest = df.iloc[-1]
            if pd.notna(latest.get("gdp_growth")):
                indicators["wb_india_gdp_growth_pct"] = round(float(latest["gdp_growth"]), 3)
            if pd.notna(latest.get("cpi_inflation")):
                cpi = float(latest["cpi_inflation"])
                indicators["wb_india_cpi_inflation_pct"] = round(cpi, 3)
                if cpi > 6:
                    notes.append(
                        f"India CPI inflation elevated ({cpi:.1f}%) -- RBI tightening "
                        "bias, headwind for INR carry"
                    )
            if pd.notna(latest.get("unemployment")):
                indicators["wb_india_unemployment_pct"] = round(float(latest["unemployment"]), 3)

            if indicators:
                notes.append(
                    "India macro data (GDP growth, CPI inflation, unemployment) sourced "
                    "from the World Bank -- relevant backdrop for USDINR/NIFTY50/BANKNIFTY, "
                    "not covered by the US-only Alpha Vantage indicators above"
                )
        except Exception as e:
            logger.warning("World Bank (wbdata) fetch failed: %s", e)

        return indicators, notes

    def _compute_currency_strength(self, indicators: dict[str, float]) -> dict[str, float]:
        """Relative currency strength scores."""
        strength: dict[str, float] = {}
        dxy_chg = indicators.get("dxy_chg_20d_pct", 0)
        strength["USD"] = round(max(-1, min(1, dxy_chg / 5)), 3)
        strength["INR"] = round(-strength["USD"] * 0.8, 3)  # inverse USD proxy
        gold_chg = indicators.get("gold_chg_20d_pct", 0)
        strength["GOLD"] = round(max(-1, min(1, gold_chg / 5)), 3)
        return strength

    @staticmethod
    def _label_regime(score: float) -> str:
        if score >= 0.35:
            return "Risk-On"
        if score <= -0.35:
            return "Risk-Off"
        return "Neutral"

    def _build_knowledge_context(self, regime_label: str, liquidity_signal: str) -> Optional[dict]:
        """Relevant macro-economics book content for the current
        risk-on/off + liquidity read, attached for transparency --
        informational only, never changes risk_on_off_score or
        regime_label. Best-effort: only runs if a real KnowledgeEngine
        instance was injected (see __init__ / registry.py)."""
        if self._knowledge_engine is None:
            return None
        try:
            query = f"{regime_label} macro regime with {liquidity_signal.lower()} liquidity conditions"
            results = self._knowledge_engine.document_store.hybrid_search(query, limit=3)
        except Exception as e:
            logger.warning("Knowledge context unavailable: %s", e)
            return None
        if not results:
            return None
        return {"query": query, "results": [r.to_dict() for r in results]}
