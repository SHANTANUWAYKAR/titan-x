"""
Module: engine.py
Description: Engine 64 -- Causal Intelligence. See MASTER_PROMPT.md's
    "PROMPT 5" section: genuinely new, no existing engine models causal
    CHAINS (Fed pause -> real yields fall -> dollar weakens -> gold
    rallies) as distinct from correlation.

    Real technique, not fabricated: Granger causality (Granger, 1969;
    implemented via statsmodels.tsa.stattools.grangercausalitytests, a
    standard, real econometric test for whether one time series' past
    values help predict another's future values beyond that series' own
    history) on real price/macro history from E02/E19. Every claimed
    causal link is TESTED against real data and reported with its real
    p-value -- never asserted from macro theory alone. A candidate chain
    is only as strong as its weakest tested link; an untested or
    not-significant link is reported honestly, never silently dropped
    from the output.

    Rule 3: no calibration script -- Granger causality is itself the
    real statistical test, not a fitted parameter; standard p<0.05
    convention, not tuned.
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

from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus

logger = logging.getLogger(__name__)

SIGNIFICANCE_P_VALUE = 0.05  # standard two-tailed convention, not fit to this platform's data
DEFAULT_MAX_LAG = 5
MIN_OBSERVATIONS = 120

# Real, standard macro-theory candidate links (textbook relationships --
# real yields drive currency strength, currency strength drives gold,
# risk sentiment drives crypto/equities) -- each ALWAYS tested against
# real data before being reported as anything more than a hypothesis.
KNOWN_CANDIDATE_LINKS: tuple[tuple[str, str, str], ...] = (
    ("^TNX", "DX-Y.NYB", "10Y yield -> Dollar Index (higher real yields historically support the dollar)"),
    ("DX-Y.NYB", "GC=F", "Dollar Index -> Gold (dollar strength historically pressures gold, inverse)"),
    ("^VIX", "^GSPC", "VIX -> S&P 500 (risk-off historically pressures equities, inverse)"),
    ("^VIX", "BTC-USD", "VIX -> Bitcoin (risk-off historically pressures crypto as a risk asset, inverse)"),
)


@dataclass
class CausalLinkResult:
    cause_symbol: str
    effect_symbol: str
    hypothesis: str
    tested: bool
    significant: Optional[bool]
    min_p_value: Optional[float]
    best_lag: Optional[int]
    n_observations: int
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "cause_symbol": self.cause_symbol, "effect_symbol": self.effect_symbol,
            "hypothesis": self.hypothesis, "tested": self.tested, "significant": self.significant,
            "min_p_value": round(self.min_p_value, 4) if self.min_p_value is not None else None,
            "best_lag": self.best_lag, "n_observations": self.n_observations, "note": self.note,
        }


@dataclass
class CausalChainReport:
    generated_at: datetime
    links: list[CausalLinkResult] = field(default_factory=list)
    chain_verdict: str = "insufficient_data"  # fully_supported | partially_supported | not_supported | insufficient_data

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "links": [l.to_dict() for l in self.links],
            "chain_verdict": self.chain_verdict,
        }


class CausalIntelligenceEngine(BaseEngine):
    """Causal Intelligence Engine (#64) -- tests real candidate macro
    causal links via Granger causality on real price history, never
    asserts a causal chain from theory alone."""

    engine_id = "e64_causal_intelligence"
    engine_name = "Causal Intelligence Engine"
    version = "1.0.0"

    def __init__(self, market_data_engine: Optional[Any] = None) -> None:
        super().__init__()
        self._market_data_engine = market_data_engine

    def initialize(self) -> EngineResult:
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Causal Intelligence Engine initialized")

    def health_check(self) -> EngineResult:
        return EngineResult(success=True, message="Healthy")

    def test_causal_link(
        self, cause_symbol: str, effect_symbol: str, hypothesis: str = "", max_lag: int = DEFAULT_MAX_LAG, years: int = 10,
    ) -> CausalLinkResult:
        if self._market_data_engine is None:
            return CausalLinkResult(cause_symbol, effect_symbol, hypothesis, False, None, None, None, 0, "No market_data_engine injected")
        try:
            from statsmodels.tsa.stattools import grangercausalitytests

            cause_fetch = self._market_data_engine.fetch_ohlcv(cause_symbol, "1d", years=years)
            effect_fetch = self._market_data_engine.fetch_ohlcv(effect_symbol, "1d", years=years)
            if not cause_fetch.success or not effect_fetch.success or cause_fetch.data is None or effect_fetch.data is None:
                return CausalLinkResult(cause_symbol, effect_symbol, hypothesis, False, None, None, None, 0, "Could not fetch real price history for one or both symbols")

            # Merge on DATE only, not full timestamp: different real data
            # sources close their trading day at different UTC hours (e.g.
            # VIX at 05:00 UTC, GC=F futures at 04:00 UTC) -- verified live,
            # merging on the full timestamp silently matched 0 rows despite
            # 10 years of real overlapping history for both series.
            cause_df = cause_fetch.data[["timestamp", "close"]].rename(columns={"close": "cause"})
            effect_df = effect_fetch.data[["timestamp", "close"]].rename(columns={"close": "effect"})
            cause_df["date_key"] = cause_df["timestamp"].dt.date
            effect_df["date_key"] = effect_df["timestamp"].dt.date
            merged = pd.merge(cause_df, effect_df, on="date_key", how="inner").sort_values("date_key")
            merged["cause_ret"] = merged["cause"].pct_change()
            merged["effect_ret"] = merged["effect"].pct_change()
            merged = merged.dropna(subset=["cause_ret", "effect_ret"])
            n = len(merged)
            if n < MIN_OBSERVATIONS:
                return CausalLinkResult(cause_symbol, effect_symbol, hypothesis, False, None, None, None, n, f"Only {n} aligned real observations, need >={MIN_OBSERVATIONS}")

            data = merged[["effect_ret", "cause_ret"]].to_numpy()  # grangercausalitytests: [effect, cause] order
            results = grangercausalitytests(data, maxlag=max_lag, verbose=False)
            p_values = {lag: round(res[0]["ssr_ftest"][1], 6) for lag, res in results.items()}
            best_lag = min(p_values, key=lambda k: p_values[k])
            min_p = p_values[best_lag]
            # Explicit native-type casts: statsmodels/numpy hand back
            # numpy.int64/numpy.float64/numpy.bool_ here (lag dict keys,
            # p-values, and their comparison), none of which json.dumps
            # can serialize -- verified live via two separate real
            # crashes from validate_e64_causal_intelligence.py (first
            # numpy.bool_, then numpy.int64) before every numeric field
            # going into the dataclass was cast explicitly rather than
            # trusting an implicit numpy->native coercion that silently
            # isn't one.
            best_lag = int(best_lag)
            min_p = float(min_p)
            n = int(n)
            significant = bool(min_p < SIGNIFICANCE_P_VALUE)
            return CausalLinkResult(
                cause_symbol, effect_symbol, hypothesis, True, significant, min_p, best_lag, n,
                note=f"Granger causality {'CONFIRMED' if significant else 'NOT significant'} (p={min_p:.4f} at lag {best_lag}, n={n} real observations)",
            )
        except Exception as e:
            logger.warning("Causal link test failed for %s -> %s: %s", cause_symbol, effect_symbol, e)
            return CausalLinkResult(cause_symbol, effect_symbol, hypothesis, False, None, None, None, 0, f"Test failed: {e}")

    def trace_causal_chain(self, chain: Optional[list[tuple[str, str, str]]] = None, max_lag: int = DEFAULT_MAX_LAG) -> EngineResult:
        """chain: list of (cause_symbol, effect_symbol, hypothesis) --
        None (default) tests every real KNOWN_CANDIDATE_LINKS entry."""
        try:
            self._set_status(EngineStatus.RUNNING)
            links_to_test = chain if chain is not None else list(KNOWN_CANDIDATE_LINKS)
            results = [self.test_causal_link(c, e, h, max_lag=max_lag) for c, e, h in links_to_test]

            tested = [r for r in results if r.tested]
            if not tested:
                verdict = "insufficient_data"
            elif all(r.significant for r in tested):
                verdict = "fully_supported"
            elif any(r.significant for r in tested):
                verdict = "partially_supported"
            else:
                verdict = "not_supported"

            report = CausalChainReport(generated_at=datetime.now(timezone.utc), links=results, chain_verdict=verdict)
            self._set_status(EngineStatus.IDLE)
            n_sig = sum(1 for r in tested if r.significant)
            return EngineResult(
                success=True, data=report,
                message=f"Causal chain: {verdict} ({n_sig}/{len(tested)} tested link(s) Granger-significant)",
            )
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("trace_causal_chain failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])
