"""
Module: test_credit_engine.py
Description: Unit tests for Engine 15 (Credit Intelligence).
Author: Shantanu Waykar
Version: 1.0.0
"""

import math

import pytest

from project_titan_x.engines.e14_fixed_income.engine import FixedIncomeIntelligenceEngine
from project_titan_x.engines.e15_credit.engine import (
    CORPORATE_RECOVERY_RATE,
    SOVEREIGN_RECOVERY_RATE,
    CreditIntelligenceEngine,
)


@pytest.fixture
def engine() -> CreditIntelligenceEngine:
    e = CreditIntelligenceEngine()
    e.initialize()
    return e


def test_health_check(engine):
    assert engine.health_check().success


def test_shares_fixed_income_engine_when_injected():
    fi_engine = FixedIncomeIntelligenceEngine()
    engine = CreditIntelligenceEngine(fixed_income_engine=fi_engine)
    assert engine._fixed_income_engine is fi_engine


def test_defaults_to_real_fixed_income_engine_when_not_injected(engine):
    assert isinstance(engine._fixed_income_engine, FixedIncomeIntelligenceEngine)


# ---- _classify_spread (pure function, no network) ----


def test_classify_spread_tight(engine):
    assert engine._classify_spread(100.0, tight_bps=250.0, wide_bps=500.0) == "tight"


def test_classify_spread_normal(engine):
    assert engine._classify_spread(300.0, tight_bps=250.0, wide_bps=500.0) == "normal"


def test_classify_spread_wide(engine):
    assert engine._classify_spread(600.0, tight_bps=250.0, wide_bps=500.0) == "wide"


def test_classify_spread_unavailable_without_value(engine):
    assert engine._classify_spread(None, tight_bps=250.0, wide_bps=500.0) == "unavailable"


# ---- _default_probability (pure function, no network) ----


def test_default_probability_formula_is_correct(engine):
    """hazard = spread / (1 - recovery); PD = 1 - exp(-hazard). Verify the
    exact math independently, not just that SOME number comes back."""
    result = engine._default_probability("corporate_ig", spread_bps=100.0, recovery_rate=0.40)
    expected_hazard = (100.0 / 10000) / (1 - 0.40)
    expected_pd = 1 - math.exp(-expected_hazard)
    assert result.implied_hazard_rate_pct == pytest.approx(expected_hazard * 100, abs=0.001)
    assert result.implied_1yr_default_probability_pct == pytest.approx(expected_pd * 100, abs=0.001)


def test_default_probability_5yr_uses_same_hazard_rate(engine):
    """5yr cumulative PD = 1 - exp(-hazard * 5), same constant hazard rate
    as the 1yr figure (flat hazard curve assumption) -- verify the exact
    math, and that it's strictly greater than the 1yr figure (cumulative
    default probability only grows with the observation horizon)."""
    result = engine._default_probability("corporate_hy", spread_bps=300.0, recovery_rate=0.40)
    expected_hazard = (300.0 / 10000) / (1 - 0.40)
    expected_pd_5yr = 1 - math.exp(-expected_hazard * 5)
    assert result.implied_5yr_default_probability_pct == pytest.approx(expected_pd_5yr * 100, abs=0.001)
    assert result.implied_5yr_default_probability_pct > result.implied_1yr_default_probability_pct


def test_default_probability_higher_spread_means_higher_pd(engine):
    low = engine._default_probability("sovereign", spread_bps=100.0, recovery_rate=0.25)
    high = engine._default_probability("sovereign", spread_bps=500.0, recovery_rate=0.25)
    assert high.implied_1yr_default_probability_pct > low.implied_1yr_default_probability_pct


def test_default_probability_higher_recovery_means_higher_pd(engine):
    """Same spread, higher recovery rate assumption -> higher implied PD:
    hazard = spread / (1 - recovery), so assuming a SMALLER loss given
    default (higher recovery) requires the model to infer a HIGHER default
    frequency to explain the SAME market-observed spread (expected loss =
    PD x LGD is held fixed by the market price; shrink LGD and PD must
    rise to compensate)."""
    high_recovery = engine._default_probability("x", spread_bps=200.0, recovery_rate=0.60)
    low_recovery = engine._default_probability("x", spread_bps=200.0, recovery_rate=0.10)
    assert high_recovery.implied_1yr_default_probability_pct > low_recovery.implied_1yr_default_probability_pct


def test_recovery_rate_conventions_are_distinct():
    """Sovereign and corporate use different, documented convention
    recovery rates -- not accidentally the same constant."""
    assert CORPORATE_RECOVERY_RATE != SOVEREIGN_RECOVERY_RATE
    assert CORPORATE_RECOVERY_RATE == 0.40
    assert SOVEREIGN_RECOVERY_RATE == 0.25


# ---- analyze() against REAL yfinance + REAL FixedIncomeIntelligenceEngine + REAL QuantResearchEngine ----


@pytest.mark.network
def test_analyze_returns_sovereign_credit_and_default_probabilities(engine):
    result = engine.analyze()
    assert result.success
    snapshot = result.data
    assert snapshot.sovereign_credit is not None
    assert snapshot.sovereign_credit.spread_pct is not None
    # At minimum, sovereign PD must be present; corporate PDs depend on the
    # real, live e14_fixed_income read succeeding.
    sources = {dp.source for dp in snapshot.default_probabilities}
    assert "sovereign" in sources


@pytest.mark.network
def test_analyze_sovereign_spread_is_real_and_positive(engine):
    """EM sovereign debt should yield more than a Treasury benchmark -- a
    real, well-established market fact, not something that could flip
    sign without a real computation bug."""
    result = engine.analyze()
    assert result.success
    spread = result.data.sovereign_credit
    if spread and spread.spread_pct is not None:
        assert spread.spread_pct > 0


@pytest.mark.network
def test_analyze_uses_real_fixed_income_engine_not_a_stub(engine):
    """Confirms e14_fixed_income is REALLY invoked -- the corporate PD
    entries must trace back to a real, independently-verifiable
    e14_fixed_income.analyze() call."""
    fi_result = engine._fixed_income_engine.analyze()
    assert fi_result.success
    result = engine.analyze()
    assert result.success
    if fi_result.data.credit_spread and fi_result.data.credit_spread.ig_spread_pct is not None:
        ig_pd = next(dp for dp in result.data.default_probabilities if dp.source == "corporate_ig")
        assert ig_pd.spread_pct == fi_result.data.credit_spread.ig_spread_pct


@pytest.mark.network
def test_analyze_credit_stress_uses_real_baseline_when_present(engine):
    result = engine.analyze()
    assert result.success
    stress = result.data.sovereign_credit_stress
    assert stress is not None
    if stress.baseline_correlation is not None:
        assert stress.regime in ("intact", "weakening", "breaking_down", "inverted")
        assert -1.0 <= stress.current_correlation <= 1.0


def test_analyze_notes_include_cds_and_no_equities_gaps(engine):
    result = engine.analyze()
    assert result.success
    joined = " ".join(result.data.notes).lower()
    assert "cds" in joined
    assert "equities" in joined or "equity" in joined


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
    from project_titan_x.engines.e15_credit.engine import SovereignCreditResult, SovereignCreditStressResult

    spread = SovereignCreditResult(spread_pct=600.0, regime="wide")
    stress = SovereignCreditStressResult(0.5, 0.1, 0.4, "breaking_down")
    assert engine._build_knowledge_context(spread, stress) is None


def test_build_knowledge_context_none_when_nothing_notable(tmp_path):
    from project_titan_x.engines.e15_credit.engine import SovereignCreditResult, SovereignCreditStressResult

    knowledge_engine = _real_knowledge_engine(
        tmp_path, "Chapter 1: Sovereign Debt\n\nSovereign credit spreads reflect default risk perceptions.",
    )
    engine = CreditIntelligenceEngine(knowledge_engine=knowledge_engine)
    engine.initialize()
    spread = SovereignCreditResult(spread_pct=350.0, regime="normal")
    stress = SovereignCreditStressResult(0.0, 0.0, 0.0, "intact")
    assert engine._build_knowledge_context(spread, stress) is None


def test_build_knowledge_context_returns_results_when_spread_notable(tmp_path):
    from project_titan_x.engines.e15_credit.engine import SovereignCreditResult, SovereignCreditStressResult

    knowledge_engine = _real_knowledge_engine(
        tmp_path,
        "Chapter 1: Emerging Market Sovereign Debt\n\nA sharply widening emerging market "
        "sovereign credit spread signals rising perceived default risk, often ahead of an "
        "actual restructuring or default event.",
    )
    engine = CreditIntelligenceEngine(knowledge_engine=knowledge_engine)
    engine.initialize()
    spread = SovereignCreditResult(spread_pct=700.0, regime="wide")
    stress = SovereignCreditStressResult(0.0, 0.0, 0.0, "intact")
    context = engine._build_knowledge_context(spread, stress)
    assert context is not None
    assert context["results"]
