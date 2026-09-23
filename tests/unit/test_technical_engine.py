"""
Module: test_technical_engine.py
Description: Unit tests for Technical Analysis Engine.
Author: Shantanu Waykar
Version: 1.0.0
"""

import numpy as np
import pandas as pd
import pytest

from project_titan_x.engines.e07_technical import TechnicalAnalysisEngine, TrendDirection


@pytest.fixture
def sample_ohlcv() -> pd.DataFrame:
    """Generate sample OHLCV data for testing."""
    np.random.seed(42)
    n = 200
    dates = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    df = pd.DataFrame({
        "timestamp": dates,
        "open": close - np.random.rand(n) * 0.5,
        "high": close + np.random.rand(n) * 1.0,
        "low": close - np.random.rand(n) * 1.0,
        "close": close,
        "volume": np.random.randint(1000, 10000, n),
    })
    return df


@pytest.fixture
def ta_engine() -> TechnicalAnalysisEngine:
    """Create TA engine instance."""
    engine = TechnicalAnalysisEngine()
    engine.initialize()
    return engine


def test_engine_initialization(ta_engine: TechnicalAnalysisEngine):
  """Test engine initializes successfully."""
  result = ta_engine.health_check()
  assert result.success


def test_analyze_returns_snapshot(ta_engine: TechnicalAnalysisEngine, sample_ohlcv: pd.DataFrame):
  """Test full analysis returns snapshot."""
  result = ta_engine.analyze(sample_ohlcv, symbol="TEST", timeframe="1d")
  assert result.success
  snapshot = result.data["snapshot"]
  assert snapshot.symbol == "TEST"
  assert snapshot.trend in TrendDirection
  assert -100 <= snapshot.score <= 100


def test_fibonacci_levels(ta_engine: TechnicalAnalysisEngine):
  """Test Fibonacci retracement calculation."""
  levels = ta_engine.fibonacci_levels(high=100, low=80)
  assert levels["0.0"] == 100
  assert levels["1.0"] == 80
  assert levels["0.5"] == 90


def test_pivot_points(ta_engine: TechnicalAnalysisEngine):
  """Test pivot point calculation."""
  pivots = ta_engine.pivot_points(high=105, low=95, close=100)
  assert "PP" in pivots
  assert pivots["R1"] > pivots["PP"]
  assert pivots["S1"] < pivots["PP"]


def test_insufficient_data(ta_engine: TechnicalAnalysisEngine):
  """Test error on insufficient data."""
  df = pd.DataFrame({
    "timestamp": pd.date_range("2024-01-01", periods=10, freq="D", tz="UTC"),
    "open": [100] * 10,
    "high": [101] * 10,
    "low": [99] * 10,
    "close": [100] * 10,
    "volume": [1000] * 10,
  })
  result = ta_engine.analyze(df)
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


def test_analyze_attaches_knowledge_context_when_injected(sample_ohlcv, tmp_path):
    knowledge_engine = _real_knowledge_engine(
        tmp_path,
        "Chapter 1: Trend Trading\n\nA bullish trend with strong momentum favors trend-following entries on pullbacks.",
    )
    engine = TechnicalAnalysisEngine(knowledge_engine=knowledge_engine)
    engine.initialize()
    result = engine.analyze(sample_ohlcv, symbol="TEST")
    assert result.success
    snapshot = result.data["snapshot"]
    assert snapshot.knowledge_context is not None
    assert snapshot.knowledge_context["results"]


def test_analyze_knowledge_context_none_without_engine(ta_engine, sample_ohlcv):
    result = ta_engine.analyze(sample_ohlcv, symbol="TEST")
    assert result.success
    assert result.data["snapshot"].knowledge_context is None


def _synthetic_ohlcv(close_values):
    n = len(close_values)
    close = np.asarray(close_values, dtype=float)
    return pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC"),
        "open": close, "high": close + 0.6, "low": close - 0.6,
        "close": close, "volume": np.full(n, 1000),
    })


def test_rsi_is_100_when_window_has_no_losses(ta_engine):
    """Regression for the 2026-08-23 RSI bug.

    `loss.replace(0, np.nan)` made RS NaN whenever the lookback window held
    no down-closes, so RSI came back NaN during the STRONGEST rallies.
    Correct RSI with zero losses is 100, not undefined -- and because every
    strategy reads rsi via .fillna(50), a parabolic rally was seen as
    perfectly neutral instead of maximally overbought, so no overbought
    rule could ever fire there. Confirmed on real data, not just synthetic:
    65 bars of AAPL and 9 of META daily history hit this window."""
    df = _synthetic_ohlcv(np.arange(100.0, 160.0))     # every bar closes higher
    rsi = ta_engine.analyze(df).data["df"]["rsi"]
    assert rsi.iloc[-1] == pytest.approx(100.0)
    assert rsi.iloc[14:].notna().all(), "no NaN may survive past the warm-up window"


def test_rsi_is_0_when_window_has_no_gains(ta_engine):
    df = _synthetic_ohlcv(np.arange(200.0, 140.0, -1.0))
    rsi = ta_engine.analyze(df).data["df"]["rsi"]
    assert rsi.iloc[-1] == pytest.approx(0.0)


def test_rsi_is_neutral_on_a_perfectly_flat_series(ta_engine):
    """Zero gains AND zero losses is genuinely undefined (0/0); 50 is the
    conventional neutral reading and is what strategies would have
    defaulted to anyway."""
    rsi = ta_engine.analyze(_synthetic_ohlcv(np.full(60, 100.0))).data["df"]["rsi"]
    assert rsi.iloc[-1] == pytest.approx(50.0)


def test_rsi_warmup_window_stays_nan(ta_engine):
    """The fix must not paper over the genuine warm-up NaNs -- those are
    real 'not enough data yet', not a defect."""
    rsi = ta_engine.analyze(_synthetic_ohlcv(np.arange(100.0, 160.0))).data["df"]["rsi"]
    assert rsi.iloc[:13].isna().all()
