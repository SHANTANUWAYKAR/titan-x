"""
Module: test_explainable_ai_engine.py
Description: Unit tests for Engine 41 (Explainable AI).
Author: Shantanu Waykar
Version: 1.0.0
"""

from dataclasses import dataclass, field
from typing import Optional

import pytest

from project_titan_x.engines.e41_explainable_ai.engine import ExplainableAIEngine


@dataclass
class _FakeEdgeValidation:
    status: str
    message: str


@dataclass
class _FakeSignal:
    asset: str = "GOLD"
    direction: str = "LONG"
    entry: float = 2000.0
    confidence_score: int = 62
    regime: str = "trending_up"
    supporting_evidence: list = field(default_factory=list)
    invalidation: str = "Candle closes below 1980.0"
    historical_context: str = "ATR-based stop, R:R 2.0:1"
    checks_passed: dict = field(default_factory=dict)
    edge_validation: Optional[_FakeEdgeValidation] = None
    macro_context: Optional[dict] = None
    fundamental_context: Optional[dict] = None
    microstructure_context: Optional[dict] = None
    economic_calendar_context: Optional[dict] = None
    knowledge_context: Optional[dict] = None
    news_context: Optional[dict] = None


@pytest.fixture
def engine() -> ExplainableAIEngine:
    e = ExplainableAIEngine()
    e.initialize()
    return e


def test_health_check(engine):
    assert engine.health_check().success


def test_explain_splits_core_and_confluence_reasons(engine):
    signal = _FakeSignal(supporting_evidence=[
        "Trend score 0.4 above entry threshold",
        "Confluence: options skew (call_skew, E13) agrees with direction",
        "Confluence: significant seasonality (bullish, E16) agrees with direction",
    ])
    result = engine.explain(signal)
    assert result.success
    explanation = result.data
    assert explanation.core_reasons == ["Trend score 0.4 above entry threshold"]
    assert len(explanation.confluence_reasons) == 2
    assert all(r.startswith("Confluence:") for r in explanation.confluence_reasons)


def test_explain_headline_contains_key_fields(engine):
    signal = _FakeSignal(asset="BTCUSD", direction="SHORT", entry=65000.1234, confidence_score=71, regime="ranging")
    result = engine.explain(signal)
    headline = result.data.headline
    assert "SHORT" in headline
    assert "BTCUSD" in headline
    assert "71" in headline
    assert "ranging" in headline


def test_summarize_macro_none_when_absent(engine):
    assert engine._summarize_macro(None) is None


def test_summarize_macro_builds_readable_string(engine):
    macro = {"regime_label": "risk_on", "risk_on_off_score": 0.35, "liquidity_signal": "expanding", "currency_strength": "USD weak"}
    summary = engine._summarize_macro(macro)
    assert "risk_on" in summary
    assert "0.35" in summary


def test_summarize_risk_flags_high_execution_risk_and_calendar_event(engine):
    signal = _FakeSignal(
        microstructure_context={"execution_risk": "high"},
        economic_calendar_context={"high_impact_within_1h": True, "high_impact_within_24h": True},
        checks_passed={"asset_supported": True, "cro_approved": False},
    )
    risk_summary = engine._summarize_risk(signal)
    assert any("Execution risk" in r for r in risk_summary)
    assert any("within 1 hour" in r for r in risk_summary)
    assert any("cro_approved" in r for r in risk_summary)


def test_summarize_historical_prefers_edge_validation_message(engine):
    signal = _FakeSignal(edge_validation=_FakeEdgeValidation(status="proven_positive_edge", message="Validated: Sharpe=0.8"))
    assert engine._summarize_historical(signal) == "Validated: Sharpe=0.8"


def test_summarize_historical_falls_back_to_historical_context(engine):
    signal = _FakeSignal(edge_validation=None, historical_context="ATR-based stop, R:R 2.0:1")
    assert engine._summarize_historical(signal) == "ATR-based stop, R:R 2.0:1"


def test_build_caveats_flags_unvalidated_edge_and_low_confidence(engine):
    signal = _FakeSignal(edge_validation=_FakeEdgeValidation(status="not_significant", message="x"), confidence_score=35)
    caveats = engine._build_caveats(signal)
    assert any("did not clear full statistical validation" in c for c in caveats)
    assert any("heuristic conviction score" in c for c in caveats)


def test_build_caveats_no_edge_validation_run(engine):
    signal = _FakeSignal(edge_validation=None, confidence_score=80)
    caveats = engine._build_caveats(signal)
    assert any("No historical edge validation was run" in c for c in caveats)


def test_summarize_knowledge_none_when_no_results(engine):
    assert engine._summarize_knowledge(None) is None
    assert engine._summarize_knowledge({"results": []}) is None


def test_summarize_knowledge_returns_top_result(engine):
    knowledge_context = {"query": "gold seasonality", "results": [{"title": "Market Wizards"}]}
    summary = engine._summarize_knowledge(knowledge_context)
    assert "Market Wizards" in summary


def test_summarize_news_none_when_no_matched_headlines(engine):
    assert engine._summarize_news(None) is None
    assert engine._summarize_news({"matched_headlines": []}) is None


def test_summarize_news_surfaces_actual_headlines_not_just_a_count(engine):
    """The real gap this was added to close: supporting_evidence only ever
    carried a "N headline(s) agree" COUNT string -- a trader had no way to
    see what the news actually said. news_summary must include the real
    headline text."""
    news_context = {
        "matched_headlines": [
            {"title": "Fed signals rate cuts as inflation cools", "source": "Reuters"},
            {"title": "Gold rallies on dovish Fed commentary", "source": "Bloomberg"},
        ],
        "aggregate_sentiment_score": 0.42,
        "agrees_with_direction": True,
        "disagrees_with_direction": False,
    }
    summary = engine._summarize_news(news_context)
    assert "Fed signals rate cuts" in summary
    assert "Gold rallies on dovish Fed" in summary
    assert "agreeing" in summary
    assert "0.42" in summary


def test_summarize_news_reports_disagreement(engine):
    news_context = {
        "matched_headlines": [{"title": "Weak jobs report pressures dollar", "source": "AP"}],
        "aggregate_sentiment_score": -0.3,
        "agrees_with_direction": False,
        "disagrees_with_direction": True,
    }
    summary = engine._summarize_news(news_context)
    assert "disagreeing" in summary


def test_explain_includes_news_summary(engine):
    signal = _FakeSignal(
        supporting_evidence=["Confluence: 2 symbol-specific headline(s) (E09) agree with direction"],
        news_context={
            "matched_headlines": [{"title": "Gold rallies on dovish Fed commentary", "source": "Bloomberg"}],
            "aggregate_sentiment_score": 0.42,
            "agrees_with_direction": True,
            "disagrees_with_direction": False,
        },
    )
    result = engine.explain(signal)
    assert result.success
    assert result.data.news_summary is not None
    assert "Gold rallies" in result.data.news_summary


def test_explain_handles_missing_optional_fields_gracefully(engine):
    """A minimal signal with no context fields at all must not crash --
    explanation is honestly sparse, not fabricated."""
    signal = _FakeSignal(supporting_evidence=[])
    result = engine.explain(signal)
    assert result.success
    assert result.data.macro_summary is None
    assert result.data.fundamental_summary is None
