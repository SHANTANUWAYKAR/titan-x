"""
Module: deflated_sharpe.py
Description: The Sharpe ratio a search of N strategies reaches by luck alone,
    and the probability an observed Sharpe beats it.

    WHY THIS EXISTS. This project scores 98,546 candidates. Picking the best of
    98,546 is a search, and the maximum of N draws from a zero-edge
    distribution grows with N -- so "the best backtest we found" is not
    evidence of edge until it clears what the search itself would produce from
    noise. This project already MEASURED that failure directly: 137 of 150 pure
    noise paths cleared its legacy selection bar at 4h. `strategy_score` has
    carried a `dsr` field since it was written, but nothing ever computed it,
    so the multiple-testing correction existed only as a column name.

    THE NUMBER THAT MATTERS. For N trials over n observations, the expected
    maximum Sharpe of N independent zero-edge strategies is

        E[max SR] ~ sqrt(1/(n-1)) * [ (1-g) * z(1 - 1/N) + g * z(1 - 1/(N e)) ]

    with g the Euler-Mascheroni constant -- Bailey & Lopez de Prado, "The
    Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting
    and Non-Normality" (2014), building on the same authors' Probabilistic
    Sharpe Ratio. Annualised, at this project's own grid size (830 candidates
    per sweep, ~10 years) that floor is about 1.01 -- while `_APLUS_GATES`
    asks for an OOS Sharpe of 0.5. The gate has been sitting a factor of two
    BELOW the noise floor, which is the arithmetic behind the 137/150 result.

    WHAT THIS IS NOT. The floor is parametric and assumes independent trials.
    A parameter sweep is NOT independent -- neighbouring parameter sets are
    highly correlated, so the effective number of trials is smaller than the
    raw count and this floor is CONSERVATIVE (too high) when applied with the
    raw grid size. That direction is deliberate: the opposite error admits
    noise. Where this project has run its empirical synthetic null, that
    measurement is strictly better evidence than this formula and should win.

    Adapted from the reference implementation in the `quant_platform` workspace
    (`src/qp/analytics/performance.py`), reworked to take summary statistics
    rather than a returns series, because this project's stored candidates keep
    metrics and not per-bar returns.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import logging
import math
from typing import Optional

logger = logging.getLogger(__name__)

_EULER_MASCHERONI = 0.5772156649015329


def _norm_ppf(p: float) -> float:
    """Inverse standard normal CDF.

    Uses scipy when present and falls back to Acklam's rational approximation
    (max abs error ~1.15e-9), so this module never becomes the reason an engine
    cannot import.
    """
    try:
        from scipy.stats import norm  # noqa: PLC0415 - optional fast path

        return float(norm.ppf(p))
    except Exception:  # pragma: no cover - exercised only without scipy
        pass

    if p <= 0.0 or p >= 1.0:
        return float("-inf") if p <= 0.0 else float("inf")
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def expected_max_sharpe(n_trials: int, n_obs: int, ppy: float = 1.0) -> Optional[float]:
    """Sharpe the BEST of `n_trials` zero-edge strategies reaches by luck.

    Args:
        n_trials: strategies searched over. For one sweep this is its grid
            size; correlated parameter siblings make this an UPPER bound on the
            effective count, so the floor it returns is conservative.
        n_obs: observations (bars) each strategy was scored on.
        ppy: periods per year. Pass the same annualisation the observed Sharpe
            used, or leave at 1.0 to get a per-observation figure.

    Returns:
        The annualised noise floor, or None when the inputs cannot support the
        estimate (fewer than 2 trials or 2 observations) -- None means "not
        computable", never "passed".
    """
    if n_trials is None or n_obs is None:
        return None
    n_trials, n_obs = int(n_trials), int(n_obs)
    if n_trials < 2 or n_obs < 2:
        return None
    g = _EULER_MASCHERONI
    z1 = _norm_ppf(1.0 - 1.0 / n_trials)
    z2 = _norm_ppf(1.0 - 1.0 / (n_trials * math.e))
    per_obs = math.sqrt(1.0 / (n_obs - 1)) * ((1.0 - g) * z1 + g * z2)
    return float(per_obs * math.sqrt(max(float(ppy), 0.0)))


def deflated_sharpe_ratio(
    observed_sharpe: float,
    n_trials: int,
    n_obs: int,
    ppy: float = 1.0,
    skew: float = 0.0,
    kurtosis: float = 3.0,
) -> Optional[float]:
    """Probability the true Sharpe exceeds the search's own noise floor.

    `skew`/`kurtosis` default to the Gaussian case (0, 3) because this
    project's stored candidates do not keep the return moments. Real trading
    returns are negatively skewed and fat-tailed, both of which REDUCE this
    probability -- so the Gaussian default is optimistic, and a candidate that
    already fails under it would only fail harder with its true moments.

    Returns a probability in [0, 1], or None when not computable. Convention
    follows the paper: >= 0.95 is the usual bar for taking a backtest
    seriously.
    """
    if observed_sharpe is None:
        return None
    floor = expected_max_sharpe(n_trials, n_obs, ppy)
    if floor is None:
        return None
    n = int(n_obs)
    # Work in per-observation units; both figures are annualised by the same
    # sqrt(ppy), so the ratio is unaffected but the variance term is not.
    scale = math.sqrt(max(float(ppy), 1e-12))
    sr = float(observed_sharpe) / scale
    sr0 = floor / scale
    denom_sq = (1.0 - skew * sr + (kurtosis - 1.0) / 4.0 * sr * sr) / (n - 1)
    if denom_sq <= 0:
        return None
    z = (sr - sr0) / math.sqrt(denom_sq)
    # Standard normal CDF via erf -- no scipy needed for this direction.
    return float(0.5 * (1.0 + math.erf(z / math.sqrt(2.0))))
