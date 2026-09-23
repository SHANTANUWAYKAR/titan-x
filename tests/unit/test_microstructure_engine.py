"""Unit tests for Market Microstructure Engine (E11)."""

import numpy as np
import pandas as pd
import pytest

from project_titan_x.engines.e11_microstructure import MarketMicrostructureEngine
from project_titan_x.engines.e11_microstructure.engine import (
    _classify_fx_session,
    _corwin_schultz_spread_series,
    _relative_volume,
    _volume_label,
)


@pytest.fixture
def engine() -> MarketMicrostructureEngine:
    e = MarketMicrostructureEngine()
    e.initialize()
    return e


def _make_df(n=60, freq="h", tz="UTC", seed=0, volume=None):
    rng = np.random.default_rng(seed)
    base = 100 + np.cumsum(rng.normal(0, 0.2, n))
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-07-01", periods=n, freq=freq, tz=tz),
        "open": base,
        "high": base + rng.uniform(0.05, 0.3, n),
        "low": base - rng.uniform(0.05, 0.3, n),
        "close": base,
        "volume": volume if volume is not None else rng.uniform(800, 1200, n),
    })


def test_health_check_always_healthy(engine):
    assert engine.health_check().success


def test_corwin_schultz_wider_range_gives_bigger_spread():
    n = 30
    tight_high, tight_low = np.full(n, 100.1), np.full(n, 99.9)
    wide_high, wide_low = np.full(n, 102.0), np.full(n, 98.0)
    tight = _corwin_schultz_spread_series(tight_high, tight_low)
    wide = _corwin_schultz_spread_series(wide_high, wide_low)
    assert np.nanmean(wide) > np.nanmean(tight)


def test_corwin_schultz_never_negative():
    rng = np.random.default_rng(1)
    n = 100
    base = 100 + np.cumsum(rng.normal(0, 0.2, n))
    high = base + rng.uniform(0.01, 0.3, n)
    low = base - rng.uniform(0.01, 0.3, n)
    spreads = _corwin_schultz_spread_series(high, low)
    valid = spreads[~np.isnan(spreads)]
    assert (valid >= 0).all()


def test_corwin_schultz_handles_bad_bars_gracefully():
    high = np.array([101.0, 0.0, 103.0, 104.0])
    low = np.array([99.0, -1.0, 90.0, 102.0])  # bar 2 has low > high (bad tick)
    spreads = _corwin_schultz_spread_series(high, low)
    assert len(spreads) == 4  # no crash


def test_relative_volume_thin_and_elevated():
    normal = np.full(25, 1000.0)
    thin, elevated = normal.copy(), normal.copy()
    thin[-1], elevated[-1] = 100.0, 3000.0
    assert _volume_label(_relative_volume(thin)) == "thin"
    assert _volume_label(_relative_volume(elevated)) == "elevated"
    assert _relative_volume(normal) == pytest.approx(1.0)


def test_relative_volume_none_when_forex_reports_zero():
    """Forex volume is 0/unreliable from Yahoo -- must read as 'unknown',
    not 'thin' (which would be a false execution-risk flag)."""
    assert _relative_volume(np.zeros(25)) is None
    assert _volume_label(None) == "unknown"


def test_classify_fx_session_peak_and_quiet():
    import datetime as dt

    peak = dt.datetime(2026, 7, 14, 13, 0, tzinfo=dt.timezone.utc)
    quiet = dt.datetime(2026, 7, 14, 2, 0, tzinfo=dt.timezone.utc)
    assert _classify_fx_session(peak)["liquidity"] == "peak"
    assert _classify_fx_session(quiet)["liquidity"] == "quiet"


def test_analyze_fails_gracefully_with_too_few_bars(engine):
    df = _make_df(n=5)
    result = engine.analyze(df, symbol="EURUSD", timeframe="1h", asset_class="forex")
    assert not result.success


def test_analyze_forex_includes_session(engine):
    df = _make_df(n=60)
    result = engine.analyze(df, symbol="EURUSD", timeframe="1h", asset_class="forex")
    assert result.success
    snap = result.data
    assert snap.session is not None
    assert snap.execution_risk in ("low", "medium", "high", "unknown")
    assert 0 <= snap.estimated_spread_percentile <= 100
    assert len(snap.notes) > 0


def test_analyze_non_forex_has_no_session(engine):
    df = _make_df(n=60)
    result = engine.analyze(df, symbol="GOLD", timeframe="1d", asset_class="commodity")
    assert result.success
    assert result.data.session is None


def test_analyze_thin_volume_flagged(engine):
    n = 60
    volume = np.full(n, 1000.0)
    volume[-1] = 50.0
    df = _make_df(n=n, volume=volume)
    result = engine.analyze(df, symbol="BTCUSD", timeframe="1d", asset_class="crypto")
    assert result.success
    assert result.data.volume_label == "thin"


def test_analyze_missing_volume_column_does_not_crash(engine):
    df = _make_df(n=60).drop(columns=["volume"])
    result = engine.analyze(df, symbol="EURUSD", timeframe="1h", asset_class="forex")
    assert result.success
    assert result.data.volume_label == "unknown"


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


def test_analyze_attaches_knowledge_context_when_injected(tmp_path):
    knowledge_engine = _real_knowledge_engine(
        tmp_path,
        "Chapter 1: Execution Risk\n\nWide bid-ask spreads and thin volume increase execution risk and slippage on market orders.",
    )
    engine = MarketMicrostructureEngine(knowledge_engine=knowledge_engine)
    engine.initialize()
    df = _make_df(n=60)
    result = engine.analyze(df, symbol="BTCUSD", timeframe="1d", asset_class="crypto")
    assert result.success
    assert result.data.knowledge_context is not None
    assert result.data.knowledge_context["results"]


def test_analyze_knowledge_context_none_without_engine(engine):
    df = _make_df(n=60)
    result = engine.analyze(df, symbol="BTCUSD", timeframe="1d", asset_class="crypto")
    assert result.success
    assert result.data.knowledge_context is None
