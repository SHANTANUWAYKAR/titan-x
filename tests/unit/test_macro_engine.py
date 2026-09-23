"""Unit tests for Macro Intelligence Engine."""

import pytest

from project_titan_x.engines.e04_macro import MacroIntelligenceEngine


@pytest.fixture
def macro_engine():
    engine = MacroIntelligenceEngine()
    engine.initialize()
    return engine


def test_macro_initialization(macro_engine):
    assert macro_engine.health_check().success


@pytest.mark.network
def test_macro_analyze(macro_engine):
    result = macro_engine.analyze()
    assert result.success
    snapshot = result.data
    assert -1.0 <= snapshot.risk_on_off_score <= 1.0
    assert snapshot.regime_label in ("Risk-On", "Risk-Off", "Neutral")
    assert snapshot.liquidity_signal in ("Expansion", "Contraction", "Neutral")
    assert len(snapshot.indicators) > 0


# ---- Real M2 money supply liquidity indicator (local FRED data) ----

def test_load_m2_liquidity_indicator_reads_real_local_file(macro_engine):
    """Real-collaborator test (Rule 4): reads the actual committed
    data/macro/m2real.csv, not a stub -- confirms the real FRED CSV
    column names/date parsing actually work."""
    indicators, notes = macro_engine._load_m2_liquidity_indicator()
    assert "fred_m2real_yoy_pct" in indicators
    assert isinstance(indicators["fred_m2real_yoy_pct"], float)
    assert "fred_m2real_as_of" in indicators


def test_load_m2_liquidity_indicator_missing_file_returns_empty(monkeypatch):
    import project_titan_x.engines.e04_macro.engine as e04_module

    monkeypatch.setattr(e04_module, "_M2REAL_PATH", e04_module.Path("/nonexistent/m2real.csv"))
    engine = MacroIntelligenceEngine()
    indicators, notes = engine._load_m2_liquidity_indicator()
    assert indicators == {}
    assert notes == []


def test_load_m2_liquidity_indicator_too_few_rows_returns_empty(tmp_path, monkeypatch):
    import project_titan_x.engines.e04_macro.engine as e04_module

    short_csv = tmp_path / "m2real.csv"
    short_csv.write_text("observation_date,M2REAL\n2026-01-01,6800.0\n2026-02-01,6810.0\n")
    monkeypatch.setattr(e04_module, "_M2REAL_PATH", short_csv)
    engine = MacroIntelligenceEngine()
    indicators, notes = engine._load_m2_liquidity_indicator()
    assert indicators == {}


def test_compute_liquidity_signal_m2_expansion_when_ffr_unavailable(macro_engine):
    signal = macro_engine._compute_liquidity_signal({"fred_m2real_yoy_pct": 5.0, "vix_price": 20}, [])
    assert signal == "Expansion"


def test_compute_liquidity_signal_m2_contraction_when_ffr_unavailable(macro_engine):
    signal = macro_engine._compute_liquidity_signal({"fred_m2real_yoy_pct": -3.0, "vix_price": 20}, [])
    assert signal == "Contraction"


def test_compute_liquidity_signal_ffr_takes_priority_over_m2(macro_engine):
    """Tier 1 (Fed Funds Rate, the actual policy stance) must win over
    tier 2 (M2 growth) when both are present and disagree."""
    signal = macro_engine._compute_liquidity_signal(
        {"av_fed_funds_rate_chg_3mo_pct": 0.5, "fred_m2real_yoy_pct": 5.0, "vix_price": 20}, []
    )
    assert signal == "Contraction"


def test_compute_liquidity_signal_falls_through_to_vix_when_m2_flat(macro_engine):
    """M2 roughly flat (neither tier threshold cleared) must defer to the
    price-based VIX/risk-score proxy, not silently return Neutral early."""
    signal = macro_engine._compute_liquidity_signal({"fred_m2real_yoy_pct": 0.5, "vix_price": 30}, [])
    assert signal == "Contraction"


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


@pytest.mark.network
def test_macro_analyze_attaches_knowledge_context_when_injected(tmp_path):
    knowledge_engine = _real_knowledge_engine(
        tmp_path,
        "Chapter 1: Risk-On Conditions\n\nA risk-on macro regime with expanding liquidity typically favors equities and commodities over safe havens.",
    )
    engine = MacroIntelligenceEngine(knowledge_engine=knowledge_engine)
    engine.initialize()
    result = engine.analyze()
    assert result.success
    assert result.data.knowledge_context is not None
    assert result.data.knowledge_context["results"]


@pytest.mark.network
def test_macro_analyze_knowledge_context_none_without_engine(macro_engine):
    result = macro_engine.analyze()
    assert result.success
    assert result.data.knowledge_context is None
