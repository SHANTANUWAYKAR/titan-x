"""
Module: engine.py
Description: Engine 14 -- Fixed Income Intelligence. Master prompt scope:
    "government bonds, treasury markets, yield curves, credit markets.
    Duration, convexity, credit spread, real yield."

    Deliberately does NOT duplicate e06_fundamental, which already covers
    "yield curves" (Treasury curve shape/slope/inversion) and "real yield"
    (TIPS ETF trend, precious-metals bias) from this same master-prompt
    line. This engine covers the genuinely uncovered pieces:

    1. Empirical duration & convexity for government bond ETFs (SHY/IEF/
       TLT/TIP), estimated via real historical regression against 10Y
       Treasury yield changes (scripts/training/train_e14_fixed_income.py)
       -- yfinance publishes no duration/convexity field for these tickers,
       so this is computed, not looked up, and validated against real
       published figures before shipping (see that script's docstring).
    2. Investment-grade and high-yield credit spreads (LQD/HYG yield minus
       a Treasury benchmark), from real live ETF yield data
       (ticker.info['yield']). Classified against static, documented
       market conventions -- NOT backtested, since yfinance's yield field
       is a live-only snapshot with no free historical time series to
       calibrate a threshold against (same honest-gap principle as
       e13_derivatives' options skew thresholds).
    3. A credit-stress regime read: HYG-vs-IEF rolling correlation (reuses
       e12_quant_research's rolling_correlation, same technique as
       e10_cross_asset) compared against a real historical baseline.
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

import numpy as np
import pandas as pd
import yfinance as yf
from project_titan_x.core.data_providers.yahoo import ticker_history, ticker_info

from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus
from project_titan_x.engines.e01_knowledge.engine import KnowledgeEngine
from project_titan_x.engines.e12_quant_research.engine import QuantResearchEngine

logger = logging.getLogger(__name__)

_CALIBRATION_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "e14_fixed_income" / "calibration.json"

YIELD_BENCHMARK_TICKER = "^TNX"
GOVT_ETF_TICKERS = {
    "SHY": "Short-Term Treasury (1-3y)",
    "IEF": "Intermediate Treasury (7-10y)",
    "TLT": "Long-Term Treasury (20y+)",
    "TIP": "TIPS (Inflation-Protected)",
}
IG_CREDIT_TICKER = "LQD"
HY_CREDIT_TICKER = "HYG"
CREDIT_BENCHMARK_TICKER = "IEF"  # duration-rough treasury benchmark for spread computation
CREDIT_STRESS_PAIR = (HY_CREDIT_TICKER, "IEF")

LIVE_LOOKBACK_PERIOD = "2y"
ROLLING_WINDOW_DAYS = 60
REGIME_SHIFT_THRESHOLD = 0.3
INVERSION_ABS_THRESHOLD = 0.15

# Static, documented market conventions for credit spread regimes (NOT
# backtested -- see module docstring). Investment-grade OAS commonly runs
# ~80-150bps in normal conditions; high-yield OAS commonly runs
# ~300-500bps. These are rough, well-known anchors, not precise constants.
IG_SPREAD_TIGHT_PCT = 0.5
IG_SPREAD_WIDE_PCT = 1.5
HY_SPREAD_TIGHT_PCT = 2.5
HY_SPREAD_WIDE_PCT = 5.0


@dataclass
class DurationConvexityResult:
    """Empirical duration/convexity for one government bond ETF."""

    ticker: str
    label: str
    empirical_duration: Optional[float]  # years; None if uncalibrated
    convexity: Optional[float]
    r_squared: Optional[float]
    # Added 2026-08-02: DV01 (dollar value of a 1bp yield move) and a
    # convexity-adjusted price-change estimate for a real, live shift
    # scenario -- see _compute_dv01 / _estimate_price_change. Both use
    # duration/convexity that were already being computed above but never
    # actually combined into an applied estimate before.
    dv01_per_100_shares: Optional[float] = None
    price_change_scenario: Optional[dict] = None


@dataclass
class CreditSpreadResult:
    """Real, live credit spread read (yield-based, not price-based)."""

    ig_spread_pct: Optional[float]  # LQD yield - IEF yield
    hy_spread_pct: Optional[float]  # HYG yield - IEF yield
    ig_regime: str = "unavailable"  # "tight" | "normal" | "wide" | "unavailable"
    hy_regime: str = "unavailable"


@dataclass
class CreditStressResult:
    """HYG-vs-Treasury rolling correlation vs. a real historical baseline."""

    current_correlation: Optional[float]
    baseline_correlation: Optional[float]
    delta_vs_baseline: Optional[float]
    regime: str = "uncalibrated"  # "intact" | "weakening" | "breaking_down" | "inverted" | "uncalibrated"


@dataclass
class FixedIncomeSnapshot:
    """Full Fixed Income Intelligence read."""

    timestamp: datetime
    duration_convexity: list[DurationConvexityResult] = field(default_factory=list)
    credit_spread: Optional[CreditSpreadResult] = None
    credit_stress: Optional[CreditStressResult] = None
    notes: list[str] = field(default_factory=list)
    knowledge_context: Optional[dict] = None


class FixedIncomeIntelligenceEngine(BaseEngine):
    """
    Fixed Income Intelligence Engine (#14) -- empirical duration/convexity,
    credit spreads, and a credit-stress correlation regime read. Purely
    descriptive/interpretive -- reads real bond ETF prices/yields, never
    places or recommends a trade.
    """

    engine_id = "e14_fixed_income"
    engine_name = "Fixed Income Intelligence Engine"
    version = "1.0.0"

    def __init__(
        self,
        knowledge_engine: Optional[KnowledgeEngine] = None,
        quant_engine: Optional[QuantResearchEngine] = None,
    ) -> None:
        super().__init__()
        self._knowledge_engine = knowledge_engine
        self._quant_engine = quant_engine if quant_engine is not None else QuantResearchEngine()
        self._duration_baseline, self._credit_stress_baseline = self._load_calibration()

    def initialize(self) -> EngineResult:
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Fixed Income Intelligence Engine initialized")

    def health_check(self) -> EngineResult:
        try:
            hist = ticker_history("IEF", "5d", context="e14.ief")
            if hist.empty:
                raise ValueError("Treasury ETF data unavailable")
            return EngineResult(success=True, message="Healthy")
        except Exception as e:
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    @staticmethod
    def _load_calibration() -> tuple[dict[str, dict], Optional[dict]]:
        """Empirical duration/convexity per ETF + credit-stress correlation
        baseline, from scripts/training/train_e14_fixed_income.py. Empty
        (not fabricated) if the training script hasn't been run yet."""
        if not _CALIBRATION_PATH.exists():
            return {}, None
        try:
            data = json.loads(_CALIBRATION_PATH.read_text())
            return data.get("duration_convexity", {}), data.get("credit_stress_correlation")
        except Exception as e:
            logger.warning("Failed to load E14 calibration from %s: %s", _CALIBRATION_PATH, e)
            return {}, None

    def analyze(self) -> EngineResult:
        try:
            self._set_status(EngineStatus.RUNNING)
            notes: list[str] = []

            duration_convexity = []
            for ticker, label in GOVT_ETF_TICKERS.items():
                duration = self._duration_baseline.get(ticker, {}).get("empirical_duration")
                convexity = self._duration_baseline.get(ticker, {}).get("convexity")
                dv01 = self._compute_dv01(ticker, duration) if duration is not None else None
                scenario = self._estimate_price_change(duration, convexity) if duration is not None else None
                duration_convexity.append(DurationConvexityResult(
                    ticker=ticker,
                    label=label,
                    empirical_duration=duration,
                    convexity=convexity,
                    r_squared=self._duration_baseline.get(ticker, {}).get("r_squared"),
                    dv01_per_100_shares=dv01,
                    price_change_scenario=scenario,
                ))
            if not self._duration_baseline:
                notes.append("No duration/convexity calibration found -- run scripts/training/train_e14_fixed_income.py")

            credit_spread = self._compute_credit_spread()
            credit_stress = self._compute_credit_stress()

            if credit_spread is None:
                notes.append("Could not compute live credit spread (yield data unavailable)")
            if credit_stress.regime == "uncalibrated" and self._credit_stress_baseline is None:
                notes.append("No credit-stress correlation baseline found -- run scripts/training/train_e14_fixed_income.py")

            snapshot = FixedIncomeSnapshot(
                timestamp=datetime.now(timezone.utc),
                duration_convexity=duration_convexity,
                credit_spread=credit_spread,
                credit_stress=credit_stress,
                notes=notes,
                knowledge_context=self._build_knowledge_context(credit_spread, credit_stress),
            )
            self._set_status(EngineStatus.IDLE)
            return EngineResult(
                success=True,
                data=snapshot,
                message=(
                    f"Fixed income snapshot: IG spread={credit_spread.ig_regime if credit_spread else 'n/a'}, "
                    f"HY spread={credit_spread.hy_regime if credit_spread else 'n/a'}, "
                    f"credit stress={credit_stress.regime}"
                ),
            )
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("Fixed income analysis failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    @staticmethod
    def _compute_dv01(ticker: str, duration: float) -> Optional[float]:
        """DV01 (dollar value of a 1 basis point yield move), per 100
        shares -- the standard reporting convention in fixed-income desks.
        DV01 = Duration x Price x 0.0001 x shares. Added 2026-08-02: a
        trivial, direct application of the empirical duration this engine
        already computes but never converted into a real dollar figure --
        "7.2 years of duration" is much less directly actionable than
        "this ETF moves ~$1.44 per 100 shares per 1bp," which is the unit
        real position-sizing/hedging decisions are made in."""
        try:
            price = float(ticker_history(ticker, "5d", context="e14")["Close"].iloc[-1])
        except Exception as e:
            logger.warning("DV01 price fetch failed for %s: %s", ticker, e)
            return None
        return round(duration * price * 0.0001 * 100, 2)

    @staticmethod
    def _estimate_price_change(duration: Optional[float], convexity: Optional[float], yield_shift_bps: float = 100.0) -> Optional[dict]:
        """Classic bond-math price-change estimate for a real yield-shift
        scenario, combining duration AND convexity -- added 2026-08-02.
        Both were already being computed/reported by this engine
        separately, but never actually applied together:

            delta_P/P ~= -Duration * delta_y + 0.5 * Convexity * delta_y^2

        Reports the scenario for BOTH a +100bps and -100bps parallel
        shift specifically to surface convexity's asymmetry -- a bond's
        price gains MORE from a rate decline than it loses from an
        equal-sized rate increase, entirely due to the positive
        convexity term flipping sign with delta_y while the linear
        duration term doesn't. This asymmetry is one of the most-cited
        practical implications of convexity in fixed-income literature,
        and was previously not demonstrable from this engine's output at
        all since duration and convexity were only ever reported side by
        side, never combined into an estimate."""
        if duration is None:
            return None
        dy_up = yield_shift_bps / 10000.0
        dy_down = -yield_shift_bps / 10000.0

        def _price_change(dy: float) -> dict:
            duration_only = -duration * dy
            convexity_term = 0.5 * convexity * dy * dy if convexity is not None else 0.0
            return {
                "duration_only_pct": round(duration_only * 100, 3),
                "duration_plus_convexity_pct": round((duration_only + convexity_term) * 100, 3),
            }

        scenario = {
            "yield_shift_bps": yield_shift_bps,
            "if_yields_rise": _price_change(dy_up),
            "if_yields_fall": _price_change(dy_down),
        }
        # Real finding worth flagging, not silently passing through: TLT
        # and TIP's calibrated convexity (see calibration.json, produced
        # by train_e14_fixed_income.py's real regression against 10Y
        # yield changes) came back NEGATIVE (-266.7 for TLT, r^2=0.79;
        # -122.7 for TIP, r^2=0.51) -- atypical for a vanilla long bond,
        # where theory predicts positive convexity. This is genuine
        # calibrated data from this project's own prior work, not
        # something to silently override, but this new price-change
        # feature makes the resulting asymmetry claim far more visible/
        # actionable than a lone convexity number was before, so it gets
        # an explicit caveat rather than being presented as equally
        # reliable to the (more theory-consistent) SHY/IEF readings.
        if convexity is not None and convexity < 0:
            scenario["caveat"] = (
                "Calibrated convexity is negative for this ETF -- atypical for a vanilla "
                "bond (theory predicts positive convexity). This is real regression output, "
                "not fabricated, but treat the convexity-adjusted figures here with more "
                "caution than the duration-only estimate."
            )
        return scenario

    def _compute_credit_spread(self) -> Optional[CreditSpreadResult]:
        """Real, live yield-based credit spread (not price-based) -- LQD/
        HYG's SEC 30-day yield estimate minus IEF's, via yfinance's
        ticker.info. Regime classified against static market conventions
        (see module-level constants and their honest-gap caveat)."""
        try:
            benchmark_yield = self._fetch_yield(CREDIT_BENCHMARK_TICKER)
            ig_yield = self._fetch_yield(IG_CREDIT_TICKER)
            hy_yield = self._fetch_yield(HY_CREDIT_TICKER)
        except Exception as e:
            logger.warning("Credit spread yield fetch failed: %s", e)
            return None

        if benchmark_yield is None:
            return None

        ig_spread = round((ig_yield - benchmark_yield) * 100, 2) if ig_yield is not None else None
        hy_spread = round((hy_yield - benchmark_yield) * 100, 2) if hy_yield is not None else None

        return CreditSpreadResult(
            ig_spread_pct=ig_spread,
            hy_spread_pct=hy_spread,
            ig_regime=self._classify_spread(ig_spread, IG_SPREAD_TIGHT_PCT * 100, IG_SPREAD_WIDE_PCT * 100),
            hy_regime=self._classify_spread(hy_spread, HY_SPREAD_TIGHT_PCT * 100, HY_SPREAD_WIDE_PCT * 100),
        )

    @staticmethod
    def _fetch_yield(ticker: str) -> Optional[float]:
        info = ticker_info(ticker, context="e14")
        y = info.get("yield")
        return float(y) * 100 if y is not None else None  # decimal -> percentage points

    @staticmethod
    def _classify_spread(spread_bps: Optional[float], tight_bps: float, wide_bps: float) -> str:
        if spread_bps is None:
            return "unavailable"
        if spread_bps < tight_bps:
            return "tight"
        if spread_bps > wide_bps:
            return "wide"
        return "normal"

    def _compute_credit_stress(self) -> CreditStressResult:
        """HYG-vs-IEF rolling correlation vs. the real historical baseline
        (reuses e12_quant_research's rolling_correlation, same technique
        as e10_cross_asset's pair reads)."""
        try:
            a_ticker, b_ticker = CREDIT_STRESS_PAIR
            closes: dict[str, pd.Series] = {}
            for ticker in (a_ticker, b_ticker):
                hist = ticker_history(ticker, LIVE_LOOKBACK_PERIOD, context="e14")
                if hist.empty:
                    return CreditStressResult(None, None, None, "uncalibrated")
                series = hist["Close"]
                series.index = series.index.tz_localize(None).normalize()
                closes[ticker] = series

            df = pd.DataFrame(closes).dropna()
            if len(df) < ROLLING_WINDOW_DAYS + 5:
                return CreditStressResult(None, None, None, "uncalibrated")

            returns = df.pct_change().dropna()
            result = self._quant_engine.rolling_correlation(
                {c: returns[c].to_numpy() for c in returns.columns}, window=ROLLING_WINDOW_DAYS
            )
            if not result.success:
                return CreditStressResult(None, None, None, "uncalibrated")

            symbols = result.data.symbols
            i, j = symbols.index(a_ticker), symbols.index(b_ticker)
            current_corr = round(float(np.array(result.data.recent_correlation_matrix)[i][j]), 3)

            baseline = self._credit_stress_baseline.get("baseline_correlation") if self._credit_stress_baseline else None
            if baseline is None:
                return CreditStressResult(current_corr, None, None, "uncalibrated")

            delta = round(current_corr - baseline, 3)
            if abs(delta) <= REGIME_SHIFT_THRESHOLD:
                regime = "intact"
            elif (current_corr >= 0) != (baseline >= 0) and abs(current_corr) > INVERSION_ABS_THRESHOLD:
                regime = "inverted"
            else:
                regime = "breaking_down"
            return CreditStressResult(current_corr, baseline, delta, regime)
        except Exception as e:
            logger.warning("Credit stress computation failed: %s", e)
            return CreditStressResult(None, None, None, "uncalibrated")

    def _build_knowledge_context(
        self, credit_spread: Optional[CreditSpreadResult], credit_stress: CreditStressResult
    ) -> Optional[dict]:
        """Relevant book content on credit spreads/duration/credit-stress
        regimes, attached for transparency -- informational only, never
        changes any computed number. No query when nothing is notable
        (spreads normal, credit stress intact/uncalibrated) -- same
        "nothing to explain, no query" principle as e05/e10/e13."""
        if self._knowledge_engine is None:
            return None
        spread_notable = credit_spread is not None and (
            credit_spread.ig_regime in ("tight", "wide") or credit_spread.hy_regime in ("tight", "wide")
        )
        stress_notable = credit_stress.regime in ("breaking_down", "inverted")
        if not (spread_notable or stress_notable):
            return None
        try:
            terms = ["fixed income credit markets"]
            if credit_spread and credit_spread.hy_regime in ("tight", "wide"):
                terms.append(f"{credit_spread.hy_regime} high yield credit spread")
            if credit_spread and credit_spread.ig_regime in ("tight", "wide"):
                terms.append(f"{credit_spread.ig_regime} investment grade credit spread")
            if stress_notable:
                terms.append(f"credit stress regime {credit_stress.regime}")
            query = " ".join(terms)
            results = self._knowledge_engine.document_store.hybrid_search(query, limit=3)
        except Exception as e:
            logger.warning("Knowledge context unavailable: %s", e)
            return None
        if not results:
            return None
        return {"query": query, "results": [r.to_dict() for r in results]}
