"""
Module: engine.py
Description: Engine 42 -- Confidence Calibration. Master prompt scope:
    "track predicted confidence vs. actual outcome; an 80% confidence
    signal should behave like 80% over time."

    Bins logged trades (e35_performance_analytics owns the trade journal
    itself; this engine reads it via constructor injection, same
    convention as e34) by their confidence_at_entry into buckets, and for
    each bucket compares predicted confidence (bucket midpoint) against
    actual win rate -- plus an overall Brier score, the standard proper
    scoring rule for probabilistic calibration (mean squared error between
    predicted probability and the binary outcome). E12's Bayesian
    win-rate update gives each bucket a credible interval, same
    statistical-honesty pattern e51_signals._bayesian_edge_calibration
    already uses.

    Honest by construction: a bucket with too few trades to say anything
    statistically meaningful is reported as "insufficient_data", never
    silently omitted or padded with a fabricated win rate -- same
    discipline as E51's own edge-gate ("insufficient_data" status).

    No calibration/training step of ITS OWN applies (Rule 3) -- this
    engine MEASURES calibration of another engine's (E51's) confidence
    scores; it has no parameters of its own to fit.

    No knowledge_engine wiring (Rule 2) -- mechanical binning/arithmetic
    on logged numbers, same "no" category as e34/e35.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-07-18
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus
from project_titan_x.engines.e35_performance_analytics.engine import PerformanceAnalyticsEngine

logger = logging.getLogger(__name__)

DEFAULT_BUCKET_WIDTH = 20
DEFAULT_MIN_TRADES_PER_BUCKET = 5


@dataclass
class ConfidenceBucket:
    """One confidence-score bucket's predicted-vs-actual read."""

    bucket_label: str
    bucket_midpoint: float  # 0.0-1.0
    n_trades: int
    status: str  # "calibrated" | "insufficient_data"
    actual_win_rate: Optional[float] = None
    predicted_confidence_mean: Optional[float] = None
    calibration_error: Optional[float] = None  # predicted - actual; positive == overconfident
    bayesian_posterior_mean: Optional[float] = None
    bayesian_credible_interval_90pct: Optional[tuple] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "bucket_label": self.bucket_label,
            "bucket_midpoint": round(self.bucket_midpoint, 4),
            "n_trades": self.n_trades,
            "status": self.status,
            "actual_win_rate": round(self.actual_win_rate, 4) if self.actual_win_rate is not None else None,
            "predicted_confidence_mean": round(self.predicted_confidence_mean, 4) if self.predicted_confidence_mean is not None else None,
            "calibration_error": round(self.calibration_error, 4) if self.calibration_error is not None else None,
            "bayesian_posterior_mean": self.bayesian_posterior_mean,
            "bayesian_credible_interval_90pct": self.bayesian_credible_interval_90pct,
        }


@dataclass
class CalibrationReport:
    """Full calibration read across every confidence bucket."""

    buckets: list[ConfidenceBucket] = field(default_factory=list)
    overall_brier_score: Optional[float] = None
    # Expected Calibration Error (Guo et al. 2017, "On Calibration of
    # Modern Neural Networks" -- the standard single-number calibration
    # summary in the ML/forecasting literature): size-weighted average of
    # each "calibrated"-status bucket's |predicted - actual| gap. Brier
    # score conflates calibration with discrimination/sharpness (a
    # strategy that's always 50% confident and wins 50% of the time is
    # perfectly CALIBRATED but has no discriminative value, and Brier
    # alone doesn't separate those); ECE isolates exactly the "does an
    # 80% confidence signal behave like 80%" question the master prompt
    # scope asks for. None (not 0.0) when there are no calibrated-status
    # buckets to average -- not a fabricated perfect score.
    expected_calibration_error: Optional[float] = None
    n_trades_total: int = 0
    n_trades_with_confidence: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "buckets": [b.to_dict() for b in self.buckets],
            "overall_brier_score": round(self.overall_brier_score, 6) if self.overall_brier_score is not None else None,
            "expected_calibration_error": (
                round(self.expected_calibration_error, 6) if self.expected_calibration_error is not None else None
            ),
            "n_trades_total": self.n_trades_total,
            "n_trades_with_confidence": self.n_trades_with_confidence,
        }


def bucket_label_for_confidence(confidence: int, bucket_width: int = DEFAULT_BUCKET_WIDTH) -> tuple[str, float]:
    """confidence in [0,100] -> (bucket label like '60-80', bucket midpoint
    as a 0.0-1.0 probability). The top bucket absorbs confidence==100 (a
    naive confidence//width would otherwise create a lone empty
    '100-120' bucket)."""
    confidence = max(0, min(100, confidence))
    lower = min((confidence // bucket_width) * bucket_width, 100 - bucket_width)
    upper = lower + bucket_width
    midpoint = (lower + upper) / 2 / 100.0
    return f"{lower}-{upper}", midpoint


def brier_score(predicted_probs, outcomes) -> Optional[float]:
    """Mean squared error between predicted probability and the binary
    outcome -- the standard proper scoring rule for probabilistic
    calibration (0 = perfect, 0.25 = a coin flip predicted with 50%
    confidence, 1.0 = maximally wrong and maximally confident)."""
    if len(predicted_probs) == 0:
        return None
    return float(np.mean([(p - float(o)) ** 2 for p, o in zip(predicted_probs, outcomes)]))


def compute_calibration(
    pairs: list[tuple[int, bool]],
    bucket_width: int = DEFAULT_BUCKET_WIDTH,
    min_trades_per_bucket: int = DEFAULT_MIN_TRADES_PER_BUCKET,
    quant_engine: Optional[Any] = None,
) -> CalibrationReport:
    """pairs: (confidence_at_entry, won) per trade. Pure function -- no
    database access, easy to unit test independent of the trade journal."""
    groups: dict[tuple[str, float], list[tuple[int, bool]]] = defaultdict(list)
    for confidence, won in pairs:
        key = bucket_label_for_confidence(confidence, bucket_width)
        groups[key].append((confidence, won))

    buckets: list[ConfidenceBucket] = []
    for (label, midpoint), items in sorted(groups.items(), key=lambda kv: kv[0][1]):
        n = len(items)
        confidences = [c for c, _ in items]
        predicted_mean = float(np.mean(confidences)) / 100.0

        if n < min_trades_per_bucket:
            buckets.append(
                ConfidenceBucket(
                    bucket_label=label, bucket_midpoint=midpoint, n_trades=n, status="insufficient_data",
                    predicted_confidence_mean=predicted_mean,
                )
            )
            continue

        wins = sum(1 for _, won in items if won)
        actual_win_rate = wins / n
        bayesian_mean, bayesian_ci = None, None
        if quant_engine is not None:
            try:
                result = quant_engine.bayesian_win_rate_update(wins, n - wins)
                if result.success and result.data is not None:
                    bayesian_mean = result.data.posterior_mean
                    bayesian_ci = result.data.credible_interval_90pct
            except Exception as e:
                logger.warning("Bayesian calibration unavailable for bucket %s: %s", label, e)

        buckets.append(
            ConfidenceBucket(
                bucket_label=label, bucket_midpoint=midpoint, n_trades=n, status="calibrated",
                actual_win_rate=actual_win_rate, predicted_confidence_mean=predicted_mean,
                calibration_error=predicted_mean - actual_win_rate,
                bayesian_posterior_mean=bayesian_mean, bayesian_credible_interval_90pct=bayesian_ci,
            )
        )

    overall_brier = brier_score([c / 100.0 for c, _ in pairs], [w for _, w in pairs])
    ece = expected_calibration_error(buckets)
    return CalibrationReport(
        buckets=buckets, overall_brier_score=overall_brier, expected_calibration_error=ece,
        n_trades_with_confidence=len(pairs),
    )


def expected_calibration_error(buckets: list[ConfidenceBucket]) -> Optional[float]:
    """Size-weighted average of |calibration_error| across "calibrated"-
    status buckets only -- an insufficient_data bucket has no
    calibration_error to weigh in. None if no bucket cleared the
    min-trades bar."""
    calibrated = [b for b in buckets if b.status == "calibrated" and b.calibration_error is not None]
    total = sum(b.n_trades for b in calibrated)
    if total == 0:
        return None
    return float(sum(b.n_trades * abs(b.calibration_error) for b in calibrated) / total)


class ConfidenceCalibrationEngine(BaseEngine):
    """
    Confidence Calibration Engine (#42) -- measures whether E51's
    confidence scores actually behave like probabilities against the real,
    logged trade journal (E35). Depends on E35 for the trade read and
    (optionally) E12 for a Bayesian-calibrated per-bucket credible
    interval, same Optional-collaborator convention as every other
    cross-engine dependency on this platform.
    """

    engine_id = "e42_confidence_calibration"
    engine_name = "Confidence Calibration Engine"
    version = "1.0.0"

    def __init__(self, performance_engine: Optional[PerformanceAnalyticsEngine] = None, quant_engine: Optional[Any] = None) -> None:
        super().__init__()
        self._performance_engine = performance_engine or PerformanceAnalyticsEngine()
        self._quant_engine = quant_engine

    def initialize(self) -> EngineResult:
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Confidence Calibration Engine initialized")

    def health_check(self) -> EngineResult:
        return self._performance_engine.health_check()

    def calibration_report(
        self,
        strategy_name: Optional[str] = None,
        bucket_width: int = DEFAULT_BUCKET_WIDTH,
        min_trades_per_bucket: int = DEFAULT_MIN_TRADES_PER_BUCKET,
        limit: int = 20000,
    ) -> EngineResult:
        trades_result = self._performance_engine.list_trades(strategy_name=strategy_name, limit=limit)
        if not trades_result.success:
            return trades_result
        trades = trades_result.data

        pairs = [
            (t["confidence_at_entry"], (t["pnl_r"] or 0.0) > 0)
            for t in trades
            if t.get("confidence_at_entry") is not None
        ]
        if not pairs:
            return EngineResult(
                success=False,
                message="No logged trades have a confidence_at_entry value yet -- nothing to calibrate against",
            )

        report = compute_calibration(pairs, bucket_width, min_trades_per_bucket, self._quant_engine)
        report.n_trades_total = len(trades)
        return EngineResult(success=True, data=report, message=f"Calibration computed from {len(pairs)} trade(s) with a logged confidence score")
