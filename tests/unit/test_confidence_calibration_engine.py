"""
Tests for Engine 42 -- Confidence Calibration.

bucket_label_for_confidence/brier_score/compute_calibration are pure
functions and tested directly (no database needed). The engine's own
trade-journal read is tested via a stub PerformanceAnalyticsEngine (fast)
plus one real-collaborator test (Rule 4) against the real E35/E12 engines.
"""

import datetime as dt

import pytest

from project_titan_x.engines.e42_confidence_calibration.engine import (
    CalibrationReport,
    ConfidenceCalibrationEngine,
    brier_score,
    bucket_label_for_confidence,
    compute_calibration,
)
from project_titan_x.engines.e35_performance_analytics.engine import PerformanceAnalyticsEngine


# ---- bucket_label_for_confidence ----

@pytest.mark.parametrize(
    "confidence,expected_label,expected_midpoint",
    [
        (0, "0-20", 0.10),
        (19, "0-20", 0.10),
        (20, "20-40", 0.30),
        (59, "40-60", 0.50),
        (60, "60-80", 0.70),
        (79, "60-80", 0.70),
        (80, "80-100", 0.90),
        (100, "80-100", 0.90),
    ],
)
def test_bucket_label_for_confidence(confidence, expected_label, expected_midpoint):
    label, midpoint = bucket_label_for_confidence(confidence)
    assert label == expected_label
    assert midpoint == pytest.approx(expected_midpoint)


def test_bucket_label_clamps_out_of_range_confidence():
    label, _ = bucket_label_for_confidence(150)
    assert label == "80-100"
    label, _ = bucket_label_for_confidence(-10)
    assert label == "0-20"


# ---- brier_score ----

def test_brier_score_perfect_predictions_is_zero():
    assert brier_score([1.0, 0.0], [True, False]) == pytest.approx(0.0)


def test_brier_score_worst_case_is_one():
    assert brier_score([1.0, 0.0], [False, True]) == pytest.approx(1.0)


def test_brier_score_coin_flip_prediction():
    assert brier_score([0.5, 0.5], [True, False]) == pytest.approx(0.25)


def test_brier_score_empty_returns_none():
    assert brier_score([], []) is None


# ---- compute_calibration ----

def test_compute_calibration_perfectly_calibrated_bucket():
    """7 wins out of 10 trades all at confidence=70 -> actual win rate
    exactly matches predicted (0.70), zero calibration error."""
    pairs = [(70, True)] * 7 + [(70, False)] * 3
    report = compute_calibration(pairs, min_trades_per_bucket=5)
    assert len(report.buckets) == 1
    bucket = report.buckets[0]
    assert bucket.status == "calibrated"
    assert bucket.actual_win_rate == pytest.approx(0.7)
    assert bucket.predicted_confidence_mean == pytest.approx(0.7)
    assert bucket.calibration_error == pytest.approx(0.0, abs=1e-9)


def test_compute_calibration_overconfident_bucket():
    """High predicted confidence (90) but a low actual win rate (30%) ->
    large positive calibration_error (predicted - actual), i.e. overconfident."""
    pairs = [(90, True)] * 3 + [(90, False)] * 7
    report = compute_calibration(pairs, min_trades_per_bucket=5)
    bucket = report.buckets[0]
    assert bucket.actual_win_rate == pytest.approx(0.3)
    assert bucket.calibration_error == pytest.approx(0.6, abs=1e-9)


def test_compute_calibration_insufficient_data_bucket_reports_honestly():
    pairs = [(50, True), (50, False)]  # only 2 trades
    report = compute_calibration(pairs, min_trades_per_bucket=5)
    bucket = report.buckets[0]
    assert bucket.status == "insufficient_data"
    assert bucket.actual_win_rate is None
    assert bucket.n_trades == 2


def test_compute_calibration_multiple_buckets_sorted_by_midpoint():
    pairs = [(10, True)] * 5 + [(90, False)] * 5
    report = compute_calibration(pairs, min_trades_per_bucket=5)
    assert len(report.buckets) == 2
    assert report.buckets[0].bucket_label == "0-20"
    assert report.buckets[1].bucket_label == "80-100"


def test_compute_calibration_overall_brier_score_uses_all_pairs():
    pairs = [(100, True)] * 5 + [(0, False)] * 5  # perfectly calibrated overall
    report = compute_calibration(pairs, min_trades_per_bucket=5)
    assert report.overall_brier_score == pytest.approx(0.0)


def test_expected_calibration_error_perfect_is_zero():
    pairs = [(100, True)] * 5 + [(0, False)] * 5
    report = compute_calibration(pairs, min_trades_per_bucket=5)
    assert report.expected_calibration_error == pytest.approx(0.0, abs=1e-9)


def test_expected_calibration_error_is_size_weighted_average_of_gaps():
    """Two calibrated buckets with different sizes and different gaps --
    ECE must be the TRADE-COUNT-weighted average of |calibration_error|,
    not a plain unweighted mean of the two buckets' gaps."""
    # Bucket "80-100": predicted ~0.9, actual win rate 0.3 -> gap 0.6, n=10
    bucket_a = [(90, True)] * 3 + [(90, False)] * 7
    # Bucket "0-20": predicted ~0.1, actual win rate 0.1 -> gap ~0.0, n=5
    bucket_b = [(10, True)] * 0 + [(10, False)] * 5
    pairs = bucket_a + bucket_b
    report = compute_calibration(pairs, min_trades_per_bucket=5)

    gap_a, n_a = 0.6, 10
    gap_b = abs(0.1 - 0.0)
    n_b = 5
    expected_ece = (n_a * gap_a + n_b * gap_b) / (n_a + n_b)
    assert report.expected_calibration_error == pytest.approx(expected_ece, abs=1e-9)


def test_expected_calibration_error_excludes_insufficient_data_buckets():
    """A bucket that never cleared min_trades_per_bucket has no
    calibration_error and must not be counted -- neither as 0 nor with any
    weight -- in the size-weighted average."""
    calibrated_bucket = [(90, True)] * 3 + [(90, False)] * 7  # n=10, gap=0.6
    tiny_bucket = [(10, True), (10, False)]  # n=2, below min_trades_per_bucket=5
    report = compute_calibration(calibrated_bucket + tiny_bucket, min_trades_per_bucket=5)
    assert any(b.status == "insufficient_data" for b in report.buckets)
    assert report.expected_calibration_error == pytest.approx(0.6, abs=1e-9)


def test_expected_calibration_error_none_when_no_bucket_qualifies():
    pairs = [(50, True), (50, False)]  # only 2 trades, below default min
    report = compute_calibration(pairs, min_trades_per_bucket=5)
    assert report.expected_calibration_error is None


def test_compute_calibration_result_is_calibration_report():
    report = compute_calibration([(50, True), (50, False), (50, True), (50, False), (50, True)], min_trades_per_bucket=5)
    assert isinstance(report, CalibrationReport)


# ---- engine (stub) ----

class _StubResult:
    def __init__(self, success=True, data=None, message=""):
        self.success = success
        self.data = data
        self.message = message


class _StubPerformanceEngine:
    def __init__(self, trades):
        self._trades = trades

    def list_trades(self, strategy_name=None, limit=20000):
        return _StubResult(True, self._trades)

    def health_check(self):
        return _StubResult(True)


_SAMPLE_TRADES = [
    {"confidence_at_entry": 70, "pnl_r": 1.5},
    {"confidence_at_entry": 70, "pnl_r": -1.0},
    {"confidence_at_entry": 70, "pnl_r": 1.0},
    {"confidence_at_entry": 70, "pnl_r": 1.2},
    {"confidence_at_entry": 70, "pnl_r": -0.5},
]


def test_engine_calibration_report_with_stub():
    engine = ConfidenceCalibrationEngine(performance_engine=_StubPerformanceEngine(_SAMPLE_TRADES))
    result = engine.calibration_report(min_trades_per_bucket=5)
    assert result.success
    assert result.data.n_trades_total == 5
    assert result.data.n_trades_with_confidence == 5


def test_engine_no_trades_with_confidence_fails_gracefully():
    trades_without_confidence = [{"confidence_at_entry": None, "pnl_r": 1.0}]
    engine = ConfidenceCalibrationEngine(performance_engine=_StubPerformanceEngine(trades_without_confidence))
    result = engine.calibration_report()
    assert not result.success


class _FailingPerformanceEngine:
    def list_trades(self, strategy_name=None, limit=20000):
        return _StubResult(False, None, "db down")

    def health_check(self):
        return _StubResult(False)


def test_engine_propagates_trade_list_failure():
    engine = ConfidenceCalibrationEngine(performance_engine=_FailingPerformanceEngine())
    result = engine.calibration_report()
    assert not result.success


# ---- engine (real collaborators, Rule 4) ----

@pytest.mark.network
def test_calibration_report_uses_real_performance_and_quant_engines():
    """Real-collaborator test: logs real trades via the real
    PerformanceAnalyticsEngine and computes calibration via the real
    QuantResearchEngine's bayesian_win_rate_update, confirming the field
    names/shapes actually match (not just a stub's assumed shape). Cleans
    up its own rows afterward (CLAUDE.md Rule 4)."""
    from sqlalchemy import delete
    from project_titan_x.core.database.models import Trade
    from project_titan_x.core.database.session import get_db_session
    from project_titan_x.engines.e12_quant_research import QuantResearchEngine

    performance_engine = PerformanceAnalyticsEngine()
    performance_engine.initialize()
    quant_engine = QuantResearchEngine()
    strategy = "test_e42_calibration_real_collab_unique_tag"
    try:
        now = dt.datetime.now(dt.timezone.utc)
        for pnl_r, confidence in [(1.0, 65), (-1.0, 65), (1.5, 65), (1.0, 65), (-0.5, 65)]:
            performance_engine.log_trade(
                symbol="GOLD", direction="long", entry_price=2000.0, exit_price=2010.0,
                entry_time=now, exit_time=now, pnl_r=pnl_r, pnl_percent=pnl_r * 0.01,
                strategy_name=strategy, confidence_at_entry=confidence,
            )
        engine = ConfidenceCalibrationEngine(performance_engine=performance_engine, quant_engine=quant_engine)
        result = engine.calibration_report(strategy_name=strategy, min_trades_per_bucket=5)
        assert result.success
        assert result.data.n_trades_with_confidence == 5
        bucket = result.data.buckets[0]
        assert bucket.status == "calibrated"
        assert bucket.bayesian_posterior_mean is not None
        assert bucket.bayesian_credible_interval_90pct is not None
    finally:
        with get_db_session() as session:
            session.execute(delete(Trade).where(Trade.strategy_name == strategy))
