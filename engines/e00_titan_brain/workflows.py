"""
Module: workflows.py
Description: Workflow orchestration for Titan Brain -- formalizes the
    real, existing analysis pipeline (E02 Market Data -> E40 Data Quality
    -> E07 Technical -> E04 Macro -> E08 Regime -> E06 Fundamental -> E51
    Signals -> E43 Committee) into one auditable, steppable object,
    instead of the ad hoc wiring scattered across scan_all_assets()/
    api/main.py's _prepare_ohlcv(). Every step's success/failure and
    message is recorded, so a failed workflow shows exactly which stage
    broke and why -- not just a final exception.

    Scope: this runs the RESEARCH pipeline (fetch -> analyze -> classify
    -> signal -> committee review) only. There is no execution engine in
    this codebase for it to hand off to, and it must not gain one that
    bypasses human approval -- see scheduler.py's governance note.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from project_titan_x.core.config import get_asset

logger = logging.getLogger(__name__)


@dataclass
class WorkflowStepResult:
    step_name: str
    success: bool
    message: str
    data: Any = None


@dataclass
class WorkflowResult:
    workflow_name: str
    success: bool
    steps: list[WorkflowStepResult] = field(default_factory=list)
    final_data: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_name": self.workflow_name,
            "success": self.success,
            "steps": [
                {"step_name": s.step_name, "success": s.success, "message": s.message}
                for s in self.steps
            ],
        }


class SignalGenerationWorkflow:
    """Fetch -> repair -> technical analysis -> macro -> regime ->
    fundamental -> signal -> committee review, for one asset. Every real
    engine call this makes has the exact signature already used
    elsewhere in the codebase (api/main.py's _prepare_ohlcv,
    e51_signals.scan_all_assets) -- this doesn't reimplement any engine
    logic, only sequences existing calls and records the trail."""

    name = "signal_generation"

    def __init__(self, registry: Any) -> None:
        self.registry = registry

    def run(
        self,
        symbol: str,
        timeframe: str = "1d",
        years: int = 2,
        macro_snapshot: Optional[Any] = None,
        fundamental_snapshot: Optional[Any] = None,
        news_items: Optional[list] = None,
        cross_asset_result: Optional[Any] = None,
    ) -> WorkflowResult:
        """
        macro_snapshot/fundamental_snapshot/news_items/cross_asset_result:
        OPTIONAL pre-fetched, asset-INDEPENDENT data (same convention as
        e51_signals.generate_signal's own news_items/cross_asset_result
        params, and the exact 4 inputs e51_signals.scan_all_assets already
        fetches once and shares across every asset in a scan). None
        (default) preserves this method's original single-asset behavior
        exactly -- each is fetched fresh, right here, same as before.

        This exists because a caller that runs this workflow for MANY
        assets in one pass (e.g. e33_opportunity_ranking, which by default
        ranks every supported asset) was calling macro.analyze(),
        fundamental.analyze(), news.fetch_headlines(), and
        cross_asset.analyze() ONCE PER ASSET for data that is identical
        regardless of which asset is being evaluated -- confirmed real,
        measured costs in scan_all_assets' own docstring (52 redundant
        news round-trips, 182 redundant cross-asset ticker fetches, for a
        13-asset scan) before that method fixed the exact same redundancy
        for its own separate code path. This workflow had never gotten the
        same fix.
        """
        steps: list[WorkflowStepResult] = []

        def failed() -> WorkflowResult:
            return WorkflowResult(workflow_name=self.name, success=False, steps=steps)

        market_data = self.registry.get("e02_market_data")
        if market_data is None:
            steps.append(WorkflowStepResult("fetch_market_data", False, "E02 Market Data engine not registered"))
            return failed()

        asset = get_asset(symbol)
        yahoo_symbol = asset.yahoo_symbol if asset else symbol
        fetch = market_data.fetch_ohlcv(yahoo_symbol, timeframe, years=years)
        steps.append(WorkflowStepResult("fetch_market_data", fetch.success, fetch.message))
        if not fetch.success:
            return failed()
        df = fetch.data

        data_quality = self.registry.get("e40_data_quality")
        if data_quality is not None:
            # validate() BEFORE repair() -- previously this workflow only
            # ever called repair(), so its own audit trail (this method's
            # whole reason to exist: "shows exactly which stage broke and
            # why") never recorded the actual quality_score/bad_ticks/
            # missing_candles read, just a generic "Repaired data: N rows"
            # message with no sense of how bad the input actually was or
            # whether the post-repair data is still trustworthy. validate()
            # failing (quality_score < 70) does NOT block the workflow --
            # repair() already exists specifically to fix what validate()
            # flags, so this is recorded for the audit trail, not a gate.
            # pd.Timedelta (what validate() uses internally for gap
            # detection) has no "wk"/"mo" unit -- confirmed directly
            # (raises "invalid unit abbreviation"). validate()'s own
            # try/except would turn that into a whole-method failure (it
            # wraps bad-tick/duplicate/null detection too, not just gap
            # detection), losing real quality info for no reason on a
            # timeframe this check simply can't gap-detect. Only pass a
            # Timedelta-compatible expected_freq; still validates
            # everything else for "1wk"/"1mo".
            expected_freq = timeframe if not timeframe.endswith(("wk", "mo")) else None
            validated = data_quality.validate(df, expected_freq=expected_freq)
            steps.append(WorkflowStepResult("data_quality_validate", validated.success, validated.message, data=validated.data))

            repaired = data_quality.repair(df)
            steps.append(WorkflowStepResult("data_quality_repair", repaired.success, repaired.message))
            if repaired.success:
                df = repaired.data

        technical = self.registry.get("e07_technical")
        if technical is None:
            steps.append(WorkflowStepResult("technical_analysis", False, "E07 Technical Analysis engine not registered"))
            return failed()
        ta_result = technical.analyze(df, symbol=symbol, timeframe=timeframe)
        steps.append(WorkflowStepResult("technical_analysis", ta_result.success, ta_result.message))
        if not ta_result.success:
            return failed()
        snapshot = ta_result.data["snapshot"]

        macro_score = 0.0
        if macro_snapshot is not None:
            steps.append(WorkflowStepResult("macro_analysis", True, "Reused shared macro snapshot (not re-fetched)"))
            macro_score = macro_snapshot.risk_on_off_score
        else:
            macro = self.registry.get("e04_macro")
            if macro is not None:
                macro_result = macro.analyze()
                steps.append(WorkflowStepResult("macro_analysis", macro_result.success, macro_result.message))
                if macro_result.success:
                    macro_snapshot = macro_result.data
                    macro_score = macro_snapshot.risk_on_off_score

        regime = self.registry.get("e08_regime")
        if regime is None:
            steps.append(WorkflowStepResult("regime_classification", False, "E08 Market Regime engine not registered"))
            return failed()
        regime_result = regime.classify(df, snapshot, macro_snapshot)
        steps.append(WorkflowStepResult("regime_classification", regime_result.success, regime_result.message, data=regime_result.data))
        if not regime_result.success:
            return failed()

        if fundamental_snapshot is not None:
            steps.append(WorkflowStepResult("fundamental_analysis", True, "Reused shared fundamental snapshot (not re-fetched)"))
        else:
            fundamental = self.registry.get("e06_fundamental")
            if fundamental is not None:
                fundamental_result = fundamental.analyze()
                steps.append(WorkflowStepResult("fundamental_analysis", fundamental_result.success, fundamental_result.message))
                if fundamental_result.success:
                    fundamental_snapshot = fundamental_result.data

        signals = self.registry.get("e51_signals")
        if signals is None:
            steps.append(WorkflowStepResult("generate_signal", False, "E51 Signal Intelligence engine not registered"))
            return failed()
        signal_result = signals.generate_signal(
            symbol, df, snapshot, regime_result.data, macro_score,
            macro_snapshot=macro_snapshot, fundamental_snapshot=fundamental_snapshot,
            news_items=news_items, cross_asset_result=cross_asset_result,
            enriched_df=ta_result.data.get("df"),
        )
        steps.append(WorkflowStepResult("generate_signal", signal_result.success, signal_result.message))
        if not signal_result.success:
            return failed()

        committee_decision = None
        signal = signal_result.data
        if signal is not None:
            committee = self.registry.get("e43_committee")
            if committee is not None:
                risk_approved = signal.checks_passed.get("cro_approved", True)
                committee_result = committee.evaluate_signal(
                    signal, macro_regime=regime_result.data.primary_regime.value,
                    macro_score=macro_score, risk_approved=risk_approved,
                )
                steps.append(WorkflowStepResult("committee_review", committee_result.success, committee_result.message))
                if committee_result.success:
                    committee_decision = committee_result.data

        return WorkflowResult(
            workflow_name=self.name,
            success=True,
            steps=steps,
            # metadata: the SAME generate_signal metadata (confidence/
            # direction/checks/edge_validation/...) that a firing signal
            # would carry, preserved even when signal is None -- e.g.
            # e33_opportunity_ranking needs a non-tradeable asset's raw
            # conviction read, not just the pass/fail verdict.
            final_data={"signal": signal, "committee_decision": committee_decision, "metadata": signal_result.metadata},
        )


WORKFLOWS: dict[str, type[SignalGenerationWorkflow]] = {
    "signal_generation": SignalGenerationWorkflow,
}
