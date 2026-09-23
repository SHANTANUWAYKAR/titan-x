"""
Module: block_bootstrap.py
Description: Block-bootstrap out-of-sample Sharpe distribution for a FIXED
    strategy_fn -- docs/UPGRADE_BRIEF.md Phase 7 item 3 ("CPCV... judge on the
    distribution of OOS paths"), reconciled against Stage 0 per
    docs/PROJECT_AUDIT.md section 11.

    WHY NOT LITERAL CPCV. Combinatorial Purged Cross-Validation (Lopez de
    Prado, AFML 2018 ch.12) was tried first, using purgedcv.
    CombinatorialPurgedCV/reconstruct_paths directly (already a project
    dependency via pbo.py). Empirically verified against two real live
    overrides (BTC-USD_1d, INFY.NS_1d) before writing this module: EVERY
    reconstructed path came back bit-for-bit identical (std=0.0 across all 5
    paths, both assets). This is not a bug -- classical CPCV's path-to-path
    variation comes entirely from re-fitting a model differently per fold; a
    fixed, already-selected strategy_fn has no fitting step, so every fold
    that contains a given historical block produces the EXACT SAME return
    values for it (the block was never re-fit, just replayed), and every
    combinatorial "path" collapses to the same deterministic sequence --
    which is exactly what e27_walk_forward.WalkForwardValidationEngine
    already computes for its own contiguous folds. Confirmed with the user
    before pivoting away from the literal CPCV algorithm.

    WHAT THIS DOES INSTEAD, AND WHY IT'S A FAIR SUBSTITUTE. Partitions
    history into `n_blocks` contiguous blocks, backtests each ONCE and
    independently (never re-run per draw), then draws `n_bootstrap` random
    resamples of `n_blocks` blocks WITH REPLACEMENT, pooling each draw's
    return arrays into one Sharpe estimate. This genuinely varies draw to
    draw (a volatile block can appear zero, one, or several times in a given
    draw), producing a real OOS Sharpe DISTRIBUTION that answers the same
    underlying question the brief wanted ("how much does my OOS estimate
    depend on which slice of history I happened to look at") without
    requiring a fitting step CPCV's machinery assumes. Same "historical-
    bootstrap, no fitted parameters" family of technique this project already
    trusts elsewhere (E23 Forecasting's empirical return-percentile
    bootstrap, E79 Portfolio Simulation's forward Monte Carlo) -- not a new
    kind of claim being introduced here.

    THE ONE REAL BOUNDARY EFFECT, KEPT HONEST. Each block is backtested
    INDEPENDENTLY (a fresh `_simulate` call, position starts flat) -- the
    same "each fold restarts flat" convention e27_walk_forward already uses.
    A position still open at a block's last bar is simply marked-to-market
    there, never fabricated a closing trade -- and each block's own FIRST bar
    has no prior close to diff against, so its return is NaN by construction
    (pandas' `.pct_change()` convention), dropped before computing any
    Sharpe.

    REPORT ONLY. Promotes nothing, gates nothing, changes no existing
    threshold or default. See research/block_bootstrap_analysis.py for a
    real-data CLI runner.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Optional

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from .engine import BacktestingEngine

CAVEATS = [
    "No fitting step exists in this design (strategy_fn is a fixed, "
    "already-selected rule) -- classical CPCV's purge/embargo, which "
    "protect a FIT from leaking across a train/test boundary, do not apply "
    "and are not used. See this module's own docstring for why literal CPCV "
    "was tried and abandoned in favor of this block-bootstrap approach.",
    "Each block is backtested independently and restarts flat (position=0); "
    "a position still open at a block's last bar is marked-to-market there, "
    "never given a fabricated closing trade.",
    "Blocks are drawn WITH REPLACEMENT per bootstrap sample, so a single "
    "unusually good or bad historical period can dominate several draws -- "
    "this measures sensitivity to WHICH periods you sample, not genuine "
    "new out-of-sample evidence beyond what the underlying blocks contain.",
    "Adjacent real-market blocks are not statistically independent (real "
    "serial correlation) -- the same caveat this project's own DSR "
    "diagnostic already states for IS Sharpe.",
]


@dataclass
class BlockBootstrapReport:
    n_blocks: int
    n_bootstrap: int
    n_bars: int
    block_sharpes: list[float] = field(default_factory=list)
    bootstrap_sharpes: list[float] = field(default_factory=list)
    mean_sharpe: float = 0.0
    median_sharpe: float = 0.0
    std_sharpe: float = 0.0
    pct_draws_positive: float = 0.0
    p05_sharpe: float = 0.0
    p95_sharpe: float = 0.0
    caveats: list[str] = field(default_factory=list)
    error: Optional[str] = None


def _contiguous_blocks(n_samples: int, n_blocks: int) -> list[np.ndarray]:
    """Partition `range(n_samples)` into `n_blocks` contiguous, roughly
    equal blocks (remainder distributed to the first few blocks)."""
    size, remainder = divmod(n_samples, n_blocks)
    cursor = 0
    blocks: list[np.ndarray] = []
    for k in range(n_blocks):
        sz = size + (1 if k < remainder else 0)
        blocks.append(np.arange(cursor, cursor + sz, dtype=np.int64))
        cursor += sz
    return blocks


def _sharpe(returns: np.ndarray, periods_per_year: float) -> float:
    clean = returns[np.isfinite(returns)]
    if clean.size < 2 or clean.std() == 0:
        return 0.0
    return float(clean.mean() / clean.std() * np.sqrt(periods_per_year))


def block_bootstrap_validation(
    df: pd.DataFrame,
    strategy_fn: Callable[[pd.DataFrame], pd.Series],
    backtesting_engine: "BacktestingEngine",
    *,
    n_blocks: int = 6,
    n_bootstrap: int = 1000,
    seed: Optional[int] = None,
    capital: float = 10_000.0,
    risk_pct: float = 1.0,
    commission_pct: float = 0.0005,
    slippage_pct: float = 0.0002,
    periods_per_year: float = 252,
) -> BlockBootstrapReport:
    """Block-bootstrap OOS Sharpe distribution for a FIXED strategy_fn (see
    this module's own docstring for the full design rationale, including why
    literal CPCV was tried first and abandoned).

    strategy_fn MUST be built on the "pre-compute the full signal once, then
    slice to whatever df is passed in" contract -- e.g. e51_signals.
    build_strategy_fn's own strategy_fn, or e24_strategy_research.
    _run_one_candidate_worker's inner closure. A strategy_fn that recomputes
    a rolling window fresh from whatever slice it's given would cold-start at
    every block boundary; every real strategy_fn in this codebase already
    avoids this (confirmed directly, not assumed).

    Report only -- promotes nothing, gates nothing, changes no existing
    threshold.
    """
    caveats = list(CAVEATS)
    n_bars = len(df)
    if n_blocks < 2:
        return BlockBootstrapReport(
            n_blocks=n_blocks, n_bootstrap=n_bootstrap, n_bars=n_bars, caveats=caveats,
            error=f"n_blocks must be >= 2, got {n_blocks}",
        )
    if n_bars < n_blocks:
        return BlockBootstrapReport(
            n_blocks=n_blocks, n_bootstrap=n_bootstrap, n_bars=n_bars, caveats=caveats,
            error=f"n_bars={n_bars} is smaller than n_blocks={n_blocks}; needs non-empty blocks",
        )

    blocks = _contiguous_blocks(n_bars, n_blocks)

    # One INDEPENDENT _simulate call per block -- never on a bootstrap draw's
    # raw concatenation of (possibly repeated, non-adjacent) blocks, which
    # would let _simulate's bar loop treat a fake seam between two disjoint
    # historical periods as adjacent bars, corrupting position/equity
    # continuity across it. Each block's own return series is computed ONCE
    # here and reused across every bootstrap draw that samples it.
    block_returns: list[np.ndarray] = []
    block_sharpes: list[float] = []
    for block_idx in blocks:
        block_df = df.iloc[block_idx]
        result = backtesting_engine._simulate(
            block_df, strategy_fn, capital, risk_pct, commission_pct, slippage_pct, periods_per_year,
        )
        equity = result.equity_curve
        if equity is None or len(equity) == 0:
            rets = np.full(len(block_idx), np.nan)
        else:
            rets = pd.Series(equity).pct_change().to_numpy(dtype=float)
            if len(rets) != len(block_idx):
                # A caller's strategy_fn should return one signal per bar in
                # the slice it was given -- if that contract is ever
                # violated, fail this block honestly (all-NaN) rather than
                # silently misaligning positions.
                rets = np.full(len(block_idx), np.nan)
        block_returns.append(rets)
        block_sharpes.append(round(_sharpe(rets, periods_per_year), 4))

    rng = np.random.RandomState(seed)
    bootstrap_sharpes: list[float] = []
    for _ in range(n_bootstrap):
        draw = rng.randint(0, n_blocks, size=n_blocks)
        pooled = np.concatenate([block_returns[b] for b in draw])
        bootstrap_sharpes.append(_sharpe(pooled, periods_per_year))

    arr = np.asarray(bootstrap_sharpes, dtype=float)
    return BlockBootstrapReport(
        n_blocks=n_blocks,
        n_bootstrap=n_bootstrap,
        n_bars=n_bars,
        block_sharpes=block_sharpes,
        bootstrap_sharpes=bootstrap_sharpes,
        mean_sharpe=round(float(arr.mean()), 4),
        median_sharpe=round(float(np.median(arr)), 4),
        std_sharpe=round(float(arr.std(ddof=1)) if arr.size > 1 else 0.0, 4),
        pct_draws_positive=round(float(np.mean(arr > 0) * 100.0), 1),
        p05_sharpe=round(float(np.percentile(arr, 5)), 4),
        p95_sharpe=round(float(np.percentile(arr, 95)), 4),
        caveats=caveats,
    )
