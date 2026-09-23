"""
Module: engine.py
Description: Engine 15 -- Credit Intelligence. Master prompt scope (draft
    detail, item #44 "Credit Risk Engine"): "corporate debt, sovereign
    debt, CDS spreads, default risk."

    Deliberately does NOT re-fetch or re-derive corporate credit spreads --
    e14_fixed_income already computes real, live LQD/HYG-vs-Treasury
    spreads; this engine reuses that result (composition, injected
    FixedIncomeIntelligenceEngine) and layers a market-implied default
    probability estimate on top, rather than duplicating the fetch.

    Genuinely new ground vs e14_fixed_income:
    1. Sovereign credit: EMB (iShares JP Morgan USD Emerging Markets Bond
       ETF, the standard free/liquid EM sovereign credit proxy) yield
       minus a Treasury benchmark -- e14 only covers CORPORATE (LQD/HYG)
       credit, not sovereign.
    2. Market-implied default probability, for both corporate (from e14's
       spread) and sovereign (from this engine's own EMB spread), via the
       standard credit-spread-to-hazard-rate approximation (Hull,
       "Options, Futures and Other Derivatives" / "Risk Management and
       Financial Institutions"): hazard_rate ~= spread / (1 - recovery),
       1yr_default_prob = 1 - exp(-hazard_rate). Recovery rate is a
       standard, documented market-convention ASSUMPTION (40% corporate
       senior unsecured, 25% sovereign -- the customary ISDA/CDS-market
       conventions), not fitted to data -- there's no free default-history
       dataset to fit one against.
    3. A sovereign credit-stress regime read: EMB-vs-Treasury rolling
       correlation vs. a real historical baseline
       (scripts/training/train_e15_credit.py), same technique as
       e10_cross_asset / e14_fixed_income's corporate credit-stress read.

    Honest gaps (explicitly NOT covered, not fabricated):
    - CDS spreads: no free CDS data source exists anywhere (Markit/IHS/
      Bloomberg are the standard sources, all proprietary/paid). Every
      free options/futures/ETF API checked in this project (yfinance,
      Deribit, CFTC) covers listed, exchange-traded instruments; CDS is an
      OTC derivatives market with no public tape.
    - Company-level corporate debt analysis (leverage ratios, interest
      coverage, specific issuer default risk): this platform excludes
      equities (core/config/assets.py) and tracks no individual company
      financials, so there is no specific corporate ISSUER to analyze --
      only the aggregate corporate bond MARKET (via LQD/HYG, e14's job).
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-07-16
"""

import json
import logging
import math
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
from project_titan_x.engines.e14_fixed_income.engine import FixedIncomeIntelligenceEngine

logger = logging.getLogger(__name__)

_CALIBRATION_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "e15_credit" / "calibration.json"

SOVEREIGN_CREDIT_TICKER = "EMB"
SOVEREIGN_BENCHMARK_TICKER = "IEF"
SOVEREIGN_STRESS_PAIR = (SOVEREIGN_CREDIT_TICKER, SOVEREIGN_BENCHMARK_TICKER)

LIVE_LOOKBACK_PERIOD = "2y"
ROLLING_WINDOW_DAYS = 60
REGIME_SHIFT_THRESHOLD = 0.3
INVERSION_ABS_THRESHOLD = 0.15

# Static, documented market conventions (NOT fitted -- see module
# docstring). Sovereign EM spreads commonly run ~250-450bps in normal
# conditions.
SOVEREIGN_SPREAD_TIGHT_PCT = 2.5
SOVEREIGN_SPREAD_WIDE_PCT = 5.0

# Standard ISDA/CDS-market-convention recovery-rate ASSUMPTIONS (not
# fitted -- no free default-history dataset exists to fit one against).
CORPORATE_RECOVERY_RATE = 0.40  # senior unsecured
SOVEREIGN_RECOVERY_RATE = 0.25


@dataclass
class SovereignCreditResult:
    """Real, live sovereign credit spread read (EMB vs Treasury)."""

    spread_pct: Optional[float]  # basis points
    regime: str = "unavailable"  # "tight" | "normal" | "wide" | "unavailable"


@dataclass
class DefaultProbabilityResult:
    """Market-implied default probability from a credit spread, via the
    standard hazard-rate approximation, at both the 1-year AND 5-year
    tenor. 5-year is included because it's the actual CDS-market STANDARD
    reference tenor (the recovery-rate conventions this engine already
    cites -- 40% corporate senior unsecured, 25% sovereign -- are
    themselves quoted market-wide against 5yr CDS, so a 1yr-only readout
    is inconsistent with the convention it's built on). Both tenors reuse
    the SAME assumed-constant hazard rate (the standard simplifying
    assumption for a flat hazard curve, same source: Hull) -- an estimate
    under a documented recovery-rate assumption, not a fitted/backtested
    figure."""

    source: str  # "corporate_ig" | "corporate_hy" | "sovereign"
    spread_pct: float  # basis points, the input
    recovery_rate_assumption: float
    implied_hazard_rate_pct: float
    implied_1yr_default_probability_pct: float
    implied_5yr_default_probability_pct: float


@dataclass
class SovereignCreditStressResult:
    """EMB-vs-Treasury rolling correlation vs. a real historical baseline."""

    current_correlation: Optional[float]
    baseline_correlation: Optional[float]
    delta_vs_baseline: Optional[float]
    regime: str = "uncalibrated"


@dataclass
class CreditIntelligenceSnapshot:
    """Full Credit Intelligence read."""

    timestamp: datetime
    sovereign_credit: Optional[SovereignCreditResult] = None
    default_probabilities: list[DefaultProbabilityResult] = field(default_factory=list)
    sovereign_credit_stress: Optional[SovereignCreditStressResult] = None
    notes: list[str] = field(default_factory=list)
    knowledge_context: Optional[dict] = None


class CreditIntelligenceEngine(BaseEngine):
    """
    Credit Intelligence Engine (#15) -- sovereign credit spread,
    market-implied default probability (corporate + sovereign), and a
    sovereign credit-stress regime read. Purely descriptive/interpretive --
    reads real bond ETF prices/yields, never places or recommends a trade.
    """

    engine_id = "e15_credit"
    engine_name = "Credit Intelligence Engine"
    version = "1.0.0"

    def __init__(
        self,
        knowledge_engine: Optional[KnowledgeEngine] = None,
        fixed_income_engine: Optional[FixedIncomeIntelligenceEngine] = None,
        quant_engine: Optional[QuantResearchEngine] = None,
    ) -> None:
        super().__init__()
        self._knowledge_engine = knowledge_engine
        self._fixed_income_engine = fixed_income_engine if fixed_income_engine is not None else FixedIncomeIntelligenceEngine()
        self._quant_engine = quant_engine if quant_engine is not None else QuantResearchEngine()
        self._credit_stress_baseline = self._load_calibration()

    def initialize(self) -> EngineResult:
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Credit Intelligence Engine initialized")

    def health_check(self) -> EngineResult:
        try:
            hist = ticker_history(SOVEREIGN_CREDIT_TICKER, "5d", context="e15.sovereign")
            if hist.empty:
                raise ValueError("Sovereign credit ETF data unavailable")
            return EngineResult(success=True, message="Healthy")
        except Exception as e:
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    @staticmethod
    def _load_calibration() -> Optional[dict]:
        """Sovereign credit-stress correlation baseline from
        scripts/training/train_e15_credit.py. None (not fabricated) if the
        training script hasn't been run yet."""
        if not _CALIBRATION_PATH.exists():
            return None
        try:
            data = json.loads(_CALIBRATION_PATH.read_text())
            return data.get("sovereign_credit_stress_correlation")
        except Exception as e:
            logger.warning("Failed to load E15 calibration from %s: %s", _CALIBRATION_PATH, e)
            return None

    def analyze(self) -> EngineResult:
        try:
            self._set_status(EngineStatus.RUNNING)
            notes: list[str] = [
                "CDS spreads not covered -- no free CDS data source exists (Markit/IHS/Bloomberg "
                "are the standard, all proprietary; CDS is an OTC market with no public tape)",
                "Company-level corporate debt analysis (leverage, interest coverage, issuer "
                "default risk) not covered -- this platform excludes equities/company financials, "
                "so there is no specific corporate issuer to analyze",
            ]

            sovereign_credit = self._compute_sovereign_credit_spread()
            default_probabilities = self._compute_default_probabilities(sovereign_credit)
            sovereign_credit_stress = self._compute_sovereign_credit_stress()

            if sovereign_credit is None:
                notes.append("Could not compute live sovereign credit spread (EMB yield data unavailable)")
            if sovereign_credit_stress.regime == "uncalibrated" and self._credit_stress_baseline is None:
                notes.append("No sovereign credit-stress correlation baseline found -- run scripts/training/train_e15_credit.py")

            snapshot = CreditIntelligenceSnapshot(
                timestamp=datetime.now(timezone.utc),
                sovereign_credit=sovereign_credit,
                default_probabilities=default_probabilities,
                sovereign_credit_stress=sovereign_credit_stress,
                notes=notes,
                knowledge_context=self._build_knowledge_context(sovereign_credit, sovereign_credit_stress),
            )
            self._set_status(EngineStatus.IDLE)
            return EngineResult(
                success=True,
                data=snapshot,
                message=(
                    f"Credit intelligence snapshot: sovereign spread={sovereign_credit.regime if sovereign_credit else 'n/a'}, "
                    f"sovereign credit stress={sovereign_credit_stress.regime}"
                ),
            )
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("Credit intelligence analysis failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def _compute_sovereign_credit_spread(self) -> Optional[SovereignCreditResult]:
        """Real, live EMB yield minus IEF yield -- the standard free/liquid
        EM sovereign credit spread proxy. Regime classified against static
        market conventions (see module-level constants and their honest-gap
        caveat -- no free historical yield series exists to backtest it)."""
        try:
            sovereign_yield = self._fetch_yield(SOVEREIGN_CREDIT_TICKER)
            benchmark_yield = self._fetch_yield(SOVEREIGN_BENCHMARK_TICKER)
        except Exception as e:
            logger.warning("Sovereign credit spread yield fetch failed: %s", e)
            return None
        if sovereign_yield is None or benchmark_yield is None:
            return None

        spread_bps = round((sovereign_yield - benchmark_yield) * 100, 2)
        return SovereignCreditResult(
            spread_pct=spread_bps,
            regime=self._classify_spread(spread_bps, SOVEREIGN_SPREAD_TIGHT_PCT * 100, SOVEREIGN_SPREAD_WIDE_PCT * 100),
        )

    @staticmethod
    def _fetch_yield(ticker: str) -> Optional[float]:
        info = ticker_info(ticker, context="e15")
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

    def _compute_default_probabilities(self, sovereign_credit: Optional[SovereignCreditResult]) -> list[DefaultProbabilityResult]:
        """Market-implied 1-year default probability from each available
        credit spread (corporate IG/HY via the injected
        FixedIncomeIntelligenceEngine, sovereign from this engine's own
        EMB spread), via the standard hazard-rate-from-spread
        approximation."""
        results: list[DefaultProbabilityResult] = []
        try:
            fi_result = self._fixed_income_engine.analyze()
            if fi_result.success and fi_result.data and fi_result.data.credit_spread:
                cs = fi_result.data.credit_spread
                if cs.ig_spread_pct is not None:
                    results.append(self._default_probability("corporate_ig", cs.ig_spread_pct, CORPORATE_RECOVERY_RATE))
                if cs.hy_spread_pct is not None:
                    results.append(self._default_probability("corporate_hy", cs.hy_spread_pct, CORPORATE_RECOVERY_RATE))
        except Exception as e:
            logger.warning("Corporate default probability computation failed: %s", e)

        if sovereign_credit is not None and sovereign_credit.spread_pct is not None:
            results.append(self._default_probability("sovereign", sovereign_credit.spread_pct, SOVEREIGN_RECOVERY_RATE))
        return results

    @staticmethod
    def _default_probability(source: str, spread_bps: float, recovery_rate: float) -> DefaultProbabilityResult:
        """hazard_rate ~= spread / (1 - recovery); cumulative default
        probability over T years, assuming a constant hazard rate (flat
        hazard curve, standard simplifying assumption), is
        1 - exp(-hazard_rate * T)."""
        spread_decimal = spread_bps / 10000
        hazard_rate = spread_decimal / (1 - recovery_rate)
        default_prob_1yr = 1 - math.exp(-hazard_rate * 1)
        default_prob_5yr = 1 - math.exp(-hazard_rate * 5)
        return DefaultProbabilityResult(
            source=source,
            spread_pct=spread_bps,
            recovery_rate_assumption=recovery_rate,
            implied_hazard_rate_pct=round(hazard_rate * 100, 3),
            implied_1yr_default_probability_pct=round(default_prob_1yr * 100, 3),
            implied_5yr_default_probability_pct=round(default_prob_5yr * 100, 3),
        )

    def _compute_sovereign_credit_stress(self) -> SovereignCreditStressResult:
        """EMB-vs-IEF rolling correlation vs. the real historical baseline
        (reuses e12_quant_research's rolling_correlation, same technique
        as e10_cross_asset / e14_fixed_income's corporate credit-stress read)."""
        try:
            a_ticker, b_ticker = SOVEREIGN_STRESS_PAIR
            closes: dict[str, pd.Series] = {}
            for ticker in (a_ticker, b_ticker):
                hist = ticker_history(ticker, LIVE_LOOKBACK_PERIOD, context="e15")
                if hist.empty:
                    return SovereignCreditStressResult(None, None, None, "uncalibrated")
                series = hist["Close"]
                series.index = series.index.tz_localize(None).normalize()
                closes[ticker] = series

            df = pd.DataFrame(closes).dropna()
            if len(df) < ROLLING_WINDOW_DAYS + 5:
                return SovereignCreditStressResult(None, None, None, "uncalibrated")

            returns = df.pct_change().dropna()
            result = self._quant_engine.rolling_correlation(
                {c: returns[c].to_numpy() for c in returns.columns}, window=ROLLING_WINDOW_DAYS
            )
            if not result.success:
                return SovereignCreditStressResult(None, None, None, "uncalibrated")

            symbols = result.data.symbols
            i, j = symbols.index(a_ticker), symbols.index(b_ticker)
            current_corr = round(float(np.array(result.data.recent_correlation_matrix)[i][j]), 3)

            baseline = self._credit_stress_baseline.get("baseline_correlation") if self._credit_stress_baseline else None
            if baseline is None:
                return SovereignCreditStressResult(current_corr, None, None, "uncalibrated")

            delta = round(current_corr - baseline, 3)
            if abs(delta) <= REGIME_SHIFT_THRESHOLD:
                regime = "intact"
            elif (current_corr >= 0) != (baseline >= 0) and abs(current_corr) > INVERSION_ABS_THRESHOLD:
                regime = "inverted"
            else:
                regime = "breaking_down"
            return SovereignCreditStressResult(current_corr, baseline, delta, regime)
        except Exception as e:
            logger.warning("Sovereign credit stress computation failed: %s", e)
            return SovereignCreditStressResult(None, None, None, "uncalibrated")

    def _build_knowledge_context(
        self, sovereign_credit: Optional[SovereignCreditResult], credit_stress: SovereignCreditStressResult
    ) -> Optional[dict]:
        """Relevant book content on sovereign credit/default risk,
        attached for transparency -- informational only, never changes any
        computed number. No query when nothing is notable (spread normal,
        credit stress intact/uncalibrated) -- same "nothing to explain, no
        query" principle as e05/e10/e13/e14."""
        if self._knowledge_engine is None:
            return None
        spread_notable = sovereign_credit is not None and sovereign_credit.regime in ("tight", "wide")
        stress_notable = credit_stress.regime in ("breaking_down", "inverted")
        if not (spread_notable or stress_notable):
            return None
        try:
            terms = ["sovereign credit risk default probability"]
            if spread_notable:
                terms.append(f"{sovereign_credit.regime} emerging market sovereign credit spread")
            if stress_notable:
                terms.append(f"sovereign credit stress regime {credit_stress.regime}")
            query = " ".join(terms)
            results = self._knowledge_engine.document_store.hybrid_search(query, limit=3)
        except Exception as e:
            logger.warning("Knowledge context unavailable: %s", e)
            return None
        if not results:
            return None
        return {"query": query, "results": [r.to_dict() for r in results]}
