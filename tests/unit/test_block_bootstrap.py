"""
Module: test_block_bootstrap.py
Description: Unit tests for the block-bootstrap OOS Sharpe distribution
    wrapper (engines/e26_backtesting/block_bootstrap.py) -- confirms the
    block partition is well-formed, the bootstrap distribution is
    deterministic under a fixed seed, and the whole pipeline discriminates a
    genuine planted edge from a genuine random walk -- same "construct a
    provably different case" discipline as test_pbo.py.
Author: Shantanu Waykar
Version: 1.0.0
"""

import numpy as np
import pandas as pd
import pytest

from project_titan_x.engines.e26_backtesting.block_bootstrap import (
    BlockBootstrapReport, _contiguous_blocks, block_bootstrap_validation,
)
from project_titan_x.engines.e26_backtesting.engine import BacktestingEngine


@pytest.fixture
def engine() -> BacktestingEngine:
    e = BacktestingEngine()
    e.initialize()
    return e


def _ohlcv(close: np.ndarray) -> pd.DataFrame:
    n = len(close)
    return pd.DataFrame({
        "timestamp": pd.date_range("2015-01-01", periods=n, freq="D", tz="UTC"),
        "open": close, "high": close * 1.005, "low": close * 0.995, "close": close,
        "volume": [1000] * n,
    })


def _always_long(df: pd.DataFrame) -> pd.Series:
    """A constant signal is already safe under the "pre-computed full
    signal, sliced per caller" contract block_bootstrap_validation requires
    -- slicing a constant produces the same constant, no cold-start risk."""
    return pd.Series(1, index=df.index)


def test_contiguous_blocks_partitions_every_index_exactly_once():
    for n_samples, n_blocks in [(100, 6), (247, 5), (30, 3), (1000, 10)]:
        blocks = _contiguous_blocks(n_samples, n_blocks)
        assert len(blocks) == n_blocks
        all_idx = np.concatenate(blocks)
        np.testing.assert_array_equal(all_idx, np.arange(n_samples))
        sizes = [len(b) for b in blocks]
        assert max(sizes) - min(sizes) <= 1


def test_invalid_n_blocks_reports_honest_error_not_a_crash(engine):
    df = _ohlcv(100 + np.arange(100, dtype=float))
    report = block_bootstrap_validation(df, _always_long, engine, n_blocks=1)
    assert report.error is not None
    assert report.bootstrap_sharpes == []


def test_too_few_bars_reports_honest_error(engine):
    df = _ohlcv(100 + np.arange(3, dtype=float))
    report = block_bootstrap_validation(df, _always_long, engine, n_blocks=6)
    assert report.error is not None


def test_bootstrap_is_deterministic_under_a_fixed_seed(engine):
    df = _ohlcv(100 + np.cumsum(np.random.RandomState(4).normal(0, 0.5, 400)))
    r1 = block_bootstrap_validation(df, _always_long, engine, n_blocks=6, n_bootstrap=200, seed=42)
    r2 = block_bootstrap_validation(df, _always_long, engine, n_blocks=6, n_bootstrap=200, seed=42)
    assert r1.bootstrap_sharpes == r2.bootstrap_sharpes


def test_bootstrap_shows_real_variance_not_a_degenerate_constant(engine):
    """The whole point of the pivot away from literal CPCV: unlike the
    combinatorial-path approach (which collapsed to std=0.0 on real data,
    see block_bootstrap.py's own docstring), resampling blocks WITH
    replacement must show genuine draw-to-draw variance."""
    rng = np.random.RandomState(9)
    n = 600
    close = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.015, n)))
    df = _ohlcv(close)
    report = block_bootstrap_validation(df, _always_long, engine, n_blocks=6, n_bootstrap=500, seed=1)
    assert report.error is None
    assert report.std_sharpe > 0.01, f"expected real bootstrap variance, got std={report.std_sharpe}"
    assert len(set(round(s, 6) for s in report.bootstrap_sharpes)) > 10


def test_planted_edge_shows_a_clearly_positive_bootstrap_distribution(engine):
    """A real, persistent upward drift with tiny noise, held always-long,
    must show a bootstrap Sharpe distribution that sits clearly above zero
    and is mostly positive."""
    rng = np.random.RandomState(11)
    n = 600
    drift = np.linspace(0, 0.6, n)
    noise = rng.normal(0, 0.002, n).cumsum()
    close = 100 * (1 + drift + noise)
    close = np.clip(close, 1, None)
    df = _ohlcv(close)

    report = block_bootstrap_validation(df, _always_long, engine, n_blocks=6, n_bootstrap=500, seed=2)
    assert report.error is None
    assert report.mean_sharpe > 0.5, f"expected a clearly positive mean Sharpe, got {report.mean_sharpe}"
    assert report.pct_draws_positive > 80.0, (
        f"expected most draws positive for a real planted edge, got {report.pct_draws_positive}%"
    )


def test_pure_random_walk_shows_a_bootstrap_distribution_straddling_zero(engine):
    """A driftless random walk, held always-long, has no real edge to find
    -- the bootstrap Sharpe distribution should be centered near zero,
    averaged across seeds since any single random walk can drift either way
    by chance."""
    means = []
    positive_fracs = []
    for seed in range(6):
        rng = np.random.RandomState(seed)
        n = 600
        close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
        df = _ohlcv(close)
        report = block_bootstrap_validation(
            df, _always_long, engine, n_blocks=6, n_bootstrap=500, seed=seed,
        )
        assert report.error is None
        means.append(report.mean_sharpe)
        positive_fracs.append(report.pct_draws_positive)

    avg_mean_sharpe = float(np.mean(means))
    avg_positive_frac = float(np.mean(positive_fracs))
    assert abs(avg_mean_sharpe) < 0.5, f"expected near-zero mean Sharpe on average, got {avg_mean_sharpe}"
    assert 20.0 < avg_positive_frac < 80.0, (
        f"expected draws roughly split between positive/negative, got {avg_positive_frac}% positive"
    )


def test_report_fields_are_internally_consistent(engine):
    df = _ohlcv(100 + np.cumsum(np.random.RandomState(2).normal(0, 0.5, 400)))
    report = block_bootstrap_validation(df, _always_long, engine, n_blocks=6, n_bootstrap=500, seed=3)
    assert report.error is None
    arr = np.asarray(report.bootstrap_sharpes)
    assert report.mean_sharpe == pytest.approx(float(arr.mean()), abs=1e-3)
    assert report.median_sharpe == pytest.approx(float(np.median(arr)), abs=1e-3)
    assert report.p05_sharpe <= report.median_sharpe <= report.p95_sharpe
    assert len(report.block_sharpes) == report.n_blocks
    assert isinstance(report.caveats, list) and len(report.caveats) >= 1
