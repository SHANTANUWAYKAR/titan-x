"""
Module: test_cross_asset_engine.py
Description: Unit tests for Engine 10 (Cross-Asset Intelligence).
Author: Shantanu Waykar
Version: 1.0.0
"""

import pytest

from project_titan_x.engines.e10_cross_asset.engine import (
    PAIR_DEFINITIONS,
    CrossAssetIntelligenceEngine,
)


@pytest.fixture
def engine() -> CrossAssetIntelligenceEngine:
    e = CrossAssetIntelligenceEngine()
    e.initialize()
    return e


def test_pair_definitions_cover_the_master_prompt_relationships():
    """Master prompt spec: DXY<->Gold, Bonds<->Stocks, Oil<->CAD,
    Yields<->USD, VIX<->Risk Assets, Copper<->Global Growth, plus the
    forex cross-asset relationships added on top of the master list
    (EUR/USD<->GBP/USD, USD/JPY<->Yields, USD/JPY<->VIX, AUD/USD<->Copper)."""
    names = {name for name, *_ in PAIR_DEFINITIONS}
    assert names == {
        "DXY vs Gold",
        "Bonds vs Stocks",
        "Oil vs CAD",
        "Yields vs USD",
        "VIX vs Risk Assets",
        "Copper vs Global Growth",
        "EUR/USD vs GBP/USD",
        "USD/JPY vs Yields",
        "USD/JPY vs VIX",
        "AUD/USD vs Copper",
    }


def test_health_check(engine):
    assert engine.health_check().success


# ---- _classify_regime (pure function, no network) ----


def test_classify_regime_uncalibrated_without_baseline(engine):
    regime, delta = engine._classify_regime(0.5, None)
    assert regime == "uncalibrated"
    assert delta is None


def test_classify_regime_intact_when_close_to_baseline(engine):
    regime, delta = engine._classify_regime(0.42, 0.5)
    assert regime == "intact"
    assert delta == pytest.approx(-0.08)


def test_classify_regime_breaking_down_same_sign_large_delta(engine):
    regime, delta = engine._classify_regime(0.1, 0.6)
    assert regime == "breaking_down"
    assert delta == pytest.approx(-0.5)


def test_classify_regime_inverted_when_sign_flips(engine):
    regime, delta = engine._classify_regime(0.4, -0.5)
    assert regime == "inverted"


def test_classify_regime_not_inverted_if_flip_is_within_noise(engine):
    """Sign technically flips (-0.05 -> 0.05) but both are tiny -- noise
    around zero correlation, not a genuine inversion."""
    regime, delta = engine._classify_regime(0.05, -0.35)
    assert regime == "breaking_down"  # abs(current)=0.05 <= INVERSION_ABS_THRESHOLD


# ---- analyze() against REAL yfinance + REAL QuantResearchEngine ----
# (not mocked -- e51's edge-gate bug went undetected for months precisely
# because the collaborator it depended on was stubbed instead of real)


@pytest.mark.network
def test_analyze_returns_all_ten_pairs_from_real_data(engine):
    result = engine.analyze()
    assert result.success
    snapshot = result.data
    assert len(snapshot.pairs) == len(PAIR_DEFINITIONS) == 10
    for pair in snapshot.pairs:
        assert -1.0 <= pair.current_correlation <= 1.0
        assert -1.0 <= pair.full_period_correlation <= 1.0
        assert pair.regime in ("intact", "weakening", "breaking_down", "inverted", "uncalibrated")


@pytest.mark.network
def test_analyze_dependency_graph_has_all_named_assets(engine):
    result = engine.analyze()
    assert result.success
    graph = result.data.dependency_graph
    assert len(graph["edges"]) == 10
    assert len(graph["nodes"]) >= 12  # 20 label slots, several tickers shared (DXY, S&P 500, Yields, VIX, Copper)


@pytest.mark.network
def test_analyze_uses_calibrated_baseline_when_present(engine, monkeypatch):
    """With a real (non-empty) calibrated baseline injected, at least one
    pair must resolve to a real regime classification, not 'uncalibrated'
    -- confirms _load_baseline's output actually reaches analyze()'s
    classification step, not just that the file loads without error."""
    engine._baseline = {"DXY vs Gold": -0.4}
    result = engine.analyze()
    assert result.success
    dxy_gold = next(p for p in result.data.pairs if p.name == "DXY vs Gold")
    assert dxy_gold.regime != "uncalibrated"
    assert dxy_gold.baseline_correlation == -0.4


@pytest.mark.network
def test_analyze_includes_forex_cross_asset_pairs(engine):
    """EUR/USD<->GBP/USD, USD/JPY<->Yields, USD/JPY<->VIX, AUD/USD<->Copper
    -- the forex relationships added on top of the master prompt's 6 named
    pairs -- must actually compute from real yfinance forex data."""
    result = engine.analyze()
    assert result.success
    by_name = {p.name: p for p in result.data.pairs}
    for name in ("EUR/USD vs GBP/USD", "USD/JPY vs Yields", "USD/JPY vs VIX", "AUD/USD vs Copper"):
        assert name in by_name
        assert -1.0 <= by_name[name].current_correlation <= 1.0


@pytest.mark.network
def test_eurusd_gbpusd_is_a_real_positive_correlation(engine):
    """Sanity check on a textbook relationship: EUR/USD and GBP/USD share
    the USD side and are well known to move together strongly. A flip to
    non-positive would indicate a real computation bug (e.g. a ticker
    swap or misaligned series), not normal market noise."""
    result = engine.analyze()
    assert result.success
    eur_gbp = next(p for p in result.data.pairs if p.name == "EUR/USD vs GBP/USD")
    assert eur_gbp.current_correlation > 0.3


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


def test_build_knowledge_context_none_without_engine(engine):
    assert engine._build_knowledge_context(["Bonds vs Stocks"]) is None


def test_build_knowledge_context_none_when_nothing_flagged(tmp_path):
    knowledge_engine = _real_knowledge_engine(
        tmp_path,
        "Chapter 1: Correlation\n\nBonds and stocks typically move inversely during equity selloffs.",
    )
    engine = CrossAssetIntelligenceEngine(knowledge_engine=knowledge_engine)
    engine.initialize()
    assert engine._build_knowledge_context([]) is None


def test_build_knowledge_context_returns_results_when_flagged(tmp_path):
    knowledge_engine = _real_knowledge_engine(
        tmp_path,
        "Chapter 1: Correlation Breakdown\n\nWhen normally negatively-correlated bonds and stocks "
        "start moving together, it signals a shift in the macro regime, often driven by inflation "
        "shocks that hit both asset classes at once.",
    )
    engine = CrossAssetIntelligenceEngine(knowledge_engine=knowledge_engine)
    engine.initialize()
    context = engine._build_knowledge_context(["Bonds vs Stocks"])
    assert context is not None
    assert context["results"]


@pytest.mark.network
def test_analyze_attaches_knowledge_context_when_pair_flagged(tmp_path):
    knowledge_engine = _real_knowledge_engine(
        tmp_path,
        "Chapter 1: Correlation Breakdown\n\nWhen normally negatively-correlated bonds and stocks "
        "start moving together, it signals an inflation-driven macro regime shift.",
    )
    engine = CrossAssetIntelligenceEngine(knowledge_engine=knowledge_engine)
    engine.initialize()
    # Force a flagged pair deterministically rather than depending on
    # today's live correlation happening to diverge from the real baseline.
    engine._baseline = {"Bonds vs Stocks": -0.9}
    result = engine.analyze()
    assert result.success
    assert "Bonds vs Stocks" in result.data.flagged_pairs
    assert result.data.knowledge_context is not None
    assert result.data.knowledge_context["results"]
