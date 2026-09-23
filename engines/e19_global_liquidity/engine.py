"""
Module: engine.py
Description: Engine 19 -- Global Liquidity. Master prompt scope (draft
    detail, item #53 "Global Liquidity Engine"): "central bank balance
    sheets, money supply, repo markets, liquidity conditions."

    UPDATE 2026-08-02: no longer gated on FRED_API_KEY. This engine now
    fetches via FredClient.series_observations_csv, the public no-key CSV
    download FRED's own graph pages use (verified live -- real 200s with
    full history for WALCL/M2SL/DFII10, no key required; see
    core.data_providers.fred module docstring). The api_key-gated REST
    path documented below is a genuinely separate endpoint that FredClient
    still supports for any future caller that wants it, but this engine no
    longer needs it. Scoped to three genuinely free FRED series that don't
    require any secondary data source:

      - WALCL: Fed total assets (the actual balance sheet -- QE/QT pace)
      - M2SL:  M2 money supply
      - DFII10: 10-Year Treasury Inflation-Indexed real yield -- positive
                real yield = textbook-restrictive monetary policy, negative
                = accommodative; this is a standard macro-economics
                definition, not a fabricated interpretation.

    Repo markets are an HONEST GAP -- no free, no-key repo-market data
    source was identified this session (SOFR/repo-rate spread data
    generally sits behind NY Fed / Bloomberg terminals or paid feeds); not
    fabricated here.

    Expanding/contracting regime thresholds (+-1% 3-month change for the
    balance sheet, +-0.5% for M2) are now genuinely CALIBRATED against real
    WALCL/M2SL history via scripts/training/train_e19_global_liquidity.py
    (percentile-of-own-history, same technique as e16_commodity's Gold/
    Silver ratio and e06_fundamental's yield curve) -- falls back to the
    original static documented conventions only if that calibration hasn't
    been run yet (data/models/e19_global_liquidity/calibration.json
    missing), same honest degrade-path as every other calibrated engine
    here.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-08-02
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus
from project_titan_x.engines.e01_knowledge.engine import KnowledgeEngine
from project_titan_x.core.data_providers.fred import FredClient, FredError

logger = logging.getLogger(__name__)

_CALIBRATION_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "e19_global_liquidity" / "calibration.json"

# Fallback static conventions -- only used if scripts/training/
# train_e19_global_liquidity.py hasn't been run yet (see _load_calibration).
BALANCE_SHEET_CHANGE_THRESHOLD_PCT = 1.0
M2_CHANGE_THRESHOLD_PCT = 0.5

LOOKBACK_DAYS = 91  # ~3 months, matches the training script's own lookback


@dataclass
class LiquiditySeriesRead:
    series_id: str
    latest_value: Optional[float]
    latest_date: Optional[str]
    pct_change_3m: Optional[float]
    regime: str = "unavailable"  # series-specific labels, see engine methods


@dataclass
class GlobalLiquiditySnapshot:
    timestamp: datetime
    fed_balance_sheet: Optional[LiquiditySeriesRead] = None
    m2_money_supply: Optional[LiquiditySeriesRead] = None
    real_yield_10y: Optional[LiquiditySeriesRead] = None
    overall_regime: str = "unconfigured"  # expanding | contracting | mixed | unconfigured
    knowledge_context: Optional[dict] = None


class GlobalLiquidityEngine(BaseEngine):
    """Global Liquidity Engine (#19) -- Fed balance sheet / M2 / real-yield
    regime read, honest no-key gap until FRED_API_KEY is configured."""

    engine_id = "e19_global_liquidity"
    engine_name = "Global Liquidity Engine"
    version = "1.0.0"

    def __init__(
        self,
        knowledge_engine: Optional[KnowledgeEngine] = None,
        fred_client: Optional[FredClient] = None,
    ) -> None:
        super().__init__()
        self._knowledge_engine = knowledge_engine
        self._fred_client = fred_client if fred_client is not None else FredClient()
        self._calibration = self._load_calibration()

    @staticmethod
    def _load_calibration() -> Optional[dict]:
        """Per-series threshold_pct from scripts/training/
        train_e19_global_liquidity.py. None (not fabricated) if the
        training script hasn't been run yet -- callers fall back to the
        static module-level constants."""
        if not _CALIBRATION_PATH.exists():
            return None
        try:
            return json.loads(_CALIBRATION_PATH.read_text()).get("series")
        except Exception as e:
            logger.warning("Failed to load E19 calibration from %s: %s", _CALIBRATION_PATH, e)
            return None

    def initialize(self) -> EngineResult:
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Global Liquidity Engine initialized")

    def health_check(self) -> EngineResult:
        try:
            obs = self._fred_client.series_observations_csv("DFII10")
            if not obs:
                raise ValueError("FRED CSV endpoint returned no observations")
            return EngineResult(success=True, message="Healthy")
        except Exception as e:
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def analyze(self, reference: Optional[datetime] = None) -> EngineResult:
        """Global liquidity regime -- not per-asset (same "market-wide"
        convention as e17_crypto's Fear & Greed note). No FRED_API_KEY
        needed -- fetches via the public no-key CSV endpoint (see module
        docstring).

        `reference` (added 2026-09-13, closing part of both PDFs in
        data/PDF/'s "IC-weighted confluence" ask): an optional as-of date
        that restricts every series to observations on or before it,
        letting a caller ask "what would this engine have reported on
        <past date>" -- the exact mechanism research/
        global_liquidity_ic_analysis.py needs to backtest whether
        e51_signals._confluence_global_liquidity's regime read has ever
        actually predicted anything, using WALCL/M2SL/DFII10's real cached
        history (data/raw/fred_cache/) rather than fabricated point-in-
        time values. None (default, unchanged) keeps today's exact live
        behavior -- every existing caller is unaffected. Honest caveat
        this can't remove: FRED sometimes revises past releases after the
        fact, so "what the series showed as of date X" here means "the
        value FRED's CURRENT vintage reports FOR date X," not necessarily
        what a live caller would have seen on X itself -- a standard,
        named limitation of backtesting on non-vintage macro data, not
        silently ignored."""
        try:
            self._set_status(EngineStatus.RUNNING)
            fed = self._read_series("WALCL", self._threshold_for("WALCL", BALANCE_SHEET_CHANGE_THRESHOLD_PCT), reference)
            m2 = self._read_series("M2SL", self._threshold_for("M2SL", M2_CHANGE_THRESHOLD_PCT), reference)
            real_yield = self._read_real_yield(reference)

            overall = self._overall_regime(fed, m2)
            snapshot = GlobalLiquiditySnapshot(
                timestamp=reference or datetime.now(timezone.utc),
                fed_balance_sheet=fed, m2_money_supply=m2, real_yield_10y=real_yield,
                overall_regime=overall,
                knowledge_context=self._build_knowledge_context(overall) if reference is None else None,
            )
            self._set_status(EngineStatus.IDLE)
            return EngineResult(success=True, data=snapshot, message=f"Global liquidity regime: {overall}")
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("Global liquidity analysis failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def _threshold_for(self, series_id: str, fallback: float) -> float:
        """Calibrated threshold_pct if available, else the static fallback
        convention -- see _load_calibration."""
        if self._calibration and series_id in self._calibration:
            return self._calibration[series_id]["threshold_pct"]
        return fallback

    def _read_series(
        self, series_id: str, threshold_pct: float, reference: Optional[datetime] = None,
    ) -> Optional[LiquiditySeriesRead]:
        try:
            obs = self._fred_client.series_observations_csv(series_id)
        except FredError as e:
            logger.warning("FRED fetch failed for %s: %s", series_id, e)
            return None
        clean = [o for o in obs if o.get("value") not in (None, ".", "")]
        if reference is not None:
            ref_date = pd.Timestamp(reference).tz_localize(None).normalize()
            clean = [o for o in clean if pd.Timestamp(o["date"]) <= ref_date]
        if len(clean) < 2:
            return LiquiditySeriesRead(series_id=series_id, latest_value=None, latest_date=None, pct_change_3m=None)

        dates = pd.to_datetime([o["date"] for o in clean])
        latest_date, latest_value = dates[-1], float(clean[-1]["value"])

        # Real calendar-date lookback (~3 months), not a fixed
        # observation-count offset -- correct for both WALCL's weekly and
        # M2SL's monthly release cadence, same technique as
        # train_e19_global_liquidity.py's calibration.
        cutoff = latest_date - timedelta(days=LOOKBACK_DAYS)
        prior_idx = dates.searchsorted(cutoff, side="right") - 1
        pct_change = None
        if prior_idx >= 0:
            past_value = float(clean[prior_idx]["value"])
            if past_value:
                pct_change = ((latest_value - past_value) / past_value) * 100

        regime = "flat"
        if pct_change is not None:
            if pct_change >= threshold_pct:
                regime = "expanding"
            elif pct_change <= -threshold_pct:
                regime = "contracting"

        return LiquiditySeriesRead(
            series_id=series_id, latest_value=latest_value, latest_date=str(latest_date.date()),
            pct_change_3m=round(pct_change, 4) if pct_change is not None else None, regime=regime,
        )

    def _read_real_yield(self, reference: Optional[datetime] = None) -> Optional[LiquiditySeriesRead]:
        try:
            obs = self._fred_client.series_observations_csv("DFII10")
        except FredError as e:
            logger.warning("FRED fetch failed for DFII10: %s", e)
            return None
        clean = [o for o in obs if o.get("value") not in (None, ".", "")]
        if reference is not None:
            ref_date = pd.Timestamp(reference).tz_localize(None).normalize()
            clean = [o for o in clean if pd.Timestamp(o["date"]) <= ref_date]
        if not clean:
            return LiquiditySeriesRead(series_id="DFII10", latest_value=None, latest_date=None, pct_change_3m=None)
        latest = clean[-1]
        value = float(latest["value"])
        # Positive real yield = restrictive policy, negative = accommodative
        # -- standard macro-economics definition, not a fabricated read.
        regime = "restrictive" if value > 0 else "accommodative"
        return LiquiditySeriesRead(
            series_id="DFII10", latest_value=value, latest_date=latest.get("date"),
            pct_change_3m=None, regime=regime,
        )

    @staticmethod
    def _overall_regime(fed: Optional[LiquiditySeriesRead], m2: Optional[LiquiditySeriesRead]) -> str:
        regimes = [r.regime for r in (fed, m2) if r is not None and r.regime in ("expanding", "contracting", "flat")]
        if not regimes:
            return "unconfigured"
        if all(r == "expanding" for r in regimes):
            return "expanding"
        if all(r == "contracting" for r in regimes):
            return "contracting"
        return "mixed"

    def _build_knowledge_context(self, overall_regime: str) -> Optional[dict]:
        """Relevant book content on liquidity-driven regimes -- only
        queried for a genuinely notable read (expanding/contracting, not
        flat/mixed/unconfigured), same "nothing to explain, no query"
        principle as every other confluence engine here."""
        if self._knowledge_engine is None or overall_regime not in ("expanding", "contracting"):
            return None
        try:
            query = f"global liquidity {overall_regime} central bank balance sheet money supply regime"
            results = self._knowledge_engine.document_store.hybrid_search(query, limit=3)
        except Exception as e:
            logger.warning("Knowledge context unavailable: %s", e)
            return None
        if not results:
            return None
        return {"query": query, "results": [r.to_dict() for r in results]}
