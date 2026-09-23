"""
Module: test_committee_engine.py
Description: Unit tests for the Investment Committee's Knowledge Researcher
    agent (E01 integration) -- confirms it always abstains (never tips the
    weighted vote) and is a no-op when no knowledge engine is injected --
    plus (added 2026-08-20) the past-verdict reflection loop (see
    CommitteeEngine's own class docstring for provenance/design).
Author: Shantanu Waykar
Version: 1.0.0
"""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from project_titan_x.engines.base import EngineResult
from project_titan_x.engines.e00_titan_brain.state import PlatformState
from project_titan_x.engines.e01_knowledge.document_store import DocumentStore
from project_titan_x.engines.e01_knowledge.engine import KnowledgeEngine
from project_titan_x.engines.e43_committee.engine import CommitteeEngine
from project_titan_x.engines.e51_signals.engine import TradingSignal


def _signal() -> TradingSignal:
    return TradingSignal(
        asset="EURUSD", direction="LONG", entry=1.1000, stop_loss=1.0950,
        take_profit_1=1.1100, take_profit_2=1.1150, risk_percent=0.5,
        expected_value=0.6, confidence_score=85, regime="Trending Up",
    )


def test_knowledge_agent_absent_when_no_engine_injected():
    committee = CommitteeEngine()
    committee.initialize()
    result = committee.evaluate_signal(_signal(), macro_regime="Risk-On", macro_score=0.3)
    assert result.success
    agent_names = [v.agent_name for v in result.data.votes]
    assert "Knowledge Researcher" not in agent_names


def test_knowledge_agent_abstains_and_never_tips_consensus(tmp_path):
    store = DocumentStore(persist_dir=tmp_path / "chroma")
    knowledge_engine = KnowledgeEngine(knowledge_dir=tmp_path / "kd", data_root=tmp_path / "data", document_store=store)
    notes = tmp_path / "data" / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    (notes / "doc.txt").write_text(
        "Chapter 1: Trend Following\n\nBuying strength in a trending up regime is a classic trend-following entry.",
        encoding="utf-8",
    )
    knowledge_engine.ingestion.ingest_all()

    committee = CommitteeEngine(knowledge_engine=knowledge_engine)
    committee.initialize()
    result = committee.evaluate_signal(_signal(), macro_regime="Risk-On", macro_score=0.3)
    assert result.success

    votes_by_agent = {v.agent_name: v for v in result.data.votes}
    assert "Knowledge Researcher" in votes_by_agent
    assert votes_by_agent["Knowledge Researcher"].vote == "ABSTAIN"
    # An ABSTAIN vote must never be counted as FOR or AGAINST.
    assert result.data.for_count == sum(1 for v in result.data.votes if v.vote == "FOR")
    assert result.data.against_count == sum(1 for v in result.data.votes if v.vote == "AGAINST")


# ---- Risk Manager agent: microstructure/economic-calendar context ----
# (added 2026-08-02 -- previously this agent only ever looked at R:R,
# completely ignoring two real risk signals already attached to the
# signal it's voting on)


def test_risk_agent_for_with_no_flags_keeps_original_confidence():
    committee = CommitteeEngine()
    vote = committee._risk_agent(_signal(), risk_approved=True)
    assert vote.vote == "FOR"
    assert vote.confidence == 85
    assert "flagged" not in vote.reasoning


def test_risk_agent_for_but_confidence_reduced_when_execution_risk_high():
    committee = CommitteeEngine()
    signal = _signal()
    signal.microstructure_context = {"execution_risk": "high"}
    vote = committee._risk_agent(signal, risk_approved=True)
    assert vote.vote == "FOR"  # R:R still adequate -- doesn't flip the veto
    assert vote.confidence == 70  # 85 - 15
    assert "execution risk HIGH" in vote.reasoning


def test_risk_agent_for_but_confidence_reduced_when_high_impact_event_imminent():
    committee = CommitteeEngine()
    signal = _signal()
    signal.economic_calendar_context = {"high_impact_within_1h": True}
    vote = committee._risk_agent(signal, risk_approved=True)
    assert vote.vote == "FOR"
    assert vote.confidence == 70
    assert "high-impact economic release" in vote.reasoning


def test_risk_agent_stacks_both_flags():
    committee = CommitteeEngine()
    signal = _signal()
    signal.microstructure_context = {"execution_risk": "high"}
    signal.economic_calendar_context = {"high_impact_within_1h": True}
    vote = committee._risk_agent(signal, risk_approved=True)
    assert vote.vote == "FOR"
    assert vote.confidence == 55  # 85 - 15*2
    assert "execution risk HIGH" in vote.reasoning
    assert "high-impact economic release" in vote.reasoning


def test_risk_agent_against_still_reports_flags_when_rr_inadequate():
    committee = CommitteeEngine()
    signal = _signal()
    signal.stop_loss = 1.0900  # widens the stop -- R:R drops to 1.0, well below 2.0
    signal.microstructure_context = {"execution_risk": "high"}
    vote = committee._risk_agent(signal, risk_approved=True)
    assert vote.vote == "AGAINST"
    assert "execution risk HIGH" in vote.reasoning
    assert "Inadequate risk:reward" in vote.reasoning


def test_risk_agent_low_execution_risk_is_not_flagged():
    """Only execution_risk == 'high' should raise a flag -- 'low'/'medium'
    are within normal bounds, not something the Risk Manager should
    editorialize about on every single trade."""
    committee = CommitteeEngine()
    signal = _signal()
    signal.microstructure_context = {"execution_risk": "low"}
    vote = committee._risk_agent(signal, risk_approved=True)
    assert vote.confidence == 85
    assert "flagged" not in vote.reasoning


# ---- past-verdict reflection loop ----


class _FakeMarketDataEngine:
    """Test double -- returns a controllable single closing price via the
    SAME EngineResult(success=True, data=<df with 'close'>) shape
    MarketDataEngine.fetch_ohlcv actually returns."""

    def __init__(self, close_price: float):
        self._close_price = close_price

    def fetch_ohlcv(self, symbol, timeframe="1d", years=1, allow_cache=False):
        df = pd.DataFrame({"close": [self._close_price]})
        return EngineResult(success=True, data=df, message="ok")


def _seed_decision(state: PlatformState, symbol: str, days_ago: float, **fields) -> str:
    decided_at = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    key = f"committee_decision.{symbol}.{decided_at}"
    payload = {"decided_at": decided_at, "resolved": False, **fields}
    state.set(key, payload)
    return key


def test_past_context_empty_without_market_data_engine_injected():
    committee = CommitteeEngine()  # no market_data_engine, no platform_state
    committee.initialize()
    result = committee.evaluate_signal(_signal(), macro_regime="Risk-On", macro_score=0.3)
    assert result.success
    assert result.data.past_context == []


def test_evaluate_signal_logs_a_pending_decision(tmp_path):
    state = PlatformState(persist_path=tmp_path / "committee_decisions.json")
    committee = CommitteeEngine(market_data_engine=_FakeMarketDataEngine(1.10), platform_state=state)
    committee.initialize()
    committee.evaluate_signal(_signal(), macro_regime="Risk-On", macro_score=0.3)

    keys = state.keys(prefix="committee_decision.EURUSD.")
    assert len(keys) == 1
    entry = state.get(keys[0])
    assert entry["resolved"] is False
    assert entry["direction"] == "LONG"
    assert entry["entry_price"] == 1.1000


def test_pending_decision_too_young_is_not_resolved(tmp_path):
    state = PlatformState(persist_path=tmp_path / "committee_decisions.json")
    key = _seed_decision(state, "EURUSD", days_ago=0.1, direction="LONG", entry_price=1.1000, consensus="APPROVED")
    committee = CommitteeEngine(market_data_engine=_FakeMarketDataEngine(1.15), platform_state=state)
    committee.initialize()
    committee.evaluate_signal(_signal(), macro_regime="Risk-On", macro_score=0.3)
    assert state.get(key)["resolved"] is False


def test_pending_approved_long_resolved_correct_when_price_rose(tmp_path):
    state = PlatformState(persist_path=tmp_path / "committee_decisions.json")
    key = _seed_decision(state, "EURUSD", days_ago=5, direction="LONG", entry_price=1.1000, consensus="APPROVED")
    committee = CommitteeEngine(market_data_engine=_FakeMarketDataEngine(1.1100), platform_state=state)
    committee.initialize()
    result = committee.evaluate_signal(_signal(), macro_regime="Risk-On", macro_score=0.3)

    resolved = state.get(key)
    assert resolved["resolved"] is True
    assert resolved["correct"] is True
    assert resolved["realized_return_pct"] == pytest.approx((1.1100 - 1.1000) / 1.1000 * 100, abs=1e-4)
    assert "validated" in resolved["lesson"]

    # The NOW-resolved entry must appear in THIS SAME call's past_context
    # (resolution happens before votes are cast, per evaluate_signal's own order).
    assert len(result.data.past_context) == 1
    assert result.data.past_context[0]["correct"] is True


def test_pending_approved_long_resolved_incorrect_when_price_fell(tmp_path):
    state = PlatformState(persist_path=tmp_path / "committee_decisions.json")
    key = _seed_decision(state, "EURUSD", days_ago=5, direction="LONG", entry_price=1.1000, consensus="APPROVED")
    committee = CommitteeEngine(market_data_engine=_FakeMarketDataEngine(1.0900), platform_state=state)
    committee.initialize()
    committee.evaluate_signal(_signal(), macro_regime="Risk-On", macro_score=0.3)

    resolved = state.get(key)
    assert resolved["correct"] is False
    assert "missed" in resolved["lesson"]


def test_pending_rejected_decision_resolves_with_no_applicable_outcome(tmp_path):
    """REJECTED means no trade was taken -- 'was it right' is genuinely
    not applicable, and must never be fabricated into True/False."""
    state = PlatformState(persist_path=tmp_path / "committee_decisions.json")
    key = _seed_decision(state, "EURUSD", days_ago=5, direction="LONG", entry_price=1.1000, consensus="REJECTED")
    committee = CommitteeEngine(market_data_engine=_FakeMarketDataEngine(1.2000), platform_state=state)
    committee.initialize()
    committee.evaluate_signal(_signal(), macro_regime="Risk-On", macro_score=0.3)

    resolved = state.get(key)
    assert resolved["resolved"] is True
    assert resolved["correct"] is None
    assert "not applicable" in resolved["lesson"]


def test_past_context_is_informational_only_never_changes_consensus(tmp_path):
    """A history of nothing but MISSED past verdicts must not change
    today's vote outcome -- past_context is attached AFTER consensus is
    already computed (see evaluate_signal's own order), architecturally
    incapable of influencing it. Verified end to end here, not just by
    reading the source."""
    state_with_bad_history = PlatformState(persist_path=tmp_path / "bad_history.json")
    for i in range(3):
        _seed_decision(
            state_with_bad_history, "EURUSD", days_ago=10 + i,
            direction="LONG", entry_price=1.1000, consensus="APPROVED",
        )
    committee_with_history = CommitteeEngine(
        market_data_engine=_FakeMarketDataEngine(1.0500),  # every past LONG call would resolve as wrong
        platform_state=state_with_bad_history,
    )
    committee_with_history.initialize()
    result_with_history = committee_with_history.evaluate_signal(_signal(), macro_regime="Risk-On", macro_score=0.3)

    committee_without_history = CommitteeEngine()
    committee_without_history.initialize()
    result_without_history = committee_without_history.evaluate_signal(_signal(), macro_regime="Risk-On", macro_score=0.3)

    assert len(result_with_history.data.past_context) == 3
    assert all(o["correct"] is False for o in result_with_history.data.past_context)
    # Despite an entirely-wrong history, today's consensus/vote breakdown
    # is identical to a committee with no history at all.
    assert result_with_history.data.consensus == result_without_history.data.consensus
    assert result_with_history.data.for_count == result_without_history.data.for_count
    assert result_with_history.data.against_count == result_without_history.data.against_count
