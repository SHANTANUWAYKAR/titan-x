"""
Module: deflated_sharpe.py
Description: Deflated Sharpe Ratio and effective-trial counting -- Stage 0 of
    the validation standards.

    THE PROBLEM IT SOLVES. E24 searches a 167-candidate grid and E24's
    `_selection_score` picks the best survivor. Searching harder raises the
    best observed Sharpe even when nothing in the grid has an edge, because
    the maximum of N noisy statistics grows with N. A raw Sharpe of 1.2
    means something very different as the winner of 1 trial than as the
    winner of 167, and nothing in the pipeline currently accounts for that.

    DSR (Bailey & Lopez de Prado, 2014) asks: given that this candidate is
    the BEST of N trials, and given the skew and kurtosis of its own
    returns, what is the probability its true Sharpe exceeds zero? It
    answers on a probability scale, so 0.95 means "5% chance this is the
    luckiest of N coin flips".

    EFFECTIVE TRIALS. N is not 167. The grid contains 30 donchian_breakout
    variants that are near-copies of each other; counting them as 30
    independent trials overstates the search and makes DSR needlessly
    harsh. `effective_rank` measures how many INDEPENDENT bets the grid
    really represents, from the eigenvalue spectrum of the candidates'
    return correlation matrix. It has no cut threshold to tune, which is
    why it is the primary estimator here.

    WHAT DSR DOES NOT CORRECT -- state this wherever DSR is reported.
    The derivation assumes returns are near-IID. These strategies hold
    positions across many bars, so their per-bar returns are serially
    dependent. The skew/kurtosis terms correct for non-normal SHAPE; they
    do not correct for autocorrelation. Serial dependence inflates the
    apparent number of independent observations T, which biases DSR
    UPWARD -- optimistic, not conservative. A DSR of 0.96 here is weaker
    evidence than a DSR of 0.96 on genuinely IID returns.

    Engine-side and dependency-free by design: research/ may import this,
    this must never import research/.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Sequence

import numpy as np

EULER_MASCHERONI = 0.5772156649015329


@dataclass
class TrialGeometry:
    """How many independent bets a candidate grid really represents."""

    n_candidates: int
    effective_rank: float
    n_clusters: Optional[int] = None      # comparison only; DSR uses effective_rank
    method: str = "effective_rank"
    note: str = ""


@dataclass
class DeflatedSharpeResult:
    sharpe: float
    deflated_sharpe: float               # probability in [0, 1]
    expected_max_sharpe: float           # the bar the winner had to clear by luck alone
    n_effective: float
    n_observations: int
    skew: float
    kurtosis: float                      # excess + 3 (i.e. 3.0 for a normal)
    passed: bool = False
    caveats: list[str] = field(default_factory=list)


def _validate(returns: np.ndarray) -> np.ndarray:
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    return r


def effective_rank(corr: np.ndarray) -> float:
    """Number of independent directions in a correlation matrix.

    Uses the spectral entropy definition: normalise the eigenvalues into a
    probability distribution and exponentiate their Shannon entropy. A set
    of k identical candidates collapses to 1; k orthogonal ones give k.

    Chosen over hierarchical clustering as the primary estimator because
    it has no cut threshold. A dendrogram cut is a free parameter that
    would itself need calibrating, and calibrating the thing that sets the
    multiple-testing penalty against the same data invites exactly the
    circularity Stage 0 exists to remove.
    """
    if corr.size == 0:
        return 1.0
    vals = np.linalg.eigvalsh(np.asarray(corr, dtype=float))
    vals = np.clip(vals, 0.0, None)
    total = vals.sum()
    if total <= 0:
        return 1.0
    p = vals / total
    p = p[p > 1e-12]
    if p.size == 0:
        return 1.0
    entropy = -np.sum(p * np.log(p))
    return float(np.exp(entropy))


def cluster_count(corr: np.ndarray, threshold: float = 0.5) -> Optional[int]:
    """Hierarchical-clustering trial count, REPORTED FOR COMPARISON ONLY.

    Distance is sqrt(0.5*(1-rho)), the standard correlation metric, with
    average linkage. `threshold` is exactly the arbitrary knob that keeps
    this out of the DSR path -- it is here so the two estimators can be
    compared on real sweeps, not because either needs the other.

    Returns None if scipy is unavailable, so the primary path never
    depends on an optional import.
    """
    try:
        from scipy.cluster.hierarchy import fcluster, linkage
        from scipy.spatial.distance import squareform
    except Exception:
        return None
    c = np.asarray(corr, dtype=float)
    if c.shape[0] < 2:
        return int(c.shape[0])
    d = np.sqrt(np.clip(0.5 * (1.0 - c), 0.0, None))
    np.fill_diagonal(d, 0.0)
    d = (d + d.T) / 2.0                    # enforce exact symmetry for squareform
    try:
        z = linkage(squareform(d, checks=False), method="average")
        return int(len(set(fcluster(z, t=threshold, criterion="distance"))))
    except Exception:
        return None


def trial_geometry(return_streams: Sequence[Sequence[float]]) -> TrialGeometry:
    """Effective trial count from a set of candidate return streams.

    Streams are truncated to a common length and constant streams dropped:
    a candidate that never traded has zero variance, and its correlation
    with anything is undefined. Leaving those in produces NaNs that
    silently poison the whole eigenvalue spectrum.
    """
    streams = [np.asarray(s, dtype=float) for s in return_streams]
    streams = [s[np.isfinite(s)] for s in streams]
    streams = [s for s in streams if s.size > 1 and np.std(s) > 1e-12]
    n_in = len(return_streams)
    if len(streams) < 2:
        return TrialGeometry(n_candidates=n_in, effective_rank=float(max(1, len(streams))),
                             note="fewer than two non-constant streams; "
                                  "effective rank not estimable, defaulted to stream count")
    m = min(s.size for s in streams)
    mat = np.vstack([s[-m:] for s in streams])
    corr = np.corrcoef(mat)
    corr = np.nan_to_num(corr, nan=0.0, posinf=0.0, neginf=0.0)
    np.fill_diagonal(corr, 1.0)
    er = effective_rank(corr)
    note = ""
    if len(streams) < n_in:
        note = (f"{n_in - len(streams)} of {n_in} candidates produced constant or empty "
                f"return streams (no trades) and were excluded from the correlation matrix")
    return TrialGeometry(n_candidates=n_in, effective_rank=er,
                         n_clusters=cluster_count(corr), note=note)


def expected_max_sharpe(n_trials: float, sharpe_variance: float) -> float:
    """Expected maximum Sharpe across n_trials of pure noise.

    Units follow `sharpe_variance`: pass the variance of ANNUALISED Sharpes
    and the result is an annualised bar. `deflated_sharpe` converts it to
    per-period before using it -- see the units note there.

    The order-statistic approximation from Bailey & Lopez de Prado: the
    expected maximum of N standard normals, scaled by the observed spread
    of Sharpes across trials. This is the bar a winner must clear before
    it is evidence of anything.
    """
    n = max(float(n_trials), 1.0)
    if n <= 1.0 or sharpe_variance <= 0:
        return 0.0
    from statistics import NormalDist
    nd = NormalDist()
    # Guard the inverse-CDF against n so large that 1 - 1/n rounds to 1.
    q1 = min(1.0 - 1.0 / n, 1.0 - 1e-12)
    q2 = min(1.0 - 1.0 / (n * math.e), 1.0 - 1e-12)
    z = (1.0 - EULER_MASCHERONI) * nd.inv_cdf(q1) + EULER_MASCHERONI * nd.inv_cdf(q2)
    return float(math.sqrt(sharpe_variance) * z)


def deflated_sharpe(
    returns: Sequence[float],
    sharpe: float,
    n_effective: float,
    sharpe_variance: float,
    periods_per_year: float = 252.0,
    threshold: float = 0.95,
) -> DeflatedSharpeResult:
    """Probability that a candidate's true Sharpe exceeds zero, given that
    it was selected as the best of `n_effective` trials.

    `sharpe` is expected ANNUALISED (as E26 reports it) and is converted to
    per-period internally, because the test statistic is built from
    per-period moments. Mixing the two silently inflates DSR.
    """
    r = _validate(returns)
    caveats = ["DSR assumes near-IID returns. These strategies hold positions across "
               "many bars, so per-bar returns are serially dependent. The skew and "
               "kurtosis terms correct for distribution SHAPE, not autocorrelation. "
               "Serial dependence overstates the effective number of observations, "
               "which biases DSR UPWARD -- this figure is optimistic, not conservative."]
    n = r.size
    if n < 30:
        return DeflatedSharpeResult(sharpe=sharpe, deflated_sharpe=0.0,
                                    expected_max_sharpe=0.0, n_effective=n_effective,
                                    n_observations=n, skew=0.0, kurtosis=3.0,
                                    passed=False,
                                    caveats=caveats + [f"only {n} return observations; "
                                                       "DSR not computed"])
    mu, sd = float(np.mean(r)), float(np.std(r, ddof=1))
    if sd <= 0:
        return DeflatedSharpeResult(sharpe=sharpe, deflated_sharpe=0.0,
                                    expected_max_sharpe=0.0, n_effective=n_effective,
                                    n_observations=n, skew=0.0, kurtosis=3.0,
                                    passed=False, caveats=caveats + ["zero return variance"])
    z = (r - mu) / sd
    skew = float(np.mean(z ** 3))
    kurt = float(np.mean(z ** 4))                     # 3.0 for a normal

    ann = math.sqrt(periods_per_year) if periods_per_year > 0 else 1.0
    sr_per_period = float(sharpe) / ann
    # UNITS. `sharpe_variance` is the spread of ANNUALISED Sharpes across the
    # grid, because that is what E26 reports and therefore what a caller
    # actually has. expected_max_sharpe returns a bar in those same
    # annualised units, so it MUST be converted to per-period before being
    # compared with sr_per_period. Skipping this subtracts an annualised
    # threshold from a per-period statistic -- on 4h bars that is a factor
    # of ~39, which drove DSR to exactly 0.0000 for every candidate at
    # N>=10 during this module's own bring-up. It looked like a decisive
    # statistical verdict and was a unit error.
    sr0_annual = expected_max_sharpe(n_effective, sharpe_variance)
    sr0 = sr0_annual / ann

    denom = 1.0 - skew * sr_per_period + ((kurt - 1.0) / 4.0) * sr_per_period ** 2
    if denom <= 0:
        return DeflatedSharpeResult(sharpe=sharpe, deflated_sharpe=0.0,
                                    expected_max_sharpe=sr0 * ann, n_effective=n_effective,
                                    n_observations=n, skew=skew, kurtosis=kurt,
                                    passed=False,
                                    caveats=caveats + ["non-positive variance term; "
                                                       "extreme skew/kurtosis"])
    stat = (sr_per_period - sr0) * math.sqrt(n - 1) / math.sqrt(denom)
    from statistics import NormalDist
    dsr = float(NormalDist().cdf(stat))
    return DeflatedSharpeResult(
        sharpe=float(sharpe), deflated_sharpe=dsr, expected_max_sharpe=float(sr0_annual),
        n_effective=float(n_effective), n_observations=n, skew=skew, kurtosis=kurt,
        passed=dsr >= threshold, caveats=caveats,
    )
