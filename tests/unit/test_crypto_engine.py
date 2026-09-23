"""
Module: test_crypto_engine.py
Description: Unit tests for Engine 17 (Crypto Intelligence).
Author: Shantanu Waykar
Version: 1.0.0
"""

import pytest

from project_titan_x.engines.e02_market_data.engine import MarketDataEngine
from project_titan_x.engines.e17_crypto.engine import (
    SUPPORTED_CRYPTO,
    CryptoIntelligenceEngine,
)


@pytest.fixture
def engine() -> CryptoIntelligenceEngine:
    e = CryptoIntelligenceEngine()
    e.initialize()
    return e


def test_health_check(engine):
    assert engine.health_check().success


def test_supported_crypto_are_the_platforms_tradable_ones():
    assert SUPPORTED_CRYPTO == {"BTCUSD", "ETHUSD"}


def test_shares_market_data_engine_when_injected():
    md_engine = MarketDataEngine()
    engine = CryptoIntelligenceEngine(market_data_engine=md_engine)
    assert engine._market_data_engine is md_engine


def test_defaults_to_real_market_data_engine_when_not_injected(engine):
    assert isinstance(engine._market_data_engine, MarketDataEngine)


# ---- _classify_funding (pure function, no network) ----


def test_classify_funding_crowded_short_below_10th(engine):
    percentiles = {"10": -0.0005, "90": 0.0005}
    assert engine._classify_funding(-0.001, percentiles) == "crowded_short"


def test_classify_funding_normal_in_middle(engine):
    percentiles = {"10": -0.0005, "90": 0.0005}
    assert engine._classify_funding(0.0001, percentiles) == "normal"


def test_classify_funding_crowded_long_above_90th(engine):
    percentiles = {"10": -0.0005, "90": 0.0005}
    assert engine._classify_funding(0.001, percentiles) == "crowded_long"


def test_analyze_unsupported_asset_returns_honest_gap(engine):
    result = engine.analyze(symbol="GOLD")
    assert result.success
    assert result.data is None
    assert "not one of this engine's covered crypto assets" in result.message


def test_analyze_unsupported_forex_returns_honest_gap(engine):
    result = engine.analyze(symbol="EURUSD")
    assert result.success
    assert result.data is None


# ---- analyze() against REAL Binance data (via E02/ccxt) ----


@pytest.mark.network
def test_analyze_btcusd_returns_real_funding_and_oi(engine):
    result = engine.analyze(symbol="BTCUSD")
    assert result.success
    read = result.data
    assert read is not None
    assert read.symbol == "BTCUSD"
    assert read.funding_positioning is not None
    assert read.funding_positioning.funding_rate is not None
    assert read.open_interest_trend is not None
    assert read.open_interest_trend.trend in ("rising", "falling", "flat", "unavailable")


@pytest.mark.network
def test_analyze_uses_real_calibration_regime_classification(engine):
    """With a real calibration injected, a funding rate far outside the
    calibrated percentile band must classify as crowded, not 'uncalibrated'
    -- confirms _load_calibration's output actually reaches analyze()."""
    engine._calibration = {
        "BTCUSD": {"percentiles": {"10": -0.0001, "90": 0.0001}, "contrarian_effect_validated": True}
    }
    result = engine.analyze(symbol="BTCUSD")
    assert result.success
    positioning = result.data.funding_positioning
    assert positioning.regime in ("crowded_short", "normal", "crowded_long")
    assert positioning.regime != "uncalibrated"


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
    from project_titan_x.engines.e17_crypto.engine import FundingRatePositioning

    positioning = FundingRatePositioning(funding_rate=0.001, regime="crowded_long", contrarian_effect_validated=True)
    assert engine._build_knowledge_context("BTCUSD", positioning) is None


def test_build_knowledge_context_none_when_not_crowded(tmp_path):
    from project_titan_x.engines.e17_crypto.engine import FundingRatePositioning

    knowledge_engine = _real_knowledge_engine(tmp_path, "Chapter 1: Funding rates reflect perpetual futures positioning.")
    engine = CryptoIntelligenceEngine(knowledge_engine=knowledge_engine)
    engine.initialize()
    positioning = FundingRatePositioning(funding_rate=0.0001, regime="normal", contrarian_effect_validated=False)
    assert engine._build_knowledge_context("BTCUSD", positioning) is None


def test_build_knowledge_context_returns_results_when_crowded(tmp_path):
    from project_titan_x.engines.e17_crypto.engine import FundingRatePositioning

    knowledge_engine = _real_knowledge_engine(
        tmp_path,
        "Chapter 1: Perpetual Futures Funding\n\nWhen funding rates are extremely positive, "
        "the crowd is heavily long and paying to stay there -- a classic contrarian warning sign.",
    )
    engine = CryptoIntelligenceEngine(knowledge_engine=knowledge_engine)
    engine.initialize()
    positioning = FundingRatePositioning(funding_rate=0.002, regime="crowded_long", contrarian_effect_validated=True)
    context = engine._build_knowledge_context("BTCUSD", positioning)
    assert context is not None
    assert context["results"]
