"""
Module: engine.py
Description: Engine 38 -- Alpha Decay Monitor. Master prompt scope: "track
    performance degradation, statistical significance, regime changes;
    warn when a strategy is losing its edge." Directly serves Core
    Philosophy #7 ("Continuous learning") -- a strategy that worked
    historically is not guaranteed to keep working, and pretending
    otherwise is exactly the complacency this engine exists to catch.

    Splits the logged trade journal (e35_performance_analytics owns it;
    this engine reads it via constructor injection, same convention as
    e34/e42) into a RECENT window and an earlier BASELINE window, reuses
    E35's own summarize() (not a re-implementation -- same formula, same
    R-multiple convention) for each window's KPIs, and uses E12's
    Bayesian win-rate update on both windows to test whether the
    difference is real: decay is only flagged when the recent window's
    90% credible interval for win rate sits ENTIRELY below the baseline
    window's -- a conservative, standard non-overlapping-interval
    significance heuristic, not just "the number went down" (a handful of
    losing trades after a winning streak is expected variance, not decay).

    Honest by construction: both windows must clear min_trades_per_window
    before any verdict is given -- "insufficient_data" otherwise, never a
    verdict from a noisy sample. Same discipline as E42/E51's own
    edge-gate.

    No calibration/training step of ITS OWN applies (Rule 3) -- this
    engine measures degradation in another engine's (E51's) real-world
    performance; it has no parameters of its own to fit.

    No knowledge_engine wiring (Rule 2) -- mechanical window comparison,
    same "no" category as e34/e35/e42.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-07-18
"""

import logging
from dataclasses import dataclass
from typing import Any, Optional

from scipy import stats

from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus
from project_titan_x.engines.e35_performance_analytics.engine import PerformanceAnalyticsEngine, summarize

logger = logging.getLogger(__name__)

DEFAULT_RECENT_WINDOW = 20
DEFAULT_MIN_TRADES_PER_WINDOW = 10
EXPECTANCY_SIGNIFICANCE_ALPHA = 0.10  # matches the win-rate test's own 90% credible interval


@dataclass
class DecayAssessment:
    """Recent-vs-baseline performance comparison for one strategy/symbol."""

    strategy_name: Optional[str]
    status: str  # "insufficient_data" | "stable" | "decay_detected" | "improving"
    decay_detected: bool
    message: str
    baseline_n_trades: int = 0
    recent_n_trades: int = 0
    baseline_expectancy_r: Optional[float] = None
    recent_expectancy_r: Optional[float] = None
    baseline_win_rate: Optional[float] = None
    recent_win_rate: Optional[float] = None
    baseline_bayesian_ci: Optional[tuple] = None
    recent_bayesian_ci: Optional[tuple] = None
    # Welch's t-test (unequal-variance two-sample t-test -- appropriate
    # here since the recent/baseline windows can differ in both size and
    # variance) on raw pnl_r, recent vs baseline: catches decay the
    # win-rate test structurally cannot -- a strategy can keep winning
    # just as OFTEN while each win shrinks and each loss grows (declining
    # expectancy with a flat win rate), which no win-rate-only test would
    # ever flag. None when scipy's test itself couldn't run (e.g.
    # degenerate zero-variance sample), not a fabricated p-value.
    expectancy_p_value: Optional[float] = None
    expectancy_decay_detected: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_name": self.strategy_name,
            "status": self.status,
            "decay_detected": self.decay_detected,
            "message": self.message,
            "baseline_n_trades": self.baseline_n_trades,
            "recent_n_trades": self.recent_n_trades,
            "baseline_expectancy_r": round(self.baseline_expectancy_r, 4) if self.baseline_expectancy_r is not None else None,
            "recent_expectancy_r": round(self.recent_expectancy_r, 4) if self.recent_expectancy_r is not None else None,
            "baseline_win_rate": round(self.baseline_win_rate, 4) if self.baseline_win_rate is not None else None,
            "recent_win_rate": round(self.recent_win_rate, 4) if self.recent_win_rate is not None else None,
            "baseline_bayesian_ci": self.baseline_bayesian_ci,
            "recent_bayesian_ci": self.recent_bayesian_ci,
            "expectancy_p_value": round(self.expectancy_p_value, 4) if self.expectancy_p_value is not None else None,
            "expectancy_decay_detected": self.expectancy_decay_detected,
        }


def assess_decay_from_trades(
    trades: list[dict[str, Any]],
    quant_engine: Optional[Any],
    strategy_name: Optional[str] = None,
    recent_window: int = DEFAULT_RECENT_WINDOW,
    min_trades_per_window: int = DEFAULT_MIN_TRADES_PER_WINDOW,
) -> DecayAssessment:
    """Pure(ish) core logic -- takes an already-fetched, most-recent-first
    trade list (E35.list_trades' own ordering) so it's testable without a
    database. quant_engine is used for the Bayesian significance test;
    None skips that specific check (falls back to a simple mean
    comparison, best-effort, same convention as every other optional
    collaborator on this platform)."""
    recent = trades[:recent_window]
    baseline = trades[recent_window:]

    if len(recent) < min_trades_per_window or len(baseline) < min_trades_per_window:
        return DecayAssessment(
            strategy_name=strategy_name, status="insufficient_data", decay_detected=False,
            message=(
                f"Need at least {min_trades_per_window} trades in both the recent and baseline windows "
                f"(have {len(recent)} recent, {len(baseline)} baseline) -- not enough to say anything meaningful yet."
            ),
            baseline_n_trades=len(baseline), recent_n_trades=len(recent),
        )

    recent_pnl_r = [t["pnl_r"] or 0.0 for t in recent]
    recent_pnl_pct = [t["pnl_percent"] or 0.0 for t in recent]
    baseline_pnl_r = [t["pnl_r"] or 0.0 for t in baseline]
    baseline_pnl_pct = [t["pnl_percent"] or 0.0 for t in baseline]

    recent_summary = summarize(recent_pnl_r, recent_pnl_pct)
    baseline_summary = summarize(baseline_pnl_r, baseline_pnl_pct)

    recent_ci, baseline_ci = None, None
    win_rate_status = "stable"
    win_rate_decay = win_rate_improving = False
    if quant_engine is not None:
        try:
            recent_wins = sum(1 for r in recent_pnl_r if r > 0)
            baseline_wins = sum(1 for r in baseline_pnl_r if r > 0)
            recent_result = quant_engine.bayesian_win_rate_update(recent_wins, len(recent) - recent_wins)
            baseline_result = quant_engine.bayesian_win_rate_update(baseline_wins, len(baseline) - baseline_wins)
            if recent_result.success and baseline_result.success:
                recent_ci = recent_result.data.credible_interval_90pct
                baseline_ci = baseline_result.data.credible_interval_90pct
                if recent_ci[1] < baseline_ci[0]:
                    win_rate_status, win_rate_decay = "decay_detected", True
                elif recent_ci[0] > baseline_ci[1]:
                    win_rate_status, win_rate_improving = "improving", True
        except Exception as e:
            logger.warning("Bayesian decay significance test unavailable: %s", e)

    # Welch's t-test on raw pnl_r: catches EXPECTANCY decay a win-rate-only
    # test structurally cannot (same win rate, shrinking edge per trade --
    # see DecayAssessment.expectancy_p_value's own docstring).
    expectancy_p_value: Optional[float] = None
    expectancy_decay = expectancy_improving = False
    try:
        t_stat, expectancy_p_value = stats.ttest_ind(recent_pnl_r, baseline_pnl_r, equal_var=False)
        significant = expectancy_p_value < EXPECTANCY_SIGNIFICANCE_ALPHA
        if significant and recent_summary.expectancy_r < baseline_summary.expectancy_r:
            expectancy_decay = True
        elif significant and recent_summary.expectancy_r > baseline_summary.expectancy_r:
            expectancy_improving = True
    except Exception as e:
        logger.warning("Expectancy decay significance test unavailable: %s", e)

    decay_detected = win_rate_decay or expectancy_decay
    if decay_detected:
        status = "decay_detected"
    elif win_rate_improving or expectancy_improving:
        status = "improving"
    else:
        status = "stable"

    reasons = []
    if win_rate_decay:
        reasons.append(
            f"win-rate credible interval ({recent_ci[0]:.1%}-{recent_ci[1]:.1%}) sits entirely below "
            f"the baseline's ({baseline_ci[0]:.1%}-{baseline_ci[1]:.1%})"
        )
    if expectancy_decay:
        reasons.append(
            f"expectancy declined from {baseline_summary.expectancy_r:.3f}R to {recent_summary.expectancy_r:.3f}R "
            f"(Welch's t-test p={expectancy_p_value:.3f})"
        )
    if decay_detected:
        message = (
            f"{'; '.join(reasons)} -- this looks like real degradation, not noise. "
            "Worth reviewing whether this strategy/asset combination still has a real edge."
        )
    elif status == "improving":
        message = "Recent performance is statistically better than the baseline window -- no decay detected."
    else:
        message = "No statistically significant difference between recent and baseline performance."

    return DecayAssessment(
        strategy_name=strategy_name, status=status, decay_detected=decay_detected, message=message,
        baseline_n_trades=len(baseline), recent_n_trades=len(recent),
        baseline_expectancy_r=baseline_summary.expectancy_r, recent_expectancy_r=recent_summary.expectancy_r,
        baseline_win_rate=baseline_summary.win_rate, recent_win_rate=recent_summary.win_rate,
        baseline_bayesian_ci=baseline_ci, recent_bayesian_ci=recent_ci,
        expectancy_p_value=float(expectancy_p_value) if expectancy_p_value is not None else None,
        expectancy_decay_detected=expectancy_decay,
    )


class AlphaDecayMonitorEngine(BaseEngine):
    """
    Alpha Decay Monitor Engine (#38) -- compares a strategy's recent
    logged performance against its own earlier baseline, flagging
    statistically real degradation (not just a losing streak) via
    non-overlapping Bayesian credible intervals. Depends on E35 for the
    trade journal and E12 for the significance test, same
    Optional-collaborator convention as every other cross-engine
    dependency on this platform.
    """

    engine_id = "e38_alpha_decay_monitor"
    engine_name = "Alpha Decay Monitor Engine"
    version = "1.0.0"

    def __init__(self, performance_engine: Optional[PerformanceAnalyticsEngine] = None, quant_engine: Optional[Any] = None) -> None:
        super().__init__()
        self._performance_engine = performance_engine or PerformanceAnalyticsEngine()
        self._quant_engine = quant_engine

    def initialize(self) -> EngineResult:
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Alpha Decay Monitor Engine initialized")

    def health_check(self) -> EngineResult:
        return self._performance_engine.health_check()

    def assess_decay(
        self,
        strategy_name: Optional[str] = None,
        recent_window: int = DEFAULT_RECENT_WINDOW,
        min_trades_per_window: int = DEFAULT_MIN_TRADES_PER_WINDOW,
        limit: int = 20000,
    ) -> EngineResult:
        trades_result = self._performance_engine.list_trades(strategy_name=strategy_name, limit=limit)
        if not trades_result.success:
            return trades_result
        assessment = assess_decay_from_trades(
            trades_result.data, self._quant_engine, strategy_name, recent_window, min_trades_per_window
        )
        return EngineResult(success=True, data=assessment, message=assessment.message)
