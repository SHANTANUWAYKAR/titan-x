"""
Module: engine.py
Description: Engine 33 -- Opportunity Ranking. Master prompt scope: "scan
    forex/stocks/crypto/indices/commodities/futures; rank top 100 by
    technical/fundamental/macro/sentiment/risk/liquidity; final conviction
    score."

    STALE CLAIM FIXED 2026-08-02: this docstring previously said stocks
    were excluded platform-wide. That was true when this file was written
    (2026-07-18) but no longer is -- core.config.assets now carries 16 real
    equities (AAPL/MSFT/.../JPM, RELIANCE/TCS/.../ITC, added at explicit
    user request with a narrower "price/technical scope only," see that
    module's own docstring). rank_opportunities' default symbol list
    (list_assets(), unfiltered) already included them with no code change
    needed -- verified live, SignalGenerationWorkflow runs cleanly end to
    end for real equity symbols (confirmed AAPL/MSFT both produce real
    signals/confidence/regime here). Only the claim above was wrong, not
    the behavior.

    Deliberately does NOT re-implement scoring: E51's own confidence score
    already blends technical + macro + confluence (cross-asset/sentiment/
    derivatives/commodity/credit/fixed-income -- see
    e51_signals._apply_confluence_adjustments), and E45's veto authority
    already covers risk. This engine's actual job is the one master-prompt
    line E51 alone doesn't do: rank EVERY supported asset by that same
    conviction score, including ones that don't clear E51's full
    risk_reward/CRO/edge-gate bar to become a tradeable signal -- "what's
    the best opportunity right now" is a broader question than "what
    tradeable signal fired right now" (scan_all_assets answers the
    narrower one).

    Runs e00_titan_brain.workflows.SignalGenerationWorkflow once per asset
    (the SAME real orchestration api/main.py's /signals/generate route and
    e51_signals.scan_all_assets both already trigger) -- reuses it rather
    than re-implementing the fetch/technical/macro/regime/fundamental/
    signal pipeline a third time.

    OPTIMIZED 2026-08-02: rank_opportunities defaults to ranking EVERY
    supported asset (~29), and used to do so via a plain sequential loop
    where each asset's workflow run independently re-fetched macro/
    fundamental/news/cross-asset data that's identical across every asset
    in the same ranking pass -- the exact redundant-fetch pattern
    scan_all_assets' own docstring already measured and fixed for ITS
    separate code path (52 redundant news round-trips, 182 redundant
    cross-asset ticker fetches, for a 13-asset scan), but this engine
    never got the same fix despite calling through a different path to
    the same underlying engines. Now fetches all 4 ONCE and shares them
    via SignalGenerationWorkflow.run's new optional params, and
    parallelizes the per-asset loop with the same bounded ThreadPoolExecutor
    pattern (6 workers, per-future + overall timeout, non-blocking
    shutdown) scan_all_assets already uses and this codebase has already
    verified safe for this exact kind of I/O-bound, no-shared-mutable-
    state fan-out.

    No calibration/training step applies (Rule 3): ranking is a sort over
    already-computed, already-validated confidence scores, not a new
    scoring model.

    No knowledge_engine wiring (Rule 2): this is orchestration + sorting,
    not an interpretive read of its own -- same "no" category as e34/e35.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-07-18
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Optional

from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus

logger = logging.getLogger(__name__)


@dataclass
class OpportunityRanking:
    """One asset's ranked conviction read."""

    symbol: str
    direction: Optional[str]  # LONG | SHORT | None
    confidence: int
    tradeable: bool  # cleared E51's full risk_reward/CRO/edge-gate bar
    regime: Optional[str]
    reason: str
    rank: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "symbol": self.symbol,
            "direction": self.direction,
            "confidence": self.confidence,
            "tradeable": self.tradeable,
            "regime": self.regime,
            "reason": self.reason,
        }


class OpportunityRankingEngine(BaseEngine):
    """
    Opportunity Ranking Engine (#33) -- ranks every one of this platform's
    supported assets by E51's own conviction score, running the real
    SignalGenerationWorkflow per asset. Takes the engine registry itself
    (same pattern e00_titan_brain already uses) rather than individual
    collaborator engines, since its whole job is orchestrating across all
    of them via the existing workflow layer, not owning any analysis logic
    itself.
    """

    engine_id = "e33_opportunity_ranking"
    engine_name = "Opportunity Ranking Engine"
    version = "1.0.0"

    def __init__(self, registry: Optional[Any] = None) -> None:
        super().__init__()
        self._registry = registry

    def initialize(self) -> EngineResult:
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Opportunity Ranking Engine initialized")

    def health_check(self) -> EngineResult:
        if self._registry is None:
            return EngineResult(success=False, message="No registry injected")
        return EngineResult(success=True, message="Healthy")

    def rank_opportunities(
        self, timeframe: str = "1d", years: int = 2, symbols: Optional[list[str]] = None
    ) -> EngineResult:
        if self._registry is None:
            return EngineResult(success=False, message="No registry injected -- cannot orchestrate per-asset analysis")

        from project_titan_x.core.config import list_assets
        from project_titan_x.engines.e00_titan_brain.workflows import SignalGenerationWorkflow

        asset_symbols = symbols if symbols is not None else [a.symbol for a in list_assets()]

        # Fetch every asset-INDEPENDENT input ONCE and share it across
        # every asset's workflow run below, via the SAME override params
        # scan_all_assets already uses for its own per-asset loop -- see
        # this class's own docstring and SignalGenerationWorkflow.run's
        # docstring for the real, measured redundant-fetch cost this
        # avoids. Each is best-effort: a missing/failed engine here just
        # leaves that shared value None, which makes the workflow fall
        # back to fetching it itself per-asset (unchanged, safe default).
        macro_snapshot = None
        macro_engine = self._registry.get("e04_macro")
        if macro_engine is not None:
            try:
                macro_result = macro_engine.analyze()
                if macro_result.success:
                    macro_snapshot = macro_result.data
            except Exception as e:
                logger.warning("Shared macro fetch failed, each asset will fetch its own: %s", e)

        fundamental_snapshot = None
        fundamental_engine = self._registry.get("e06_fundamental")
        if fundamental_engine is not None:
            try:
                fundamental_result = fundamental_engine.analyze()
                if fundamental_result.success:
                    fundamental_snapshot = fundamental_result.data
            except Exception as e:
                logger.warning("Shared fundamental fetch failed, each asset will fetch its own: %s", e)

        news_items = None
        news_engine = self._registry.get("e03_news")
        if news_engine is not None:
            try:
                news_result = news_engine.fetch_headlines(limit_per_feed=10)
                news_items = news_result.data if news_result.success and news_result.data else []
            except Exception as e:
                logger.warning("Shared news fetch failed, each asset will fetch its own: %s", e)

        cross_asset_result = None
        cross_asset_engine = self._registry.get("e10_cross_asset")
        if cross_asset_engine is not None:
            try:
                cross_asset_result = cross_asset_engine.analyze()
            except Exception as e:
                logger.warning("Shared cross-asset fetch failed, each asset will fetch its own: %s", e)

        workflow = SignalGenerationWorkflow(self._registry)

        def _rank_one(symbol: str) -> OpportunityRanking:
            try:
                result = workflow.run(
                    symbol, timeframe, years,
                    macro_snapshot=macro_snapshot, fundamental_snapshot=fundamental_snapshot,
                    news_items=news_items, cross_asset_result=cross_asset_result,
                )
            except Exception as e:
                logger.warning("Opportunity ranking workflow failed for %s: %s", symbol, e)
                return OpportunityRanking(symbol=symbol, direction=None, confidence=0, tradeable=False, regime=None, reason=f"workflow error: {e}")

            if not result.success:
                failed_step = next((s for s in result.steps if not s.success), None)
                reason = failed_step.message if failed_step else "workflow failed"
                return OpportunityRanking(symbol=symbol, direction=None, confidence=0, tradeable=False, regime=None, reason=reason)

            signal = result.final_data.get("signal")
            metadata = result.final_data.get("metadata") or {}
            regime_step = next((s for s in result.steps if s.step_name == "regime_classification"), None)
            regime_label = regime_step.data.primary_regime.value if (regime_step and regime_step.data) else None

            if signal is not None:
                return OpportunityRanking(
                    symbol=symbol, direction=signal.direction, confidence=signal.confidence_score,
                    tradeable=True, regime=signal.regime, reason="All signal criteria met",
                )
            direction = metadata.get("direction")
            if direction is None:
                # No clear directional bias -- checks["confidence_threshold"]
                # may incidentally also read False here (confidence
                # defaults low with no direction), but that's a side
                # effect, not the real reason: don't misreport it as a
                # failed threshold check.
                reason = "No clear directional bias"
            else:
                checks = metadata.get("checks", {})
                failed = [k for k, v in checks.items() if not v]
                reason = f"Not tradeable: {', '.join(failed)}" if failed else "Not tradeable"
            return OpportunityRanking(
                symbol=symbol, direction=direction, confidence=metadata.get("confidence") or 0,
                tradeable=False, regime=regime_label, reason=reason,
            )

        # Parallelized across assets -- same bounded-pool, non-blocking-
        # shutdown pattern e51_signals.scan_all_assets already uses and
        # this codebase has already verified safe: each asset's work here
        # is almost entirely I/O-bound, and every shared input above was
        # fetched once and is never mutated per-asset, so there's no
        # shared-state race. shutdown(wait=False) (not a `with` block) so
        # one asset's hung network call can't block this method from
        # returning once its own timeout budget is spent.
        rankings: list[OpportunityRanking] = []
        seen_symbols: set[str] = set()
        executor = ThreadPoolExecutor(max_workers=min(6, len(asset_symbols)) or 1)
        try:
            futures = {executor.submit(_rank_one, symbol): symbol for symbol in asset_symbols}
            for future in as_completed(futures, timeout=240):
                symbol = futures[future]
                try:
                    ranking = future.result(timeout=30)
                except Exception as e:
                    logger.warning("Ranking timed out or errored for %s: %s", symbol, e)
                    ranking = OpportunityRanking(symbol=symbol, direction=None, confidence=0, tradeable=False, regime=None, reason=f"timed out or errored: {e}")
                rankings.append(ranking)
                seen_symbols.add(symbol)
        except TimeoutError:
            logger.warning(
                "rank_opportunities: overall budget exceeded with %d/%d assets completed",
                len(seen_symbols), len(asset_symbols),
            )
        finally:
            executor.shutdown(wait=False)

        # Every REQUESTED symbol must appear in the output (unlike
        # scan_all_assets, which only ever returns actual tradeable
        # signals and is fine silently dropping a straggler) -- this
        # engine's whole point is ranking EVERY asset, tradeable or not.
        for symbol in asset_symbols:
            if symbol not in seen_symbols:
                rankings.append(
                    OpportunityRanking(symbol=symbol, direction=None, confidence=0, tradeable=False, regime=None, reason="ranking timed out")
                )

        rankings = rank_and_number(rankings)
        return EngineResult(success=True, data=rankings, message=f"Ranked {len(rankings)} opportunities")


def rank_and_number(rankings: list[OpportunityRanking]) -> list[OpportunityRanking]:
    """Sort by (tradeable, confidence) descending -- assets that cleared
    E51's full risk_reward/CRO/edge-gate bar always outrank ones that
    didn't, regardless of raw confidence, since "tradeable" is a
    categorically stronger claim than an unvalidated heuristic score. A
    standalone function (not a method) so it's testable without needing
    the real per-asset workflow to populate a list first."""
    ranked = sorted(rankings, key=lambda r: (r.tradeable, r.confidence), reverse=True)
    for i, r in enumerate(ranked, start=1):
        r.rank = i
    return ranked
