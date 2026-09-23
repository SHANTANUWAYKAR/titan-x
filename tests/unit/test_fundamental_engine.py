"""
Module: test_fundamental_engine.py
Description: Unit tests for Fundamental Analysis Engine (E05, adapted scope).
Author: Shantanu Waykar
Version: 1.0.0
"""

import pandas as pd
import pytest

from project_titan_x.engines import e06_fundamental
from project_titan_x.engines.e06_fundamental import FundamentalAnalysisEngine
from project_titan_x.engines.e06_fundamental.engine import (
    BRENT_TICKER,
    TIPS_ETF_TICKER,
    WTI_TICKER,
    YIELD_TICKERS,
    relevance_for_symbol,
)


@pytest.fixture
def fundamental_engine() -> FundamentalAnalysisEngine:
    engine = FundamentalAnalysisEngine()
    engine.initialize()
    return engine


class _FakeTicker:
    def __init__(self, closes: list[float]):
        self._closes = closes

    def history(self, period: str = "5d"):
        if not self._closes:
            return pd.DataFrame()
        return pd.DataFrame({"Close": self._closes})


def _patch_yf(monkeypatch, price_map: dict):
    """price_map: {ticker: [closes...]} -- last element is "current"."""

    def fake_ticker(ticker: str):
        return _FakeTicker(price_map.get(ticker, []))

    monkeypatch.setattr(e06_fundamental.engine.yf, "Ticker", fake_ticker)


def test_engine_initialization(fundamental_engine):
    info = fundamental_engine.get_info()
    assert info["engine_id"] == "e06_fundamental"
    assert info["status"] == "idle"


def test_health_check_reports_unhealthy_on_empty_data(fundamental_engine, monkeypatch):
    _patch_yf(monkeypatch, {})
    result = fundamental_engine.health_check()
    assert not result.success


def test_health_check_healthy_when_data_available(fundamental_engine, monkeypatch):
    _patch_yf(monkeypatch, {YIELD_TICKERS["10y"]: [4.5]})
    result = fundamental_engine.health_check()
    assert result.success


# ---- Yield curve ----


def test_yield_curve_detects_inversion(fundamental_engine, monkeypatch):
    _patch_yf(monkeypatch, {
        YIELD_TICKERS["3m"]: [5.2],
        YIELD_TICKERS["5y"]: [4.0],
        YIELD_TICKERS["10y"]: [3.9],
        YIELD_TICKERS["30y"]: [4.1],
        TIPS_ETF_TICKER: [],
        WTI_TICKER: [],
        BRENT_TICKER: [],
    })
    result = fundamental_engine.analyze()
    assert result.success
    yc = result.data.yield_curve
    assert yc is not None
    assert yc.inverted is True
    assert yc.shape == "inverted"
    assert yc.slope_10y_3m_pct == pytest.approx(3.9 - 5.2, abs=0.001)


def test_yield_curve_detects_normal_shape(fundamental_engine, monkeypatch):
    _patch_yf(monkeypatch, {
        YIELD_TICKERS["3m"]: [3.7],
        YIELD_TICKERS["5y"]: [4.3],
        YIELD_TICKERS["10y"]: [4.6],
        YIELD_TICKERS["30y"]: [5.0],
        TIPS_ETF_TICKER: [],
        WTI_TICKER: [],
        BRENT_TICKER: [],
    })
    result = fundamental_engine.analyze()
    assert result.success
    yc = result.data.yield_curve
    assert yc.shape == "normal"
    assert yc.inverted is False


def test_yield_curve_unavailable_returns_none(fundamental_engine, monkeypatch):
    _patch_yf(monkeypatch, {TIPS_ETF_TICKER: [], WTI_TICKER: [], BRENT_TICKER: []})
    result = fundamental_engine.analyze()
    # No yield data, no TIPS, no crude -> nothing at all -> failure
    assert not result.success


# ---- Real yield / TIPS proxy ----


def test_real_yield_falling_is_bullish_for_metals(fundamental_engine, monkeypatch):
    closes = [100.0] * 40 + [103.0]  # up >1% over 20d window at the tail
    _patch_yf(monkeypatch, {
        YIELD_TICKERS["3m"]: [], YIELD_TICKERS["5y"]: [], YIELD_TICKERS["10y"]: [], YIELD_TICKERS["30y"]: [],
        TIPS_ETF_TICKER: closes,
        WTI_TICKER: [], BRENT_TICKER: [],
    })
    result = fundamental_engine.analyze()
    assert result.success
    ry = result.data.real_yield
    assert ry is not None
    assert ry.real_yield_direction == "falling"
    assert ry.precious_metals_bias == "bullish"


def test_real_yield_rising_is_bearish_for_metals(fundamental_engine, monkeypatch):
    closes = [100.0] * 40 + [97.0]  # down >1%
    _patch_yf(monkeypatch, {
        YIELD_TICKERS["3m"]: [], YIELD_TICKERS["5y"]: [], YIELD_TICKERS["10y"]: [], YIELD_TICKERS["30y"]: [],
        TIPS_ETF_TICKER: closes,
        WTI_TICKER: [], BRENT_TICKER: [],
    })
    result = fundamental_engine.analyze()
    assert result.success
    ry = result.data.real_yield
    assert ry.real_yield_direction == "rising"
    assert ry.precious_metals_bias == "bearish"


def test_real_yield_insufficient_history_returns_none(fundamental_engine, monkeypatch):
    _patch_yf(monkeypatch, {
        # Give the yield curve valid data so overall analyze() still
        # succeeds -- this test isolates real_yield's OWN "too short" guard,
        # not the "every source failed" case (covered separately above).
        YIELD_TICKERS["3m"]: [4.0], YIELD_TICKERS["5y"]: [4.0], YIELD_TICKERS["10y"]: [4.0], YIELD_TICKERS["30y"]: [4.0],
        TIPS_ETF_TICKER: [100.0, 101.0],  # too short
        WTI_TICKER: [], BRENT_TICKER: [],
    })
    result = fundamental_engine.analyze()
    assert result.success
    assert result.data.real_yield is None


# ---- Crude oil ----


def test_crude_oil_normal_brent_premium(fundamental_engine, monkeypatch):
    _patch_yf(monkeypatch, {
        YIELD_TICKERS["3m"]: [], YIELD_TICKERS["5y"]: [], YIELD_TICKERS["10y"]: [], YIELD_TICKERS["30y"]: [],
        TIPS_ETF_TICKER: [],
        WTI_TICKER: [75.0],
        BRENT_TICKER: [78.0],  # ~4% premium, within norm
    })
    result = fundamental_engine.analyze()
    assert result.success
    c = result.data.crude_oil
    assert c is not None
    assert c.regime == "normal_brent_premium"
    assert c.spread == pytest.approx(3.0, abs=0.01)


def test_crude_oil_wide_brent_premium(fundamental_engine, monkeypatch):
    _patch_yf(monkeypatch, {
        YIELD_TICKERS["3m"]: [], YIELD_TICKERS["5y"]: [], YIELD_TICKERS["10y"]: [], YIELD_TICKERS["30y"]: [],
        TIPS_ETF_TICKER: [],
        WTI_TICKER: [60.0],
        BRENT_TICKER: [70.0],  # ~16.7% premium, well above norm
    })
    result = fundamental_engine.analyze()
    assert result.success
    assert result.data.crude_oil.regime == "wide_brent_premium"


def test_crude_oil_wti_premium_is_unusual(fundamental_engine, monkeypatch):
    _patch_yf(monkeypatch, {
        YIELD_TICKERS["3m"]: [], YIELD_TICKERS["5y"]: [], YIELD_TICKERS["10y"]: [], YIELD_TICKERS["30y"]: [],
        TIPS_ETF_TICKER: [],
        WTI_TICKER: [80.0],
        BRENT_TICKER: [78.0],  # WTI above Brent -- unusual
    })
    result = fundamental_engine.analyze()
    assert result.success
    assert result.data.crude_oil.regime == "wti_premium_unusual"


def test_coverage_notes_always_present(fundamental_engine, monkeypatch):
    _patch_yf(monkeypatch, {
        YIELD_TICKERS["3m"]: [4.0], YIELD_TICKERS["5y"]: [4.0], YIELD_TICKERS["10y"]: [4.0], YIELD_TICKERS["30y"]: [4.0],
        TIPS_ETF_TICKER: [], WTI_TICKER: [], BRENT_TICKER: [],
    })
    result = fundamental_engine.analyze()
    assert result.success
    notes = " ".join(result.data.coverage_notes)
    assert "equity" in notes.lower()
    assert "crypto" in notes.lower()
    assert "sovereign bond" in notes.lower() or "foreign" in notes.lower()


# ---- relevance_for_symbol: honesty check -- no fabricated applicability ----


@pytest.mark.parametrize("symbol", ["GOLD", "gold", "SILVER"])
def test_relevance_precious_metals_get_real_yield(symbol):
    r = relevance_for_symbol(symbol)
    assert r["yield_curve_relevant"] is True
    assert r["real_yield_relevant"] is True
    assert r["crude_oil_relevant"] is False


def test_relevance_crude_gets_wti_brent_only():
    r = relevance_for_symbol("CRUDE")
    assert r["yield_curve_relevant"] is True
    assert r["real_yield_relevant"] is False
    assert r["crude_oil_relevant"] is True


@pytest.mark.parametrize("symbol", ["EURUSD", "GBPUSD", "USDJPY", "USDINR", "BTCUSD", "ETHUSD", "NIFTY50", "BANKNIFTY"])
def test_relevance_forex_crypto_indices_get_no_asset_specific_driver(symbol):
    r = relevance_for_symbol(symbol)
    assert r["yield_curve_relevant"] is True  # broad macro backdrop still applies
    assert r["real_yield_relevant"] is False  # not fabricated for a currency/index/crypto
    assert r["crude_oil_relevant"] is False


# ---- EUR yield curve (ECB) ----


class _FakeECBClient:
    def __init__(self, yields: dict):
        self._yields = yields

    def latest_yield(self, tenor, rating="aaa", yield_curve_type="spot_rate"):
        return self._yields.get(tenor)


def test_eur_yield_curve_none_without_ecb_client(fundamental_engine, monkeypatch):
    _patch_yf(monkeypatch, {
        YIELD_TICKERS["3m"]: [4.0], YIELD_TICKERS["5y"]: [4.0], YIELD_TICKERS["10y"]: [4.0], YIELD_TICKERS["30y"]: [4.0],
        TIPS_ETF_TICKER: [], WTI_TICKER: [], BRENT_TICKER: [],
    })
    result = fundamental_engine.analyze()
    assert result.success
    assert result.data.eur_yield_curve is None


def test_eur_yield_curve_detects_inversion_and_differential(monkeypatch):
    engine = FundamentalAnalysisEngine(ecb_client=_FakeECBClient({"3m": 4.5, "2y": 4.0, "5y": 3.8, "10y": 3.7}))
    engine.initialize()
    _patch_yf(monkeypatch, {
        YIELD_TICKERS["3m"]: [5.0], YIELD_TICKERS["5y"]: [4.3], YIELD_TICKERS["10y"]: [4.6], YIELD_TICKERS["30y"]: [5.0],
        TIPS_ETF_TICKER: [], WTI_TICKER: [], BRENT_TICKER: [],
    })
    result = engine.analyze()
    assert result.success
    eyc = result.data.eur_yield_curve
    assert eyc is not None
    assert eyc.inverted is True
    assert eyc.shape == "inverted"
    assert eyc.slope_10y_3m_pct == pytest.approx(3.7 - 4.5, abs=0.001)
    # US 10Y (4.6) - EUR 10Y (3.7) = +0.9, US yields more
    assert eyc.us_eur_10y_differential_pct == pytest.approx(0.9, abs=0.001)


def test_eur_yield_curve_normal_shape_with_no_us_curve_has_no_differential(monkeypatch):
    engine = FundamentalAnalysisEngine(ecb_client=_FakeECBClient({"3m": 3.0, "2y": 3.3, "5y": 3.5, "10y": 3.8}))
    engine.initialize()
    _patch_yf(monkeypatch, {
        # No US yield data at all -- yield_curve will be None.
        TIPS_ETF_TICKER: [], WTI_TICKER: [], BRENT_TICKER: [],
    })
    result = engine.analyze()
    assert result.success
    eyc = result.data.eur_yield_curve
    assert eyc is not None
    assert eyc.shape == "normal"
    assert eyc.us_eur_10y_differential_pct is None


def test_eur_yield_curve_missing_tenor_returns_none(monkeypatch):
    engine = FundamentalAnalysisEngine(ecb_client=_FakeECBClient({"2y": 3.0}))  # no 3m/10y
    engine.initialize()
    _patch_yf(monkeypatch, {
        YIELD_TICKERS["3m"]: [4.0], YIELD_TICKERS["5y"]: [4.0], YIELD_TICKERS["10y"]: [4.0], YIELD_TICKERS["30y"]: [4.0],
        TIPS_ETF_TICKER: [], WTI_TICKER: [], BRENT_TICKER: [],
    })
    result = engine.analyze()
    assert result.success
    assert result.data.eur_yield_curve is None


def test_relevance_eurusd_gets_eur_yield_curve_only():
    r = relevance_for_symbol("EURUSD")
    assert r["eur_yield_curve_relevant"] is True
    assert r["real_yield_relevant"] is False
    assert r["crude_oil_relevant"] is False


@pytest.mark.parametrize("symbol", ["GBPUSD", "USDJPY", "GOLD", "CRUDE", "BTCUSD"])
def test_relevance_non_eurusd_symbols_get_no_eur_yield_curve(symbol):
    r = relevance_for_symbol(symbol)
    assert r["eur_yield_curve_relevant"] is False


@pytest.mark.network
def test_eur_yield_curve_against_real_ecb_data():
    """Live smoke test against the real ECB data-detail-api -- same
    real-collaborator-not-a-stub discipline as test_analyze_against_real_data
    below (Rule 4: at least one test per integration point must use the
    real collaborator)."""
    from project_titan_x.core.data_providers.ecb import ECBClient

    engine = FundamentalAnalysisEngine(ecb_client=ECBClient())
    engine.initialize()
    result = engine.analyze()
    assert result.success
    eyc = result.data.eur_yield_curve
    assert eyc is not None
    assert "3m" in eyc.yields_pct and "10y" in eyc.yields_pct
    assert eyc.shape in ("normal", "flat", "inverted")


@pytest.mark.network
def test_analyze_against_real_data(fundamental_engine):
    """Live smoke test against real Yahoo Finance data -- same convention as
    test_macro_engine.py's test_macro_analyze."""
    result = fundamental_engine.analyze()
    assert result.success
    snapshot = result.data
    assert snapshot.yield_curve is not None or snapshot.real_yield is not None or snapshot.crude_oil is not None


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
def test_analyze_attaches_knowledge_context_when_injected(tmp_path):
    knowledge_engine = _real_knowledge_engine(
        tmp_path,
        "Chapter 1: Yield Curve Inversion\n\nAn inverted yield curve has historically preceded recessions by 6 to 18 months.",
    )
    engine = FundamentalAnalysisEngine(knowledge_engine=knowledge_engine)
    engine.initialize()
    result = engine.analyze()
    assert result.success
    assert result.data.knowledge_context is not None
    assert result.data.knowledge_context["results"]


@pytest.mark.network
def test_analyze_knowledge_context_none_without_engine(fundamental_engine):
    result = fundamental_engine.analyze()
    assert result.success
    assert result.data.knowledge_context is None
