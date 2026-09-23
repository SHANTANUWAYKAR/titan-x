"""Unit tests for Sentiment Intelligence Engine (E09)."""

import pytest

from project_titan_x.engines.e09_sentiment import SentimentIntelligenceEngine


@pytest.fixture
def sentiment_engine() -> SentimentIntelligenceEngine:
    engine = SentimentIntelligenceEngine()
    engine.initialize()
    return engine


def test_engine_initialization(sentiment_engine: SentimentIntelligenceEngine):
    result = sentiment_engine.health_check()
    assert result.success


def test_analyze_text_rejects_empty_string(sentiment_engine: SentimentIntelligenceEngine):
    result = sentiment_engine.analyze_text("")
    assert not result.success


def test_analyze_text_positive_headline(sentiment_engine: SentimentIntelligenceEngine):
    result = sentiment_engine.analyze_text("Company beats earnings expectations, shares rally sharply")
    assert result.success
    r = result.data
    assert r.label == "positive"
    assert r.compound_score > 0
    assert -1.0 <= r.compound_score <= 1.0


def test_analyze_text_negative_headline(sentiment_engine: SentimentIntelligenceEngine):
    result = sentiment_engine.analyze_text("Stocks crash as recession fears grip investors")
    assert result.success
    r = result.data
    assert r.label == "negative"
    assert r.compound_score < 0


def test_analyze_batch_aggregates_scores(sentiment_engine: SentimentIntelligenceEngine):
    texts = [
        "Company beats earnings expectations, shares rally",
        "Stocks crash amid recession fears",
    ]
    result = sentiment_engine.analyze_batch(texts)
    assert result.success
    assert result.data["n"] == 2
    assert -1.0 <= result.data["aggregate_score"] <= 1.0
    assert result.data["aggregate_label"] in ("positive", "negative", "neutral")


def test_analyze_batch_rejects_empty_list(sentiment_engine: SentimentIntelligenceEngine):
    result = sentiment_engine.analyze_batch([])
    assert not result.success


# ---- knowledge_context (E01 integration) ----


def _real_knowledge_engine(tmp_path, note_text: str):
    from project_titan_x.engines.e01_knowledge.document_store import DocumentStore
    from project_titan_x.engines.e01_knowledge.engine import KnowledgeEngine

    store = DocumentStore(persist_dir=tmp_path / "chroma")
    knowledge_engine = KnowledgeEngine(knowledge_dir=tmp_path / "kd", data_root=tmp_path / "data", document_store=store)
    notes = tmp_path / "data" / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    (notes / "doc.txt").write_text(note_text, encoding="utf-8")
    knowledge_engine.ingestion.ingest_all()
    return knowledge_engine


def test_analyze_text_attaches_knowledge_context_when_injected(tmp_path):
    knowledge_engine = _real_knowledge_engine(
        tmp_path,
        "Chapter 1: Overconfidence\n\nOverconfidence bias leads investors to trade too frequently and underestimate risk during positive sentiment.",
    )
    engine = SentimentIntelligenceEngine(knowledge_engine=knowledge_engine)
    engine.initialize()
    result = engine.analyze_text("Company beats earnings expectations, shares rally sharply")
    assert result.success
    assert result.data.knowledge_context is not None
    assert result.data.knowledge_context["results"]


def test_analyze_text_knowledge_context_none_without_engine(sentiment_engine):
    result = sentiment_engine.analyze_text("Company beats earnings expectations")
    assert result.success
    assert result.data.knowledge_context is None


def test_analyze_batch_attaches_single_aggregate_knowledge_context(tmp_path):
    """Batch scoring must trigger exactly one knowledge lookup (on the
    aggregate label), not one per text -- see _score_text()'s docstring."""
    knowledge_engine = _real_knowledge_engine(
        tmp_path,
        "Chapter 1: Market Panic\n\nNegative sentiment cascades often overshoot fundamental value during panic selling.",
    )
    engine = SentimentIntelligenceEngine(knowledge_engine=knowledge_engine)
    engine.initialize()
    result = engine.analyze_batch(["Stocks crash amid recession fears", "Markets tumble on inflation data"])
    assert result.success
    assert result.data["knowledge_context"] is not None
    # Per-item results must NOT carry their own knowledge_context (that
    # would mean N lookups happened, not one).
    assert all(r.knowledge_context is None for r in result.data["results"])
