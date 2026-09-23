"""
Module: test_derivatives_engine.py
Description: Unit tests for Engine 13 (Derivatives Intelligence).
Author: Shantanu Waykar
Version: 1.0.0
"""

from datetime import datetime, timedelta, timezone

import pytest

from project_titan_x.engines.e13_derivatives.engine import (
    DerivativesIntelligenceEngine,
    _parse_instrument,
)


@pytest.fixture
def engine() -> DerivativesIntelligenceEngine:
    e = DerivativesIntelligenceEngine()
    e.initialize()
    return e


# ---- _parse_instrument (pure function, no network) ----


def test_parse_instrument_call():
    result = _parse_instrument("BTC-16JUL26-56000-C")
    assert result is not None
    expiry, strike, option_type = result
    # Deribit options settle at 08:00 UTC on the expiry date, not midnight
    # (real bug fixed 2026-08-02, see _parse_instrument's own docstring).
    assert expiry == datetime(2026, 7, 16, 8, 0, tzinfo=timezone.utc)
    assert strike == 56000.0
    assert option_type == "C"


def test_parse_instrument_put():
    result = _parse_instrument("ETH-25SEP26-16000-P")
    assert result is not None
    expiry, strike, option_type = result
    assert expiry == datetime(2026, 9, 25, 8, 0, tzinfo=timezone.utc)
    assert strike == 16000.0
    assert option_type == "P"


def test_parse_instrument_rejects_malformed_name():
    assert _parse_instrument("BTC-PERPETUAL") is None
    assert _parse_instrument("BTC-16JUL26-56000-X") is None
    assert _parse_instrument("not-a-valid-name-at-all-either") is None


# ---- _compute_skew (pure function, no network) ----


def test_compute_skew_put_skew_when_otm_put_iv_higher(engine):
    now = datetime.now(timezone.utc)
    expiry = now
    parsed = [
        {"expiry": expiry, "strike": 90.0, "type": "P", "mark_iv": 60.0, "open_interest": 1, "volume": 1, "instrument_name": "X-P"},
        {"expiry": expiry, "strike": 110.0, "type": "C", "mark_iv": 50.0, "open_interest": 1, "volume": 1, "instrument_name": "X-C"},
    ]
    skew, label = engine._compute_skew(parsed, spot_price=100.0, nearest_expiry=expiry)
    assert skew == pytest.approx(10.0)
    assert label == "put_skew"


def test_compute_skew_call_skew_when_otm_call_iv_higher(engine):
    now = datetime.now(timezone.utc)
    expiry = now
    parsed = [
        {"expiry": expiry, "strike": 90.0, "type": "P", "mark_iv": 40.0, "open_interest": 1, "volume": 1, "instrument_name": "X-P"},
        {"expiry": expiry, "strike": 110.0, "type": "C", "mark_iv": 55.0, "open_interest": 1, "volume": 1, "instrument_name": "X-C"},
    ]
    skew, label = engine._compute_skew(parsed, spot_price=100.0, nearest_expiry=expiry)
    assert skew == pytest.approx(-15.0)
    assert label == "call_skew"


def test_compute_skew_flat_when_within_threshold(engine):
    now = datetime.now(timezone.utc)
    expiry = now
    parsed = [
        {"expiry": expiry, "strike": 90.0, "type": "P", "mark_iv": 50.0, "open_interest": 1, "volume": 1, "instrument_name": "X-P"},
        {"expiry": expiry, "strike": 110.0, "type": "C", "mark_iv": 51.0, "open_interest": 1, "volume": 1, "instrument_name": "X-C"},
    ]
    skew, label = engine._compute_skew(parsed, spot_price=100.0, nearest_expiry=expiry)
    assert label == "flat"


def test_compute_skew_unavailable_without_expiry(engine):
    skew, label = engine._compute_skew([], spot_price=100.0, nearest_expiry=None)
    assert skew is None
    assert label == "unavailable"


def test_compute_skew_unavailable_when_only_one_side_present(engine):
    now = datetime.now(timezone.utc)
    parsed = [{"expiry": now, "strike": 90.0, "type": "P", "mark_iv": 50.0, "open_interest": 1, "volume": 1, "instrument_name": "X-P"}]
    skew, label = engine._compute_skew(parsed, spot_price=100.0, nearest_expiry=now)
    assert skew is None
    assert label == "unavailable"


def test_health_check(engine):
    assert engine.health_check().success


# ---- analyze() against REAL Deribit API (not mocked) ----


@pytest.mark.network
def test_analyze_btc_returns_real_data(engine):
    result = engine.analyze(symbol="BTCUSD")
    assert result.success
    snapshot = result.data
    assert snapshot is not None
    assert snapshot.currency == "BTC"
    assert snapshot.spot_price > 0
    assert snapshot.put_call_ratio_oi == snapshot.put_call_ratio_oi  # not NaN
    assert snapshot.term_structure
    assert snapshot.skew_label in ("put_skew", "call_skew", "flat", "unavailable")


@pytest.mark.network
def test_analyze_eth_returns_real_data(engine):
    result = engine.analyze(symbol="ETHUSD")
    assert result.success
    snapshot = result.data
    assert snapshot is not None
    assert snapshot.currency == "ETH"
    assert snapshot.spot_price > 0


@pytest.mark.network
def test_analyze_btc_and_eth_are_genuinely_different_markets(engine):
    """BTC and ETH must resolve to their OWN distinct live option chains,
    not accidentally share cached/duplicated data."""
    btc = engine.analyze(symbol="BTCUSD").data
    eth = engine.analyze(symbol="ETHUSD").data
    assert btc.spot_price != eth.spot_price
    assert btc.currency != eth.currency


@pytest.mark.network
def test_analyze_atm_greeks_are_real_when_available(engine):
    result = engine.analyze(symbol="BTCUSD")
    assert result.success
    greeks = result.data.atm_greeks
    if greeks:  # best-effort -- absent only if Deribit's ticker calls fail
        assert "call" in greeks or "put" in greeks
        for side in ("call", "put"):
            if side in greeks:
                assert -1.5 <= greeks[side]["delta"] <= 1.5


def test_analyze_unsupported_asset_returns_honest_gap(engine):
    result = engine.analyze(symbol="GOLD")
    assert result.success
    assert result.data is None
    assert "no free options data" in result.message.lower()


def test_analyze_forex_returns_honest_gap(engine):
    result = engine.analyze(symbol="EURUSD")
    assert result.success
    assert result.data is None


# ---- analyze_index_option_chain() -- added 2026-08-21, real Kite Connect
# NIFTY/BANKNIFTY option chain. Uses a fake client (no live credentials
# available) mirroring the interface's real shape, same pattern this file
# already uses for the network-marked-vs-not split above. ----


def _expiry_in_days(days: int = 7) -> str:
    """Expiry relative to TODAY, shared by the fake instrument dump and
    the tests that request it.

    Both sides must derive from the same helper. This file previously
    hardcoded "2026-08-27" in three places; when that date arrived, the
    option had zero time value, Black-Scholes could not invert for IV, and
    the test failed with nothing wrong in the engine. Deriving the date
    keeps the "7 days to expiry" premise true on any future run, and
    keeps the requested expiry matching the instruments on offer.
    """
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d")


class _FakeKiteClient:
    """Matches KiteConnectClient's public surface without a real network
    call -- returns fixed synthetic instrument/quote data."""

    is_configured = True

    def get_instruments(self, exchange=None):
        import pandas as pd
        expiry = _expiry_in_days(7)
        return pd.DataFrame([
            {"tradingsymbol": "NIFTY24AUG18000CE", "name": "NIFTY", "expiry": expiry, "strike": 18000.0, "instrument_type": "CE"},
            {"tradingsymbol": "NIFTY24AUG18000PE", "name": "NIFTY", "expiry": expiry, "strike": 18000.0, "instrument_type": "PE"},
        ])

    def get_quote(self, instruments):
        data = {"NSE:NIFTY 50": {"last_price": 18050.0}}
        if "NFO:NIFTY24AUG18000CE" in instruments:
            data["NFO:NIFTY24AUG18000CE"] = {"last_price": 120.0, "oi": 50000}
        if "NFO:NIFTY24AUG18000PE" in instruments:
            data["NFO:NIFTY24AUG18000PE"] = {"last_price": 95.0, "oi": 42000}
        return data


class _NotConfiguredKiteClient:
    is_configured = False


def test_analyze_index_option_chain_not_configured_returns_honest_gap(engine):
    engine._kite = _NotConfiguredKiteClient()
    result = engine.analyze_index_option_chain("NIFTY50")
    assert result.success
    assert result.data is None
    assert "not configured" in result.message.lower()


def test_analyze_index_option_chain_unsupported_symbol_returns_honest_gap(engine):
    result = engine.analyze_index_option_chain("RELIANCE")
    assert result.success
    assert result.data is None
    assert "no indian index option-chain support" in result.message.lower()


def test_analyze_index_option_chain_returns_real_synthetic_snapshot(engine):
    """Expiry is computed RELATIVE to today, never hardcoded.

    This test previously passed expiry="2026-08-27" with a comment saying
    "7 days to expiry" -- true only on the day it was written. On
    2026-08-27 the date arrived, time-to-expiry became zero, and the
    Black-Scholes IV inversion correctly failed to solve an option with no
    time value. The engine was fine; the test had a built-in expiry date.
    A relative expiry keeps the 7-day premise true on every future run.
    """
    engine._kite = _FakeKiteClient()
    result = engine.analyze_index_option_chain("NIFTY50", expiry=_expiry_in_days(7))
    assert result.success
    snapshot = result.data
    assert snapshot is not None
    assert snapshot.underlying_symbol == "NIFTY50"
    assert snapshot.spot_price == 18050.0
    assert len(snapshot.rows) == 1
    row = snapshot.rows[0]
    assert row.strike == 18000.0
    assert row.ce_ltp == 120.0
    assert row.ce_oi == 50000
    assert row.pe_ltp == 95.0
    # Real spot (18050) is close to strike (18000) with 7 days to expiry
    # and a nonzero premium -- Black-Scholes IV inversion should succeed,
    # not silently fail, on this plausible synthetic price.
    assert row.ce_iv is not None
    assert row.ce_greeks is not None


def test_analyze_index_option_chain_defaults_to_nearest_live_expiry(engine):
    """No expiry passed -- must discover it from the fake instrument dump
    rather than requiring the caller to know it in advance."""
    engine._kite = _FakeKiteClient()
    result = engine.analyze_index_option_chain("NIFTY50")
    assert result.success
    # Same helper the fake dump derives its expiry from -- asserting a
    # literal date here is what made the sibling test expire on 2026-08-27.
    assert result.data.expiry.isoformat() == _expiry_in_days(7)


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
    assert engine._build_knowledge_context("BTC", "put_skew", 1.5, "average") is None


def test_build_knowledge_context_none_when_nothing_notable(tmp_path):
    knowledge_engine = _real_knowledge_engine(
        tmp_path, "Chapter 1: Options\n\nPut skew reflects downside hedging demand in crypto markets.",
    )
    engine = DerivativesIntelligenceEngine(knowledge_engine=knowledge_engine)
    engine.initialize()
    assert engine._build_knowledge_context("BTC", "flat", 1.0, "average") is None


def test_build_knowledge_context_returns_results_when_skew_notable(tmp_path):
    knowledge_engine = _real_knowledge_engine(
        tmp_path,
        "Chapter 1: Options Skew\n\nPersistent put skew in crypto options reflects structural "
        "demand for downside protection -- traders pay up for puts as portfolio insurance.",
    )
    engine = DerivativesIntelligenceEngine(knowledge_engine=knowledge_engine)
    engine.initialize()
    context = engine._build_knowledge_context("BTC", "put_skew", 1.5, "average")
    assert context is not None
    assert context["results"]


def test_build_knowledge_context_returns_results_when_vol_regime_notable(tmp_path):
    knowledge_engine = _real_knowledge_engine(
        tmp_path,
        "Chapter 1: Volatility Regimes\n\nA low realized volatility regime often precedes a "
        "sharp expansion in price movement as compressed ranges eventually resolve.",
    )
    engine = DerivativesIntelligenceEngine(knowledge_engine=knowledge_engine)
    engine.initialize()
    context = engine._build_knowledge_context("BTC", "flat", 1.0, "low")
    assert context is not None
    assert context["results"]


# ---- realized-vol regime classification (pure function, no network) ----


def test_classify_vol_regime_uncalibrated_without_baseline(engine):
    engine._realized_vol_baseline = {}
    assert engine._classify_vol_regime("BTC", 50.0) == "uncalibrated"


def test_classify_vol_regime_uncalibrated_without_current_value(engine):
    engine._realized_vol_baseline = {"BTC": {10: 30, 25: 40, 50: 54, 75: 73, 90: 95}}
    assert engine._classify_vol_regime("BTC", None) == "uncalibrated"


def test_classify_vol_regime_low(engine):
    engine._realized_vol_baseline = {"BTC": {10: 30, 25: 40, 50: 54, 75: 73, 90: 95}}
    assert engine._classify_vol_regime("BTC", 20.0) == "low"


def test_classify_vol_regime_below_average(engine):
    engine._realized_vol_baseline = {"BTC": {10: 30, 25: 40, 50: 54, 75: 73, 90: 95}}
    assert engine._classify_vol_regime("BTC", 35.0) == "below_average"


def test_classify_vol_regime_average(engine):
    engine._realized_vol_baseline = {"BTC": {10: 30, 25: 40, 50: 54, 75: 73, 90: 95}}
    assert engine._classify_vol_regime("BTC", 60.0) == "average"


def test_classify_vol_regime_above_average(engine):
    engine._realized_vol_baseline = {"BTC": {10: 30, 25: 40, 50: 54, 75: 73, 90: 95}}
    assert engine._classify_vol_regime("BTC", 80.0) == "above_average"


def test_classify_vol_regime_high(engine):
    engine._realized_vol_baseline = {"BTC": {10: 30, 25: 40, 50: 54, 75: 73, 90: 95}}
    assert engine._classify_vol_regime("BTC", 100.0) == "high"


@pytest.mark.network
def test_analyze_computes_real_realized_vol_and_regime(engine):
    """Confirms the real training-script-produced baseline is actually
    loaded and reachable from a live analyze() call, not just from
    directly-injected test dicts."""
    result = engine.analyze(symbol="BTCUSD")
    assert result.success
    snapshot = result.data
    assert snapshot.realized_vol_30d is not None
    assert snapshot.realized_vol_30d > 0
    assert snapshot.realized_vol_regime in ("low", "below_average", "average", "above_average", "high", "uncalibrated")
    if snapshot.nearest_expiry_atm_iv is not None:
        assert snapshot.iv_minus_rv == pytest.approx(snapshot.nearest_expiry_atm_iv - snapshot.realized_vol_30d, abs=0.01)


@pytest.mark.network
def test_analyze_attaches_knowledge_context_when_skew_notable(tmp_path):
    knowledge_engine = _real_knowledge_engine(
        tmp_path,
        "Chapter 1: Options Skew\n\nPersistent put skew in crypto options reflects structural "
        "demand for downside protection against sharp drawdowns.",
    )
    engine = DerivativesIntelligenceEngine(knowledge_engine=knowledge_engine)
    engine.initialize()
    result = engine.analyze(symbol="BTCUSD")
    assert result.success
    if result.data.skew_label in ("put_skew", "call_skew"):
        assert result.data.knowledge_context is not None
        assert result.data.knowledge_context["results"]
