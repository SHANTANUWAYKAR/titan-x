"""
Module: pbo.py
Description: Probability of Backtest Overfitting (PBO) via Combinatorially
    Symmetric Cross-Validation (Bailey, Borwein, Lopez de Prado & Zhu,
    2017) -- REPO_REFERENCE.md Tier 1 (purgedcv).

    WHAT THIS ANSWERS, AND HOW IT DIFFERS FROM STAGE 0. Stage 0
    (research/synthetic_null.py) asks "how often does this SAME grid,
    run against data engineered to have NO edge, produce a false
    winner" -- a synthetic-null false-positive rate. PBO asks a
    different, complementary question of the REAL, already-searched
    grid: "does the configuration that looked best IN-SAMPLE tend to
    rank below the OOS median across many resampled train/test splits
    of the SAME real data". A grid can clear Stage 0's bar (hard for
    pure noise to pass) and still have a high PBO if the search itself
    over-mines this one dataset -- the two diagnostics are not
    redundant, and neither replaces the other.

    WHY purgedcv AND NOT A HAND-ROLLED VERSION. CSCV's combinatorial
    fold enumeration (choose half the blocks as the IS side, replay
    every choice, rank the IS-best against its own OOS complement) is
    easy to get subtly wrong -- off-by-one path reconstruction, a
    flipped rank-vs-logit sign. purgedcv is a real, tested, MIT-licensed
    implementation of the exact Bailey et al. algorithm; reimplementing
    it by hand would replay the reimplementation risk this project
    already avoids elsewhere (see GARCH's own "use the real library for
    real numerical subtlety" precedent in E12's docstring).

    INPUT SHAPE. `return_streams` is one real per-bar return array per
    grid candidate, all sharing the same time axis (same underlying df,
    same IS window) -- exactly what
    `e24_strategy_research.engine._run_one_candidate_worker(...,
    capture_returns=True)` already produces for Stage 0's own
    effective-rank calculation (`deflated_sharpe.trial_geometry`), reused
    here rather than a second bespoke capture path.

    HONESTY. Reported, never gating -- same precedent as
    `BacktestingEngine.monte_carlo_significance_test`'s
    `significant_at_5pct` and `deflated_sharpe`'s own `passed` field:
    neither moves `passed_validation`, and neither does this. Whether
    PBO should ever become a promotion gate is a real threshold-policy
    decision, deliberately left open rather than folded in unvalidated.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

import numpy as np

CAVEATS = [
    "PBO measures whether THIS grid's in-sample-best configuration tends "
    "to rank below the out-of-sample median across resampled splits of the "
    "SAME real data it was searched on -- it is not a test against a "
    "no-edge null (that is Stage 0's synthetic-null role) and does not "
    "correct for serial dependence in the per-bar returns.",
]


@dataclass
class PBOReport:
    n_configs_used: int
    n_configs_dropped: int
    n_splits: int
    n_combos: int
    pbo: float                              # in [0, 1]; > 0.5 means the search mostly fits noise
    slope: float                            # OLS slope of OOS on IS performance for the IS-best config
    caveats: list[str] = field(default_factory=list)


def probability_of_backtest_overfitting(
    return_streams: Sequence[Optional[Sequence[float]]],
    n_splits: int = 16,
) -> PBOReport:
    """PBO via purgedcv's CSCV implementation, from real per-candidate
    return streams a grid search already produced.

    Streams that are None (a candidate whose backtest failed to produce
    an equity curve -- see `_run_one_candidate_worker`'s own
    `capture_returns` docstring) or constant/too-short are dropped
    rather than zero-filled, matching `trial_geometry`'s own "never
    silently poison the analysis with a fabricated stream" discipline.
    """
    n_in = len(return_streams)
    cleaned = []
    for s in return_streams:
        if s is None:
            continue
        arr = np.asarray(s, dtype=float)
        arr = arr[np.isfinite(arr)]
        if arr.size < n_splits or np.std(arr) <= 1e-12:
            continue
        cleaned.append(arr)
    n_dropped = n_in - len(cleaned)

    if len(cleaned) < 2:
        return PBOReport(
            n_configs_used=len(cleaned), n_configs_dropped=n_dropped, n_splits=n_splits,
            n_combos=0, pbo=float("nan"), slope=float("nan"),
            caveats=CAVEATS + [f"only {len(cleaned)} usable candidate(s) out of {n_in}; "
                                "PBO needs at least 2"],
        )

    import purgedcv

    m = min(s.size for s in cleaned)
    mat = np.vstack([s[-m:] for s in cleaned])
    result = purgedcv.probability_of_backtest_overfitting(mat, n_splits=n_splits)
    return PBOReport(
        n_configs_used=len(cleaned), n_configs_dropped=n_dropped, n_splits=n_splits,
        n_combos=int(result.n_combos), pbo=float(result.pbo), slope=float(result.slope),
        caveats=list(CAVEATS),
    )
