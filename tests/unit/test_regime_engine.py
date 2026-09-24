"""Unit tests for Market Regime Engine."""

import numpy as np
import pandas as pd
import pytest

from project_titan_x.engines.e08_regime import MarketRegime, MarketRegimeEngine
from project_titan_x.engines.e07_technical import TechnicalAnalysisEngine, TrendDirection
from project_titan_x.engines.e07_technical.engine import TechnicalSnapshot
from tests._artifacts import requires_data


@pytest.fixture
def regime_engine():
    engine = MarketRegimeEngine()
    engine.initialize()
    return engine


@pytest.fixture
def trending_df():
    np.random.seed(42)
    n = 200
    close = 100 + np.cumsum(np.random.rand(n) * 0.8)
    return pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC"),
        "open": close - 0.3,
        "high": close + 0.5,
        "low": close - 0.5,
        "close": close,
        "volume": np.random.randint(1000, 5000, n),
    })


def test_regime_classification(regime_engine, trending_df):
    ta = TechnicalAnalysisEngine()
    ta.initialize()
    ta_result = ta.analyze(trending_df, symbol="TEST", timeframe="1d")
    assert ta_result.success

    result = regime_engine.classify(trending_df, ta_result.data["snapshot"])
    assert result.success
    r = result.data
    assert isinstance(r.primary_regime, MarketRegime)
    assert 0 <= r.confidence <= 100
    assert isinstance(r.suitable_strategies, list)


def test_strategy_suitability(regime_engine):
    assert regime_engine.is_strategy_suitable("mean_reversion", MarketRegime.RANGING)
    assert not regime_engine.is_strategy_suitable("mean_reversion", MarketRegime.CRISIS)


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


def test_classify_attaches_knowledge_context_when_injected(trending_df, tmp_path):
    knowledge_engine = _real_knowledge_engine(
        tmp_path,
        "Chapter 1: Trend Following\n\nA sustained uptrend with strong ADX readings favors trend-following entries over mean reversion.",
    )
    ta = TechnicalAnalysisEngine()
    ta.initialize()
    ta_result = ta.analyze(trending_df, symbol="TEST", timeframe="1d")

    engine = MarketRegimeEngine(knowledge_engine=knowledge_engine)
    engine.initialize()
    result = engine.classify(trending_df, ta_result.data["snapshot"])
    assert result.success
    assert result.data.knowledge_context is not None
    assert result.data.knowledge_context["results"]


def test_classify_knowledge_context_none_without_engine(regime_engine, trending_df):
    ta = TechnicalAnalysisEngine()
    ta.initialize()
    ta_result = ta.analyze(trending_df, symbol="TEST", timeframe="1d")
    result = regime_engine.classify(trending_df, ta_result.data["snapshot"])
    assert result.success
    assert result.data.knowledge_context is None


# ---- HMM per-symbol calibration wiring ----
#
# scripts/training/train_e08_regime.py grid-searches n_components/
# covariance_type per real symbol and persists the winner -- these confirm
# the live engine actually reads and uses it, not just computes and
# discards it (the exact bug this wiring fixes: GOLD's real calibration
# found n_components=3, but the engine was hardcoded to always use 2).

@requires_data("models/e08_regime/GOLD_1d_hmm_meta.json")
def test_load_hmm_calibration_returns_real_winner_for_gold(regime_engine):
    calibration = regime_engine._load_hmm_calibration("GOLD", "1d")
    assert calibration is not None
    assert calibration["n_components"] == 3
    assert calibration["covariance_type"] == "diag"


def test_load_hmm_calibration_returns_none_for_uncalibrated_symbol(regime_engine):
    assert regime_engine._load_hmm_calibration("NOT_A_REAL_SYMBOL", "1d") is None


@requires_data("models/e08_regime/GOLD_1d_hmm_meta.json")
def test_fit_hmm_volatility_regime_uses_calibrated_n_components(regime_engine, trending_df, monkeypatch):
    """Real-collaborator-adjacent test: confirms _fit_hmm_volatility_regime
    actually passes GOLD's real calibrated n_components=3 into GaussianHMM,
    not the hardcoded default of 2."""
    captured_kwargs = {}
    import project_titan_x.engines.e08_regime.engine as engine_module
    original_hmm = engine_module.GaussianHMM

    def _capturing_hmm(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return original_hmm(*args, **kwargs)

    monkeypatch.setattr(engine_module, "GaussianHMM", _capturing_hmm)
    regime_engine._fit_hmm_volatility_regime(trending_df, symbol="GOLD", timeframe="1d")
    assert captured_kwargs["n_components"] == 3
    assert captured_kwargs["covariance_type"] == "diag"


def test_fit_hmm_volatility_regime_falls_back_to_default_without_calibration(regime_engine, trending_df, monkeypatch):
    captured_kwargs = {}
    import project_titan_x.engines.e08_regime.engine as engine_module
    original_hmm = engine_module.GaussianHMM

    def _capturing_hmm(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return original_hmm(*args, **kwargs)

    monkeypatch.setattr(engine_module, "GaussianHMM", _capturing_hmm)
    regime_engine._fit_hmm_volatility_regime(trending_df, symbol="NOT_A_REAL_SYMBOL", timeframe="1d")
    assert captured_kwargs["n_components"] == 2
    assert captured_kwargs["covariance_type"] == "diag"


def test_fit_hmm_volatility_regime_without_symbol_uses_default(regime_engine, trending_df, monkeypatch):
    """Backward compatibility: calling without symbol/timeframe (as any
    pre-existing direct caller would) must behave exactly as before."""
    captured_kwargs = {}
    import project_titan_x.engines.e08_regime.engine as engine_module
    original_hmm = engine_module.GaussianHMM

    def _capturing_hmm(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return original_hmm(*args, **kwargs)

    monkeypatch.setattr(engine_module, "GaussianHMM", _capturing_hmm)
    regime_engine._fit_hmm_volatility_regime(trending_df)
    assert captured_kwargs["n_components"] == 2
    assert captured_kwargs["covariance_type"] == "diag"


@requires_data("models/e08_regime/GOLD_1d_hmm_meta.json")
def test_classify_passes_technical_symbol_and_timeframe_through_to_hmm(regime_engine, trending_df, monkeypatch):
    """End-to-end: classify() must forward technical.symbol/timeframe into
    the HMM fit, not just _fit_hmm_volatility_regime called directly."""
    captured_kwargs = {}
    import project_titan_x.engines.e08_regime.engine as engine_module
    original_hmm = engine_module.GaussianHMM

    def _capturing_hmm(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return original_hmm(*args, **kwargs)

    monkeypatch.setattr(engine_module, "GaussianHMM", _capturing_hmm)
    ta = TechnicalAnalysisEngine()
    ta.initialize()
    ta_result = ta.analyze(trending_df, symbol="GOLD", timeframe="1d")
    result = regime_engine.classify(trending_df, ta_result.data["snapshot"])
    assert result.success
    assert captured_kwargs["n_components"] == 3
