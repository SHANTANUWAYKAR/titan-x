"""
Module: engine.py
Description: Engine 43 — Multi-Agent Investment Committee.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-08-02
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from project_titan_x.core.config import get_asset
from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus
from project_titan_x.engines.e00_titan_brain.state import PlatformState
from project_titan_x.engines.e01_knowledge.engine import KnowledgeEngine
from project_titan_x.engines.e51_signals.engine import TradingSignal

logger = logging.getLogger(__name__)


@dataclass
class AgentVote:
    """Single agent vote on a trade proposal."""

    agent_name: str
    vote: str  # FOR, AGAINST, ABSTAIN
    reasoning: str
    confidence: int = 50


@dataclass
class PastVerdictOutcome:
    """One RESOLVED past committee verdict for the SAME asset -- what
    actually happened, fed back as context for the current verdict. See
    CommitteeEngine's own class docstring for provenance/design."""

    decided_at: str  # ISO timestamp
    direction: str
    entry_price: float
    consensus: str  # APPROVED | REJECTED
    realized_return_pct: Optional[float] = None
    correct: Optional[bool] = None  # None for REJECTED (no trade taken, not applicable)
    lesson: str = ""


@dataclass
class CommitteeDecision:
    """Final committee decision on a trade proposal."""

    proposal_summary: str
    votes: list[AgentVote] = field(default_factory=list)
    consensus: str = "NO_CONSENSUS"
    for_count: int = 0
    against_count: int = 0
    cio_recommendation: str = ""
    risk_veto: bool = False
    human_approval_required: bool = True
    dissent_summary: str = ""
    # Added 2026-08-20: resolved past verdicts for this SAME asset,
    # informational only -- attached for transparency, read by NOTHING
    # else in this class, same "never changes the underlying computation"
    # discipline as knowledge_context elsewhere in this codebase. Never
    # empty-vs-None ambiguity: always a list, empty when no history exists
    # yet or no platform_state was injected.
    past_context: list[dict] = field(default_factory=list)


class CommitteeEngine(BaseEngine):
    """
    Multi-Agent Investment Committee — structured debate and vote.

    Agents: Macro, Fundamental, Technical, Quant, Microstructure,
    Portfolio Manager, Risk Manager (veto), Performance Auditor,
    Knowledge Researcher, CIO.

    **Past-verdict reflection loop (added 2026-08-20).** Found while
    reviewing TauricResearch/TradingAgents (cloned read-only for
    reference): its `TradingMemoryLog` closes a loop this engine never
    had -- "this committee said APPROVE on asset X on date D -> what
    actually happened -> a structured lesson surfaced back the next time
    X comes up." Confirmed genuinely absent here (and in E36/E37, which
    operate at the whole-trade-journal/regime level, never tied to a
    SPECIFIC committee verdict) via a full-repo grep before building this.
    TradingAgents' own version calls an LLM to write the reflection --
    this platform has no LLM anywhere (Rule 1's own "extractive, not
    generated" precedent for E01), so the adaptation here is entirely
    template-based: every piece TradingAgents' reflection step needs
    (sign-match between predicted direction and realized return, a
    human-readable lesson string) is derivable from numbers this engine
    and E02 Market Data already have, with no free-text reasoning
    required. Persisted via the SAME `PlatformState` JSON-persistence
    class E00 Titan Brain already uses (a dedicated instance/file here,
    `data/state/committee_decisions.json` -- not shared with E00's own
    instance, since E00 is constructed AFTER this engine in registry.py's
    build order) -- reusing the existing mechanism rather than building a
    second, parallel one. Deliberately informational-only for this first
    version: `past_context` is attached to `CommitteeDecision` for
    transparency and read by NOTHING else in this class (same discipline
    as `knowledge_context` elsewhere in this codebase) -- it does NOT
    change vote weights or the consensus outcome. Letting past accuracy
    actually influence agent weighting would be a real, separate,
    Rule-3-calibrated change, not something to fold in unvalidated.
    """

    engine_id = "e43_committee"
    engine_name = "Multi-Agent Investment Committee"
    version = "1.0.0"

    AGENT_WEIGHTS = {
        "Risk Manager": 2.0,
        "Technical Analyst": 1.5,
        "Macro Analyst": 1.5,
        "Quant Researcher": 1.2,
        "Portfolio Manager": 1.2,
        "Chief Investment Officer": 1.0,
    }

    # A verdict needs at least this many days between decision and
    # resolution before its realized outcome means anything -- resolving
    # against same-day/next-day noise would produce a lesson dominated by
    # short-term chop rather than whether the underlying call was right.
    MIN_RESOLUTION_AGE_DAYS = 1.0
    PAST_CONTEXT_LIMIT = 5
    DEFAULT_DECISION_LOG_PATH = Path("data") / "state" / "committee_decisions.json"

    def __init__(
        self,
        knowledge_engine: Optional[KnowledgeEngine] = None,
        market_data_engine: Optional[Any] = None,
        platform_state: Optional[PlatformState] = None,
    ) -> None:
        super().__init__()
        # Optional and None by default: without it, evaluate_signal() behaves
        # exactly as before (no Knowledge Researcher vote). Pass a real
        # instance (as registry.py does) to turn it on.
        self._knowledge_engine = knowledge_engine
        # Both Optional/None-by-default -- same graceful-degradation
        # convention as every other cross-engine dependency here. Without
        # BOTH injected, past_context stays an empty list and evaluate_signal
        # behaves exactly as it did before this feature existed.
        self._market_data_engine = market_data_engine
        self._platform_state = platform_state or (
            PlatformState(persist_path=self.DEFAULT_DECISION_LOG_PATH) if market_data_engine is not None else None
        )

    def initialize(self) -> EngineResult:
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Investment Committee initialized")

    def health_check(self) -> EngineResult:
        return EngineResult(success=True, message="Healthy")

    def evaluate_signal(
        self,
        signal: TradingSignal,
        macro_regime: str = "Neutral",
        macro_score: float = 0.0,
        risk_approved: bool = True,
    ) -> EngineResult:
        """
        Run full committee evaluation on a trading signal.

        Args:
            signal: Trading signal to evaluate.
            macro_regime: Current macro regime label.
            macro_score: Risk-on/off score.
            risk_approved: Whether CRO already approved.

        Returns:
            EngineResult with CommitteeDecision.
        """
        try:
            self._set_status(EngineStatus.RUNNING)
            self._resolve_pending_decisions(signal.asset)
            past_context = self._get_past_context(signal.asset)
            votes: list[AgentVote] = []

            votes.append(self._macro_agent(signal, macro_regime, macro_score))
            votes.append(self._technical_agent(signal))
            votes.append(self._quant_agent(signal))
            votes.append(self._portfolio_agent(signal))
            votes.append(self._risk_agent(signal, risk_approved))
            knowledge_vote = self._knowledge_agent(signal)
            if knowledge_vote is not None:
                votes.append(knowledge_vote)
            votes.append(self._cio_agent(signal, votes))

            for_count = sum(1 for v in votes if v.vote == "FOR")
            against_count = sum(1 for v in votes if v.vote == "AGAINST")

            weighted_for = sum(
                self.AGENT_WEIGHTS.get(v.agent_name, 1.0)
                for v in votes if v.vote == "FOR"
            )
            weighted_against = sum(
                self.AGENT_WEIGHTS.get(v.agent_name, 1.0)
                for v in votes if v.vote == "AGAINST"
            )

            risk_veto = any(
                v.agent_name == "Risk Manager" and v.vote == "AGAINST"
                for v in votes
            )

            if risk_veto:
                consensus = "REJECTED"
                cio_rec = f"REJECT — Risk Manager veto on {signal.direction} {signal.asset}"
            elif weighted_for > weighted_against:
                consensus = "APPROVED"
                cio_rec = (
                    f"APPROVE {signal.direction} {signal.asset} @ {signal.entry:.4f} "
                    f"— risk {signal.risk_percent}% (human approval required)"
                )
            else:
                consensus = "REJECTED"
                cio_rec = f"REJECT {signal.direction} {signal.asset} — committee dissent"

            dissent = [v for v in votes if v.vote == "AGAINST"]
            dissent_summary = "; ".join(f"{v.agent_name}: {v.reasoning}" for v in dissent)

            decision = CommitteeDecision(
                proposal_summary=f"{signal.direction} {signal.asset} @ {signal.entry:.4f}",
                votes=votes,
                consensus=consensus,
                for_count=for_count,
                against_count=against_count,
                cio_recommendation=cio_rec,
                risk_veto=risk_veto,
                human_approval_required=True,
                dissent_summary=dissent_summary,
                past_context=[o.__dict__ for o in past_context],
            )
            self._log_pending_decision(signal, consensus)

            self._set_status(EngineStatus.IDLE)
            return EngineResult(
                success=True,
                data=decision,
                message=f"Committee: {consensus}",
                metadata={"consensus": consensus, "risk_veto": risk_veto},
            )
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def _decision_key_prefix(self, symbol: str) -> str:
        return f"committee_decision.{symbol}."

    def _resolve_pending_decisions(self, symbol: str) -> None:
        """Resolve any PENDING past verdicts for `symbol` that are old
        enough (>= MIN_RESOLUTION_AGE_DAYS) against the real realized
        price move since entry -- the reflection half of the loop
        described in this class's own docstring. Best-effort: silently
        no-ops without both collaborators injected, same graceful-
        absence convention as every other Optional dependency here."""
        if self._platform_state is None or self._market_data_engine is None:
            return
        prefix = self._decision_key_prefix(symbol)
        now = datetime.now(timezone.utc)
        for key in self._platform_state.keys(prefix=prefix):
            entry = self._platform_state.get(key)
            if not entry or entry.get("resolved"):
                continue
            try:
                decided_at = datetime.fromisoformat(entry["decided_at"])
            except (KeyError, ValueError):
                continue
            age_days = (now - decided_at).total_seconds() / 86400
            if age_days < self.MIN_RESOLUTION_AGE_DAYS:
                continue
            self._resolve_one(symbol, key, entry)

    def _resolve_one(self, symbol: str, key: str, entry: dict) -> None:
        asset = get_asset(symbol)
        yahoo_symbol = asset.yahoo_symbol if asset else symbol
        try:
            fetch = self._market_data_engine.fetch_ohlcv(yahoo_symbol, "1d", years=1)
            if not fetch.success or fetch.data is None or fetch.data.empty:
                return
            current_price = float(fetch.data["close"].iloc[-1])
        except Exception as e:
            logger.warning("Could not resolve past committee verdict for %s: %s", symbol, e)
            return

        entry_price = float(entry["entry_price"])
        direction = entry["direction"]
        directional_sign = 1 if direction == "LONG" else -1
        realized_return_pct = (current_price - entry_price) / entry_price * 100 * directional_sign

        decided_date = entry["decided_at"][:10]
        if entry["consensus"] == "APPROVED":
            correct = realized_return_pct > 0
            lesson = (
                f"{symbol} {direction} approved {decided_date}: "
                f"{'validated' if correct else 'missed'} -- realized "
                f"{realized_return_pct:+.2f}% move since entry {entry_price:.5f} "
                f"(now {current_price:.5f})."
            )
        else:
            correct = None  # REJECTED -- no trade taken, "was it right" isn't applicable, never fabricated
            lesson = f"{symbol} {direction} rejected {decided_date} -- no trade taken, outcome not applicable."

        entry["resolved"] = True
        entry["realized_return_pct"] = round(realized_return_pct, 4)
        entry["correct"] = correct
        entry["lesson"] = lesson
        self._platform_state.set(key, entry)

    def _get_past_context(self, symbol: str) -> list[PastVerdictOutcome]:
        """The most recent RESOLVED verdicts for `symbol`, most recent
        first -- informational only, see this class's own docstring."""
        if self._platform_state is None:
            return []
        prefix = self._decision_key_prefix(symbol)
        keys = sorted(self._platform_state.keys(prefix=prefix), reverse=True)
        outcomes: list[PastVerdictOutcome] = []
        for key in keys:
            if len(outcomes) >= self.PAST_CONTEXT_LIMIT:
                break
            entry = self._platform_state.get(key)
            if not entry or not entry.get("resolved"):
                continue
            outcomes.append(PastVerdictOutcome(
                decided_at=entry["decided_at"],
                direction=entry["direction"],
                entry_price=entry["entry_price"],
                consensus=entry["consensus"],
                realized_return_pct=entry.get("realized_return_pct"),
                correct=entry.get("correct"),
                lesson=entry.get("lesson", ""),
            ))
        return outcomes

    def _log_pending_decision(self, signal: TradingSignal, consensus: str) -> None:
        """Persist THIS verdict as pending, to be resolved by a future
        call once enough time has passed. Best-effort/no-op without
        platform_state injected."""
        if self._platform_state is None:
            return
        now = datetime.now(timezone.utc)
        key = f"{self._decision_key_prefix(signal.asset)}{now.isoformat()}"
        self._platform_state.set(key, {
            "decided_at": now.isoformat(),
            "direction": signal.direction,
            "entry_price": signal.entry,
            "consensus": consensus,
            "resolved": False,
        })

    def _macro_agent(self, signal: TradingSignal, regime: str, score: float) -> AgentVote:
        if signal.direction == "LONG" and score >= 0:
            return AgentVote("Macro Analyst", "FOR", f"Macro {regime} supports long risk", 70)
        if signal.direction == "SHORT" and score <= 0:
            return AgentVote("Macro Analyst", "FOR", f"Macro {regime} supports short risk", 70)
        if abs(score) < 0.2:
            return AgentVote("Macro Analyst", "ABSTAIN", "Macro neutral — no strong view", 50)
        return AgentVote("Macro Analyst", "AGAINST", f"Macro {regime} conflicts with {signal.direction}", 65)

    def _technical_agent(self, signal: TradingSignal) -> AgentVote:
        if signal.confidence_score >= 80:
            return AgentVote(
                "Technical Analyst", "FOR",
                f"TA confidence {signal.confidence_score}% with regime {signal.regime}", 80
            )
        return AgentVote(
            "Technical Analyst", "AGAINST",
            f"TA confidence {signal.confidence_score}% below threshold", 60
        )

    def _quant_agent(self, signal: TradingSignal) -> AgentVote:
        if signal.expected_value >= 0.5 and signal.risk_percent <= 1.0:
            return AgentVote(
                "Quant Researcher", "FOR",
                f"Positive EV {signal.expected_value:.2f}R at {signal.risk_percent}% risk", 75
            )
        if signal.expected_value < 0:
            return AgentVote("Quant Researcher", "AGAINST", f"Negative EV {signal.expected_value:.2f}", 70)
        return AgentVote("Quant Researcher", "ABSTAIN", "Marginal statistical edge", 55)

    def _portfolio_agent(self, signal: TradingSignal) -> AgentVote:
        if signal.risk_percent <= 1.0:
            return AgentVote(
                "Portfolio Manager", "FOR",
                f"Small-capital friendly risk {signal.risk_percent}%", 70
            )
        return AgentVote("Portfolio Manager", "AGAINST", f"Risk {signal.risk_percent}% too high for capital", 75)

    # Floating-point tolerance for the R:R >= 2.0 threshold below: a
    # deliberately-configured exact 2:1 setup (a common, real trader
    # convention -- "risk 50 pips, target 100 pips") can land at e.g.
    # 1.9999999999999556 after float subtraction, which a strict >= 2.0
    # comparison would wrongly veto. Confirmed live with this exact
    # fixture: entry=1.1000/stop_loss=1.0950/take_profit_1=1.1100
    # computes rr=1.9999999999999556, not 2.0.
    _RR_TOLERANCE = 1e-9

    def _risk_agent(self, signal: TradingSignal, risk_approved: bool) -> AgentVote:
        if not risk_approved:
            return AgentVote("Risk Manager", "AGAINST", "CRO veto — trade fails risk rules", 95)
        rr = abs(signal.take_profit_1 - signal.entry) / abs(signal.entry - signal.stop_loss)

        # Real, already-computed risk factors attached to this signal that
        # this agent previously never read at all -- E11's execution-risk
        # read (spread percentile + Amihud illiquidity, see
        # e11_microstructure) and E05's imminent-high-impact-event flag.
        # Added 2026-08-02: doesn't change the FOR/AGAINST veto itself
        # (R:R remains the hard gate, same as before -- flipping a veto's
        # trigger condition is a bigger behavioral change than this
        # engine's own module docstring's Rule 3/thin-orchestration scope
        # warrants without a dedicated review), but the one agent whose
        # entire job is risk assessment should not stay silent about real
        # risk data that's sitting right there on the signal it's voting
        # on.
        risk_flags: list[str] = []
        micro = getattr(signal, "microstructure_context", None)
        if micro and micro.get("execution_risk") == "high":
            risk_flags.append("execution risk HIGH (E11: wide spread/thin volume/elevated price impact)")
        cal = getattr(signal, "economic_calendar_context", None)
        if cal and cal.get("high_impact_within_1h"):
            risk_flags.append("high-impact economic release due within 1h (E05)")

        if rr >= 2.0 - self._RR_TOLERANCE and signal.stop_loss > 0:
            reasoning = f"R:R {rr:.1f}:1 with valid stop"
            confidence = 85
            if risk_flags:
                reasoning += f" -- but flagged: {'; '.join(risk_flags)}"
                confidence -= 15 * len(risk_flags)
            return AgentVote("Risk Manager", "FOR", reasoning, max(confidence, 40))

        reasoning = "Inadequate risk:reward or missing stop"
        if risk_flags:
            reasoning += f"; additionally flagged: {'; '.join(risk_flags)}"
        return AgentVote("Risk Manager", "AGAINST", reasoning, 90)

    def _knowledge_agent(self, signal: TradingSignal) -> Optional[AgentVote]:
        """Knowledge Researcher: surfaces relevant trader/book knowledge
        for this trade's direction and regime (requirement #16: "every
        engine should retrieve relevant knowledge before making
        decisions"). Always ABSTAINs -- it contributes evidence for human
        review, not a directional judgement, so it can never tip the
        weighted FOR/AGAINST count or count toward the CIO agent's
        for_votes majority check. Returns None (no vote cast at all) if no
        knowledge engine was injected or nothing relevant was found."""
        if self._knowledge_engine is None:
            return None
        try:
            query = f"{signal.direction} trade in {signal.regime} regime for {signal.asset}"
            results = self._knowledge_engine.document_store.hybrid_search(query, limit=2)
        except Exception as e:
            logger.warning("Knowledge Researcher agent unavailable: %s", e)
            return None
        if not results:
            return None
        excerpt = results[0].chunk.text[:200]
        return AgentVote(
            "Knowledge Researcher", "ABSTAIN",
            f"Relevant knowledge found ({results[0].chunk.title}): {excerpt}...", 50,
        )

    def _cio_agent(self, signal: TradingSignal, votes: list[AgentVote]) -> AgentVote:
        for_votes = [v for v in votes if v.vote == "FOR"]
        if len(for_votes) >= 3:
            return AgentVote(
                "Chief Investment Officer", "FOR",
                f"Committee majority supports {signal.direction} {signal.asset}", 75
            )
        return AgentVote(
            "Chief Investment Officer", "ABSTAIN",
            "Insufficient committee conviction — wait for better setup", 60
        )
