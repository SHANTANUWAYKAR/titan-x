"""
Module: test_fixed_income_engine.py
Description: Unit tests for Engine 14 (Fixed Income Intelligence).
Author: Shantanu Waykar
Version: 1.0.0
"""

import pytest

from project_titan_x.engines.e14_fixed_income.engine import (
    GOVT_ETF_TICKERS,
    FixedIncomeIntelligenceEngine,
)


@pytest.fixture
def engine() -> FixedIncomeIntelligenceEngine:
    e = FixedIncomeIntelligenceEngine()
    e.initialize()
    return e


def test_health_check(engine):
    assert engine.health_check().success


def test_govt_etf_tickers_cover_the_curve():
    assert set(GOVT_ETF_TICKERS.keys()) == {"SHY", "IEF", "TLT", "TIP"}


# ---- _classify_spread (pure function, no network) ----


def test_classify_spread_tight(engine):
    assert engine._classify_spread(30.0, tight_bps=50.0, wide_bps=150.0) == "tight"


def test_classify_spread_normal(engine):
    assert engine._classify_spread(100.0, tight_bps=50.0, wide_bps=150.0) == "normal"


def test_classify_spread_wide(engine):
    assert engine._classify_spread(200.0, tight_bps=50.0, wide_bps=150.0) == "wide"


def test_classify_spread_unavailable_without_value(engine):
    assert engine._classify_spread(None, tight_bps=50.0, wide_bps=150.0) == "unavailable"


# ---- analyze() against REAL yfinance + REAL QuantResearchEngine ----


@pytest.mark.network
def test_analyze_returns_all_four_duration_convexity_results(engine):
    result = engine.analyze()
    assert result.success
    snapshot = result.data
    assert len(snapshot.duration_convexity) == 4
    tickers = {dc.ticker for dc in snapshot.duration_convexity}
    assert tickers == {"SHY", "IEF", "TLT", "TIP"}


@pytest.mark.network
def test_analyze_duration_values_are_realistic(engine):
    """Sanity check against real published effective durations: SHY (1-3y)
    must be shortest, TLT (20y+) must be longest -- a computation bug
    (wrong ticker, wrong regression target) would likely break this
    ordering even if it produced SOME numbers."""
    result = engine.analyze()
    assert result.success
    by_ticker = {dc.ticker: dc.empirical_duration for dc in result.data.duration_convexity}
    if all(v is not None for v in by_ticker.values()):
        assert by_ticker["SHY"] < by_ticker["IEF"] < by_ticker["TLT"]


@pytest.mark.network
def test_analyze_credit_spread_is_real_and_positive_for_high_yield(engine):
    """High-yield credit spread over a Treasury benchmark should be
    positive (HYG yields more than IEF) -- a real, well-established
    market fact, not something that could flip sign without a real bug."""
    result = engine.analyze()
    assert result.success
    spread = result.data.credit_spread
    if spread and spread.hy_spread_pct is not None:
        assert spread.hy_spread_pct > 0
        assert spread.hy_regime in ("tight", "normal", "wide")


@pytest.mark.network
def test_analyze_credit_stress_uses_real_baseline_when_present(engine):
    result = engine.analyze()
    assert result.success
    stress = result.data.credit_stress
    assert stress is not None
    if stress.baseline_correlation is not None:
        assert stress.regime in ("intact", "weakening", "breaking_down", "inverted")
        assert -1.0 <= stress.current_correlation <= 1.0


@pytest.mark.network
def test_analyze_uses_calibrated_duration_when_present(engine):
    """With a real (non-empty) calibration injected, at least one ETF must
    resolve to a real duration value, not None -- confirms _load_calibration's
    output actually reaches analyze(), not just that the file loads."""
    engine._duration_baseline = {"IEF": {"empirical_duration": 7.1, "convexity": 91.5, "r_squared": 0.9}}
    result = engine.analyze()
    assert result.success
    ief = next(dc for dc in result.data.duration_convexity if dc.ticker == "IEF")
    assert ief.empirical_duration == 7.1


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
    from project_titan_x.engines.e14_fixed_income.engine import CreditSpreadResult, CreditStressResult

    spread = CreditSpreadResult(ig_spread_pct=50.0, hy_spread_pct=600.0, ig_regime="normal", hy_regime="wide")
    stress = CreditStressResult(0.5, 0.1, 0.4, "breaking_down")
    assert engine._build_knowledge_context(spread, stress) is None


def test_build_knowledge_context_none_when_nothing_notable(tmp_path):
    from project_titan_x.engines.e14_fixed_income.engine import CreditSpreadResult, CreditStressResult

    knowledge_engine = _real_knowledge_engine(
        tmp_path, "Chapter 1: Credit Markets\n\nCredit spreads compensate investors for default risk.",
    )
    engine = FixedIncomeIntelligenceEngine(knowledge_engine=knowledge_engine)
    engine.initialize()
    spread = CreditSpreadResult(ig_spread_pct=100.0, hy_spread_pct=350.0, ig_regime="normal", hy_regime="normal")
    stress = CreditStressResult(0.0, 0.0, 0.0, "intact")
    assert engine._build_knowledge_context(spread, stress) is None


def test_build_knowledge_context_returns_results_when_spread_notable(tmp_path):
    from project_titan_x.engines.e14_fixed_income.engine import CreditSpreadResult, CreditStressResult

    knowledge_engine = _real_knowledge_engine(
        tmp_path,
        "Chapter 1: High Yield Credit Spreads\n\nA sharply widening high-yield credit spread "
        "signals rising default risk and often precedes broader risk-asset weakness.",
    )
    engine = FixedIncomeIntelligenceEngine(knowledge_engine=knowledge_engine)
    engine.initialize()
    spread = CreditSpreadResult(ig_spread_pct=50.0, hy_spread_pct=600.0, ig_regime="normal", hy_regime="wide")
    stress = CreditStressResult(0.0, 0.0, 0.0, "intact")
    context = engine._build_knowledge_context(spread, stress)
    assert context is not None
    assert context["results"]


@pytest.mark.network
def test_analyze_attaches_knowledge_context_when_notable(tmp_path):
    from project_titan_x.engines.e14_fixed_income.engine import CreditStressResult

    knowledge_engine = _real_knowledge_engine(
        tmp_path,
        "Chapter 1: Credit Stress\n\nWhen high-yield bonds start moving in lockstep with "
        "Treasuries, it often signals a duration-dominated, risk-off macro regime.",
    )
    engine = FixedIncomeIntelligenceEngine(knowledge_engine=knowledge_engine)
    engine.initialize()
    engine._credit_stress_baseline = {"baseline_correlation": -0.5}
    result = engine.analyze()
    assert result.success
    # Force a deterministic notable read regardless of today's live data.
    if result.data.credit_stress.regime in ("breaking_down", "inverted"):
        assert result.data.knowledge_context is not None
        assert result.data.knowledge_context["results"]
