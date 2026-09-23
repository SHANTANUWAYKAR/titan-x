"""
Module: test_walk_forward_engine.py
Description: Unit tests for Engine 27 (Walk-Forward Validation).
Author: Shantanu Waykar
Version: 1.0.0
"""

import pytest

from project_titan_x.engines.e27_walk_forward.engine import (
    FoldResult,
    WalkForwardValidationEngine,
)


@pytest.fixture
def engine() -> WalkForwardValidationEngine:
    e = WalkForwardValidationEngine()
    e.initialize()
    return e


def test_health_check(engine):
    assert engine.health_check().success


def test_run_walk_forward_without_signal_engine_fails(engine):
    result = engine.run_walk_forward("SP500")
    assert not result.success
    assert "signal_engine" in result.message


def test_run_walk_forward_unknown_asset_fails():
    class _FakeSignalEngine:
        def build_strategy_fn(self, *a, **k):
            raise AssertionError("should not be called for an unknown asset")

    engine = WalkForwardValidationEngine(signal_engine=_FakeSignalEngine())
    result = engine.run_walk_forward("NOT_A_REAL_ASSET")
    assert not result.success


# ---- _aggregate (pure function, no network) ----


def _fold(sharpe: float, passed: bool, is_sharpe: float = 1.0) -> FoldResult:
    wfe = (sharpe / is_sharpe) if is_sharpe > 0 else None
    return FoldResult(
        fold_index=0, n_bars=300, is_sharpe=is_sharpe, is_trades=10, oos_sharpe=sharpe,
        passed_validation=passed, walk_forward_efficiency=wfe,
    )


def test_aggregate_insufficient_data_below_two_folds(engine):
    report = engine._aggregate("X", "1d", 5, [_fold(1.0, True)])
    assert report.verdict == "insufficient_data"


def test_aggregate_stable_edge_when_full_bar_cleared_most_folds(engine):
    folds = [_fold(1.0, True), _fold(0.8, True), _fold(0.5, True), _fold(-0.2, False)]
    report = engine._aggregate("X", "1d", 4, folds)
    assert report.pass_rate == 0.75
    assert report.verdict == "stable_edge"


def test_aggregate_directionally_consistent_low_sample_when_oos_positive_but_trade_count_low():
    """The exact real finding this engine surfaced for SP500's validated
    Donchian override: consistently positive OOS Sharpe across folds, but
    no individual fold has enough trades to independently clear E26's
    full 30-trade bar -- must NOT be reported as 'no_edge'."""
    folds = [_fold(1.9, False), _fold(0.08, False), _fold(1.5, False), _fold(-0.17, False), _fold(1.5, False)]
    engine = WalkForwardValidationEngine()
    report = engine._aggregate("SP500", "1d", 5, folds)
    assert report.pass_rate == 0.0
    assert report.oos_sharpe_positive_rate == 0.8
    assert report.verdict == "directionally_consistent_low_sample"


def test_aggregate_unstable_edge_when_mixed_and_below_threshold(engine):
    folds = [_fold(1.0, False), _fold(-1.0, False), _fold(-0.5, False), _fold(0.2, False), _fold(-0.3, False)]
    report = engine._aggregate("X", "1d", 5, folds)
    assert report.oos_sharpe_positive_rate < 0.6
    assert report.oos_sharpe_positive_rate > 0
    assert report.verdict == "unstable_edge"


def test_aggregate_no_edge_when_every_fold_negative(engine):
    folds = [_fold(-1.0, False), _fold(-0.5, False), _fold(-0.2, False)]
    report = engine._aggregate("X", "1d", 3, folds)
    assert report.oos_sharpe_positive_rate == 0.0
    assert report.verdict == "no_edge"


# ---- walk_forward_efficiency (Pardo overfitting diagnostic) ----


def test_walk_forward_efficiency_is_oos_over_is_sharpe():
    """Real formula check, not just 'some number comes back': WFE = OOS
    Sharpe / IS Sharpe."""
    folds = [
        _fold(0.5, True, is_sharpe=1.0),   # WFE = 0.5
        _fold(1.0, True, is_sharpe=2.0),   # WFE = 0.5
    ]
    for f in folds:
        assert f.walk_forward_efficiency == pytest.approx(0.5)
    report = WalkForwardValidationEngine._aggregate("X", "1d", 2, folds)
    assert report.mean_walk_forward_efficiency == pytest.approx(0.5)


def test_walk_forward_efficiency_undefined_when_is_sharpe_not_positive():
    """No meaningful in-sample edge to compare OOS against -- must be None,
    not a fabricated or divide-by-near-zero ratio."""
    fold = _fold(0.3, False, is_sharpe=-0.2)
    assert fold.walk_forward_efficiency is None


def test_mean_walk_forward_efficiency_none_when_no_fold_has_positive_is_sharpe():
    folds = [_fold(0.1, False, is_sharpe=-0.5), _fold(-0.2, False, is_sharpe=0.0)]
    report = WalkForwardValidationEngine._aggregate("X", "1d", 2, folds)
    assert report.mean_walk_forward_efficiency is None


def test_mean_walk_forward_efficiency_ignores_undefined_folds():
    """Aggregation must average only the folds where WFE is actually
    defined, not treat an undefined fold as 0."""
    folds = [
        _fold(1.0, True, is_sharpe=1.0),    # WFE = 1.0
        _fold(0.3, False, is_sharpe=-0.1),  # WFE = None -- must be excluded, not counted as 0
    ]
    report = WalkForwardValidationEngine._aggregate("X", "1d", 2, folds)
    assert report.mean_walk_forward_efficiency == pytest.approx(1.0)


# ---- knowledge_context ----


def test_build_knowledge_context_none_without_engine(engine):
    assert engine._build_knowledge_context("SP500", "no_edge") is None


def test_build_knowledge_context_none_for_stable_edge():
    class _StubKnowledge:
        document_store = None

    engine = WalkForwardValidationEngine(knowledge_engine=_StubKnowledge())
    assert engine._build_knowledge_context("SP500", "stable_edge") is None


@pytest.mark.network
def test_run_walk_forward_sp500_end_to_end():
    from project_titan_x.engines.e51_signals.engine import SignalIntelligenceEngine

    engine = WalkForwardValidationEngine(signal_engine=SignalIntelligenceEngine())
    result = engine.run_walk_forward("SP500", timeframe="1d", n_folds=5, years=8)
    assert result.success
    report = result.data
    assert report.n_folds_evaluated >= 2
    assert report.verdict in ("stable_edge", "directionally_consistent_low_sample", "unstable_edge", "no_edge", "insufficient_data")
