"""
Module: test_pbo.py
Description: Unit tests for the PBO (Probability of Backtest Overfitting)
    wrapper around purgedcv (engines/e26_backtesting/pbo.py). Confirms the
    wrapper discriminates a genuinely overfit search (many noise configs,
    one lucky winner) from a genuinely robust one (a real, persistent
    effect shared across configs) -- the same "construct a case where the
    two are provably different" discipline as E31's CVaR tests.
Author: Shantanu Waykar
Version: 1.0.0
"""

import numpy as np
import pytest

from project_titan_x.engines.e26_backtesting.pbo import probability_of_backtest_overfitting


def test_too_few_usable_candidates_reports_honest_nan():
    report = probability_of_backtest_overfitting([None, [0.01] * 20], n_splits=8)
    assert report.n_configs_used <= 1
    assert np.isnan(report.pbo)
    assert "at least 2" in report.caveats[-1]


def test_none_and_constant_streams_are_dropped_not_zero_filled():
    rng = np.random.RandomState(0)
    real = [rng.normal(0, 0.01, 200) for _ in range(6)]
    streams = [None, [0.0] * 200] + real
    report = probability_of_backtest_overfitting(streams, n_splits=8)
    assert report.n_configs_used == 6
    assert report.n_configs_dropped == 2


def test_pbo_averages_near_chance_for_pure_noise_configs():
    """20 pure-noise configs share no real predictive structure, so no
    config's IS rank should predict its OOS rank -- PBO should average
    close to the 'no better than chance' 0.5 line ACROSS SEEDS. A single
    seed can land anywhere (finite-sample noise on only 20 configs), which
    is exactly why this asserts the multi-seed mean rather than one draw --
    the property PBO's own theory guarantees is the expectation, not any
    single realization."""
    n_obs = 400
    pbos = []
    for seed in range(8):
        rng = np.random.RandomState(seed)
        streams = [rng.normal(0, 0.01, n_obs) for _ in range(20)]
        pbos.append(probability_of_backtest_overfitting(streams, n_splits=16).pbo)
    mean_pbo = float(np.mean(pbos))
    assert 0.3 < mean_pbo < 0.7, f"pure-noise PBO should hover near 0.5, got mean={mean_pbo}"


def test_pbo_is_low_when_one_config_has_a_real_persistent_edge():
    """19 pure-noise configs plus ONE with a real, persistent positive
    drift baked into every bar -- that one should keep winning both IS
    and OOS almost every combination, giving a low PBO."""
    rng = np.random.RandomState(7)
    n_obs = 400
    streams = [rng.normal(0, 0.01, n_obs) for _ in range(19)]
    streams.append(rng.normal(0.01, 0.01, n_obs))         # real, persistent drift
    report = probability_of_backtest_overfitting(streams, n_splits=16)
    assert report.n_configs_used == 20
    assert report.pbo < 0.35


def test_caveats_always_present_and_never_gates_anything():
    rng = np.random.RandomState(1)
    streams = [rng.normal(0, 0.01, 200) for _ in range(5)]
    report = probability_of_backtest_overfitting(streams, n_splits=8)
    assert report.caveats
    assert not hasattr(report, "passed_validation")
