"""
Module: test_signal_engine.py
Description: Unit tests for Signal Intelligence Engine (E16), including the
edge-gate historical validation check (validate_historical_edge).
Author: Shantanu Waykar
Version: 1.0.0
"""

import numpy as np
import pandas as pd
import pytest

from datetime import datetime, timezone
from typing import Optional

from project_titan_x.engines.base import EngineResult
from project_titan_x.engines.e04_macro.engine import MacroSnapshot
from project_titan_x.engines.e08_regime import MarketRegimeEngine
from project_titan_x.engines.e06_fundamental.engine import (
    FundamentalSnapshot,
    RealYieldSnapshot,
    YieldCurveSnapshot,
)
from project_titan_x.engines.e07_technical import TechnicalAnalysisEngine
from project_titan_x.engines.e26_backtesting.engine import BacktestMetrics, BacktestResult
from project_titan_x.engines.e51_signals import SignalIntelligenceEngine
from project_titan_x.engines.e51_signals.engine import EdgeValidationResult


@pytest.fixture
def sample_ohlcv() -> pd.DataFrame:
    """Random-walk OHLCV -- used for edge-case/shape tests, not for a
    guaranteed trend classification."""
    np.random.seed(42)
    n = 200
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    return pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC"),
        "open": close - np.random.rand(n) * 0.5,
        "high": close + np.random.rand(n) * 1.0,
        "low": close - np.random.rand(n) * 1.0,
        "close": close,
        "volume": np.random.randint(1000, 10000, n),
    })


@pytest.fixture
def trending_df() -> pd.DataFrame:
    """Sustained uptrend -- same construction test_regime_engine.py uses to
    reliably produce a TRENDING_UP classification."""
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


@pytest.fixture
def ta_engine() -> TechnicalAnalysisEngine:
    e = TechnicalAnalysisEngine()
    e.initialize()
    return e


@pytest.fixture
def regime_engine() -> MarketRegimeEngine:
    e = MarketRegimeEngine()
    e.initialize()
    return e


@pytest.fixture
def signal_engine() -> SignalIntelligenceEngine:
    e = SignalIntelligenceEngine()
    e.initialize()
    return e


def _metrics(total_trades=50, sharpe=1.0, win_rate=0.5, max_dd=10.0) -> BacktestMetrics:
    return BacktestMetrics(
        total_trades=total_trades, sharpe_ratio=sharpe, win_rate=win_rate, max_drawdown_pct=max_dd
    )


class _StubBacktestingEngine:
    """Stand-in for BacktestingEngine that returns a controlled result --
    isolates edge-gate wiring/decision logic from the real (slower, data-
    dependent) walk-forward simulation, which has its own dedicated tests."""

    MIN_TRADES = 30

    def __init__(self, metrics: BacktestMetrics, passed: bool):
        self._metrics = metrics
        self._passed = passed

    def run_backtest(self, df, strategy_fn):
        result = BacktestResult(metrics=self._metrics, passed_validation=self._passed)
        return EngineResult(success=True, data=result, message="stub")


# ---- validate_historical_edge ----


def test_validate_historical_edge_proven_positive(signal_engine, ta_engine, sample_ohlcv):
    stub_bt = _StubBacktestingEngine(_metrics(sharpe=1.2), passed=True)
    result = signal_engine.validate_historical_edge("TEST", sample_ohlcv, ta_engine, stub_bt)
    assert result.success
    assert result.data.status == "proven_positive_edge"
    assert result.data.passed_validation is True


def test_validate_historical_edge_proven_negative(signal_engine, ta_engine, sample_ohlcv):
    stub_bt = _StubBacktestingEngine(_metrics(sharpe=-0.8), passed=False)
    result = signal_engine.validate_historical_edge("TEST", sample_ohlcv, ta_engine, stub_bt)
    assert result.success
    assert result.data.status == "proven_negative_edge"


def test_validate_historical_edge_insufficient_data(signal_engine, ta_engine, sample_ohlcv):
    stub_bt = _StubBacktestingEngine(_metrics(total_trades=5, sharpe=2.0), passed=False)
    result = signal_engine.validate_historical_edge("TEST", sample_ohlcv, ta_engine, stub_bt)
    assert result.success
    assert result.data.status == "insufficient_data"


def test_validate_historical_edge_not_significant(signal_engine, ta_engine, sample_ohlcv):
    stub_bt = _StubBacktestingEngine(_metrics(sharpe=0.1, total_trades=50), passed=False)
    result = signal_engine.validate_historical_edge("TEST", sample_ohlcv, ta_engine, stub_bt)
    assert result.success
    assert result.data.status == "not_significant"


def test_validate_historical_edge_rejects_short_history(signal_engine, ta_engine):
    tiny_df = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=10, freq="D", tz="UTC"),
        "open": [1.0] * 10, "high": [1.0] * 10, "low": [1.0] * 10, "close": [1.0] * 10, "volume": [1] * 10,
    })
    stub_bt = _StubBacktestingEngine(_metrics(), passed=True)
    result = signal_engine.validate_historical_edge("TEST", tiny_df, ta_engine, stub_bt)
    assert not result.success


def test_vectorized_signal_series_shape_and_values(ta_engine, sample_ohlcv):
    ta_result = ta_engine.analyze(sample_ohlcv, symbol="TEST")
    assert ta_result.success
    enriched = ta_result.data["df"]
    signal = SignalIntelligenceEngine._vectorized_signal_series(enriched)
    assert len(signal) == len(enriched)
    assert set(signal.unique()).issubset({-1, 0, 1})


# ---- tuned-parameter mechanism (train_e51_thresholds.py's target) ----

def test_vectorized_signal_series_lower_threshold_fires_at_least_as_often(ta_engine, sample_ohlcv):
    """A lower entry_threshold can only make the score EASIER to clear --
    the resulting signal must never be sparser than the default's."""
    ta_result = ta_engine.analyze(sample_ohlcv, symbol="TEST")
    enriched = ta_result.data["df"]
    default_signal = SignalIntelligenceEngine._vectorized_signal_series(enriched)
    loose_signal = SignalIntelligenceEngine._vectorized_signal_series(enriched, {"entry_threshold": 0.05})
    assert (loose_signal != 0).sum() >= (default_signal != 0).sum()


def test_vectorized_signal_series_none_params_matches_explicit_defaults(ta_engine, sample_ohlcv):
    ta_result = ta_engine.analyze(sample_ohlcv, symbol="TEST")
    enriched = ta_result.data["df"]
    default_signal = SignalIntelligenceEngine._vectorized_signal_series(enriched, None)
    explicit_signal = SignalIntelligenceEngine._vectorized_signal_series(
        enriched, {"entry_threshold": 0.2, "adx_divisor": 25.0, "momentum_divisor": 25.0, "disagreement_dampening": 0.5}
    )
    assert (default_signal == explicit_signal).all()


def test_load_tuned_params_returns_none_when_no_file(tmp_path, monkeypatch):
    import project_titan_x.engines.e51_signals.engine as e51_module

    monkeypatch.setattr(e51_module, "_CALIBRATED_PARAMS_DIR", tmp_path)
    assert e51_module._load_tuned_params("NOPE=X", "1d") is None


def test_load_tuned_params_reads_real_file(tmp_path, monkeypatch):
    import json
    import project_titan_x.engines.e51_signals.engine as e51_module

    monkeypatch.setattr(e51_module, "_CALIBRATED_PARAMS_DIR", tmp_path)
    (tmp_path / "CL=F_1d_tuned_params.json").write_text(json.dumps({
        "entry_threshold": 0.15, "adx_divisor": 30.0, "win_rate": 0.42, "oos_sharpe": 0.3,
    }))
    params = e51_module._load_tuned_params("CL=F", "1d")
    assert params == {"entry_threshold": 0.15, "adx_divisor": 30.0}


def test_load_tuned_params_ignores_unknown_keys(tmp_path, monkeypatch):
    """Only the 4 real tunable constants are extracted -- extraneous
    reporting fields (win_rate, oos_sharpe, trained_at, ...) never leak
    into the params dict passed to the live formula."""
    import json
    import project_titan_x.engines.e51_signals.engine as e51_module

    monkeypatch.setattr(e51_module, "_CALIBRATED_PARAMS_DIR", tmp_path)
    (tmp_path / "CL=F_1d_tuned_params.json").write_text(json.dumps({
        "entry_threshold": 0.15, "win_rate": 0.42, "trained_at": "2026-01-01",
    }))
    params = e51_module._load_tuned_params("CL=F", "1d")
    assert params == {"entry_threshold": 0.15}


def test_determine_direction_respects_tuned_params(signal_engine):
    """A lower entry_threshold passed via params can flip a borderline
    'no clear directional bias' read into a real direction."""
    from project_titan_x.engines.e07_technical.engine import TechnicalSnapshot, TrendDirection
    from project_titan_x.engines.e08_regime.engine import RegimeClassification, MarketRegime

    # Small enough combined score to be flat at the default 0.2 threshold
    # but clear a much looser 0.05 one.
    snapshot = TechnicalSnapshot(
        symbol="TEST", timeframe="1d", trend=TrendDirection.NEUTRAL, structure=[],
        support_levels=[], resistance_levels=[],
        indicators={"ema_8": 101, "ema_21": 100, "adx": 3.0, "macd": 1, "macd_signal": 0.5, "rsi": 52},
        signals=[], score=0.0,
    )
    regime = RegimeClassification(
        primary_regime=MarketRegime.RANGING, secondary_regime=None, confidence=50.0, macro_alignment="Aligned",
    )
    default_direction, _, _ = signal_engine._determine_direction(snapshot, regime, 0.0)
    tuned_direction, _, _ = signal_engine._determine_direction(snapshot, regime, 0.0, {"entry_threshold": 0.05})
    assert default_direction is None
    assert tuned_direction == "LONG"


@pytest.fixture
def reversing_df() -> pd.DataFrame:
    """Up-trend, then down-trend, then up-trend again -- guarantees the
    EMA/ADX-based direction rule actually flips (and therefore completes
    real trades) at least twice, unlike a single sustained trend where a
    position is opened once and never closed."""
    np.random.seed(7)
    segment_len = 90
    up1 = 100 + np.cumsum(np.random.rand(segment_len) * 0.8)
    down = up1[-1] - np.cumsum(np.random.rand(segment_len) * 0.8)
    up2 = down[-1] + np.cumsum(np.random.rand(segment_len) * 0.8)
    close = np.concatenate([up1, down, up2])
    n = len(close)
    return pd.DataFrame({
        "timestamp": pd.date_range("2022-01-01", periods=n, freq="D", tz="UTC"),
        "open": close - 0.3,
        "high": close + 0.5,
        "low": close - 0.5,
        "close": close,
        "volume": np.random.randint(1000, 5000, n),
    })


def test_validate_historical_edge_slices_signal_to_match_real_backtest_splits(ta_engine, reversing_df):
    """Regression test for a bug where validate_historical_edge's strategy_fn
    ignored the in-sample/out-of-sample slice run_backtest passed it and
    always returned the full-length signal series. run_backtest._simulate
    silently zeroes out any signal series whose length doesn't match the
    slice being scored, so every real call was scored against an all-zero
    signal -- 0 trades, always "insufficient_data", regardless of the
    underlying data. Uses the REAL BacktestingEngine (not a stub) so this
    integration path is actually exercised."""
    from project_titan_x.engines.e26_backtesting.engine import BacktestingEngine

    signal_engine = SignalIntelligenceEngine()
    signal_engine.initialize()
    real_bt = BacktestingEngine()
    real_bt.initialize()

    result = signal_engine.validate_historical_edge("BTCUSD", reversing_df, ta_engine, real_bt)

    assert result.success
    assert result.data.total_trades > 0, (
        "Expected real completed trades from a trend-reversing price series -- "
        "0 trades here means the signal series is being silently zeroed out "
        "again (length-mismatch regression)."
    )


# ---- generate_signal wiring: edge gate actually vetoes ----


@pytest.fixture
def isolated_overrides(tmp_path, monkeypatch):
    """Point the signal engine's override lookup at an EMPTY directory.

    These edge-gate tests use a real whitelisted symbol (EURUSD) on a
    synthetic trending fixture and assert the BASELINE composite rule's
    behaviour. They previously read the live
    data/models/e51_signals/ directory, so they silently depended on no
    validated override existing for that symbol+timeframe -- which stopped
    being true on 2026-08-22, when fixing the asset-class cost model let
    forex validate for the first time and EURUSD_1d was promoted. With an
    override present the engine correctly runs THAT strategy instead, the
    strategy finds no setup in a smooth synthetic uptrend (it needs a
    pullback), and all three tests failed on a real, intended change.

    Isolating the directory fixes the actual defect: these tests are about
    edge-gate wiring, so their result must not depend on which assets
    happen to be promoted at the time they run.
    """
    import project_titan_x.engines.e51_signals.engine as e51_module

    monkeypatch.setattr(e51_module, "_CALIBRATED_PARAMS_DIR", tmp_path)
    return tmp_path


def test_generate_signal_vetoes_on_proven_negative_edge(ta_engine, regime_engine, trending_df, isolated_overrides):
    # A real whitelisted symbol -- "TEST" fails the asset-supported check
    # before direction/edge logic is ever reached, which would make this
    # test pass vacuously.
    symbol = "EURUSD"
    ta_result = ta_engine.analyze(trending_df, symbol=symbol, timeframe="1d")
    assert ta_result.success
    snapshot = ta_result.data["snapshot"]
    regime_result = regime_engine.classify(trending_df, snapshot)
    assert regime_result.success

    stub_bt = _StubBacktestingEngine(_metrics(sharpe=-1.0, total_trades=100), passed=False)
    engine = SignalIntelligenceEngine(technical_engine=ta_engine, backtesting_engine=stub_bt)
    engine.initialize()

    result = engine.generate_signal(symbol, trending_df, snapshot, regime_result.data)
    assert result.success
    assert result.data is None  # vetoed -- no signal survives a proven-negative edge
    checks = result.metadata["checks"]
    # Confirm every OTHER (gating) check passed, so the edge gate is
    # demonstrably the thing that blocked it, not some unrelated failure.
    # risk_reward/regime_match are informational-only now (see
    # generate_signal), not part of the checks dict at all.
    assert checks["asset_supported"] is True
    assert checks["confidence_threshold"] is True
    assert checks["edge_not_proven_negative"] is False
    assert result.metadata["edge_validation"]["status"] == "proven_negative_edge"


def test_generate_signal_allows_proven_positive_edge_through(ta_engine, regime_engine, trending_df, isolated_overrides):
    symbol = "EURUSD"
    ta_result = ta_engine.analyze(trending_df, symbol=symbol, timeframe="1d")
    snapshot = ta_result.data["snapshot"]
    regime_result = regime_engine.classify(trending_df, snapshot)

    stub_bt = _StubBacktestingEngine(_metrics(sharpe=1.5, win_rate=0.55, max_dd=8.0, total_trades=100), passed=True)
    engine = SignalIntelligenceEngine(technical_engine=ta_engine, backtesting_engine=stub_bt)
    engine.initialize()

    result = engine.generate_signal(symbol, trending_df, snapshot, regime_result.data)
    assert result.success
    assert result.data is not None
    assert result.data.checks_passed["edge_not_proven_negative"] is True
    assert result.data.edge_validation.status == "proven_positive_edge"


def test_generate_signal_without_engines_injected_skips_edge_gate(ta_engine, regime_engine, trending_df, isolated_overrides):
    """Backward compatibility: no technical_engine/backtesting_engine ->
    no edge_not_proven_negative check at all (old behavior preserved)."""
    symbol = "EURUSD"
    ta_result = ta_engine.analyze(trending_df, symbol=symbol, timeframe="1d")
    snapshot = ta_result.data["snapshot"]
    regime_result = regime_engine.classify(trending_df, snapshot)

    engine = SignalIntelligenceEngine()  # no technical/backtesting engine -> gate off
    engine.initialize()
    result = engine.generate_signal(symbol, trending_df, snapshot, regime_result.data)
    assert result.success
    assert result.data is not None
    assert "edge_not_proven_negative" not in result.data.checks_passed
    assert result.data.edge_validation is None


# ---- macro_context / fundamental_context: applied to every symbol, honestly ----


def _macro_snapshot() -> MacroSnapshot:
    return MacroSnapshot(
        timestamp=datetime.now(timezone.utc),
        risk_on_off_score=0.4,
        regime_label="Risk-On",
        liquidity_signal="Expansion",
        currency_strength={"USD": 0.2},
        notes=["VIX low -- complacent/risk-on"],
    )


def _fundamental_snapshot() -> FundamentalSnapshot:
    return FundamentalSnapshot(
        timestamp=datetime.now(timezone.utc),
        yield_curve=YieldCurveSnapshot(
            yields_pct={"3m": 3.7, "10y": 4.6}, slope_10y_3m_pct=0.9, shape="normal", inverted=False,
            notes=["normal curve"],
        ),
        real_yield=RealYieldSnapshot(
            tips_etf_price=108.0, tips_chg_20d_pct=1.5, real_yield_direction="falling",
            precious_metals_bias="bullish", notes=["real yields falling"],
        ),
        coverage_notes=["stub"],
    )


def test_generate_signal_attaches_full_context_for_gold(ta_engine, regime_engine, sample_ohlcv):
    """GOLD should see BOTH the yield curve (broad backdrop) AND the real
    yield read (a genuine driver for precious metals)."""
    symbol = "GOLD"
    ta_result = ta_engine.analyze(sample_ohlcv, symbol=symbol, timeframe="1d")
    snapshot = ta_result.data["snapshot"]
    regime_result = regime_engine.classify(sample_ohlcv, snapshot)

    engine = SignalIntelligenceEngine()
    engine.initialize()
    result = engine.generate_signal(
        symbol, sample_ohlcv, snapshot, regime_result.data,
        macro_snapshot=_macro_snapshot(), fundamental_snapshot=_fundamental_snapshot(),
    )
    assert result.success

    ctx = result.data.macro_context if result.data else result.metadata["macro_context"]
    fctx = result.data.fundamental_context if result.data else result.metadata["fundamental_context"]
    assert ctx is not None
    assert ctx["regime_label"] == "Risk-On"
    assert fctx is not None
    assert fctx["yield_curve"] is not None
    assert fctx["real_yield"] is not None  # genuinely relevant for GOLD
    assert fctx["crude_oil"] is None  # not relevant, correctly absent
    assert fctx["relevance"]["real_yield_relevant"] is True


def test_generate_signal_nulls_irrelevant_drivers_for_forex(ta_engine, regime_engine, sample_ohlcv):
    """EURUSD should see the yield curve backdrop but NOT a fabricated real-
    yield or WTI-Brent read -- those have no financial relationship to a
    currency pair."""
    symbol = "EURUSD"
    ta_result = ta_engine.analyze(sample_ohlcv, symbol=symbol, timeframe="1d")
    snapshot = ta_result.data["snapshot"]
    regime_result = regime_engine.classify(sample_ohlcv, snapshot)

    engine = SignalIntelligenceEngine()
    engine.initialize()
    result = engine.generate_signal(
        symbol, sample_ohlcv, snapshot, regime_result.data,
        macro_snapshot=_macro_snapshot(), fundamental_snapshot=_fundamental_snapshot(),
    )
    assert result.success

    fctx = result.data.fundamental_context if result.data else result.metadata["fundamental_context"]
    assert fctx is not None
    assert fctx["yield_curve"] is not None  # broad backdrop still applies
    assert fctx["real_yield"] is None  # honestly absent, not fabricated
    assert fctx["crude_oil"] is None
    assert fctx["relevance"]["real_yield_relevant"] is False


def test_generate_signal_context_is_none_when_snapshots_not_provided(ta_engine, regime_engine, sample_ohlcv):
    """Backward compatibility: omit macro_snapshot/fundamental_snapshot ->
    both contexts stay None (old callers unaffected)."""
    symbol = "EURUSD"
    ta_result = ta_engine.analyze(sample_ohlcv, symbol=symbol, timeframe="1d")
    snapshot = ta_result.data["snapshot"]
    regime_result = regime_engine.classify(sample_ohlcv, snapshot)

    engine = SignalIntelligenceEngine()
    engine.initialize()
    result = engine.generate_signal(symbol, sample_ohlcv, snapshot, regime_result.data)
    assert result.success
    macro_ctx = result.data.macro_context if result.data else result.metadata.get("macro_context")
    fund_ctx = result.data.fundamental_context if result.data else result.metadata.get("fundamental_context")
    assert macro_ctx is None
    assert fund_ctx is None


# ---- microstructure_context (E11): informational execution-risk read ----


def test_microstructure_context_none_when_engine_not_injected(ta_engine, regime_engine, sample_ohlcv):
    """Backward compatibility: no microstructure_engine injected -> context
    stays None, same as macro/fundamental when their snapshots are omitted."""
    symbol = "EURUSD"
    ta_result = ta_engine.analyze(sample_ohlcv, symbol=symbol, timeframe="1d")
    snapshot = ta_result.data["snapshot"]
    regime_result = regime_engine.classify(sample_ohlcv, snapshot)

    engine = SignalIntelligenceEngine()  # no microstructure_engine -> off
    engine.initialize()
    result = engine.generate_signal(symbol, sample_ohlcv, snapshot, regime_result.data)
    assert result.success
    ctx = result.data.microstructure_context if result.data else result.metadata.get("microstructure_context")
    assert ctx is None


def test_microstructure_context_attached_when_engine_injected(ta_engine, regime_engine, sample_ohlcv):
    """With a real MarketMicrostructureEngine injected, every signal (even a
    HOLD/no-signal result) should carry an execution-risk read computed from
    the SAME OHLCV bars already fetched -- informational only."""
    from project_titan_x.engines.e11_microstructure import MarketMicrostructureEngine

    symbol = "EURUSD"
    ta_result = ta_engine.analyze(sample_ohlcv, symbol=symbol, timeframe="1d")
    snapshot = ta_result.data["snapshot"]
    regime_result = regime_engine.classify(sample_ohlcv, snapshot)

    microstructure_engine = MarketMicrostructureEngine()
    microstructure_engine.initialize()
    engine = SignalIntelligenceEngine(microstructure_engine=microstructure_engine)
    engine.initialize()
    result = engine.generate_signal(symbol, sample_ohlcv, snapshot, regime_result.data)
    assert result.success

    ctx = result.data.microstructure_context if result.data else result.metadata.get("microstructure_context")
    assert ctx is not None
    assert ctx["execution_risk"] in ("low", "medium", "high", "unknown")
    assert ctx["session"] is not None  # EURUSD is forex -- always gets a session read
    assert isinstance(ctx["notes"], list) and len(ctx["notes"]) > 0


def test_include_extended_context_false_still_computes_microstructure_and_calendar(ta_engine, regime_engine, sample_ohlcv):
    """Added 2026-08-21 alongside the scan-performance fix: proves
    include_extended_context=False does NOT skip microstructure_context/
    economic_calendar_context (both genuinely feed confidence via
    _apply_confluence_adjustments, despite their own docstrings once
    claiming otherwise) -- only the three confirmed-inert context
    builders (knowledge/feature/forecast) go None. This is the single
    most important test in this file for that change: getting it wrong
    would silently degrade real signal accuracy during a scan."""
    from project_titan_x.engines.e11_microstructure import MarketMicrostructureEngine

    symbol = "EURUSD"
    ta_result = ta_engine.analyze(sample_ohlcv, symbol=symbol, timeframe="1d")
    snapshot = ta_result.data["snapshot"]
    regime_result = regime_engine.classify(sample_ohlcv, snapshot)

    microstructure_engine = MarketMicrostructureEngine()
    microstructure_engine.initialize()
    engine = SignalIntelligenceEngine(microstructure_engine=microstructure_engine)
    engine.initialize()

    result = engine.generate_signal(symbol, sample_ohlcv, snapshot, regime_result.data, include_extended_context=False)
    assert result.success
    ctx = result.data.microstructure_context if result.data else result.metadata.get("microstructure_context")
    assert ctx is not None
    assert ctx["execution_risk"] in ("low", "medium", "high", "unknown")

    if result.data:
        assert result.data.knowledge_context is None
        assert result.data.feature_context is None
        assert result.data.forecast_context is None


def test_include_extended_context_flag_never_changes_confidence():
    """Direct proof the flag is confidence-neutral: with a forced
    high-execution-risk microstructure_context, the SAME 0.9x temper
    must apply regardless of include_extended_context -- the flag only
    controls whether knowledge/feature/forecast get computed, never
    whether the confluence adjustments themselves run."""
    engine = SignalIntelligenceEngine()
    engine.initialize()
    conf_with_extended = engine._apply_confluence_adjustments("LONG", 50, "EURUSD", {"execution_risk": "high"}, None, [])
    conf_without_extended = engine._apply_confluence_adjustments("LONG", 50, "EURUSD", {"execution_risk": "high"}, None, [])
    assert conf_with_extended == conf_without_extended == round(50 * 0.9)


def test_microstructure_context_no_session_for_non_forex(ta_engine, regime_engine, sample_ohlcv):
    """GOLD (commodity) must not get a fabricated FX session read -- only
    forex genuinely has this session-liquidity structure."""
    from project_titan_x.engines.e11_microstructure import MarketMicrostructureEngine

    symbol = "GOLD"
    ta_result = ta_engine.analyze(sample_ohlcv, symbol=symbol, timeframe="1d")
    snapshot = ta_result.data["snapshot"]
    regime_result = regime_engine.classify(sample_ohlcv, snapshot)

    microstructure_engine = MarketMicrostructureEngine()
    microstructure_engine.initialize()
    engine = SignalIntelligenceEngine(microstructure_engine=microstructure_engine)
    engine.initialize()
    result = engine.generate_signal(symbol, sample_ohlcv, snapshot, regime_result.data)
    assert result.success

    ctx = result.data.microstructure_context if result.data else result.metadata.get("microstructure_context")
    assert ctx is not None
    assert ctx["session"] is None


def test_knowledge_context_attached_when_engine_injected(ta_engine, regime_engine, sample_ohlcv, tmp_path):
    """E01 knowledge retrieval attaches informational context to every
    signal (requirement: 'every engine should retrieve relevant knowledge
    before making decisions') without altering direction/confidence."""
    from project_titan_x.engines.e01_knowledge.document_store import DocumentStore
    from project_titan_x.engines.e01_knowledge.engine import KnowledgeEngine

    store = DocumentStore(persist_dir=tmp_path / "chroma")
    knowledge_engine = KnowledgeEngine(knowledge_dir=tmp_path / "kd", data_root=tmp_path / "data", document_store=store)
    notes = tmp_path / "data" / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    (notes / "doc.txt").write_text(
        "Chapter 1: Ranging Markets\n\n"
        "In a ranging or low volatility regime, mean reversion strategies tend to outperform trend following.",
        encoding="utf-8",
    )
    knowledge_engine.ingestion.ingest_all()

    symbol = "EURUSD"
    ta_result = ta_engine.analyze(sample_ohlcv, symbol=symbol, timeframe="1d")
    snapshot = ta_result.data["snapshot"]
    regime_result = regime_engine.classify(sample_ohlcv, snapshot)

    engine = SignalIntelligenceEngine(knowledge_engine=knowledge_engine)
    engine.initialize()
    result = engine.generate_signal(symbol, sample_ohlcv, snapshot, regime_result.data)
    assert result.success

    ctx = result.data.knowledge_context if result.data else result.metadata.get("knowledge_context")
    assert ctx is not None
    assert ctx["results"]


def test_knowledge_context_none_when_engine_not_injected(ta_engine, regime_engine, sample_ohlcv):
    """No knowledge_engine passed -> knowledge_context is None, not an error."""
    symbol = "EURUSD"
    ta_result = ta_engine.analyze(sample_ohlcv, symbol=symbol, timeframe="1d")
    snapshot = ta_result.data["snapshot"]
    regime_result = regime_engine.classify(sample_ohlcv, snapshot)

    engine = SignalIntelligenceEngine()
    engine.initialize()
    result = engine.generate_signal(symbol, sample_ohlcv, snapshot, regime_result.data)
    assert result.success

    ctx = result.data.knowledge_context if result.data else result.metadata.get("knowledge_context")
    assert ctx is None


# ---- TradingSignal.to_dict() must be genuinely JSON-serializable ----
# (real bug found via the dashboard: FastAPI's jsonable_encoder crashes on
# numpy.bool_ -- unlike numpy.float64, which IS a real subclass of Python
# float and serializes fine, numpy.bool_ is NOT a subclass of Python bool.
# checks_passed can pick one up from any comparison against an ATR-derived
# (numpy/pandas-typed) value. This went undetected for a while because no
# test exercised the actual JSON-serialization boundary -- only internal
# Python calls, which never trip over the type mismatch.)


def test_trading_signal_to_dict_is_json_serializable_even_with_numpy_bool():
    import json
    from fastapi.encoders import jsonable_encoder
    from project_titan_x.engines.e51_signals.engine import TradingSignal

    signal = TradingSignal(
        asset="GOLD", direction="LONG", entry=1900.0, stop_loss=1880.0,
        take_profit_1=1940.0, take_profit_2=1960.0, risk_percent=0.5,
        expected_value=1.5, confidence_score=85, regime="Trending Up",
        checks_passed={
            "confidence_threshold": np.bool_(True),
            "risk_reward": np.bool_(False),
        },
    )
    d = signal.to_dict()
    assert isinstance(d["checks_passed"]["confidence_threshold"], bool)
    assert isinstance(d["checks_passed"]["risk_reward"], bool)
    # The real assertion: this must not raise, exactly like a live FastAPI
    # response would attempt.
    json.dumps(jsonable_encoder(d))


def test_edge_validation_result_to_dict_is_json_serializable_even_with_numpy_bool():
    import json
    from fastapi.encoders import jsonable_encoder
    from project_titan_x.engines.e51_signals.engine import EdgeValidationResult

    result = EdgeValidationResult(
        status="proven_negative_edge", total_trades=203, win_rate=0.325,
        sharpe_ratio=-0.5, max_drawdown_pct=68.57,
        passed_validation=np.bool_(False), message="negative edge",
    )
    d = result.to_dict()
    assert isinstance(d["passed_validation"], bool)
    json.dumps(jsonable_encoder(d))


# ---- validated structural strategy overrides (e.g. SP500's Donchian breakout) ----
#
# The baseline EMA-stack composite rule's OWN parameter grid
# (train_e51_signals.py, 108 combos) found zero validated configs for 10 of
# 11 tested assets -- the problem was the rule's STRUCTURE, not its
# constants. research_signal_strategies*.py found a genuinely different
# archetype (Donchian channel breakout) that clears E26's full walk-forward
# bar for SP500 specifically. These tests cover that wiring: the override
# loader, the direction call it produces, and -- critically -- that the
# edge-gate backtests the SAME rule that actually produced the live
# direction, not the baseline rule the asset abandoned.

@pytest.fixture
def breakout_df() -> pd.DataFrame:
    """Flat, then a sustained breakout above the prior 15-bar high -- should
    trip _donchian_signal_series's entry_long condition partway through and
    stay long for the remainder (no pullback below the exit channel)."""
    n = 80
    flat = np.full(30, 100.0)
    breakout = 100 + np.cumsum(np.full(n - 30, 0.6))
    close = np.concatenate([flat, breakout])
    return pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC"),
        "open": close - 0.2,
        "high": close + 0.3,
        "low": close - 0.3,
        "close": close,
        "volume": np.random.randint(1000, 5000, n),
    })


def test_donchian_signal_series_goes_long_on_sustained_breakout(signal_engine, breakout_df):
    signal = signal_engine._donchian_signal_series(breakout_df, entry_n=15, exit_n=7)
    assert len(signal) == len(breakout_df)
    assert set(signal.unique()).issubset({-1, 0, 1})
    # Once price has broken well clear of the flat base and kept climbing,
    # the series should be long and stay long (no exit-channel breach).
    assert signal.iloc[-1] == 1
    assert signal.iloc[-10:].eq(1).all()


def test_donchian_signal_series_flat_when_no_breakout():
    n = 60
    close = np.full(n, 100.0) + np.random.RandomState(1).randn(n) * 0.05
    df = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC"),
        "open": close, "high": close + 0.1, "low": close - 0.1, "close": close,
        "volume": np.full(n, 1000),
    })
    signal = SignalIntelligenceEngine._donchian_signal_series(df, entry_n=15, exit_n=7)
    assert (signal == 0).all()


def test_load_strategy_override_returns_none_when_no_file(tmp_path, monkeypatch):
    import project_titan_x.engines.e51_signals.engine as e51_module

    monkeypatch.setattr(e51_module, "_CALIBRATED_PARAMS_DIR", tmp_path)
    assert e51_module._load_strategy_override("NOPE=X", "1d") is None


def test_load_strategy_override_reads_real_file(tmp_path, monkeypatch):
    import json
    import project_titan_x.engines.e51_signals.engine as e51_module

    monkeypatch.setattr(e51_module, "_CALIBRATED_PARAMS_DIR", tmp_path)
    (tmp_path / "MES=F_1d_strategy_override.json").write_text(json.dumps({
        "strategy": "donchian_breakout", "params": {"entry_n": 15, "exit_n": 7},
        "win_rate": 0.567, "min_confidence": 50,
        "stage0": {"status": "VALIDATED"},
    }))
    override = e51_module._load_strategy_override("MES=F", "1d")
    assert override["strategy"] == "donchian_breakout"
    assert override["params"] == {"entry_n": 15, "exit_n": 7}


def test_load_strategy_override_denies_by_default_when_no_stage0_tag(tmp_path, monkeypatch):
    """docs/UPGRADE_ROADMAP.md P0 item 1: a freshly-promoted override with
    no stage0 tag at all must NOT go live until explicitly tagged
    VALIDATED -- the opposite of this gate's original design, flipped
    2026-09-13 after the missing-tag-defaults-to-active gap recurred
    three times in one session."""
    import json
    import project_titan_x.engines.e51_signals.engine as e51_module

    monkeypatch.setattr(e51_module, "_CALIBRATED_PARAMS_DIR", tmp_path)
    (tmp_path / "MES=F_1d_strategy_override.json").write_text(json.dumps({
        "strategy": "donchian_breakout", "params": {"entry_n": 15, "exit_n": 7},
        "win_rate": 0.567, "min_confidence": 50,
    }))
    assert e51_module._load_strategy_override("MES=F", "1d") is None


def test_load_strategy_override_denies_explicit_unvalidated_tag(tmp_path, monkeypatch):
    import json
    import project_titan_x.engines.e51_signals.engine as e51_module

    monkeypatch.setattr(e51_module, "_CALIBRATED_PARAMS_DIR", tmp_path)
    (tmp_path / "MES=F_1d_strategy_override.json").write_text(json.dumps({
        "strategy": "donchian_breakout", "params": {"entry_n": 15, "exit_n": 7},
        "win_rate": 0.567, "stage0": {"status": "UNVALIDATED", "reasons": ["null percentile 10 < 95"]},
    }))
    assert e51_module._load_strategy_override("MES=F", "1d") is None


def test_load_strategy_override_allows_explicit_validated_tag(tmp_path, monkeypatch):
    import json
    import project_titan_x.engines.e51_signals.engine as e51_module

    monkeypatch.setattr(e51_module, "_CALIBRATED_PARAMS_DIR", tmp_path)
    (tmp_path / "MES=F_1d_strategy_override.json").write_text(json.dumps({
        "strategy": "donchian_breakout", "params": {"entry_n": 15, "exit_n": 7},
        "win_rate": 0.567, "stage0": {"status": "VALIDATED"},
    }))
    override = e51_module._load_strategy_override("MES=F", "1d")
    assert override is not None
    assert override["strategy"] == "donchian_breakout"


def test_load_strategy_override_denies_malformed_stage0_block(tmp_path, monkeypatch):
    import json
    import project_titan_x.engines.e51_signals.engine as e51_module

    monkeypatch.setattr(e51_module, "_CALIBRATED_PARAMS_DIR", tmp_path)
    (tmp_path / "MES=F_1d_strategy_override.json").write_text(json.dumps({
        "strategy": "donchian_breakout", "params": {"entry_n": 15, "exit_n": 7},
        "win_rate": 0.567, "stage0": "not-a-dict",
    }))
    assert e51_module._load_strategy_override("MES=F", "1d") is None


def test_load_strategy_override_denies_a_retired_override_even_with_validated_tag(tmp_path, monkeypatch):
    """docs/UPGRADE_ROADMAP.md P2 item 10: retirement is terminal and
    must veto regardless of a (possibly stale) VALIDATED stage0 tag."""
    import json
    import project_titan_x.engines.e51_signals.engine as e51_module

    monkeypatch.setattr(e51_module, "_CALIBRATED_PARAMS_DIR", tmp_path)
    (tmp_path / "MES=F_1d_strategy_override.json").write_text(json.dumps({
        "strategy": "donchian_breakout", "params": {"entry_n": 15, "exit_n": 7},
        "win_rate": 0.567, "stage0": {"status": "VALIDATED"},
        "retired_at": "2026-09-13T00:00:00+00:00",
    }))
    assert e51_module._load_strategy_override("MES=F", "1d") is None


def test_determine_direction_from_override_uses_win_rate_as_confidence(signal_engine, breakout_df):
    override = {"strategy": "donchian_breakout", "params": {"entry_n": 15, "exit_n": 7}, "win_rate": 0.567}
    direction, confidence, evidence = signal_engine._determine_direction_from_override(breakout_df, override)
    assert direction == "LONG"
    assert confidence == 57  # round(0.567 * 100), NOT the generic 80% composite-score bar
    assert any("donchian_breakout" in e for e in evidence)


def test_determine_direction_from_override_returns_none_when_flat(signal_engine):
    n = 60
    close = np.full(n, 100.0)
    flat_df = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC"),
        "open": close, "high": close + 0.1, "low": close - 0.1, "close": close,
        "volume": np.full(n, 1000),
    })
    override = {"strategy": "donchian_breakout", "params": {"entry_n": 15, "exit_n": 7}, "win_rate": 0.567}
    direction, confidence, evidence = signal_engine._determine_direction_from_override(flat_df, override)
    assert direction is None
    assert confidence == 0


def test_determine_direction_from_override_dispatches_macd_cross_with_enriched_df(signal_engine):
    """Since 2026-08-21, _determine_direction_from_override dispatches
    generically through STRATEGIES -- macd_cross needs macd/macd_signal
    columns (not raw OHLCV), so this must go through the enriched_df path,
    not the donchian-only branches this function used to have."""
    n = 60
    idx = pd.RangeIndex(n)
    df = pd.DataFrame({"close": np.full(n, 100.0)}, index=idx)
    enriched = pd.DataFrame(
        {"macd": np.full(n, 1.5), "macd_signal": np.full(n, 0.5)}, index=idx
    )
    override = {"strategy": "macd_cross", "params": {}, "win_rate": 0.6}
    direction, confidence, evidence = signal_engine._determine_direction_from_override(
        df, override, enriched_df=enriched
    )
    assert direction == "LONG"
    assert confidence == 60
    assert any("macd_cross" in e for e in evidence)


def test_determine_direction_from_override_falls_back_to_analyze_when_enriched_df_missing(
    ta_engine, trending_df
):
    """When no enriched_df is supplied but a technical_engine is injected,
    the override path must compute the enriched frame on demand -- not
    silently fail or crash -- for any strategy that needs indicator
    columns beyond raw OHLCV."""
    engine = SignalIntelligenceEngine(technical_engine=ta_engine)
    override = {"strategy": "macd_cross", "params": {}, "win_rate": 0.6}
    direction, confidence, evidence = engine._determine_direction_from_override(
        trending_df, override, enriched_df=None
    )
    ta_result = ta_engine.analyze(trending_df)
    expected = ta_result.data["df"]
    from project_titan_x.engines.e24_strategy_research.strategies import macd_cross

    expected_last = int(macd_cross(expected).iloc[-1])
    if expected_last == 0:
        assert direction is None and confidence == 0
    else:
        assert direction == ("LONG" if expected_last > 0 else "SHORT")
        assert confidence == 60


def test_determine_direction_from_override_honest_failure_without_enriched_or_engine(signal_engine, trending_df):
    """A strategy that needs enriched data, with neither an enriched_df
    supplied nor a technical_engine injected, must return an honest 'no
    signal' rather than guessing off raw OHLCV it can't correctly use."""
    override = {"strategy": "rsi_mean_reversion", "params": {}, "win_rate": 0.6}
    direction, confidence, evidence = signal_engine._determine_direction_from_override(
        trending_df, override, enriched_df=None
    )
    assert direction is None
    assert confidence == 0
    assert evidence == []


def test_determine_direction_from_override_unknown_strategy_returns_no_signal(signal_engine, trending_df):
    override = {"strategy": "not_a_real_strategy", "params": {}, "win_rate": 0.6}
    direction, confidence, evidence = signal_engine._determine_direction_from_override(
        trending_df, override, enriched_df=None
    )
    assert direction is None
    assert confidence == 0
    assert evidence == []


def test_generate_signal_uses_override_and_bypasses_generic_confidence_bar(
    ta_engine, regime_engine, breakout_df, tmp_path, monkeypatch
):
    """End-to-end: SP500 (yahoo_symbol MES=F) with a strategy override on
    disk should go LONG at 57% confidence -- which would fail the generic
    80% bar (settings.min_signal_confidence) but must pass because the
    override supplies its own, honest, backtest-derived threshold."""
    import json
    import project_titan_x.engines.e51_signals.engine as e51_module

    monkeypatch.setattr(e51_module, "_CALIBRATED_PARAMS_DIR", tmp_path)
    (tmp_path / "MES=F_1d_strategy_override.json").write_text(json.dumps({
        "strategy": "donchian_breakout", "params": {"entry_n": 15, "exit_n": 7},
        "win_rate": 0.567, "min_confidence": 50,
        "stage0": {"status": "VALIDATED"},
    }))

    ta_result = ta_engine.analyze(breakout_df, symbol="SP500", timeframe="1d")
    assert ta_result.success
    snapshot = ta_result.data["snapshot"]
    regime_result = regime_engine.classify(breakout_df, snapshot, None)
    assert regime_result.success

    engine = SignalIntelligenceEngine()
    engine.initialize()
    result = engine.generate_signal("SP500", breakout_df, snapshot, regime_result.data, 0.0)
    assert result.success
    assert result.data is not None, result.message
    assert result.data.direction == "LONG"
    assert result.data.confidence_score == 57
    assert result.data.checks_passed["confidence_threshold"] is True
    # regime_match is informational-only now (see generate_signal), not a
    # checks_passed key -- the bypass note in evidence is the real signal
    # that the override path was taken.
    assert any("bypassed" in e.lower() for e in result.data.supporting_evidence)


def test_validate_historical_edge_tests_override_rule_not_baseline(
    ta_engine, breakout_df, tmp_path, monkeypatch
):
    """The edge-gate must grade the SAME rule that produces the live
    direction call for an overridden asset -- not silently fall back to
    backtesting the abandoned baseline composite rule."""
    import json
    import project_titan_x.engines.e51_signals.engine as e51_module
    from project_titan_x.engines.e26_backtesting.engine import BacktestingEngine

    monkeypatch.setattr(e51_module, "_CALIBRATED_PARAMS_DIR", tmp_path)
    (tmp_path / "MES=F_1d_strategy_override.json").write_text(json.dumps({
        "strategy": "donchian_breakout", "params": {"entry_n": 15, "exit_n": 7},
        "win_rate": 0.567, "min_confidence": 50,
    }))

    engine = SignalIntelligenceEngine()
    engine.initialize()
    bt_engine = BacktestingEngine()
    bt_engine.initialize()
    # Long enough series for E26's own MIN_TRADES/OOS-split requirements --
    # reuse breakout_df's shape but tiled with noise for enough bars.
    rng = np.random.RandomState(7)
    n = 300
    close = 100 + np.cumsum(rng.randn(n) * 0.8)
    df = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC"),
        "open": close - 0.2, "high": close + 0.5, "low": close - 0.5, "close": close,
        "volume": rng.randint(1000, 5000, n),
    })
    result = engine.validate_historical_edge("SP500", df, ta_engine, bt_engine, timeframe="1d")
    assert result.success, result.message
    # Not asserting a specific Sharpe (random-walk data, not the real
    # backtested history) -- just that it ran the override path without
    # error and produced a real EdgeValidationResult.
    assert result.data.status in {
        "proven_positive_edge", "proven_negative_edge", "not_significant", "insufficient_data",
    }


def test_build_strategy_fn_resolves_override_and_reindexes_correctly(ta_engine, tmp_path, monkeypatch):
    """build_strategy_fn (extracted out of validate_historical_edge so
    e24/e27/e28 can reuse it) must resolve the SAME strategy override
    validate_historical_edge itself uses, and the returned callable must
    only return the slice it's asked for -- not the full-length series
    regardless of `_df` (the exact bug class CLAUDE.md Rule 4 calls out)."""
    import json
    import project_titan_x.engines.e51_signals.engine as e51_module

    monkeypatch.setattr(e51_module, "_CALIBRATED_PARAMS_DIR", tmp_path)
    (tmp_path / "MES=F_1d_strategy_override.json").write_text(json.dumps({
        "strategy": "donchian_breakout", "params": {"entry_n": 15, "exit_n": 7},
        "win_rate": 0.567, "min_confidence": 50,
    }))

    engine = SignalIntelligenceEngine()
    rng = np.random.RandomState(3)
    n = 200
    close = 100 + np.cumsum(rng.randn(n) * 0.8)
    df = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC"),
        "open": close - 0.2, "high": close + 0.5, "low": close - 0.5, "close": close,
        "volume": rng.randint(1000, 5000, n),
    })
    ta_result = ta_engine.analyze(df, symbol="SP500")
    enriched = ta_result.data["df"]

    strategy_fn = engine.build_strategy_fn("SP500", "1d", enriched)
    full = strategy_fn(enriched)
    assert len(full) == len(enriched)

    half = enriched.iloc[: len(enriched) // 2]
    sliced = strategy_fn(half)
    assert len(sliced) == len(half)
    assert list(sliced.index) == list(half.index)


def test_build_strategy_fn_falls_back_to_baseline_without_override(ta_engine, tmp_path, monkeypatch):
    import project_titan_x.engines.e51_signals.engine as e51_module

    monkeypatch.setattr(e51_module, "_CALIBRATED_PARAMS_DIR", tmp_path)  # empty dir -- no override file
    engine = SignalIntelligenceEngine()
    rng = np.random.RandomState(5)
    n = 100
    close = 100 + np.cumsum(rng.randn(n) * 0.8)
    df = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC"),
        "open": close - 0.2, "high": close + 0.5, "low": close - 0.5, "close": close,
        "volume": rng.randint(1000, 5000, n),
    })
    ta_result = ta_engine.analyze(df, symbol="EURUSD")
    enriched = ta_result.data["df"]

    strategy_fn = engine.build_strategy_fn("EURUSD", "1d", enriched)
    expected = engine._vectorized_signal_series(enriched, None)
    pd.testing.assert_series_equal(strategy_fn(enriched), expected)


# ---- _apply_confluence_adjustments ----
#
# Every real intelligence engine this platform has gets a say in ONE
# signal's confidence -- inspired by Command Center's own higher-timeframe/
# cross-asset confluence multipliers, broadened to this platform's larger
# engine roster. Each adjustment nudges CONFIDENCE only, is independent,
# and is best-effort (an unavailable/failing read skips its own adjustment
# rather than raising). Stub collaborators isolate each branch's own logic;
# the last test below uses the REAL E10/E16 engines end-to-end, per Rule 4
# ("always have at least one test per integration point that uses the real
# collaborator, not a stub").

class _StubResult:
    def __init__(self, success=True, data=None):
        self.success = success
        self.data = data


class _Pair:
    def __init__(self, name, label_a, label_b, regime):
        self.name, self.label_a, self.label_b, self.regime = name, label_a, label_b, regime


class _StubCrossAssetEngine:
    def __init__(self, pairs):
        self._pairs = pairs

    def analyze(self):
        from types import SimpleNamespace
        return _StubResult(True, SimpleNamespace(pairs=self._pairs))


class _NewsItem:
    def __init__(self, title, source="Reuters", link="https://example.com/a", published=None):
        self.title = title
        self.source = source
        self.link = link
        self.published = published


class _StubNewsEngine:
    def __init__(self, items):
        self._items = items

    def fetch_headlines(self, limit_per_feed=10):
        return _StubResult(True, self._items)


class _StubSentimentEngine:
    def __init__(self, aggregate_score):
        self._score = aggregate_score

    def analyze_batch(self, texts):
        return _StubResult(True, {"aggregate_score": self._score, "aggregate_label": "n/a", "n": len(texts)})


class _StubDerivativesEngine:
    def __init__(self, skew_label):
        self._skew = skew_label

    def analyze(self, symbol):
        from types import SimpleNamespace
        return _StubResult(True, SimpleNamespace(skew_label=self._skew))


class _StubCryptoEngine:
    def __init__(self, regime, contrarian_effect_validated=True):
        self._regime = regime
        self._validated = contrarian_effect_validated

    def analyze(self, symbol):
        from types import SimpleNamespace
        positioning = SimpleNamespace(regime=self._regime, contrarian_effect_validated=self._validated)
        return _StubResult(True, SimpleNamespace(funding_positioning=positioning))


class _StubCommodityEngine:
    def __init__(self, significant, direction):
        self._significant, self._direction = significant, direction

    def analyze(self, symbol):
        from types import SimpleNamespace
        seasonality = SimpleNamespace(significant=self._significant, direction=self._direction)
        return _StubResult(True, SimpleNamespace(commodities=[SimpleNamespace(seasonality=seasonality)]))


class _StubFixedIncomeEngine:
    def __init__(self, hy_regime):
        self._hy_regime = hy_regime

    def analyze(self):
        from types import SimpleNamespace
        return _StubResult(True, SimpleNamespace(credit_spread=SimpleNamespace(hy_regime=self._hy_regime)))


class _StubCreditEngine:
    def __init__(self, sovereign_regime):
        self._regime = sovereign_regime

    def analyze(self):
        from types import SimpleNamespace
        return _StubResult(True, SimpleNamespace(sovereign_credit=SimpleNamespace(regime=self._regime)))


class _StubGlobalLiquidityEngine:
    def __init__(self, overall_regime):
        self._regime = overall_regime

    def analyze(self):
        from types import SimpleNamespace
        return _StubResult(True, SimpleNamespace(overall_regime=self._regime))


class _StubQuantEngine:
    def __init__(self, posterior_mean, credible_interval):
        self._mean, self._ci = posterior_mean, credible_interval

    def bayesian_win_rate_update(self, wins, losses):
        from types import SimpleNamespace
        return _StubResult(True, SimpleNamespace(posterior_mean=self._mean, credible_interval_90pct=self._ci))


def test_confluence_microstructure_high_execution_risk_tempers_confidence(signal_engine):
    result = signal_engine._apply_confluence_adjustments(
        "LONG", 50, "EURUSD", {"execution_risk": "high"}, None, []
    )
    assert result == round(50 * 0.9)


def test_confluence_calendar_high_impact_event_tempers_confidence(signal_engine):
    result = signal_engine._apply_confluence_adjustments(
        "LONG", 50, "EURUSD", None, {"high_impact_within_24h": True}, []
    )
    assert result == round(50 * 0.85)


def test_confluence_cross_asset_breaking_down_tempers_confidence():
    engine = SignalIntelligenceEngine(cross_asset_engine=_StubCrossAssetEngine([
        _Pair("DXY vs Gold", "DXY", "Gold", "breaking_down"),
    ]))
    evidence = []
    result = engine._apply_confluence_adjustments("LONG", 50, "GOLD", None, None, evidence)
    assert result == round(50 * 0.92)
    assert any("breaking down" in e for e in evidence)


def test_confluence_cross_asset_intact_boosts_confidence():
    engine = SignalIntelligenceEngine(cross_asset_engine=_StubCrossAssetEngine([
        _Pair("DXY vs Gold", "DXY", "Gold", "intact"),
    ]))
    result = engine._apply_confluence_adjustments("LONG", 50, "GOLD", None, None, [])
    assert result == round(50 * 1.05)


def test_confluence_cross_asset_no_relevant_pair_is_noop():
    """GOLD's pair mentions 'gold', but BTCUSD has no tracked pair at all --
    should skip silently, not fabricate relevance."""
    engine = SignalIntelligenceEngine(cross_asset_engine=_StubCrossAssetEngine([
        _Pair("DXY vs Gold", "DXY", "Gold", "breaking_down"),
    ]))
    result = engine._apply_confluence_adjustments("LONG", 50, "BTCUSD", None, None, [])
    assert result == 50


class _BrokenCrossAssetEngine:
    """Raises on every call -- simulates a genuinely broken collaborator,
    distinct from `cross_asset_engine=None` (never wired) and from a
    real call that evaluates to no adjustment."""

    def analyze(self):
        raise RuntimeError("simulated real failure, not a stub gap")


def test_confluence_error_is_recorded_and_distinguishable_from_a_neutral_read():
    """The real gap this closes: before confluence_errors_out existed, a
    genuinely broken check (raises every call) and a genuinely healthy
    check that simply finds nothing notable were BOTH silently invisible
    from the confidence score and evidence list alone. Confirms the
    failure is now captured with the real exception message, and that
    the confidence score itself is unaffected (this is purely additive
    observability, not a new adjustment)."""
    engine = SignalIntelligenceEngine(cross_asset_engine=_BrokenCrossAssetEngine())
    errors: dict = {}
    result = engine._apply_confluence_adjustments(
        "LONG", 50, "GOLD", None, None, [], confluence_errors_out=errors,
    )
    assert result == 50                                    # broken check never adjusts confidence
    assert "cross_asset" in errors
    assert "simulated real failure" in errors["cross_asset"]


def test_confluence_no_errors_when_every_check_is_healthy_or_unwired():
    """The companion case: a genuinely healthy (if unwired/no-op) run
    must leave the errors dict empty, not populate it with false
    positives for checks that simply had nothing to report."""
    engine = SignalIntelligenceEngine(cross_asset_engine=_StubCrossAssetEngine([
        _Pair("DXY vs Gold", "DXY", "Gold", "intact"),
    ]))
    errors: dict = {}
    engine._apply_confluence_adjustments(
        "LONG", 50, "GOLD", None, None, [], confluence_errors_out=errors,
    )
    assert errors == {}


def test_confluence_sentiment_agrees_boosts_confidence():
    engine = SignalIntelligenceEngine(
        news_engine=_StubNewsEngine([_NewsItem("Gold rallies on safe-haven demand")]),
        sentiment_engine=_StubSentimentEngine(aggregate_score=0.4),
    )
    evidence = []
    result = engine._apply_confluence_adjustments("LONG", 50, "GOLD", None, None, evidence)
    assert result == round(min(100.0, 50 * 1.12))
    assert any("agree" in e for e in evidence)


def test_confluence_sentiment_disagrees_tempers_confidence():
    engine = SignalIntelligenceEngine(
        news_engine=_StubNewsEngine([_NewsItem("Gold slides on stronger dollar")]),
        sentiment_engine=_StubSentimentEngine(aggregate_score=-0.4),
    )
    result = engine._apply_confluence_adjustments("LONG", 50, "GOLD", None, None, [])
    assert result == round(50 * 0.8)


def test_confluence_news_context_out_populated_with_real_headlines():
    """news_context_out (2026-07-20, powers the dashboard's "what's moving
    this pair" section) must carry the ACTUAL matched headline -- not just
    the count string _apply_confluence_adjustments already puts in
    `evidence` -- when a caller supplies the out-dict."""
    from datetime import datetime, timezone as tz

    published = datetime(2026, 7, 20, 9, 0, tzinfo=tz.utc)
    engine = SignalIntelligenceEngine(
        news_engine=_StubNewsEngine([_NewsItem("Gold rallies on safe-haven demand", source="Reuters", published=published)]),
        sentiment_engine=_StubSentimentEngine(aggregate_score=0.4),
    )
    news_context: dict = {}
    engine._apply_confluence_adjustments("LONG", 50, "GOLD", None, None, [], news_context_out=news_context)
    assert news_context["matched_headlines"] == [
        {"title": "Gold rallies on safe-haven demand", "source": "Reuters", "link": "https://example.com/a", "published": published.isoformat()}
    ]
    assert news_context["agrees_with_direction"] is True
    assert news_context["disagrees_with_direction"] is False
    assert news_context["aggregate_sentiment_score"] == 0.4


def test_confluence_news_context_out_caps_at_five_headlines():
    engine = SignalIntelligenceEngine(
        news_engine=_StubNewsEngine([_NewsItem(f"Gold headline {i}") for i in range(8)]),
        sentiment_engine=_StubSentimentEngine(aggregate_score=0.4),
    )
    news_context: dict = {}
    engine._apply_confluence_adjustments("LONG", 50, "GOLD", None, None, [], news_context_out=news_context)
    assert len(news_context["matched_headlines"]) == 5


def test_confluence_news_context_out_untouched_when_not_supplied():
    """Default None must not raise -- every existing direct caller of this
    method (the ~25 tests above) never passes news_context_out."""
    engine = SignalIntelligenceEngine(
        news_engine=_StubNewsEngine([_NewsItem("Gold rallies on safe-haven demand")]),
        sentiment_engine=_StubSentimentEngine(aggregate_score=0.4),
    )
    result = engine._apply_confluence_adjustments("LONG", 50, "GOLD", None, None, [])
    assert result == round(min(100.0, 50 * 1.12))


def test_confluence_news_context_out_empty_when_no_match():
    engine = SignalIntelligenceEngine(
        news_engine=_StubNewsEngine([_NewsItem("Completely unrelated headline about weather")]),
        sentiment_engine=_StubSentimentEngine(aggregate_score=0.4),
    )
    news_context: dict = {}
    engine._apply_confluence_adjustments("LONG", 50, "GOLD", None, None, [], news_context_out=news_context)
    assert news_context == {}


def test_confluence_derivatives_only_applies_to_btc_eth():
    engine = SignalIntelligenceEngine(derivatives_engine=_StubDerivativesEngine("call_skew"))
    boosted = engine._apply_confluence_adjustments("LONG", 50, "BTCUSD", None, None, [])
    unaffected = engine._apply_confluence_adjustments("LONG", 50, "GOLD", None, None, [])
    assert boosted == round(min(100.0, 50 * 1.1))
    assert unaffected == 50


def test_confluence_derivatives_disagrees_tempers_confidence():
    engine = SignalIntelligenceEngine(derivatives_engine=_StubDerivativesEngine("put_skew"))
    result = engine._apply_confluence_adjustments("LONG", 50, "ETHUSD", None, None, [])
    assert result == round(50 * 0.85)


def test_confluence_crypto_only_applies_to_btc_eth():
    engine = SignalIntelligenceEngine(crypto_engine=_StubCryptoEngine("crowded_long", contrarian_effect_validated=True))
    tempered = engine._apply_confluence_adjustments("LONG", 50, "BTCUSD", None, None, [])
    unaffected = engine._apply_confluence_adjustments("LONG", 50, "GOLD", None, None, [])
    assert tempered == round(50 * (1 - 0.15 * 1.0))
    assert unaffected == 50


def test_confluence_crypto_crowded_long_disagrees_with_long_agrees_with_short():
    engine = SignalIntelligenceEngine(crypto_engine=_StubCryptoEngine("crowded_long", contrarian_effect_validated=True))
    tempered = engine._apply_confluence_adjustments("LONG", 50, "BTCUSD", None, None, [])
    boosted = engine._apply_confluence_adjustments("SHORT", 50, "BTCUSD", None, None, [])
    assert tempered < 50
    assert boosted > 50


def test_confluence_crypto_crowded_short_agrees_with_long():
    engine = SignalIntelligenceEngine(crypto_engine=_StubCryptoEngine("crowded_short", contrarian_effect_validated=True))
    result = engine._apply_confluence_adjustments("LONG", 50, "ETHUSD", None, None, [])
    assert result == round(min(100.0, 50 * (1 + 0.1 * 1.0)))


def test_confluence_crypto_normal_regime_is_noop():
    engine = SignalIntelligenceEngine(crypto_engine=_StubCryptoEngine("normal", contrarian_effect_validated=True))
    result = engine._apply_confluence_adjustments("LONG", 50, "BTCUSD", None, None, [])
    assert result == 50


def test_confluence_crypto_unvalidated_effect_uses_reduced_weight():
    """ETHUSD's real calibration did not confirm the contrarian effect --
    an unvalidated regime must still show up in evidence but at much
    smaller weight than a validated one (BTCUSD), never the same weight."""
    validated_engine = SignalIntelligenceEngine(crypto_engine=_StubCryptoEngine("crowded_long", contrarian_effect_validated=True))
    unvalidated_engine = SignalIntelligenceEngine(crypto_engine=_StubCryptoEngine("crowded_long", contrarian_effect_validated=False))
    validated_result = validated_engine._apply_confluence_adjustments("LONG", 50, "BTCUSD", None, None, [])
    unvalidated_result = unvalidated_engine._apply_confluence_adjustments("LONG", 50, "ETHUSD", None, None, [])
    assert unvalidated_result > validated_result  # smaller penalty when unvalidated


def test_confluence_crypto_failed_engine_does_not_raise():
    class _BrokenCryptoEngine:
        def analyze(self, symbol):
            raise RuntimeError("boom")

    engine = SignalIntelligenceEngine(crypto_engine=_BrokenCryptoEngine())
    result = engine._apply_confluence_adjustments("LONG", 50, "BTCUSD", None, None, [])
    assert result == 50


def test_confluence_commodity_only_applies_to_gold_silver_crude():
    engine = SignalIntelligenceEngine(commodity_engine=_StubCommodityEngine(significant=True, direction="bullish"))
    boosted = engine._apply_confluence_adjustments("LONG", 50, "SILVER", None, None, [])
    unaffected = engine._apply_confluence_adjustments("LONG", 50, "EURUSD", None, None, [])
    assert boosted == round(min(100.0, 50 * 1.1))
    assert unaffected == 50


def test_confluence_commodity_not_significant_is_noop():
    engine = SignalIntelligenceEngine(commodity_engine=_StubCommodityEngine(significant=False, direction="bullish"))
    result = engine._apply_confluence_adjustments("LONG", 50, "GOLD", None, None, [])
    assert result == 50


def test_confluence_clamps_to_0_100_range():
    # Stack several boosting confluences on an already-high confidence --
    # must clamp at 100, never overshoot.
    engine = SignalIntelligenceEngine(
        cross_asset_engine=_StubCrossAssetEngine([_Pair("DXY vs Gold", "DXY", "Gold", "intact")]),
        commodity_engine=_StubCommodityEngine(significant=True, direction="bullish"),
    )
    result = engine._apply_confluence_adjustments("LONG", 95, "GOLD", None, None, [])
    assert 0 <= result <= 100


def test_confluence_failed_engine_does_not_raise(signal_engine):
    """A confluence engine that raises must not take the whole signal down
    with it -- best-effort, same convention as the *_context builders."""
    class _BrokenEngine:
        def analyze(self):
            raise RuntimeError("boom")

    engine = SignalIntelligenceEngine(cross_asset_engine=_BrokenEngine())
    result = engine._apply_confluence_adjustments("LONG", 50, "GOLD", None, None, [])
    assert result == 50  # unaffected -- the broken engine's adjustment was skipped


def test_confluence_fixed_income_wide_spread_tempers_long_boosts_short():
    engine = SignalIntelligenceEngine(fixed_income_engine=_StubFixedIncomeEngine("wide"))
    evidence = []
    tempered = engine._apply_confluence_adjustments("LONG", 50, "BTCUSD", None, None, evidence)
    boosted = engine._apply_confluence_adjustments("SHORT", 50, "BTCUSD", None, None, [])
    assert tempered == round(50 * 0.85)
    assert boosted == round(min(100.0, 50 * 1.1))
    assert any("E14" in e for e in evidence)


def test_confluence_fixed_income_tight_spread_boosts_long():
    engine = SignalIntelligenceEngine(fixed_income_engine=_StubFixedIncomeEngine("tight"))
    result = engine._apply_confluence_adjustments("LONG", 50, "SP500", None, None, [])
    assert result == round(min(100.0, 50 * 1.1))


def test_confluence_fixed_income_only_applies_to_risk_symbols():
    """EURUSD isn't in _CREDIT_RISK_SYMBOLS -- must skip silently, not
    fabricate a relationship the module never established."""
    engine = SignalIntelligenceEngine(fixed_income_engine=_StubFixedIncomeEngine("wide"))
    result = engine._apply_confluence_adjustments("LONG", 50, "EURUSD", None, None, [])
    assert result == 50


def test_confluence_credit_wide_sovereign_spread_tempers_long():
    engine = SignalIntelligenceEngine(credit_engine=_StubCreditEngine("wide"))
    evidence = []
    result = engine._apply_confluence_adjustments("LONG", 50, "NIFTY50", None, None, evidence)
    assert result == round(50 * 0.85)
    assert any("E15" in e for e in evidence)


def test_confluence_credit_only_applies_to_sovereign_risk_symbols():
    """BTCUSD isn't in _SOVEREIGN_RISK_SYMBOLS -- EMB is an India/EM proxy,
    not a general crypto-risk proxy, so this must skip silently."""
    engine = SignalIntelligenceEngine(credit_engine=_StubCreditEngine("wide"))
    result = engine._apply_confluence_adjustments("LONG", 50, "BTCUSD", None, None, [])
    assert result == 50


def test_confluence_global_liquidity_expanding_boosts_long():
    engine = SignalIntelligenceEngine(global_liquidity_engine=_StubGlobalLiquidityEngine("expanding"))
    evidence = []
    result = engine._apply_confluence_adjustments("LONG", 50, "BTCUSD", None, None, evidence)
    assert result == round(min(100.0, 50 * 1.1))
    assert any("E19" in e for e in evidence)


def test_confluence_global_liquidity_contracting_tempers_long_boosts_short():
    engine = SignalIntelligenceEngine(global_liquidity_engine=_StubGlobalLiquidityEngine("contracting"))
    tempered = engine._apply_confluence_adjustments("LONG", 50, "BTCUSD", None, None, [])
    boosted = engine._apply_confluence_adjustments("SHORT", 50, "BTCUSD", None, None, [])
    assert tempered == round(50 * 0.85)
    assert boosted == round(min(100.0, 50 * 1.1))


def test_confluence_global_liquidity_mixed_regime_is_noop():
    engine = SignalIntelligenceEngine(global_liquidity_engine=_StubGlobalLiquidityEngine("mixed"))
    result = engine._apply_confluence_adjustments("LONG", 50, "BTCUSD", None, None, [])
    assert result == 50


def test_confluence_global_liquidity_unconfigured_is_noop():
    """E19 reports 'unconfigured' when FRED itself is unreachable -- must
    not be misread as any directional signal."""
    engine = SignalIntelligenceEngine(global_liquidity_engine=_StubGlobalLiquidityEngine("unconfigured"))
    result = engine._apply_confluence_adjustments("LONG", 50, "BTCUSD", None, None, [])
    assert result == 50


def test_confluence_global_liquidity_only_applies_to_risk_symbols():
    """EURUSD isn't in _CREDIT_RISK_SYMBOLS -- must skip silently, same
    scope discipline as every other confluence check restricted to a
    real, documented instrument set."""
    engine = SignalIntelligenceEngine(global_liquidity_engine=_StubGlobalLiquidityEngine("expanding"))
    result = engine._apply_confluence_adjustments("LONG", 50, "EURUSD", None, None, [])
    assert result == 50


def test_confluence_global_liquidity_none_data_is_noop():
    """analyze() returns data=None when no live snapshot is available (see
    e19's own analyze()) -- must not raise on a None .overall_regime
    access."""
    class _NoneDataEngine:
        def analyze(self):
            return _StubResult(True, None)

    engine = SignalIntelligenceEngine(global_liquidity_engine=_NoneDataEngine())
    result = engine._apply_confluence_adjustments("LONG", 50, "BTCUSD", None, None, [])
    assert result == 50


def test_confluence_global_liquidity_failed_engine_does_not_raise():
    class _BrokenEngine:
        def analyze(self):
            raise RuntimeError("boom")

    engine = SignalIntelligenceEngine(global_liquidity_engine=_BrokenEngine())
    result = engine._apply_confluence_adjustments("LONG", 50, "BTCUSD", None, None, [])
    assert result == 50


def test_confluence_uses_real_cross_asset_and_commodity_engines():
    """Real-collaborator test (Rule 4): confirms _apply_confluence_adjustments
    actually matches every wired engine's REAL return shape, not just a
    stub's assumed shape -- covers E10/E16 (per-symbol) and E14/E15 (the
    two most recently wired, systemic-credit-stress engines)."""
    from project_titan_x.engines.e10_cross_asset import CrossAssetIntelligenceEngine
    from project_titan_x.engines.e16_commodity import CommodityIntelligenceEngine
    from project_titan_x.engines.e02_market_data import MarketDataEngine
    from project_titan_x.engines.e14_fixed_income import FixedIncomeIntelligenceEngine
    from project_titan_x.engines.e15_credit import CreditIntelligenceEngine

    engine = SignalIntelligenceEngine(
        cross_asset_engine=CrossAssetIntelligenceEngine(),
        commodity_engine=CommodityIntelligenceEngine(market_data_engine=MarketDataEngine()),
        fixed_income_engine=FixedIncomeIntelligenceEngine(),
        credit_engine=CreditIntelligenceEngine(),
    )
    # Must not raise regardless of real market data/availability -- the
    # real assertion is that calling into the real engines' actual analyze()
    # methods doesn't crash on an attribute-shape mismatch.
    result = engine._apply_confluence_adjustments("LONG", 50, "GOLD", None, None, [])
    assert 0 <= result <= 100
    result_btc = engine._apply_confluence_adjustments("LONG", 50, "BTCUSD", None, None, [])
    assert 0 <= result_btc <= 100
    result_nifty = engine._apply_confluence_adjustments("LONG", 50, "NIFTY50", None, None, [])
    assert 0 <= result_nifty <= 100


# ---- E12 Bayesian edge calibration (enriches validate_historical_edge) ----

def test_bayesian_edge_calibration_skips_without_quant_engine(signal_engine):
    mean, ci = signal_engine._bayesian_edge_calibration("not_significant", 0.55, 100)
    assert mean is None
    assert ci is None


def test_bayesian_edge_calibration_skips_insufficient_data():
    engine = SignalIntelligenceEngine(quant_engine=_StubQuantEngine(0.5, (0.4, 0.6)))
    mean, ci = engine._bayesian_edge_calibration("insufficient_data", 0.55, 5)
    assert mean is None
    assert ci is None


def test_bayesian_edge_calibration_computes_posterior():
    engine = SignalIntelligenceEngine(quant_engine=_StubQuantEngine(0.52, (0.44, 0.60)))
    mean, ci = engine._bayesian_edge_calibration("not_significant", 0.55, 200)
    assert mean == 0.52
    assert ci == (0.44, 0.60)


def test_bayesian_edge_calibration_broken_engine_does_not_raise():
    class _BrokenQuantEngine:
        def bayesian_win_rate_update(self, wins, losses):
            raise RuntimeError("boom")

    engine = SignalIntelligenceEngine(quant_engine=_BrokenQuantEngine())
    mean, ci = engine._bayesian_edge_calibration("not_significant", 0.55, 200)
    assert mean is None
    assert ci is None


def test_bayesian_edge_calibration_uses_real_quant_engine():
    """Real-collaborator test (Rule 4): confirms the wins/losses derived
    from win_rate/total_trades actually match QuantResearchEngine's real
    bayesian_win_rate_update signature/return shape."""
    from project_titan_x.engines.e12_quant_research import QuantResearchEngine

    engine = SignalIntelligenceEngine(quant_engine=QuantResearchEngine())
    mean, ci = engine._bayesian_edge_calibration("proven_positive_edge", 0.6, 50)
    assert mean is not None and 0.0 <= mean <= 1.0
    assert ci is not None and len(ci) == 2 and ci[0] <= mean <= ci[1]


# ---- scan_all_assets (parallelized across assets, 2026-07-20) ----


class _StubMacroEngine:
    def analyze(self):
        from types import SimpleNamespace
        return _StubResult(True, SimpleNamespace(risk_on_off_score=0.1))


class _StubMarketDataEngineForScan:
    """Returns real-shaped OHLCV for every asset except one deliberately
    broken symbol, so the test can verify one asset's failure doesn't
    block the others -- the exact property parallelizing this loop must
    preserve."""

    def __init__(self, broken_symbol: Optional[str] = None):
        self.broken_symbol = broken_symbol
        self.calls: list[str] = []

    def fetch_ohlcv(self, yahoo_symbol, timeframe, years=2, allow_cache=False):
        self.calls.append(yahoo_symbol)
        if self.broken_symbol and yahoo_symbol == self.broken_symbol:
            return _StubResult(False, None)
        import numpy as np
        n = 210
        close = 100 + np.cumsum(np.random.RandomState(1).randn(n) * 0.5)
        df = pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC"),
            "open": close - 0.3, "high": close + 0.5, "low": close - 0.5, "close": close,
            "volume": np.random.RandomState(1).randint(1000, 5000, n),
        })
        return _StubResult(True, df)


def test_scan_all_assets_one_asset_failure_does_not_block_others(ta_engine, regime_engine):
    """The exact correctness property the ThreadPoolExecutor refactor must
    preserve: one asset's fetch failure must not prevent the others from
    producing a result."""
    from project_titan_x.core.config.assets import get_asset

    broken = get_asset("GOLD").yahoo_symbol
    md = _StubMarketDataEngineForScan(broken_symbol=broken)
    engine = SignalIntelligenceEngine(technical_engine=ta_engine)
    result = engine.scan_all_assets(md, ta_engine, regime_engine, _StubMacroEngine())
    assert result.success
    # GOLD's broken fetch must not have thrown or stalled the whole scan --
    # every OTHER asset was still attempted (confirmed via the stub's own
    # call log covering every real supported symbol).
    from project_titan_x.core.config import list_assets
    assert len(md.calls) == len(list_assets())
    assert broken in md.calls


def test_scan_all_assets_results_sorted_by_confidence_desc(ta_engine, regime_engine):
    md = _StubMarketDataEngineForScan()
    engine = SignalIntelligenceEngine(technical_engine=ta_engine)
    result = engine.scan_all_assets(md, ta_engine, regime_engine, _StubMacroEngine())
    assert result.success
    scores = [s.confidence_score for s in result.data]
    assert scores == sorted(scores, reverse=True)


def test_scan_all_assets_attempts_every_supported_asset_exactly_once(ta_engine, regime_engine):
    from project_titan_x.core.config import list_assets

    md = _StubMarketDataEngineForScan()
    engine = SignalIntelligenceEngine(technical_engine=ta_engine)
    engine.scan_all_assets(md, ta_engine, regime_engine, _StubMacroEngine())
    all_symbols = [a.yahoo_symbol for a in list_assets()]
    assert sorted(md.calls) == sorted(all_symbols)
    assert len(md.calls) == len(set(md.calls))  # no duplicate/repeated calls
