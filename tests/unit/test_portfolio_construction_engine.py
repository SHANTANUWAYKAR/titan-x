"""
Tests for Engine 31 -- Portfolio Construction.

Every method is a pure function of a covariance matrix/return series (no
network/database dependency), so these tests exercise real mathematical
properties directly -- e.g. risk parity on an uncorrelated covariance
matrix has a known closed-form solution (inverse-volatility weighting),
which is a much stronger check than merely "it runs."
"""

import numpy as np
import pytest

from project_titan_x.engines.e31_portfolio_construction.engine import (
    BlackLittermanResult,
    EfficientFrontierResult,
    KellyGrowthResult,
    NCOResult,
    PortfolioConstructionEngine,
    RiskfolioOptimizationResult,
    RISKFOLIO_MEASURES,
    RiskParityResult,
    TailRiskWeightsResult,
    VolatilityTargetResult,
    WeightsResult,
    black_litterman_posterior,
    cdar_minimizing_weights,
    covariance_matrix_from_returns,
    cvar_minimizing_weights,
    efficient_frontier,
    historical_cdar,
    historical_cvar,
    implied_equilibrium_returns,
    kelly_growth_weights,
    leverage_for_target_vol,
    max_sharpe_weights,
    min_variance_weights,
    nco_weights,
    portfolio_return,
    portfolio_volatility,
    risk_contributions,
    riskfolio_optimize_weights,
    risk_parity_weights,
    scale_weights_to_target_vol,
)


# ---- covariance_matrix_from_returns ----

def test_covariance_matrix_from_returns_basic():
    returns = {"A": [0.01, 0.02, -0.01, 0.03], "B": [0.02, 0.01, 0.00, 0.01]}
    symbols, cov = covariance_matrix_from_returns(returns)
    assert symbols == ["A", "B"]
    assert cov.shape == (2, 2)
    assert cov[0, 1] == cov[1, 0]  # symmetric


def test_covariance_matrix_from_returns_needs_at_least_2_symbols():
    with pytest.raises(ValueError):
        covariance_matrix_from_returns({"A": [0.01, 0.02]})


def test_covariance_matrix_from_returns_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        covariance_matrix_from_returns({"A": [0.01, 0.02, 0.03], "B": [0.01, 0.02]})


def test_covariance_matrix_from_returns_shrinkage_defaults_off_and_matches_sample_cov():
    """use_shrinkage=False (the default) must behave EXACTLY as before --
    no behavior change for any existing caller."""
    rng = np.random.default_rng(0)
    returns = {"A": rng.normal(0, 0.01, 200).tolist(), "B": rng.normal(0, 0.01, 200).tolist()}
    symbols_default, cov_default = covariance_matrix_from_returns(returns)
    symbols_explicit, cov_explicit_off = covariance_matrix_from_returns(returns, use_shrinkage=False)
    assert symbols_default == symbols_explicit
    np.testing.assert_array_almost_equal(cov_default, cov_explicit_off)


def test_covariance_matrix_from_returns_shrinkage_true_differs_from_sample_and_stays_valid():
    rng = np.random.default_rng(1)
    returns = {
        "A": rng.normal(0, 0.01, 60).tolist(),
        "B": rng.normal(0, 0.01, 60).tolist(),
        "C": rng.normal(0, 0.01, 60).tolist(),
    }
    _, cov_sample = covariance_matrix_from_returns(returns, use_shrinkage=False)
    _, cov_shrunk = covariance_matrix_from_returns(returns, use_shrinkage=True)
    assert cov_shrunk.shape == cov_sample.shape
    # Shrinkage pulls off-diagonal terms toward zero and is a genuinely
    # different matrix from plain sample covariance on real noisy data --
    # not a no-op.
    assert not np.allclose(cov_sample, cov_shrunk)
    # A real covariance matrix (shrunk or not) must stay symmetric and
    # positive semi-definite (all eigenvalues >= 0, up to float tolerance).
    assert np.allclose(cov_shrunk, cov_shrunk.T)
    eigenvalues = np.linalg.eigvalsh(cov_shrunk)
    assert (eigenvalues >= -1e-10).all()


def test_min_variance_weights_valid_with_shrunk_covariance():
    """The shrunk covariance must be a drop-in replacement everywhere a
    plain cov_matrix is accepted -- min_variance_weights takes a raw
    matrix, so it shouldn't care which path produced it."""
    rng = np.random.default_rng(2)
    returns = {s: rng.normal(0, 0.01, 80).tolist() for s in ["A", "B", "C", "D"]}
    _, cov_shrunk = covariance_matrix_from_returns(returns, use_shrinkage=True)
    weights = min_variance_weights(cov_shrunk, long_only=True)
    assert weights.sum() == pytest.approx(1.0, abs=1e-6)
    assert (weights >= -1e-9).all()


# ---- min_variance_weights ----

def test_min_variance_weights_unconstrained_sums_to_one():
    cov = np.array([[0.04, 0.01], [0.01, 0.09]])
    w = min_variance_weights(cov, long_only=False)
    assert w.sum() == pytest.approx(1.0)


def test_min_variance_weights_long_only_sums_to_one_and_nonnegative():
    cov = np.array([[0.04, 0.01], [0.01, 0.09]])
    w = min_variance_weights(cov, long_only=True)
    assert w.sum() == pytest.approx(1.0, abs=1e-4)
    assert all(x >= -1e-8 for x in w)


def test_min_variance_weights_rejects_non_square_cov():
    with pytest.raises(ValueError):
        min_variance_weights(np.array([[0.04, 0.01, 0.0], [0.01, 0.09, 0.0]]))


def test_min_variance_weights_long_only_actually_optimizes_at_real_world_variance_scale():
    """Regression test: caught live against real market data (GOLD/SILVER/
    BTCUSD/EURUSD, real daily-return variances ~1e-4 to 1e-3) where SLSQP's
    default ftol=1e-6 made it report "converged" after a single iteration
    sitting exactly at the equal-weight starting point x0, never actually
    searching -- toy-scale covariances (~0.01-0.09, as in the other tests
    above) never triggered this because the default ftol is calibrated for
    O(1)-magnitude objectives. A low-variance asset here must get MORE
    weight than a high-variance, uncorrelated one -- equal weighting is not
    the min-variance answer at this scale."""
    cov = np.array([
        [1.15e-04, 0.0, 0.0],
        [0.0, 1.21e-03, 0.0],  # ~10x the variance of asset 0
        [0.0, 0.0, 2.82e-05],  # lowest variance -- should dominate the allocation
    ])
    w = min_variance_weights(cov, long_only=True)
    assert not np.allclose(w, [1 / 3, 1 / 3, 1 / 3], atol=1e-3), "optimizer must not be stuck at its starting guess"
    assert w[2] > w[0] > w[1]  # lowest-variance asset gets the most weight, highest gets the least
    assert portfolio_volatility(w, cov) < portfolio_volatility([1 / 3, 1 / 3, 1 / 3], cov)


# ---- max_sharpe_weights ----

def test_max_sharpe_weights_sums_to_one():
    cov = np.array([[0.04, 0.0], [0.0, 0.09]])
    means = [0.10, 0.05]
    w = max_sharpe_weights(means, cov)
    assert w.sum() == pytest.approx(1.0)


def test_max_sharpe_weights_degenerate_all_zero_excess_raises():
    cov = np.array([[0.04, 0.0], [0.0, 0.09]])
    means = [0.0, 0.0]
    with pytest.raises(ValueError):
        max_sharpe_weights(means, cov, risk_free_rate=0.0)


# ---- portfolio_return / portfolio_volatility ----

def test_portfolio_return_is_weighted_mean():
    assert portfolio_return([0.5, 0.5], [0.10, 0.20]) == pytest.approx(0.15)


def test_portfolio_volatility_matches_manual_calc():
    cov = np.array([[0.04, 0.0], [0.0, 0.09]])
    w = [0.5, 0.5]
    expected = np.sqrt(0.25 * 0.04 + 0.25 * 0.09)
    assert portfolio_volatility(w, cov) == pytest.approx(expected)


# ---- efficient_frontier ----

def test_efficient_frontier_returns_expected_structure():
    cov = np.array([[0.04, 0.01], [0.01, 0.09]])
    means = [0.08, 0.12]
    frontier = efficient_frontier(means, cov, n_points=5, long_only=True)
    assert len(frontier) == 5
    for point in frontier:
        assert set(point.keys()) == {"target_return", "volatility", "weights"}
        assert point["volatility"] >= 0


def test_efficient_frontier_volatility_generally_increases_with_target_return():
    """Not strictly monotonic in every pathological case, but for a normal
    2-asset frontier, higher target return should require at least as much
    volatility as the min-variance point."""
    cov = np.array([[0.04, 0.0], [0.0, 0.09]])
    means = [0.05, 0.15]
    frontier = efficient_frontier(means, cov, n_points=10, long_only=True)
    vols = [p["volatility"] for p in frontier]
    assert vols[-1] >= vols[0]


# ---- risk_contributions / risk_parity_weights ----

def test_risk_contributions_sum_to_portfolio_volatility():
    cov = np.array([[0.04, 0.01], [0.01, 0.09]])
    w = [0.6, 0.4]
    rc = risk_contributions(w, cov)
    assert float(np.sum(rc)) == pytest.approx(portfolio_volatility(w, cov))


def test_risk_parity_uncorrelated_assets_matches_inverse_volatility_closed_form():
    """For UNCORRELATED assets, equal risk contribution has a known closed
    form: w_i proportional to 1/std_i. variances [0.01, 0.04, 0.09] ->
    stds [0.1, 0.2, 0.3] -> weights proportional to [10, 5, 3.333]."""
    cov = np.diag([0.01, 0.04, 0.09])
    w = risk_parity_weights(cov)
    expected_raw = np.array([1 / 0.1, 1 / 0.2, 1 / 0.3])
    expected = expected_raw / expected_raw.sum()
    assert w == pytest.approx(expected, abs=1e-3)


def test_risk_parity_weights_sum_to_one():
    cov = np.array([[0.04, 0.015, 0.01], [0.015, 0.09, 0.02], [0.01, 0.02, 0.16]])
    w = risk_parity_weights(cov)
    assert w.sum() == pytest.approx(1.0, abs=1e-4)


def test_risk_parity_produces_equal_risk_contributions():
    cov = np.array([[0.04, 0.015, 0.01], [0.015, 0.09, 0.02], [0.01, 0.02, 0.16]])
    w = risk_parity_weights(cov)
    rc = risk_contributions(w, cov)
    assert rc[0] == pytest.approx(rc[1], abs=1e-3)
    assert rc[1] == pytest.approx(rc[2], abs=1e-3)


# ---- Black-Litterman ----

def test_implied_equilibrium_returns_matches_formula():
    cov = np.array([[0.04, 0.0], [0.0, 0.09]])
    w = [0.5, 0.5]
    pi = implied_equilibrium_returns(w, cov, risk_aversion=2.0)
    expected = 2.0 * cov @ np.array(w)
    assert pi == pytest.approx(expected)


def test_black_litterman_posterior_moves_toward_a_strong_bullish_view():
    """A single, high-confidence (tiny omega) bullish view on asset 0 should
    pull that asset's posterior return meaningfully above its prior
    equilibrium return."""
    cov = np.array([[0.04, 0.01], [0.01, 0.09]])
    market_weights = [0.5, 0.5]
    P = [[1, 0]]  # a view purely on asset 0
    Q = [0.30]  # a strong 30% view, well above any reasonable equilibrium prior
    result = black_litterman_posterior(market_weights, cov, P, Q, omega=[[0.0001]])
    assert result["posterior_returns"][0] > result["prior_equilibrium_returns"][0]


def test_black_litterman_posterior_barely_moves_with_huge_view_uncertainty():
    """A view with enormous uncertainty (huge omega) should barely shift the
    posterior away from the prior -- the view is effectively ignored."""
    cov = np.array([[0.04, 0.01], [0.01, 0.09]])
    market_weights = [0.5, 0.5]
    P = [[1, 0]]
    Q = [0.30]
    result = black_litterman_posterior(market_weights, cov, P, Q, omega=[[1e6]])
    assert result["posterior_returns"][0] == pytest.approx(result["prior_equilibrium_returns"][0], abs=1e-3)


def test_black_litterman_rejects_mismatched_P_and_Q():
    cov = np.array([[0.04, 0.01], [0.01, 0.09]])
    with pytest.raises(ValueError):
        black_litterman_posterior([0.5, 0.5], cov, P=[[1, 0], [0, 1]], Q=[0.1])


# ---- volatility targeting ----

def test_leverage_for_target_vol_basic():
    assert leverage_for_target_vol(current_vol=0.10, target_vol=0.20) == pytest.approx(2.0)


def test_leverage_for_target_vol_capped_at_max_leverage():
    assert leverage_for_target_vol(current_vol=0.01, target_vol=1.0, max_leverage=3.0) == pytest.approx(3.0)


def test_leverage_for_target_vol_rejects_nonpositive_current_vol():
    with pytest.raises(ValueError):
        leverage_for_target_vol(current_vol=0.0, target_vol=0.1)


def test_scale_weights_to_target_vol_hits_target_when_not_leverage_capped():
    cov = np.array([[0.04, 0.0], [0.0, 0.09]])
    w = [0.5, 0.5]
    result = scale_weights_to_target_vol(w, cov, target_vol=0.10)
    scaled_vol = portfolio_volatility(result["scaled_weights"], cov)
    assert scaled_vol == pytest.approx(0.10, abs=1e-6)


# ---- historical_cvar / historical_cdar / cvar_minimizing_weights / cdar_minimizing_weights ----

def _synthetic_returns(n_periods: int = 500, seed: int = 7) -> np.ndarray:
    """Two assets, T x 2: asset 0 is calm (small, symmetric noise), asset
    1 has the SAME mean/std day-to-day but occasional large negative
    shocks (fat left tail) -- CVaR/CDaR should clearly prefer asset 0
    despite both having near-identical ordinary variance, which is
    exactly the real-world case variance-based optimization can't see
    and tail-risk optimization is built for."""
    rng = np.random.RandomState(seed)
    calm = rng.normal(0.0005, 0.01, n_periods)
    risky = rng.normal(0.0005, 0.01, n_periods)
    shock_idx = rng.choice(n_periods, size=n_periods // 40, replace=False)
    risky[shock_idx] -= 0.08  # occasional sharp drawdowns, same mean/std otherwise
    return np.column_stack([calm, risky])


def test_historical_cvar_all_in_worse_asset_exceeds_all_in_better_asset():
    returns = _synthetic_returns()
    cvar_calm = historical_cvar([1.0, 0.0], returns, alpha=0.95)
    cvar_risky = historical_cvar([0.0, 1.0], returns, alpha=0.95)
    assert cvar_risky > cvar_calm  # the fat-tailed asset's CVaR must be clearly worse


def test_historical_cvar_matches_hand_computed_value_on_a_tiny_example():
    # Single asset, weight=1: CVaR is just the mean of the worst 20% of losses.
    returns = np.array([[0.05], [-0.10], [0.02], [-0.20], [0.01]])
    result = historical_cvar([1.0], returns, alpha=0.8)
    losses = -returns[:, 0]  # [-0.05, 0.10, -0.02, 0.20, -0.01]
    var = np.percentile(losses, 80)
    expected = losses[losses >= var].mean()
    assert result == pytest.approx(expected)


def test_historical_cdar_all_in_worse_asset_exceeds_all_in_better_asset():
    returns = _synthetic_returns()
    cdar_calm = historical_cdar([1.0, 0.0], returns, alpha=0.95)
    cdar_risky = historical_cdar([0.0, 1.0], returns, alpha=0.95)
    assert cdar_risky > cdar_calm


def test_historical_cdar_zero_for_a_monotonically_rising_path():
    returns = np.full((50, 1), 0.001)  # steady gains, never a drawdown
    result = historical_cdar([1.0], returns, alpha=0.95)
    assert result == pytest.approx(0.0, abs=1e-9)


def test_cvar_minimizing_weights_prefers_the_calmer_asset():
    returns = _synthetic_returns()
    weights = cvar_minimizing_weights(returns, alpha=0.95)
    assert weights[0] > weights[1]  # allocates more to the fat-tail-free asset
    assert weights.sum() == pytest.approx(1.0)
    # And the resulting CVaR must genuinely beat an equal-weight portfolio.
    optimized_cvar = historical_cvar(weights, returns, alpha=0.95)
    equal_weight_cvar = historical_cvar([0.5, 0.5], returns, alpha=0.95)
    assert optimized_cvar < equal_weight_cvar


def test_cdar_minimizing_weights_prefers_the_calmer_asset():
    returns = _synthetic_returns()
    weights = cdar_minimizing_weights(returns, alpha=0.95)
    assert weights[0] > weights[1]
    assert weights.sum() == pytest.approx(1.0)


def test_cvar_minimizing_weights_rejects_shape_mismatch():
    returns = _synthetic_returns()
    with pytest.raises(ValueError):
        historical_cvar([1.0, 0.0, 0.0], returns, alpha=0.95)  # 3 weights, 2 assets


# ---- Kelly (log-growth) optimization -- Riskfolio-Lib, REPO_REFERENCE.md Tier 3 ----

def _drift_returns(n_periods: int = 400, seed: int = 11) -> tuple[np.ndarray, list[str]]:
    """Two assets sharing the SAME variance but asset 1 has real, persistent
    positive drift -- Kelly growth optimization should tilt toward it, since
    log-growth (unlike a pure Sharpe/variance objective at equal vol) rewards
    the asset that actually compounds wealth faster."""
    rng = np.random.RandomState(seed)
    flat = rng.normal(0.0000, 0.01, n_periods)
    drifting = rng.normal(0.0020, 0.01, n_periods)
    return np.column_stack([flat, drifting]), ["FLAT", "DRIFT"]


def test_kelly_growth_weights_tilts_toward_the_real_drift_asset():
    returns, symbols = _drift_returns()
    weights, expected_log_growth = kelly_growth_weights(returns, symbols, kelly="exact")
    assert weights.sum() == pytest.approx(1.0, abs=1e-4)
    assert weights[1] > weights[0]
    assert expected_log_growth > 0


def test_kelly_growth_weights_rejects_symbol_count_mismatch():
    returns, _ = _drift_returns()
    with pytest.raises(ValueError, match="return columns"):
        kelly_growth_weights(returns, ["ONLY_ONE"])


def test_engine_kelly_growth_optimization_returns_result(engine):
    returns, symbols = _drift_returns()
    result = engine.kelly_growth_optimization(symbols, returns)
    assert result.success
    assert isinstance(result.data, KellyGrowthResult)
    assert result.data.symbols == symbols
    assert sum(result.data.weights) == pytest.approx(1.0, abs=1e-4)


# ---- General Riskfolio-Lib optimizer -- any risk measure, Tier 3 ----

@pytest.mark.parametrize("rm", ["MV", "CVaR", "EVaR", "UCI", "SLPM", "MDD", "CDaR"])
def test_riskfolio_optimize_weights_across_representative_measures(rm):
    """A real, distinct sample of RISKFOLIO_MEASURES (not all ~20 -- see
    the function's own docstring) -- every one must return a real,
    long-only, fully-invested weight vector and a finite risk value."""
    returns = _synthetic_returns()
    weights, risk_value = riskfolio_optimize_weights(returns, ["calm", "risky"], rm=rm)
    assert weights.sum() == pytest.approx(1.0, abs=1e-3)
    assert (weights >= -1e-6).all()
    assert np.isfinite(risk_value)
    assert risk_value >= 0


def test_riskfolio_optimize_weights_prefers_the_calmer_asset_under_tail_measures():
    """Same fat-tailed-vs-calm construction as the CVaR/CDaR tests above --
    a tail-sensitive Riskfolio-Lib measure should show the same real
    qualitative behavior as this module's own hand-built CVaR/CDaR."""
    returns = _synthetic_returns()
    for rm in ["CVaR", "EVaR", "CDaR"]:
        weights, _ = riskfolio_optimize_weights(returns, ["calm", "risky"], rm=rm)
        assert weights[0] > weights[1], f"{rm} did not prefer the calmer asset"


def test_riskfolio_optimize_weights_rejects_unknown_measure():
    returns = _synthetic_returns()
    with pytest.raises(ValueError, match="RISKFOLIO_MEASURES"):
        riskfolio_optimize_weights(returns, ["calm", "risky"], rm="NOT_A_REAL_MEASURE")


def test_riskfolio_optimize_weights_rejects_symbol_count_mismatch():
    returns = _synthetic_returns()
    with pytest.raises(ValueError, match="return columns"):
        riskfolio_optimize_weights(returns, ["only_one"])


def test_engine_riskfolio_optimization_returns_result(engine):
    returns = _synthetic_returns()
    result = engine.riskfolio_optimization(["calm", "risky"], returns, rm="EVaR")
    assert result.success
    assert isinstance(result.data, RiskfolioOptimizationResult)
    assert result.data.risk_measure == "EVaR"
    assert sum(result.data.weights) == pytest.approx(1.0, abs=1e-3)


def test_engine_riskfolio_optimization_surfaces_invalid_measure_as_failure(engine):
    returns = _synthetic_returns()
    result = engine.riskfolio_optimization(["calm", "risky"], returns, rm="NOT_A_REAL_MEASURE")
    assert not result.success


# ---- Nested Clustered Optimization (HCPortfolio), Tier 3 ----
# NCO needs >=3 assets -- Riskfolio-Lib's own optimal-cluster-count gap
# statistic cannot resolve with only 2 (confirmed live: a real ValueError,
# not this project's own bug), so these use a 3-asset fixture rather than
# the 2-asset _synthetic_returns() the rest of this file shares.

def _three_asset_returns(n_periods: int = 400, seed: int = 17) -> np.ndarray:
    rng = np.random.RandomState(seed)
    a = rng.normal(0.0005, 0.01, n_periods)
    b = rng.normal(0.0003, 0.015, n_periods)
    c = rng.normal(0.0008, 0.02, n_periods)
    return np.column_stack([a, b, c])


def test_nco_weights_returns_real_long_only_fully_invested_weights():
    returns = _three_asset_returns()
    weights = nco_weights(returns, ["A", "B", "C"])
    assert weights.sum() == pytest.approx(1.0, abs=1e-3)
    assert (weights >= -1e-6).all()


def test_nco_weights_rejects_symbol_count_mismatch():
    returns = _three_asset_returns()
    with pytest.raises(ValueError, match="return columns"):
        nco_weights(returns, ["only_one"])


def test_engine_nco_optimization_returns_result(engine):
    returns = _three_asset_returns()
    result = engine.nco_optimization(["A", "B", "C"], returns)
    assert result.success
    assert isinstance(result.data, NCOResult)
    assert sum(result.data.weights) == pytest.approx(1.0, abs=1e-3)


# ---- PortfolioConstructionEngine (wrapper) ----

@pytest.fixture
def engine() -> PortfolioConstructionEngine:
    e = PortfolioConstructionEngine()
    e.initialize()
    return e


def test_engine_min_variance_returns_weights_result(engine):
    cov = [[0.04, 0.01], [0.01, 0.09]]
    result = engine.min_variance(["GOLD", "SILVER"], cov)
    assert result.success
    assert isinstance(result.data, WeightsResult)
    assert result.data.symbols == ["GOLD", "SILVER"]
    assert sum(result.data.weights) == pytest.approx(1.0)


def test_engine_max_sharpe_returns_weights_result(engine):
    cov = [[0.04, 0.0], [0.0, 0.09]]
    result = engine.max_sharpe(["GOLD", "SILVER"], [0.10, 0.05], cov)
    assert result.success
    assert result.data.portfolio_return is not None


def test_engine_efficient_frontier_returns_result(engine):
    cov = [[0.04, 0.01], [0.01, 0.09]]
    result = engine.efficient_frontier(["GOLD", "SILVER"], [0.08, 0.12], cov, n_points=5)
    assert result.success
    assert isinstance(result.data, EfficientFrontierResult)
    assert len(result.data.frontier) == 5


def test_engine_risk_parity_returns_result(engine):
    cov = [[0.04, 0.0], [0.0, 0.09]]
    result = engine.risk_parity(["GOLD", "SILVER"], cov)
    assert result.success
    assert isinstance(result.data, RiskParityResult)


def test_engine_cvar_optimization_returns_result(engine):
    returns = _synthetic_returns()
    result = engine.cvar_optimization(["CALM", "RISKY"], returns, alpha=0.95)
    assert result.success
    assert isinstance(result.data, TailRiskWeightsResult)
    assert result.data.measure == "cvar"
    assert result.data.weights[0] > result.data.weights[1]


def test_engine_cdar_optimization_returns_result(engine):
    returns = _synthetic_returns()
    result = engine.cdar_optimization(["CALM", "RISKY"], returns, alpha=0.95)
    assert result.success
    assert isinstance(result.data, TailRiskWeightsResult)
    assert result.data.measure == "cdar"


def test_engine_cvar_optimization_bad_shape_does_not_raise(engine):
    """1-D returns_matrix (a single period's worth of scalars, not a real
    T x N scenario matrix) fails historical_cvar's own ndim check inside
    cvar_minimizing_weights -- must come back as success=False, not
    propagate. (Note: like every other engine method in this module,
    symbols-list-length is never cross-checked against the matrix's own
    dimension -- that's a pre-existing, consistent convention across the
    whole engine, not something unique to this method.)"""
    result = engine.cvar_optimization(["A", "B"], [0.01, 0.02, 0.03])
    assert not result.success


def test_engine_black_litterman_returns_result(engine):
    cov = [[0.04, 0.01], [0.01, 0.09]]
    result = engine.black_litterman(["GOLD", "SILVER"], [0.5, 0.5], cov, P=[[1, 0]], Q=[0.15])
    assert result.success
    assert isinstance(result.data, BlackLittermanResult)


def test_engine_volatility_target_returns_result(engine):
    cov = [[0.04, 0.0], [0.0, 0.09]]
    result = engine.volatility_target(["GOLD", "SILVER"], [0.5, 0.5], cov, target_vol=0.10)
    assert result.success
    assert isinstance(result.data, VolatilityTargetResult)


def test_engine_min_variance_bad_cov_shape_does_not_raise(engine):
    """Best-effort convention: a math error (bad shape, singular matrix)
    returns success=False, never propagates an exception."""
    result = engine.min_variance(["GOLD", "SILVER"], [[0.04, 0.01, 0.0], [0.01, 0.09, 0.0]])
    assert not result.success


def test_engine_black_litterman_bad_shapes_does_not_raise(engine):
    cov = [[0.04, 0.01], [0.01, 0.09]]
    result = engine.black_litterman(["GOLD", "SILVER"], [0.5, 0.5], cov, P=[[1, 0], [0, 1]], Q=[0.1])
    assert not result.success


def test_engine_to_dict_serializes_cleanly(engine):
    cov = [[0.04, 0.01], [0.01, 0.09]]
    result = engine.min_variance(["GOLD", "SILVER"], cov)
    d = result.data.to_dict()
    assert d["symbols"] == ["GOLD", "SILVER"]
    assert isinstance(d["weights"], list)
