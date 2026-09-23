"""
Module: test_commodity_engine.py
Description: Unit tests for Engine 16 (Commodity Intelligence).
Author: Shantanu Waykar
Version: 1.0.0
"""

import pytest

from project_titan_x.engines.e02_market_data.engine import MarketDataEngine
from project_titan_x.engines.e16_commodity.engine import (
    SUPPORTED_COMMODITIES,
    CommodityIntelligenceEngine,
)


@pytest.fixture
def engine() -> CommodityIntelligenceEngine:
    e = CommodityIntelligenceEngine()
    e.initialize()
    return e


def test_health_check(engine):
    assert engine.health_check().success


def test_supported_commodities_are_the_platforms_tradable_ones():
    assert SUPPORTED_COMMODITIES == {"GOLD", "SILVER", "CRUDE"}


def test_shares_market_data_engine_when_injected():
    md_engine = MarketDataEngine()
    engine = CommodityIntelligenceEngine(market_data_engine=md_engine)
    assert engine._market_data_engine is md_engine


def test_defaults_to_real_market_data_engine_when_not_injected(engine):
    assert isinstance(engine._market_data_engine, MarketDataEngine)


# ---- _classify_positioning (pure function, no network) ----


def test_classify_positioning_extreme_short_below_10th(engine):
    percentiles = {"10": -50.0, "25": -40.0, "75": -10.0, "90": 10.0}
    rank, regime = engine._classify_positioning(-60.0, percentiles)
    assert rank == "below_10th"
    assert regime == "extreme_short"


def test_classify_positioning_normal_in_middle(engine):
    percentiles = {"10": -50.0, "25": -40.0, "75": -10.0, "90": 10.0}
    rank, regime = engine._classify_positioning(-20.0, percentiles)
    assert rank == "25th_75th"
    assert regime == "normal"


def test_classify_positioning_extreme_long_above_90th(engine):
    percentiles = {"10": -50.0, "25": -40.0, "75": -10.0, "90": 10.0}
    rank, regime = engine._classify_positioning(20.0, percentiles)
    assert rank == "above_90th"
    assert regime == "extreme_long"


# ---- analyze() against REAL yfinance + REAL CFTC data (via E02) ----


@pytest.mark.network
def test_analyze_gold_returns_real_data(engine):
    result = engine.analyze(symbol="GOLD")
    assert result.success
    snapshot = result.data
    assert snapshot is not None
    read = snapshot.commodities[0]
    assert read.symbol == "GOLD"
    assert read.seasonality is not None
    assert 1 <= read.seasonality.month <= 12


@pytest.mark.network
def test_analyze_all_three_commodities_return_real_distinct_data(engine):
    """GOLD/SILVER/CRUDE must each resolve to their OWN distinct live
    positioning read, not accidentally share/duplicate one result."""
    reads = {}
    for symbol in ("GOLD", "SILVER", "CRUDE"):
        result = engine.analyze(symbol=symbol)
        assert result.success
        reads[symbol] = result.data.commodities[0]
    positioning_values = [
        r.commercial_positioning.net_positioning_pct
        for r in reads.values()
        if r.commercial_positioning and r.commercial_positioning.net_positioning_pct is not None
    ]
    assert len(set(positioning_values)) == len(positioning_values)  # all distinct


@pytest.mark.network
def test_analyze_uses_calibrated_seasonality_when_present(engine):
    """With a real (non-empty) calibration injected, the current month
    must resolve to real calibrated values, not None -- confirms
    _load_calibration's output actually reaches analyze()."""
    engine._calibration = {
        "GOLD": {"seasonality": {"1": {"mean_return_pct": 3.0, "p_value": 0.004, "n_years": 26, "significant": True, "direction": "bullish"}}}
    }
    from datetime import datetime, timezone
    result = engine.analyze(symbol="GOLD", reference=datetime(2026, 1, 15, tzinfo=timezone.utc))
    assert result.success
    seasonality = result.data.commodities[0].seasonality
    assert seasonality.significant is True
    assert seasonality.mean_return_pct == 3.0


def test_analyze_unsupported_commodity_returns_honest_gap(engine):
    result = engine.analyze(symbol="EURUSD")
    assert result.success
    assert result.data is None
    assert "not one of this engine's covered commodities" in result.message


def test_analyze_index_returns_honest_gap(engine):
    result = engine.analyze(symbol="NIFTY50")
    assert result.success
    assert result.data is None


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
    from project_titan_x.engines.e16_commodity.engine import CommercialPositioningResult, SeasonalityResult

    seasonality = SeasonalityResult(month=1, month_name="January", mean_return_pct=3.0, p_value=0.004, n_years=26, significant=True, direction="bullish")
    positioning = CommercialPositioningResult(net_positioning_pct=-60.0, percentile_rank="below_10th", regime="extreme_short")
    assert engine._build_knowledge_context("GOLD", seasonality, positioning) is None


def test_build_knowledge_context_none_when_nothing_notable(tmp_path):
    from project_titan_x.engines.e16_commodity.engine import CommercialPositioningResult, SeasonalityResult

    knowledge_engine = _real_knowledge_engine(
        tmp_path, "Chapter 1: Commodities\n\nSeasonality reflects recurring supply-demand patterns.",
    )
    engine = CommodityIntelligenceEngine(knowledge_engine=knowledge_engine)
    engine.initialize()
    seasonality = SeasonalityResult(month=3, month_name="March", mean_return_pct=0.3, p_value=0.7, n_years=26, significant=False, direction="neutral")
    positioning = CommercialPositioningResult(net_positioning_pct=-30.0, percentile_rank="25th_75th", regime="normal")
    assert engine._build_knowledge_context("GOLD", seasonality, positioning) is None


def test_build_knowledge_context_returns_results_when_seasonality_significant(tmp_path):
    from project_titan_x.engines.e16_commodity.engine import CommercialPositioningResult, SeasonalityResult

    knowledge_engine = _real_knowledge_engine(
        tmp_path,
        "Chapter 1: Gold Seasonality\n\nGold has historically shown strength in January, often "
        "attributed to renewed investment demand and portfolio rebalancing at the start of the year.",
    )
    engine = CommodityIntelligenceEngine(knowledge_engine=knowledge_engine)
    engine.initialize()
    seasonality = SeasonalityResult(month=1, month_name="January", mean_return_pct=3.0, p_value=0.004, n_years=26, significant=True, direction="bullish")
    positioning = CommercialPositioningResult(net_positioning_pct=-30.0, percentile_rank="25th_75th", regime="normal")
    context = engine._build_knowledge_context("GOLD", seasonality, positioning)
    assert context is not None
    assert context["results"]


def test_build_knowledge_context_returns_results_when_positioning_extreme(tmp_path):
    from project_titan_x.engines.e16_commodity.engine import CommercialPositioningResult, SeasonalityResult

    knowledge_engine = _real_knowledge_engine(
        tmp_path,
        "Chapter 1: Commitment of Traders\n\nExtreme commercial hedger positioning often precedes "
        "a reversal, as producers are typically well-informed about supply-demand fundamentals.",
    )
    engine = CommodityIntelligenceEngine(knowledge_engine=knowledge_engine)
    engine.initialize()
    seasonality = SeasonalityResult(month=3, month_name="March", mean_return_pct=0.3, p_value=0.7, n_years=26, significant=False, direction="neutral")
    positioning = CommercialPositioningResult(net_positioning_pct=-60.0, percentile_rank="below_10th", regime="extreme_short")
    context = engine._build_knowledge_context("GOLD", seasonality, positioning)
    assert context is not None
    assert context["results"]
