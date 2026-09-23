"""
Module: engine.py
Description: Engine 31 -- Portfolio Construction. Master prompt scope:
    "portfolio heat, correlation/sector/currency/factor/tail risk. Capital
    allocation, risk budgeting, volatility targeting, exposure management."
    Quantitative Finance section explicitly requires Black-Litterman and
    Risk Parity.

    Every method here is a pure function of the covariance matrix/return
    series passed in -- no network calls, no lookahead, easy to unit test,
    same decoupling convention as e12_quant_research (fetching real price
    history lives at the API layer/other engines, not here). Unconstrained
    mean-variance solutions use closed-form linear algebra; long-only
    solutions and risk parity fall back to constrained numerical
    optimization (scipy SLSQP) since no closed form exists once w >= 0.

    Ported from a sibling project's real, working portfolio_construction
    service (reviewed for correctness) and adapted to accept/return this
    engine's own symbol-labeled result dataclasses instead of bare
    arrays/dicts.

    No calibration/training step applies (Rule 3): every formula here is an
    exact, well-established closed-form or numerical-optimization result
    (Markowitz 1952, Black-Litterman 1992), not a fitted parameter. The two
    literal constants below (default risk_aversion=2.5, tau=0.05) are the
    standard textbook/practitioner defaults from the original Black-
    Litterman paper and its common implementations -- a documented industry
    convention, not a fabricated or backtested figure (same honest-
    convention precedent as e13_derivatives' options-skew thresholds).

    No knowledge_engine wiring (Rule 2): every output here is a numerical
    optimization result, not an interpretive classification/judgment call
    -- same "no" category as e34/e35/e40.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-07-18
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
from scipy.cluster.hierarchy import linkage
from scipy.optimize import minimize
from scipy.spatial.distance import squareform
from sklearn.covariance import LedoitWolf

from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus

logger = logging.getLogger(__name__)

# Standard Black-Litterman defaults (He & Litterman 1999 and most
# practitioner implementations) -- documented convention, not fitted.
DEFAULT_RISK_AVERSION = 2.5
DEFAULT_TAU = 0.05
DEFAULT_MAX_LEVERAGE = 3.0


@dataclass
class WeightsResult:
    """Portfolio weights from a mean-variance solution."""

    symbols: list[str]
    weights: list[float]
    portfolio_return: Optional[float] = None
    portfolio_volatility: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbols": self.symbols,
            "weights": [round(w, 6) for w in self.weights],
            "portfolio_return": round(self.portfolio_return, 6) if self.portfolio_return is not None else None,
            "portfolio_volatility": round(self.portfolio_volatility, 6) if self.portfolio_volatility is not None else None,
        }


@dataclass
class EfficientFrontierResult:
    """A traced efficient frontier: volatility-minimizing weights at each of
    a range of target returns."""

    symbols: list[str]
    frontier: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"symbols": self.symbols, "frontier": self.frontier}


@dataclass
class RiskParityResult:
    """Weights allocating equal RISK contribution (not equal capital) per asset."""

    symbols: list[str]
    weights: list[float]
    risk_contributions: list[float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbols": self.symbols,
            "weights": [round(w, 6) for w in self.weights],
            "risk_contributions": [round(r, 6) for r in self.risk_contributions],
        }


@dataclass
class HierarchicalRiskParityResult:
    """Weights from Hierarchical Risk Parity (Lopez de Prado 2016)."""

    symbols: list[str]
    weights: list[float]
    cluster_order: list[str]  # symbols in the order the hierarchical clustering placed them

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbols": self.symbols,
            "weights": [round(w, 6) for w in self.weights],
            "cluster_order": self.cluster_order,
        }


@dataclass
class TailRiskWeightsResult:
    """Weights minimizing a tail-risk measure (CVaR or CDaR) computed via
    historical simulation, not a parametric estimate."""

    symbols: list[str]
    weights: list[float]
    measure: str  # "cvar" or "cdar"
    alpha: float
    risk_value: float  # the resulting portfolio's CVaR/CDaR at these weights, in return units (e.g. 0.032 = 3.2%)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbols": self.symbols,
            "weights": [round(w, 6) for w in self.weights],
            "measure": self.measure,
            "alpha": self.alpha,
            "risk_value": round(self.risk_value, 6),
        }


@dataclass
class KellyGrowthResult:
    """Weights maximizing expected LOGARITHMIC (Kelly/compound-growth)
    return, not arithmetic mean-variance utility -- a genuinely different
    objective from max_sharpe_weights above, not a replacement for it
    (REPO_REFERENCE.md Tier 3: Riskfolio-Lib's "Kelly (log growth)
    objectives")."""

    symbols: list[str]
    weights: list[float]
    kelly_method: str          # "exact" (true log-utility) or "approx" (2nd-order Taylor)
    expected_log_growth: float  # portfolio's expected log return at these weights

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbols": self.symbols,
            "weights": [round(w, 6) for w in self.weights],
            "kelly_method": self.kelly_method,
            "expected_log_growth": round(self.expected_log_growth, 6),
        }


# Riskfolio-Lib's real `rm` catalog (its own optimization() docstring,
# verified directly, not guessed) -- RLVaR/RLDaR/RLVaR-range measures
# excluded: Riskfolio-Lib's own docs say "I recommend only use this
# function with MOSEK solver", a commercial solver this platform does not
# have and has no reason to add for one risk-measure family.
RISKFOLIO_MEASURES = frozenset({
    "MV", "KT", "EM", "MAD", "GMD", "MSV", "SKT", "ESM", "FLPM", "SLPM",
    "CVaR", "TG", "EVaR", "WR", "RG", "CVRG", "TGRG", "EVRG",
    "MDD", "ADD", "CDaR", "EDaR", "UCI",
})


@dataclass
class RiskfolioOptimizationResult:
    """Weights from Riskfolio-Lib's own real optimizer for ANY of its
    (non-MOSEK-only) risk measures -- CVaR/CDaR/Kelly above each hand-
    build/wrap ONE measure; this is the general case, added once cvxpy
    was actually available (REPO_REFERENCE.md Tier 3), so a future need
    for e.g. EVaR (a smoother, coherent CVaR alternative), UCI (Ulcer
    Index -- a real, commonly-requested drawdown measure this platform
    has never had), or SLPM (Sortino-based downside deviation) doesn't
    mean hand-deriving a new scipy objective each time."""

    symbols: list[str]
    weights: list[float]
    risk_measure: str
    objective: str
    risk_value: float          # the realized value of `risk_measure` at these weights

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbols": self.symbols,
            "weights": [round(w, 6) for w in self.weights],
            "risk_measure": self.risk_measure,
            "objective": self.objective,
            "risk_value": round(self.risk_value, 6),
        }


@dataclass
class NCOResult:
    """Weights from Nested Clustered Optimization (Lopez de Prado) via
    Riskfolio-Lib's HCPortfolio -- distinct from this module's own hand-
    built hierarchical_risk_parity_weights (classic HRP: quasi-
    diagonalize, then recursive bisection with no further optimization).
    NCO instead clusters assets, solves a REAL mean-variance optimization
    WITHIN each cluster (a smaller, better-conditioned sub-problem than
    optimizing the full covariance matrix at once), then a second
    optimization ACROSS clusters -- a structural answer to mean-variance's
    well-known instability to estimation error, distinct from (and
    stackable with) the Ledoit-Wolf shrinkage this module already offers
    via covariance_matrix_from_returns."""

    symbols: list[str]
    weights: list[float]
    risk_measure: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbols": self.symbols,
            "weights": [round(w, 6) for w in self.weights],
            "risk_measure": self.risk_measure,
        }


@dataclass
class BlackLittermanResult:
    """Posterior expected returns blending market equilibrium with investor views."""

    symbols: list[str]
    prior_equilibrium_returns: list[float]
    posterior_returns: list[float]
    posterior_covariance_adjustment: list[list[float]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbols": self.symbols,
            "prior_equilibrium_returns": [round(r, 6) for r in self.prior_equilibrium_returns],
            "posterior_returns": [round(r, 6) for r in self.posterior_returns],
            "posterior_covariance_adjustment": self.posterior_covariance_adjustment,
        }


@dataclass
class VolatilityTargetResult:
    """A weight vector scaled so realized portfolio volatility matches a target."""

    symbols: list[str]
    scaled_weights: list[float]
    leverage: float
    original_volatility: float
    target_volatility: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbols": self.symbols,
            "scaled_weights": [round(w, 6) for w in self.scaled_weights],
            "leverage": round(self.leverage, 4),
            "original_volatility": round(self.original_volatility, 6),
            "target_volatility": round(self.target_volatility, 6),
        }


# ---- pure math (module-level, mirrors the reviewed source 1:1) ----

def _validate_cov(cov_matrix: np.ndarray, n: int) -> None:
    if cov_matrix.shape != (n, n):
        raise ValueError("cov_matrix must be square and match the number of assets")


def covariance_matrix_from_returns(
    returns_by_symbol: dict[str, Any], use_shrinkage: bool = False
) -> tuple[list[str], np.ndarray]:
    """Build an ordered (symbols, covariance matrix) pair from aligned
    periodic-return series -- the bridge from real return data (as
    e12_quant_research.correlation_clustering also takes) to the raw
    cov_matrix every method below operates on.

    use_shrinkage (added 2026-08-20, default False -- preserves existing
    behavior for every caller already in production): when True, applies
    Ledoit-Wolf shrinkage (Ledoit & Wolf 2004, Journal of Portfolio
    Management) instead of the plain sample covariance -- a well-
    established, textbook bias-variance tradeoff that shrinks the noisy
    sample covariance toward a structured target, which matters most
    exactly where min_variance_weights/max_sharpe_weights below invert the
    matrix directly (np.linalg.inv(cov)): estimation noise in a raw sample
    covariance gets amplified by that inversion into unstable, extreme
    weights, especially with this platform's realistically short/noisy
    real return windows (daily/hourly bars for a ~29-asset universe, not
    the huge equity cross-sections shrinkage was originally validated on).

    Real gap, not a fabricated one -- found while reviewing skfolio
    (scikit-learn-compatible portfolio library, cloned read-only for
    reference): this platform had NO covariance-conditioning step at all
    before this. Kept OPT-IN (not the new default) because Rule 3's own
    "a new candidate only replaces the shipped default if it demonstrably
    beats it on real held-out data" standard applies here exactly the same
    as any other engine's calibration -- see
    scripts/training/validate_e31_ledoit_wolf_shrinkage.py for the real,
    live validation this project's own discipline requires before ever
    flipping a default, and CLAUDE.md for the honest result."""
    symbols = list(returns_by_symbol.keys())
    if len(symbols) < 2:
        raise ValueError("Need at least 2 symbols to build a covariance matrix")
    lengths = {len(v) for v in returns_by_symbol.values()}
    if len(lengths) != 1:
        raise ValueError("All return series must be the same length (aligned dates)")
    matrix = np.column_stack([np.asarray(returns_by_symbol[s], dtype=float) for s in symbols])
    if use_shrinkage:
        cov = LedoitWolf().fit(matrix).covariance_
    else:
        cov = np.cov(matrix, rowvar=False)
    return symbols, cov


def min_variance_weights(cov_matrix, long_only: bool = False) -> np.ndarray:
    cov = np.asarray(cov_matrix, dtype=float)
    n = cov.shape[0]
    _validate_cov(cov, n)

    if not long_only:
        ones = np.ones(n)
        inv_cov = np.linalg.inv(cov)
        raw = inv_cov @ ones
        return raw / raw.sum()

    def objective(w):
        return w @ cov @ w

    return _constrained_optimize(objective, n)


def max_sharpe_weights(mean_returns, cov_matrix, risk_free_rate: float = 0.0, long_only: bool = False) -> np.ndarray:
    means = np.asarray(mean_returns, dtype=float)
    cov = np.asarray(cov_matrix, dtype=float)
    n = len(means)
    _validate_cov(cov, n)

    excess = means - risk_free_rate

    if not long_only:
        inv_cov = np.linalg.inv(cov)
        raw = inv_cov @ excess
        if raw.sum() == 0:
            raise ValueError("degenerate solution: weights sum to zero (check inputs)")
        return raw / raw.sum()

    def objective(w):
        port_return = w @ excess
        port_vol = np.sqrt(w @ cov @ w)
        if port_vol == 0:
            return 0.0
        return -port_return / port_vol  # minimize negative Sharpe == maximize Sharpe

    return _constrained_optimize(objective, n)


def _constrained_optimize(objective, n: int) -> np.ndarray:
    x0 = np.full(n, 1 / n)
    bounds = [(0.0, 1.0)] * n
    constraints = [{"type": "eq", "fun": lambda w: w.sum() - 1}]
    # ftol=1e-6 is scipy's default, calibrated for O(1)-magnitude
    # objectives. Portfolio variance from real daily returns is typically
    # O(1e-4) to O(1e-3) -- at that scale the default ftol makes SLSQP
    # report "converged" after a single iteration sitting exactly at x0,
    # never actually searching (caught live: GOLD/SILVER/BTCUSD/EURUSD
    # long-only min-variance returned flat 25/25/25/25 despite the assets'
    # wildly different variances, nit=1). A much tighter ftol, matching
    # risk_parity_weights' own convention below, forces real iteration.
    result = minimize(
        objective, x0, method="SLSQP", bounds=bounds, constraints=constraints,
        options={"maxiter": 1000, "ftol": 1e-12},
    )
    if not result.success:
        raise ValueError(f"optimization failed to converge: {result.message}")
    weights = np.clip(result.x, 0, None)
    return weights / weights.sum()


def portfolio_return(weights, mean_returns) -> float:
    return float(np.asarray(weights) @ np.asarray(mean_returns))


def portfolio_volatility(weights, cov_matrix) -> float:
    w = np.asarray(weights, dtype=float)
    cov = np.asarray(cov_matrix, dtype=float)
    return float(np.sqrt(w @ cov @ w))


def efficient_frontier(mean_returns, cov_matrix, n_points: int = 20, long_only: bool = True) -> list[dict]:
    """Trace the efficient frontier by targeting a range of returns between
    the min-variance portfolio's return and the max single-asset return,
    minimizing variance at each target return level."""
    means = np.asarray(mean_returns, dtype=float)
    cov = np.asarray(cov_matrix, dtype=float)
    n = len(means)
    _validate_cov(cov, n)

    min_var_w = min_variance_weights(cov, long_only=long_only)
    min_var_return = portfolio_return(min_var_w, means)
    max_return = float(means.max())

    if max_return <= min_var_return:
        max_return = min_var_return + 1e-6

    targets = np.linspace(min_var_return, max_return, n_points)
    frontier = []
    for target in targets:
        def objective(w):
            return w @ cov @ w

        constraints = [
            {"type": "eq", "fun": lambda w: w.sum() - 1},
            {"type": "eq", "fun": lambda w, t=target: w @ means - t},
        ]
        bounds = [(0.0, 1.0)] * n if long_only else [(-1.0, 1.0)] * n
        x0 = np.full(n, 1 / n)
        # Same tight-ftol fix as _constrained_optimize -- see its comment.
        result = minimize(
            objective, x0, method="SLSQP", bounds=bounds, constraints=constraints,
            options={"maxiter": 1000, "ftol": 1e-12},
        )
        if not result.success:
            continue
        w = result.x
        # Same clip+renormalize as _constrained_optimize/risk_parity_weights
        # -- without it, SLSQP's float-noise on the w.sum()==1 constraint
        # leaks straight into the reported weights instead of being
        # corrected, so frontier points can silently drift off summing to 1.
        if long_only:
            w = np.clip(w, 0, None)
        w = w / w.sum()
        frontier.append(
            {
                "target_return": float(target),
                "volatility": float(np.sqrt(w @ cov @ w)),
                "weights": w.tolist(),
            }
        )
    return frontier


def risk_contributions(weights, cov_matrix) -> np.ndarray:
    """Each asset's contribution to total portfolio volatility (Euler
    decomposition): RC_i = w_i * (cov @ w)_i / portfolio_vol, summing to
    the total portfolio volatility."""
    w = np.asarray(weights, dtype=float)
    cov = np.asarray(cov_matrix, dtype=float)
    port_var = w @ cov @ w
    port_vol = np.sqrt(port_var)
    if port_vol == 0:
        return np.zeros_like(w)
    marginal_contributions = cov @ w
    return w * marginal_contributions / port_vol


def risk_parity_weights(cov_matrix, tolerance: float = 1e-10, max_iter: int = 1000) -> np.ndarray:
    cov = np.asarray(cov_matrix, dtype=float)
    n = cov.shape[0]
    _validate_cov(cov, n)

    def objective(w):
        rc = risk_contributions(w, cov)
        target = rc.mean()
        return float(np.sum((rc - target) ** 2))

    x0 = np.full(n, 1 / n)
    bounds = [(1e-6, 1.0)] * n
    constraints = [{"type": "eq", "fun": lambda w: w.sum() - 1}]
    result = minimize(
        objective, x0, method="SLSQP", bounds=bounds, constraints=constraints,
        options={"maxiter": max_iter, "ftol": tolerance},
    )
    if not result.success:
        raise ValueError(f"risk parity optimization failed to converge: {result.message}")

    weights = np.clip(result.x, 0, None)
    return weights / weights.sum()


def _correlation_distance(cov_matrix: np.ndarray) -> np.ndarray:
    """Standard HRP distance metric: d_ij = sqrt(0.5 * (1 - corr_ij)) --
    a proper metric (satisfies the triangle inequality, unlike 1-corr_ij
    alone) derived from the correlation matrix implied by cov_matrix."""
    std = np.sqrt(np.diag(cov_matrix))
    corr = cov_matrix / np.outer(std, std)
    corr = np.clip(corr, -1.0, 1.0)  # guard against float noise pushing |corr| slightly past 1
    return np.sqrt(0.5 * (1.0 - corr))


def _quasi_diagonalize(link: np.ndarray, n: int) -> list[int]:
    """Returns the leaf order (original asset indices) implied by a scipy
    linkage matrix, by recursively expanding the root cluster into its
    constituent original leaf indices in dendrogram (left-to-right) order
    -- assets that clustered together end up adjacent in the returned
    order, which is what makes the later recursive bisection split
    genuinely-similar assets together rather than an arbitrary subset."""
    link = link.astype(int)

    def _expand(cluster_id: int) -> list[int]:
        if cluster_id < n:
            return [cluster_id]
        left, right = link[cluster_id - n, 0], link[cluster_id - n, 1]
        return _expand(int(left)) + _expand(int(right))

    root_id = n + link.shape[0] - 1
    return _expand(root_id)


def _cluster_variance(cov: np.ndarray, indices: list[int]) -> float:
    """Inverse-variance-weighted portfolio variance WITHIN a cluster --
    the standard HRP convention for sizing a sub-cluster's overall risk
    (not equal-weight, not the cluster's own true min-variance solution,
    which would require inverting a sub-matrix -- inverse-variance
    weighting is what the original HRP paper uses specifically because it
    needs no matrix inversion at all, staying consistent with why HRP
    exists in the first place)."""
    sub_cov = cov[np.ix_(indices, indices)]
    diag = np.diag(sub_cov)
    inv_var_weights = 1.0 / diag
    inv_var_weights = inv_var_weights / inv_var_weights.sum()
    return float(inv_var_weights @ sub_cov @ inv_var_weights)


def _recursive_bisection(cov: np.ndarray, sorted_indices: list[int]) -> np.ndarray:
    """HRP's third step: repeatedly split the (already quasi-diagonalized)
    asset order in half, allocating weight between each half INVERSELY
    proportional to that half's own cluster variance (a lower-variance
    half gets more weight) -- recursing down until every split is a
    single asset. This is what makes HRP a genuine risk-parity method
    (like risk_parity_weights above) while still needing no matrix
    inversion (unlike it)."""
    n = cov.shape[0]
    weights = np.ones(n)

    def _bisect(indices: list[int]) -> None:
        if len(indices) <= 1:
            return
        mid = len(indices) // 2
        left, right = indices[:mid], indices[mid:]
        left_var = _cluster_variance(cov, left)
        right_var = _cluster_variance(cov, right)
        total = left_var + right_var
        alloc_left = 1.0 - left_var / total if total > 0 else 0.5
        for i in left:
            weights[i] *= alloc_left
        for i in right:
            weights[i] *= (1.0 - alloc_left)
        _bisect(left)
        _bisect(right)

    _bisect(sorted_indices)
    return weights


def hierarchical_risk_parity_weights(cov_matrix) -> tuple[np.ndarray, list[int]]:
    """Hierarchical Risk Parity (Lopez de Prado, "Building Diversified
    Portfolios that Outperform Out-of-Sample", Journal of Portfolio
    Management, 2016). Three steps: (1) hierarchical clustering of assets
    by correlation distance, (2) quasi-diagonalization -- reorder assets
    so correlated ones sit adjacent, (3) recursive bisection -- repeatedly
    split the ordered list and allocate weight inversely to each half's
    variance, down to individual assets.

    Deliberately never inverts the covariance matrix at any step (unlike
    min_variance_weights/max_sharpe_weights above, both of which call
    np.linalg.inv(cov) directly) -- HRP's entire reason for existing is
    robustness when the covariance matrix is ill-conditioned or
    near-singular (e.g. several highly correlated assets), the exact
    condition under which matrix inversion becomes numerically unstable
    or fails outright. Returns (weights, sorted_indices) -- the second
    value is the asset order the clustering produced, useful for
    understanding which assets the algorithm grouped together.
    """
    cov = np.asarray(cov_matrix, dtype=float)
    n = cov.shape[0]
    _validate_cov(cov, n)
    if n < 2:
        raise ValueError("Need at least 2 assets for hierarchical risk parity")

    dist = _correlation_distance(cov)
    condensed = squareform(dist, checks=False)
    link = linkage(condensed, method="single")
    sorted_indices = _quasi_diagonalize(link, n)
    weights = _recursive_bisection(cov, sorted_indices)
    return weights / weights.sum(), sorted_indices


def historical_cvar(weights, returns_matrix, alpha: float = 0.95) -> float:
    """Conditional Value at Risk (Expected Shortfall) at confidence level
    `alpha`, computed via historical simulation on real scenario returns --
    NOT a parametric (Gaussian) estimate, so it captures real fat tails
    directly from the data rather than assuming a distribution shape.
    `returns_matrix` is T periods x N assets of REAL historical returns
    (not synthesized); portfolio returns are `returns_matrix @ weights`
    per period. VaR_alpha is the alpha-quantile of the LOSS distribution
    (e.g. alpha=0.95 -> the 95th-percentile loss, the boundary of the
    worst 5% of outcomes); CVaR_alpha is the average loss CONDITIONAL ON
    being at or beyond that boundary -- always >= VaR, and unlike VaR it's
    a coherent risk measure (subadditive: diversifying can never make it
    worse), the specific property Rockafellar & Uryasev's 2000 paper
    ("Optimization of Conditional Value-at-Risk") is built around."""
    w = np.asarray(weights, dtype=float)
    returns = np.asarray(returns_matrix, dtype=float)
    if returns.ndim != 2 or returns.shape[1] != len(w):
        raise ValueError(f"returns_matrix shape {returns.shape} incompatible with {len(w)} weights")
    port_returns = returns @ w
    losses = -port_returns
    var = float(np.percentile(losses, alpha * 100))
    tail = losses[losses >= var]
    return float(tail.mean()) if len(tail) > 0 else var


def historical_cdar(weights, returns_matrix, alpha: float = 0.95) -> float:
    """Conditional Drawdown at Risk -- the same tail-averaging idea as
    CVaR above, but applied to the portfolio's own DRAWDOWN series
    (peak-to-current decline of its cumulative return path) instead of
    single-period losses. Answers a different question than CVaR: CVaR
    asks "how bad is a bad PERIOD," CDaR asks "how bad is a bad
    SUSTAINED decline" -- a real distinction Riskfolio-Lib's own risk
    measure catalogue treats as a separate, non-redundant objective
    (Chekhlov, Uryasev & Zabarankin 2005, "Drawdown Measure in Portfolio
    Optimization"). Cumulative path is a simple compounding product of
    the same real per-period returns_matrix @ weights series CVaR uses --
    no separate data source, no fabricated path."""
    w = np.asarray(weights, dtype=float)
    returns = np.asarray(returns_matrix, dtype=float)
    if returns.ndim != 2 or returns.shape[1] != len(w):
        raise ValueError(f"returns_matrix shape {returns.shape} incompatible with {len(w)} weights")
    port_returns = returns @ w
    cumulative = np.cumprod(1.0 + port_returns)
    running_max = np.maximum.accumulate(cumulative)
    drawdowns = np.where(running_max > 0, (running_max - cumulative) / running_max, 0.0)
    var_dd = float(np.percentile(drawdowns, alpha * 100))
    tail = drawdowns[drawdowns >= var_dd]
    return float(tail.mean()) if len(tail) > 0 else var_dd


def cvar_minimizing_weights(returns_matrix, alpha: float = 0.95) -> np.ndarray:
    """Weights minimizing historical_cvar via the same scipy SLSQP
    scaffold (_constrained_optimize) every other numerically-optimized
    method in this module already uses -- deliberately NOT a cvxpy-based
    LP formulation of the classic Rockafellar-Uryasev auxiliary-variable
    problem (the textbook approach, and what Riskfolio-Lib itself uses
    internally): this platform has no cvxpy dependency anywhere, and
    adding one for a single objective when the existing scipy scaffold
    already handles every other non-closed-form objective here (risk
    parity's own sum-of-squared-deviations objective is just as
    non-quadratic) would be inconsistent with how this whole module is
    built. Always long-only (box-bounded [0,1], sum-to-1) -- same
    convention as risk_parity_weights, which also has no unconstrained/
    short-allowed variant, since there is no closed form for either
    objective even in principle."""
    returns = np.asarray(returns_matrix, dtype=float)
    if returns.ndim != 2:
        raise ValueError(f"returns_matrix must be 2-D (periods x assets), got shape {returns.shape}")
    n = returns.shape[1]

    def objective(w):
        return historical_cvar(w, returns, alpha)

    return _constrained_optimize(objective, n)


def cdar_minimizing_weights(returns_matrix, alpha: float = 0.95) -> np.ndarray:
    """Weights minimizing historical_cdar -- same scipy SLSQP scaffold and
    same long-only-only rationale as cvar_minimizing_weights above."""
    returns = np.asarray(returns_matrix, dtype=float)
    if returns.ndim != 2:
        raise ValueError(f"returns_matrix must be 2-D (periods x assets), got shape {returns.shape}")
    n = returns.shape[1]

    def objective(w):
        return historical_cdar(w, returns, alpha)

    return _constrained_optimize(objective, n)


def kelly_growth_weights(
    returns_matrix, symbols: list[str], rm: str = "MV", kelly: str = "exact", rf: float = 0.0,
) -> tuple[np.ndarray, float]:
    """Portfolio-level Kelly (log-growth) optimization via Riskfolio-Lib.

    WHY THIS IS NOT A DUPLICATE of e12_quant_research's own
    kelly_criterion or max_sharpe_weights above. E12's Kelly is a SINGLE-
    BET fractional-Kelly sizing formula (what fraction of capital to risk
    on one trade given its own win-rate/payoff); max_sharpe_weights
    maximizes arithmetic mean-variance utility across many assets. This
    maximizes the PORTFOLIO's expected log return directly (`kelly="exact"`
    is Riskfolio-Lib's true log-utility objective, not a variance proxy
    for it) -- a genuinely different multi-asset objective, answering
    "what allocation grows compounded wealth fastest", not "what has the
    best risk-adjusted single-period return".

    WHY Riskfolio-Lib AND NOT A HAND-ROLLED cvxpy PROGRAM. Log-utility
    portfolio optimization has no closed form and is numerically
    fussier than the quadratic mean-variance problems this module
    solves elsewhere with plain scipy SLSQP (E31's own prior CVaR/CDaR
    work deliberately avoided a NEW cvxpy dependency for exactly this
    reason) -- now that cvxpy arrived transitively via PyPortfolioOpt/
    Riskfolio-Lib (REPO_REFERENCE.md Tier 1/3), reusing Riskfolio-Lib's
    own tested DCP-compliant formulation is the real-library-for-real-
    numerical-subtlety choice, not a second implementation of the same
    solver risk.

    Returns (weights, expected_log_growth) -- never fabricates a result
    on a degenerate/singular return matrix; a real Riskfolio-Lib failure
    propagates as whatever exception it raises, same as this module's
    other optimizers surfacing np.linalg.LinAlgError.
    """
    import pandas as pd
    import riskfolio as rp

    returns = np.asarray(returns_matrix, dtype=float)
    if returns.ndim != 2:
        raise ValueError(f"returns_matrix must be 2-D (periods x assets), got shape {returns.shape}")
    if returns.shape[1] != len(symbols):
        raise ValueError(f"{returns.shape[1]} return columns but {len(symbols)} symbols")

    port = rp.Portfolio(returns=pd.DataFrame(returns, columns=symbols))
    port.assets_stats(method_mu="hist", method_cov="hist")
    w_df = port.optimization(model="Classic", rm=rm, obj="Sharpe", kelly=kelly, rf=rf)
    weights = w_df["weights"].reindex(symbols).to_numpy(dtype=float)

    log_returns = np.log1p(returns)
    expected_log_growth = float(log_returns.mean(axis=0) @ weights)
    return weights, expected_log_growth


def riskfolio_optimize_weights(
    returns_matrix, symbols: list[str], rm: str = "CVaR", obj: str = "Sharpe",
    rf: float = 0.0, alpha: float = 0.05,
) -> tuple[np.ndarray, float]:
    """Weights from Riskfolio-Lib's own real optimizer for any risk measure
    in RISKFOLIO_MEASURES -- the general case behind kelly_growth_weights
    above and this module's own hand-built CVaR/CDaR (both of which
    predate cvxpy being a real dependency here, see their own docstrings).

    WHY GENERALIZE NOW. Hand-deriving a new scipy SLSQP objective per risk
    measure (the historical_cvar/historical_cdar pattern) does not scale
    to Riskfolio-Lib's real ~20-measure catalog, and reimplementing even
    one of the more exotic ones (EVaR is a genuine convex-optimization
    formulation, not a closed-form reduction) would replay the same
    reimplementation risk this project already avoids for GARCH/
    statsmodels. One general wrapper over Riskfolio-Lib's own tested
    formulations, verified against a small representative subset rather
    than all ~20, covers the rest by the same mechanism.

    `alpha` only matters for tail measures (CVaR/EVaR/CDaR/EDaR/TG/...);
    Riskfolio-Lib itself ignores it for measures that don't use it (e.g.
    'MV', 'MAD'), so no per-measure branching is needed here.

    Returns (weights, risk_value) -- risk_value is the REALIZED value of
    `rm` at the optimized weights, computed via Riskfolio-Lib's own
    Sharpe_Risk (the same function its own optimizer's Sharpe ratio uses
    internally), not re-derived by hand.
    """
    import pandas as pd
    import riskfolio as rp

    if rm not in RISKFOLIO_MEASURES:
        raise ValueError(f"rm={rm!r} not in RISKFOLIO_MEASURES: {sorted(RISKFOLIO_MEASURES)}")

    returns = np.asarray(returns_matrix, dtype=float)
    if returns.ndim != 2:
        raise ValueError(f"returns_matrix must be 2-D (periods x assets), got shape {returns.shape}")
    if returns.shape[1] != len(symbols):
        raise ValueError(f"{returns.shape[1]} return columns but {len(symbols)} symbols")

    returns_df = pd.DataFrame(returns, columns=symbols)
    # `alpha` is a Portfolio CONSTRUCTOR arg, not an optimization() kwarg --
    # confirmed directly (optimization() raises TypeError on an alpha=
    # kwarg), not assumed from the docstring alone.
    port = rp.Portfolio(returns=returns_df, alpha=alpha)
    port.assets_stats(method_mu="hist", method_cov="hist")
    w_df = port.optimization(model="Classic", rm=rm, obj=obj, rf=rf)
    weights = w_df["weights"].reindex(symbols).to_numpy(dtype=float)

    risk_value = float(rp.Sharpe_Risk(returns_df, w=w_df, rm=rm, rf=rf, alpha=alpha))
    return weights, risk_value


def nco_weights(returns_matrix, symbols: list[str], rm: str = "MV", codependence: str = "pearson") -> np.ndarray:
    """Nested Clustered Optimization via Riskfolio-Lib's HCPortfolio --
    see NCOResult's own docstring for what makes this distinct from this
    module's existing hierarchical_risk_parity_weights.

    HERC/HERC2 (Riskfolio-Lib's OTHER two HCPortfolio models) are
    deliberately NOT exposed here or anywhere in this module. Confirmed
    live, not assumed: Riskfolio-Lib 7.3.0 (the latest PyPI release as of
    2026-09-11 -- `pip index versions` shows no newer one) has a real
    internal bug -- `HCPortfolio.optimization(model="HERC", ...)`
    unconditionally forwards a `linkage` kwarg into its own private
    `_hierarchical_recursive_bisection`, which does not accept one:
    `TypeError: ..._hierarchical_recursive_bisection() got an unexpected
    keyword argument 'linkage'`. HRP itself (HCPortfolio's third model)
    works but is not re-exposed either -- this module already has its
    own hand-built, tested HRP; wrapping Riskfolio-Lib's copy would be a
    pure duplicate, not a new capability.

    NEEDS AT LEAST 3 ASSETS. Confirmed live: with only 2, Riskfolio-Lib's
    own optimal-cluster-count gap statistic (`AuxFunctions.py`'s
    `two_diff_gap_stat`) divides by an empty comparison and raises
    `ValueError: cannot convert float NaN to integer` -- a real structural
    minimum for a NESTED clustering method (you cannot nest one cluster),
    not something this wrapper works around or silently pads.
    """
    import pandas as pd
    import riskfolio as rp

    returns = np.asarray(returns_matrix, dtype=float)
    if returns.ndim != 2:
        raise ValueError(f"returns_matrix must be 2-D (periods x assets), got shape {returns.shape}")
    if returns.shape[1] != len(symbols):
        raise ValueError(f"{returns.shape[1]} return columns but {len(symbols)} symbols")

    returns_df = pd.DataFrame(returns, columns=symbols)
    hc = rp.HCPortfolio(returns=returns_df)
    w_df = hc.optimization(model="NCO", codependence=codependence, rm=rm)
    return w_df["weights"].reindex(symbols).to_numpy(dtype=float)


def implied_equilibrium_returns(market_weights, cov_matrix, risk_aversion: float = DEFAULT_RISK_AVERSION) -> np.ndarray:
    """pi = risk_aversion * Sigma @ w_market -- the returns that would make
    the given (caller-supplied) market-weighted portfolio mean-variance-
    optimal. This platform's actual assets (forex/crypto/commodities/
    indices/bonds) have no single clean "market cap" convention the way
    equity indices do, so market_weights is always caller-supplied, never
    auto-derived/fabricated here."""
    w = np.asarray(market_weights, dtype=float)
    cov = np.asarray(cov_matrix, dtype=float)
    return risk_aversion * cov @ w


def black_litterman_posterior(
    market_weights,
    cov_matrix,
    P,
    Q,
    risk_aversion: float = DEFAULT_RISK_AVERSION,
    tau: float = DEFAULT_TAU,
    omega=None,
) -> dict[str, Any]:
    """P: (n_views, n_assets) pick matrix. Q: (n_views,) view returns.
    omega: (n_views, n_views) view uncertainty covariance; if None, uses
    the standard default omega = diag(tau * P @ Sigma @ P.T)."""
    cov = np.asarray(cov_matrix, dtype=float)
    n = cov.shape[0]
    pi = implied_equilibrium_returns(market_weights, cov, risk_aversion)

    P = np.atleast_2d(np.asarray(P, dtype=float))
    Q = np.asarray(Q, dtype=float).flatten()
    if P.shape[1] != n:
        raise ValueError("P must have n_assets columns")
    if P.shape[0] != len(Q):
        raise ValueError("P's row count must match len(Q)")

    tau_cov = tau * cov
    if omega is None:
        omega = np.diag(np.diag(P @ tau_cov @ P.T))
    else:
        omega = np.asarray(omega, dtype=float)

    tau_cov_inv = np.linalg.inv(tau_cov)
    omega_inv = np.linalg.inv(omega)

    posterior_cov_factor = np.linalg.inv(tau_cov_inv + P.T @ omega_inv @ P)
    posterior_mean = posterior_cov_factor @ (tau_cov_inv @ pi + P.T @ omega_inv @ Q)

    return {
        "prior_equilibrium_returns": pi.tolist(),
        "posterior_returns": posterior_mean.tolist(),
        "posterior_covariance_adjustment": posterior_cov_factor.tolist(),
    }


def leverage_for_target_vol(current_vol: float, target_vol: float, max_leverage: float = DEFAULT_MAX_LEVERAGE) -> float:
    if current_vol <= 0:
        raise ValueError("current_vol must be positive")
    if target_vol < 0:
        raise ValueError("target_vol must be non-negative")
    if max_leverage <= 0:
        raise ValueError("max_leverage must be positive")

    raw_leverage = target_vol / current_vol
    return float(min(raw_leverage, max_leverage))


def scale_weights_to_target_vol(weights, cov_matrix, target_vol: float, max_leverage: float = DEFAULT_MAX_LEVERAGE) -> dict[str, Any]:
    w = np.asarray(weights, dtype=float)
    cov = np.asarray(cov_matrix, dtype=float)
    current_vol = float(np.sqrt(w @ cov @ w))
    leverage = leverage_for_target_vol(current_vol, target_vol, max_leverage)
    scaled_weights = w * leverage
    return {
        "scaled_weights": scaled_weights.tolist(),
        "leverage": leverage,
        "original_volatility": current_vol,
        "target_volatility": target_vol,
    }


class PortfolioConstructionEngine(BaseEngine):
    """
    Portfolio Construction Engine (#31) -- mean-variance optimization
    (min-variance, max-Sharpe, efficient frontier), risk parity, Black-
    Litterman, and volatility targeting across this platform's own asset
    universe. Every method is a pure function of the covariance matrix/
    return series passed in (see module docstring) -- callers (API routes,
    other engines) fetch real price history and compute returns/covariance
    themselves, same decoupling convention as e12_quant_research.
    """

    engine_id = "e31_portfolio_construction"
    engine_name = "Portfolio Construction Engine"
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__()

    def initialize(self) -> EngineResult:
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Portfolio Construction Engine initialized")

    def health_check(self) -> EngineResult:
        return EngineResult(success=True, message="Healthy")

    def min_variance(self, symbols: list[str], cov_matrix, long_only: bool = False) -> EngineResult:
        try:
            weights = min_variance_weights(cov_matrix, long_only)
            result = WeightsResult(
                symbols=symbols, weights=weights.tolist(),
                portfolio_volatility=portfolio_volatility(weights, cov_matrix),
            )
            return EngineResult(success=True, data=result, message="Min-variance weights computed")
        except (ValueError, np.linalg.LinAlgError) as e:
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def max_sharpe(
        self, symbols: list[str], mean_returns, cov_matrix, risk_free_rate: float = 0.0, long_only: bool = False
    ) -> EngineResult:
        try:
            weights = max_sharpe_weights(mean_returns, cov_matrix, risk_free_rate, long_only)
            result = WeightsResult(
                symbols=symbols, weights=weights.tolist(),
                portfolio_return=portfolio_return(weights, mean_returns),
                portfolio_volatility=portfolio_volatility(weights, cov_matrix),
            )
            return EngineResult(success=True, data=result, message="Max-Sharpe weights computed")
        except (ValueError, np.linalg.LinAlgError) as e:
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def efficient_frontier(
        self, symbols: list[str], mean_returns, cov_matrix, n_points: int = 20, long_only: bool = True
    ) -> EngineResult:
        try:
            frontier = efficient_frontier(mean_returns, cov_matrix, n_points, long_only)
            result = EfficientFrontierResult(symbols=symbols, frontier=frontier)
            return EngineResult(success=True, data=result, message=f"Traced {len(frontier)}-point efficient frontier")
        except (ValueError, np.linalg.LinAlgError) as e:
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def risk_parity(self, symbols: list[str], cov_matrix) -> EngineResult:
        try:
            weights = risk_parity_weights(cov_matrix)
            contributions = risk_contributions(weights, cov_matrix)
            result = RiskParityResult(symbols=symbols, weights=weights.tolist(), risk_contributions=contributions.tolist())
            return EngineResult(success=True, data=result, message="Risk parity weights computed")
        except (ValueError, np.linalg.LinAlgError) as e:
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def hierarchical_risk_parity(self, symbols: list[str], cov_matrix) -> EngineResult:
        try:
            weights, sorted_indices = hierarchical_risk_parity_weights(cov_matrix)
            cluster_order = [symbols[i] for i in sorted_indices]
            result = HierarchicalRiskParityResult(symbols=symbols, weights=weights.tolist(), cluster_order=cluster_order)
            return EngineResult(success=True, data=result, message="Hierarchical risk parity weights computed")
        except (ValueError, np.linalg.LinAlgError) as e:
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def cvar_optimization(self, symbols: list[str], returns_matrix, alpha: float = 0.95) -> EngineResult:
        try:
            weights = cvar_minimizing_weights(returns_matrix, alpha)
            risk_value = historical_cvar(weights, returns_matrix, alpha)
            result = TailRiskWeightsResult(
                symbols=symbols, weights=weights.tolist(), measure="cvar", alpha=alpha, risk_value=risk_value,
            )
            return EngineResult(success=True, data=result, message=f"CVaR-minimizing weights computed (alpha={alpha})")
        except (ValueError, np.linalg.LinAlgError) as e:
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def cdar_optimization(self, symbols: list[str], returns_matrix, alpha: float = 0.95) -> EngineResult:
        try:
            weights = cdar_minimizing_weights(returns_matrix, alpha)
            risk_value = historical_cdar(weights, returns_matrix, alpha)
            result = TailRiskWeightsResult(
                symbols=symbols, weights=weights.tolist(), measure="cdar", alpha=alpha, risk_value=risk_value,
            )
            return EngineResult(success=True, data=result, message=f"CDaR-minimizing weights computed (alpha={alpha})")
        except (ValueError, np.linalg.LinAlgError) as e:
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def kelly_growth_optimization(
        self, symbols: list[str], returns_matrix, rm: str = "MV", kelly: str = "exact", rf: float = 0.0,
    ) -> EngineResult:
        try:
            weights, expected_log_growth = kelly_growth_weights(returns_matrix, symbols, rm=rm, kelly=kelly, rf=rf)
            result = KellyGrowthResult(
                symbols=symbols, weights=weights.tolist(), kelly_method=kelly,
                expected_log_growth=expected_log_growth,
            )
            return EngineResult(success=True, data=result,
                                message=f"Kelly log-growth weights computed (kelly={kelly})")
        except (ValueError, np.linalg.LinAlgError) as e:
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def riskfolio_optimization(
        self, symbols: list[str], returns_matrix, rm: str = "CVaR", obj: str = "Sharpe",
        rf: float = 0.0, alpha: float = 0.05,
    ) -> EngineResult:
        try:
            weights, risk_value = riskfolio_optimize_weights(
                returns_matrix, symbols, rm=rm, obj=obj, rf=rf, alpha=alpha)
            result = RiskfolioOptimizationResult(
                symbols=symbols, weights=weights.tolist(), risk_measure=rm, objective=obj,
                risk_value=risk_value,
            )
            return EngineResult(success=True, data=result,
                                message=f"Riskfolio-Lib weights computed (rm={rm}, obj={obj})")
        except (ValueError, np.linalg.LinAlgError) as e:
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def nco_optimization(
        self, symbols: list[str], returns_matrix, rm: str = "MV", codependence: str = "pearson",
    ) -> EngineResult:
        try:
            weights = nco_weights(returns_matrix, symbols, rm=rm, codependence=codependence)
            result = NCOResult(symbols=symbols, weights=weights.tolist(), risk_measure=rm)
            return EngineResult(success=True, data=result,
                                message=f"NCO weights computed (rm={rm}, codependence={codependence})")
        except (ValueError, np.linalg.LinAlgError) as e:
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def black_litterman(
        self,
        symbols: list[str],
        market_weights,
        cov_matrix,
        P,
        Q,
        risk_aversion: float = DEFAULT_RISK_AVERSION,
        tau: float = DEFAULT_TAU,
        omega=None,
    ) -> EngineResult:
        try:
            posterior = black_litterman_posterior(market_weights, cov_matrix, P, Q, risk_aversion, tau, omega)
            result = BlackLittermanResult(symbols=symbols, **posterior)
            return EngineResult(success=True, data=result, message="Black-Litterman posterior computed")
        except (ValueError, np.linalg.LinAlgError) as e:
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def volatility_target(
        self, symbols: list[str], weights, cov_matrix, target_vol: float, max_leverage: float = DEFAULT_MAX_LEVERAGE
    ) -> EngineResult:
        try:
            scaled = scale_weights_to_target_vol(weights, cov_matrix, target_vol, max_leverage)
            result = VolatilityTargetResult(symbols=symbols, **scaled)
            return EngineResult(success=True, data=result, message="Weights scaled to target volatility")
        except ValueError as e:
            return EngineResult(success=False, message=str(e), errors=[str(e)])
