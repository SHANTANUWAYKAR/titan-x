"""
Module: engine.py
Description: Engine 8 — Quantitative Research (VaR/CVaR, Sharpe/Sortino/
Calmar, Kelly Criterion, PCA correlation clustering, cointegration testing,
Bayesian win-rate updating).
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-07-13
"""

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import polars as pl
from scipy import stats as scipy_stats
from sklearn.decomposition import PCA
from statsmodels.regression.linear_model import OLS
from statsmodels.tools import add_constant
from statsmodels.tsa.stattools import adfuller, coint

from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus
from project_titan_x.engines.e01_knowledge.engine import KnowledgeEngine

logger = logging.getLogger(__name__)

TRADING_DAYS_PER_YEAR = 252


@dataclass
class RiskMetrics:
    """Portfolio/return-series risk-adjusted performance metrics."""

    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    cagr_pct: float
    max_drawdown_pct: float
    value_at_risk_pct: float
    conditional_var_pct: float
    var_confidence: float
    n_periods: int


@dataclass
class KellyResult:
    """Kelly Criterion position sizing result."""

    kelly_fraction: float
    half_kelly_fraction: float
    edge: float
    win_rate: float
    win_loss_ratio: float
    recommendation: str
    knowledge_context: Optional[dict] = None


@dataclass
class CointegrationResult:
    """Engle-Granger cointegration test result between two price series."""

    t_statistic: float
    p_value: float
    critical_values: dict
    is_cointegrated: bool
    confidence_level: str


@dataclass
class StationarityResult:
    """Augmented Dickey-Fuller stationarity test result for a single series."""

    adf_statistic: float
    p_value: float
    critical_values: dict
    is_stationary: bool
    confidence_level: str


@dataclass
class HalfLifeResult:
    """Ornstein-Uhlenbeck half-life of mean reversion for a spread series."""

    half_life_periods: Optional[float]  # None if the series shows no mean-reverting tendency (beta >= 0)
    mean_reverting: bool
    theta: float  # OLS beta (speed-of-reversion) coefficient; negative = mean-reverting


@dataclass
class HurstExponentResult:
    """Hurst exponent -- H<0.5 mean-reverting, H~0.5 random walk, H>0.5 trending/persistent."""

    hurst_exponent: float
    interpretation: str  # "mean_reverting" | "random_walk" | "trending"
    r_squared: float  # fit quality of the log(R/S) vs log(lag) regression the exponent came from


@dataclass
class CorrelationClusterResult:
    """Correlation matrix + PCA-based concentration-risk analysis."""

    symbols: list
    correlation_matrix: list
    explained_variance_ratio: list
    n_components_for_90pct: int
    diversification_ratio: float
    highly_correlated_pairs: list


@dataclass
class RollingCorrelationResult:
    """Rolling vs. full-period pairwise correlation -- surfaces cross-asset
    correlation REGIME SHIFTS (e.g. normally low-correlation assets suddenly
    moving together in a risk-off shock) that correlation_clustering's
    single static snapshot can't see, since that reports one number per
    pair across the whole sample."""

    symbols: list
    window: int
    recent_correlation_matrix: list
    full_period_correlation_matrix: list
    correlation_regime_shifts: list


@dataclass
class GARCHVolatilityResult:
    """GARCH(1,1) conditional volatility fit + multi-step-ahead forecast."""

    omega: float
    alpha: float
    beta: float
    persistence: float  # alpha + beta; close to 1 = shocks decay slowly
    current_conditional_volatility_pct: float  # most recent in-sample fitted vol, annualized
    forecast_volatility_pct: list  # one value per horizon step, annualized
    forecast_horizon: int
    long_run_volatility_pct: Optional[float]  # unconditional long-run vol; None if persistence >= 1 (non-stationary)
    converged: bool


@dataclass
class BayesianWinRateResult:
    """Beta-Binomial Bayesian update of a strategy's true win rate."""

    prior_alpha: float
    prior_beta: float
    posterior_alpha: float
    posterior_beta: float
    posterior_mean: float
    credible_interval_90pct: tuple


class QuantResearchEngine(BaseEngine):
    """
    Quantitative Research Engine — cross-asset/portfolio-level quant toolkit.

    Distinct in scope from e26_backtesting (which simulates ONE strategy's
    trade sequence via Monte Carlo/stress test): this engine operates on
    arbitrary return/price series across MULTIPLE assets -- risk-adjusted
    performance ratios, tail-risk (VaR/CVaR), position sizing (Kelly),
    portfolio concentration risk (correlation/PCA), pairs-trading validation
    (cointegration), and calibrating confidence in an edge (Bayesian
    win-rate updating). Every method is a pure function of the series/counts
    passed in -- no network calls, no lookahead, easy to unit test.
    """

    engine_id = "e12_quant_research"
    engine_name = "Quantitative Research Engine"
    version = "1.0.0"

    def __init__(self, knowledge_engine: Optional[KnowledgeEngine] = None) -> None:
        super().__init__()
        # Optional and None by default: without it, kelly_criterion()
        # behaves exactly as before (no knowledge_context). Pass a real
        # instance (as registry.py does) to turn it on.
        self._knowledge_engine = knowledge_engine

    def initialize(self) -> EngineResult:
        """Initialize engine (stateless -- nothing to warm up)."""
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Quantitative Research Engine initialized")

    def health_check(self) -> EngineResult:
        """Health check (always healthy -- no external dependencies)."""
        return EngineResult(success=True, message="Healthy")

    # ---- Risk-adjusted performance ----

    def compute_risk_metrics(
        self,
        returns: np.ndarray,
        risk_free_rate: float = 0.0,
        periods_per_year: int = TRADING_DAYS_PER_YEAR,
        var_confidence: float = 0.95,
    ) -> EngineResult:
        """
        Compute Sharpe, Sortino, Calmar, CAGR, max drawdown, historical VaR
        and CVaR from a periodic returns series (fractional returns, e.g.
        0.01 for +1% -- NOT a price series).

        Args:
            returns: Periodic fractional returns.
            risk_free_rate: Annualized risk-free rate (e.g. 0.05 for 5%).
            periods_per_year: Annualization factor (252 for daily, 52 weekly).
            var_confidence: VaR/CVaR confidence level (e.g. 0.95).

        Returns:
            EngineResult with a RiskMetrics instance in data.
        """
        try:
            returns = np.asarray(returns, dtype=float)
            returns = returns[~np.isnan(returns)]
            if len(returns) < 2:
                return EngineResult(success=False, message="Need at least 2 return observations")

            rf_period = risk_free_rate / periods_per_year
            excess = returns - rf_period

            mean_ret = float(np.mean(excess))
            std_ret = float(np.std(excess, ddof=1))
            sharpe = (mean_ret / std_ret * np.sqrt(periods_per_year)) if std_ret > 0 else 0.0

            # Downside deviation = RMS deviation from the target (0), over
            # ALL periods (standard Sortino/empyrical/vectorbt convention)
            # -- NOT the sample std of just the negative subset around ITS
            # OWN mean. The latter (previous implementation here) measures
            # dispersion of losses around their average loss rather than
            # around zero, which can collapse to ~0 for a series of
            # steady, similarly-sized losses even though real downside
            # risk is present, silently zeroing out the Sortino ratio.
            downside_sq = np.where(excess < 0, excess, 0.0) ** 2
            downside_std = float(np.sqrt(np.mean(downside_sq)))
            sortino = (mean_ret / downside_std * np.sqrt(periods_per_year)) if downside_std > 0 else 0.0

            equity_curve = np.cumprod(1 + returns)
            running_max = np.maximum.accumulate(equity_curve)
            drawdown = (equity_curve - running_max) / running_max
            max_dd_pct = float(-drawdown.min() * 100)

            n_periods = len(returns)
            years = n_periods / periods_per_year
            total_return = float(equity_curve[-1])
            cagr_pct = ((total_return ** (1 / years)) - 1) * 100 if years > 0 and total_return > 0 else 0.0

            calmar = (cagr_pct / max_dd_pct) if max_dd_pct > 0 else 0.0

            var_pct = self._historical_var(returns, var_confidence) * 100
            cvar_pct = self._historical_cvar(returns, var_confidence) * 100

            metrics = RiskMetrics(
                sharpe_ratio=round(sharpe, 4),
                sortino_ratio=round(sortino, 4),
                calmar_ratio=round(calmar, 4),
                cagr_pct=round(cagr_pct, 2),
                max_drawdown_pct=round(max_dd_pct, 2),
                value_at_risk_pct=round(var_pct, 3),
                conditional_var_pct=round(cvar_pct, 3),
                var_confidence=var_confidence,
                n_periods=n_periods,
            )
            self._set_status(EngineStatus.IDLE)
            return EngineResult(success=True, data=metrics, message="Risk metrics computed")
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("Risk metrics computation failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    @staticmethod
    def _historical_var(returns: np.ndarray, confidence: float) -> float:
        """Historical VaR: loss at the (1-confidence) percentile (positive = loss)."""
        percentile = (1 - confidence) * 100
        return float(-np.percentile(returns, percentile))

    @staticmethod
    def _historical_cvar(returns: np.ndarray, confidence: float) -> float:
        """Historical CVaR/Expected Shortfall: mean loss BEYOND the VaR threshold."""
        percentile = (1 - confidence) * 100
        threshold = np.percentile(returns, percentile)
        tail = returns[returns <= threshold]
        if len(tail) == 0:
            return float(-threshold)
        return float(-tail.mean())

    def parametric_var(self, returns: np.ndarray, confidence: float = 0.95) -> EngineResult:
        """Parametric (variance-covariance) VaR assuming normally distributed returns."""
        try:
            returns = np.asarray(returns, dtype=float)
            returns = returns[~np.isnan(returns)]
            if len(returns) < 2:
                return EngineResult(success=False, message="Need at least 2 return observations")
            mean = float(np.mean(returns))
            std = float(np.std(returns, ddof=1))
            z = scipy_stats.norm.ppf(1 - confidence)
            var = -(mean + z * std)
            return EngineResult(
                success=True,
                data={"parametric_var_pct": round(var * 100, 3), "confidence": confidence},
                message="Parametric VaR computed",
            )
        except Exception as e:
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    # ---- Position sizing ----

    def kelly_criterion(
        self, win_rate: float, avg_win: float, avg_loss: float, fraction_cap: float = 0.25
    ) -> EngineResult:
        """
        Kelly Criterion: the mathematically optimal fraction of capital to
        risk given a known edge. Full Kelly is capped (default 25%) and
        half-Kelly is always also returned -- the standard real-world
        adjustment, since full Kelly assumes the win-rate/payoff estimates
        are exact, which they never are with a finite trade sample.

        Args:
            win_rate: Historical win rate (0-1).
            avg_win: Average win size in R-multiples or % (positive).
            avg_loss: Average loss size in R-multiples or % (positive number).
            fraction_cap: Hard sanity cap on the suggested fraction.
        """
        try:
            if not (0 < win_rate < 1):
                return EngineResult(success=False, message="win_rate must be between 0 and 1")
            if avg_win <= 0 or avg_loss <= 0:
                return EngineResult(success=False, message="avg_win and avg_loss must be positive")

            win_loss_ratio = avg_win / avg_loss
            loss_rate = 1 - win_rate
            kelly_fraction = win_rate - (loss_rate / win_loss_ratio)
            edge = win_rate * avg_win - loss_rate * avg_loss

            kelly_fraction_capped = max(0.0, min(kelly_fraction, fraction_cap))
            half_kelly = kelly_fraction_capped / 2

            if kelly_fraction <= 0:
                recommendation = "No positive edge detected -- Kelly says do not size this bet at all."
            elif kelly_fraction > fraction_cap:
                recommendation = (
                    f"Full Kelly ({kelly_fraction:.1%}) exceeds the {fraction_cap:.0%} sanity cap -- "
                    f"using half of the capped value ({half_kelly:.1%}) is the standard real-world "
                    "adjustment for parameter uncertainty."
                )
            else:
                recommendation = f"Half-Kelly ({half_kelly:.1%}) is the conservative real-world sizing."

            result = KellyResult(
                kelly_fraction=round(kelly_fraction_capped, 4),
                half_kelly_fraction=round(half_kelly, 4),
                edge=round(edge, 4),
                win_rate=win_rate,
                win_loss_ratio=round(win_loss_ratio, 4),
                recommendation=recommendation,
                knowledge_context=self._build_knowledge_context(),
            )
            return EngineResult(success=True, data=result, message="Kelly fraction computed")
        except Exception as e:
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def _build_knowledge_context(self) -> Optional[dict]:
        """Relevant position-sizing/Kelly Criterion book content, attached
        for transparency -- informational only, never changes the computed
        kelly_fraction/recommendation. Best-effort: only runs if a real
        KnowledgeEngine instance was injected (see __init__ / registry.py)."""
        if self._knowledge_engine is None:
            return None
        try:
            results = self._knowledge_engine.document_store.hybrid_search(
                "Kelly criterion position sizing edge win rate payoff ratio", limit=3
            )
        except Exception as e:
            logger.warning("Knowledge context unavailable: %s", e)
            return None
        if not results:
            return None
        return {"results": [r.to_dict() for r in results]}

    # ---- Portfolio concentration risk ----

    def correlation_clustering(
        self, returns_by_symbol: dict, high_correlation_threshold: float = 0.7
    ) -> EngineResult:
        """
        Correlation matrix + PCA across multiple assets' return series --
        surfaces hidden concentration risk (assets that LOOK diversified by
        name/asset-class but move together).

        Args:
            returns_by_symbol: {symbol: array of aligned periodic returns}.
                All arrays must be the same length (same dates/order).
            high_correlation_threshold: Absolute correlation above which a
                pair is flagged as a hidden-concentration risk.
        """
        try:
            symbols = list(returns_by_symbol.keys())
            if len(symbols) < 2:
                return EngineResult(success=False, message="Need at least 2 symbols to compute correlation")

            lengths = {len(v) for v in returns_by_symbol.values()}
            if len(lengths) != 1:
                return EngineResult(success=False, message="All return series must be the same length (aligned dates)")

            matrix = np.column_stack([np.asarray(returns_by_symbol[s], dtype=float) for s in symbols])
            corr = np.corrcoef(matrix, rowvar=False)

            pairs = []
            for i in range(len(symbols)):
                for j in range(i + 1, len(symbols)):
                    if abs(corr[i, j]) >= high_correlation_threshold:
                        pairs.append(
                            {
                                "symbol_a": symbols[i],
                                "symbol_b": symbols[j],
                                "correlation": round(float(corr[i, j]), 3),
                            }
                        )

            n_components = min(len(symbols), matrix.shape[0])
            pca = PCA(n_components=n_components)
            pca.fit(matrix)
            explained = pca.explained_variance_ratio_
            cumulative = np.cumsum(explained)
            n_for_90 = int(np.searchsorted(cumulative, 0.9) + 1)

            # How many independent risk factors your book actually has vs.
            # how many symbols you think you hold. 1.0 = fully independent;
            # low = hidden concentration behind an apparently diverse list.
            diversification_ratio = float(n_for_90 / len(symbols))

            result = CorrelationClusterResult(
                symbols=symbols,
                correlation_matrix=corr.round(3).tolist(),
                explained_variance_ratio=[round(float(x), 4) for x in explained],
                n_components_for_90pct=n_for_90,
                diversification_ratio=round(diversification_ratio, 3),
                highly_correlated_pairs=pairs,
            )
            return EngineResult(success=True, data=result, message="Correlation/PCA analysis complete")
        except Exception as e:
            logger.error("Correlation clustering failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def rolling_correlation(
        self,
        returns_by_symbol: dict,
        window: int = 30,
        shift_threshold: float = 0.3,
    ) -> EngineResult:
        """
        Rolling (recent-window) vs. full-period cross-asset correlation,
        computed with polars for the columnar correlation math. Flags pairs
        whose recent correlation has moved sharply away from their
        full-period correlation -- a correlation REGIME SHIFT (classically,
        normally-diversifying assets suddenly moving together in a risk-off
        shock), which correlation_clustering's single static matrix can't
        surface since it only reports one number per pair for the whole
        sample.

        Args:
            returns_by_symbol: {symbol: array of aligned periodic returns}.
                All arrays must be the same length (same dates/order).
            window: Recent-window length (in periods) to compare against
                the full-period correlation.
            shift_threshold: Absolute correlation change above which a pair
                is flagged as a regime shift.
        """
        try:
            symbols = list(returns_by_symbol.keys())
            if len(symbols) < 2:
                return EngineResult(success=False, message="Need at least 2 symbols to compute correlation")

            lengths = {len(v) for v in returns_by_symbol.values()}
            if len(lengths) != 1:
                return EngineResult(success=False, message="All return series must be the same length (aligned dates)")
            n_periods = lengths.pop()
            if n_periods < window + 5:
                return EngineResult(
                    success=False,
                    message=f"Need at least {window + 5} periods for a {window}-period rolling window",
                )

            pldf = pl.DataFrame({s: np.asarray(returns_by_symbol[s], dtype=float) for s in symbols})
            full_corr = pldf.corr().to_numpy()
            recent_corr = pldf.tail(window).corr().to_numpy()

            shifts = []
            for i in range(len(symbols)):
                for j in range(i + 1, len(symbols)):
                    delta = float(recent_corr[i, j] - full_corr[i, j])
                    if abs(delta) >= shift_threshold:
                        shifts.append({
                            "symbol_a": symbols[i],
                            "symbol_b": symbols[j],
                            "full_period_correlation": round(float(full_corr[i, j]), 3),
                            "recent_correlation": round(float(recent_corr[i, j]), 3),
                            "shift": round(delta, 3),
                        })

            result = RollingCorrelationResult(
                symbols=symbols,
                window=window,
                recent_correlation_matrix=np.round(recent_corr, 3).tolist(),
                full_period_correlation_matrix=np.round(full_corr, 3).tolist(),
                correlation_regime_shifts=shifts,
            )
            return EngineResult(
                success=True,
                data=result,
                message=f"Rolling correlation complete ({len(shifts)} regime shift(s) flagged)",
            )
        except Exception as e:
            logger.error("Rolling correlation failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    # ---- Pairs / stat-arb research ----

    def test_cointegration(self, series_a: np.ndarray, series_b: np.ndarray) -> EngineResult:
        """
        Engle-Granger cointegration test between two PRICE series (not
        returns) -- the standard first check before trusting a pairs/
        stat-arb strategy. Two series can each be individually non-stationary
        (random walks) yet cointegrated (a stable long-run relationship),
        which is the actual precondition a mean-reversion pairs trade relies
        on -- correlation alone is not sufficient and can be spurious.
        """
        try:
            series_a = np.asarray(series_a, dtype=float)
            series_b = np.asarray(series_b, dtype=float)
            if len(series_a) != len(series_b):
                return EngineResult(success=False, message="Series must be the same length")
            if len(series_a) < 30:
                return EngineResult(success=False, message="Need at least 30 observations for a meaningful test")

            t_stat, p_value, crit_values = coint(series_a, series_b)

            if p_value < 0.01:
                confidence_level = "strong (p<0.01)"
            elif p_value < 0.05:
                confidence_level = "moderate (p<0.05)"
            elif p_value < 0.10:
                confidence_level = "weak (p<0.10)"
            else:
                confidence_level = "not cointegrated"

            result = CointegrationResult(
                t_statistic=round(float(t_stat), 4),
                p_value=round(float(p_value), 4),
                critical_values={
                    "1%": round(float(crit_values[0]), 4),
                    "5%": round(float(crit_values[1]), 4),
                    "10%": round(float(crit_values[2]), 4),
                },
                is_cointegrated=bool(p_value < 0.05),
                confidence_level=confidence_level,
            )
            return EngineResult(success=True, data=result, message=f"Cointegration test: {confidence_level}")
        except Exception as e:
            logger.error("Cointegration test failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def test_stationarity(self, series: np.ndarray) -> EngineResult:
        """
        Augmented Dickey-Fuller test on a SINGLE series -- added
        2026-08-02, standalone complement to test_cointegration above
        (which needs a PAIR). Directly useful for checking whether a
        pairs-trade SPREAD itself is stationary (the actual tradeable
        object once you have two cointegrated legs), or any other single
        series someone wants to check for mean-reversion vs random-walk/
        trending behavior, without needing a second series to pair it
        against. Uses statsmodels.tsa.stattools.adfuller -- same library
        this engine already depends on for coint() above, no new
        dependency.

        Args:
            series: The series to test (e.g. a price series or a pairs-trade spread).
        """
        try:
            series = np.asarray(series, dtype=float)
            series = series[~np.isnan(series)]
            if len(series) < 30:
                return EngineResult(success=False, message="Need at least 30 observations for a meaningful test")

            adf_stat, p_value, _, _, crit_values, _ = adfuller(series)

            if p_value < 0.01:
                confidence_level = "strong (p<0.01)"
            elif p_value < 0.05:
                confidence_level = "moderate (p<0.05)"
            elif p_value < 0.10:
                confidence_level = "weak (p<0.10)"
            else:
                confidence_level = "not stationary"

            result = StationarityResult(
                adf_statistic=round(float(adf_stat), 4),
                p_value=round(float(p_value), 4),
                critical_values={k: round(float(v), 4) for k, v in crit_values.items()},
                is_stationary=bool(p_value < 0.05),
                confidence_level=confidence_level,
            )
            return EngineResult(success=True, data=result, message=f"Stationarity test: {confidence_level}")
        except Exception as e:
            logger.error("Stationarity test failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def half_life_of_mean_reversion(self, spread: np.ndarray) -> EngineResult:
        """
        Ornstein-Uhlenbeck half-life of mean reversion -- added 2026-08-02,
        the natural next question after test_cointegration confirms two
        series ARE cointegrated: HOW FAST does their spread actually
        revert? A cointegrated pair with a 400-period half-life is not
        practically tradeable the same way one with a 5-period half-life
        is -- cointegration alone doesn't say which.

        Fits spread_t - spread_{t-1} = alpha + theta * spread_{t-1} + noise
        via OLS (the discretized Ornstein-Uhlenbeck / AR(1) form); if
        theta < 0 (genuine mean reversion), half_life = -ln(2) / theta.
        If theta >= 0, the series shows no mean-reverting tendency at all
        over this sample and half_life is reported as None -- not a
        fabricated number.

        Args:
            spread: A price/spread series (e.g. the residual of a cointegrated pair), not returns.
        """
        try:
            spread = np.asarray(spread, dtype=float)
            spread = spread[~np.isnan(spread)]
            if len(spread) < 20:
                return EngineResult(success=False, message="Need at least 20 observations for a meaningful half-life estimate")

            lagged = spread[:-1]
            delta = spread[1:] - lagged
            X = add_constant(lagged)
            model = OLS(delta, X).fit()
            theta = float(model.params[1])

            if theta < 0:
                half_life = -np.log(2) / theta
                mean_reverting = True
            else:
                half_life = None
                mean_reverting = False

            result = HalfLifeResult(
                half_life_periods=round(half_life, 2) if half_life is not None else None,
                mean_reverting=mean_reverting,
                theta=round(theta, 6),
            )
            msg = f"Half-life: {half_life:.1f} periods" if half_life is not None else "No mean-reverting tendency detected (theta >= 0)"
            return EngineResult(success=True, data=result, message=msg)
        except Exception as e:
            logger.error("Half-life computation failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    @staticmethod
    def _rescaled_range(chunk: np.ndarray) -> float:
        """R/S statistic for one chunk: the range of cumulative
        mean-centered deviations, divided by the chunk's own standard
        deviation -- the core building block of classical R/S (rescaled
        range) Hurst-exponent estimation."""
        deviations = chunk - chunk.mean()
        cumulative = np.cumsum(deviations)
        r = cumulative.max() - cumulative.min()
        s = chunk.std(ddof=1)
        return float(r / s) if s > 0 else 0.0

    def hurst_exponent(self, series: np.ndarray, min_lag: int = 10, max_lag: Optional[int] = None) -> EngineResult:
        """
        Hurst exponent via classical R/S (rescaled range) analysis --
        added 2026-08-02. H < 0.5 indicates mean-reverting behavior
        (useful alongside test_stationarity/half_life_of_mean_reversion
        above), H ~ 0.5 a genuine random walk, H > 0.5 trending/
        persistent behavior (a series that keeps moving in the same
        direction more than chance alone would predict) -- one of the
        most-cited single-number regime diagnostics in quantitative
        finance literature, previously entirely absent from this engine.

        Splits the series' INCREMENTS (not the level series itself) into
        non-overlapping chunks at a range of lag sizes, computes each
        chunk's R/S statistic, averages per lag, then fits
        log(avg R/S) = H * log(lag) + c via OLS -- the slope is the Hurst
        exponent. r_squared of that fit is reported alongside so a poor
        fit (unreliable estimate) is visible, not hidden behind a single
        confident-looking number.

        Real bug caught in testing: the classical R/S method is defined
        on a series' INCREMENTS, not its level -- running it on the level
        series directly (as this did before) effectively double-
        integrates the data, badly distorting the lag-scaling relationship
        the whole method depends on. Confirmed directly: a pure random
        walk (should read ~0.5) and a strongly mean-reverting
        Ornstein-Uhlenbeck series (should read well below 0.5, verified
        via half_life_of_mean_reversion/test_stationarity on the SAME
        synthetic series both correctly identifying it as mean-reverting)
        both came back above 0.9 ("trending") before this fix -- taking
        np.diff(series) first fixes it.

        Args:
            series: The series to analyze (typically a price series -- differenced internally, don't pass returns).
            min_lag: Smallest chunk size to test.
            max_lag: Largest chunk size to test (defaults to n//4).
        """
        try:
            series = np.asarray(series, dtype=float)
            series = series[~np.isnan(series)]
            increments = np.diff(series)
            n = len(increments)
            if n < min_lag * 4:
                return EngineResult(success=False, message=f"Need at least {min_lag * 4 + 1} observations for a meaningful Hurst estimate")

            effective_max_lag = max_lag or n // 4
            candidate_lags = np.unique(np.logspace(np.log10(min_lag), np.log10(effective_max_lag), num=15).astype(int))

            valid_lags, avg_rs = [], []
            for lag in candidate_lags:
                if lag < 2:
                    continue
                n_chunks = n // lag
                if n_chunks < 1:
                    continue
                rs_values = [self._rescaled_range(increments[i * lag:(i + 1) * lag]) for i in range(n_chunks)]
                rs_values = [v for v in rs_values if v > 0]
                if rs_values:
                    valid_lags.append(lag)
                    avg_rs.append(float(np.mean(rs_values)))

            if len(valid_lags) < 3:
                return EngineResult(success=False, message="Not enough valid lag windows to fit a Hurst exponent")

            log_lags = np.log(valid_lags)
            log_rs = np.log(avg_rs)
            X = add_constant(log_lags)
            model = OLS(log_rs, X).fit()
            hurst = float(model.params[1])
            r_squared = float(model.rsquared)

            if hurst < 0.45:
                interpretation = "mean_reverting"
            elif hurst > 0.55:
                interpretation = "trending"
            else:
                interpretation = "random_walk"

            result = HurstExponentResult(
                hurst_exponent=round(hurst, 4), interpretation=interpretation, r_squared=round(r_squared, 4),
            )
            return EngineResult(success=True, data=result, message=f"Hurst exponent: {hurst:.3f} ({interpretation})")
        except Exception as e:
            logger.error("Hurst exponent computation failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    # ---- Volatility forecasting ----

    def garch_volatility_forecast(
        self,
        returns: np.ndarray,
        horizon: int = 10,
        periods_per_year: int = TRADING_DAYS_PER_YEAR,
    ) -> EngineResult:
        """
        GARCH(1,1) conditional volatility fit + multi-step-ahead forecast.

        MASTER_PROMPT.md's own QUANTITATIVE FINANCE section explicitly
        requires "...PCA, Cointegration, GARCH, Volatility Forecasting,
        Correlation Clustering..." -- everything else in that list is
        implemented somewhere in this engine already (PCA/correlation
        clustering above, cointegration above), but GARCH itself was a
        real, undocumented gap: absent from every engine in this codebase
        (confirmed via a full-repo grep 2026-08-20; the only prior mention
        was e20_factor_research's own docstring quoting this same master-
        prompt line, never implemented). Unlike the FOMC-dates or CDS-
        spread gaps documented elsewhere in this project, this one had no
        "no free data source" justification -- GARCH needs only a return
        series this engine already accepts everywhere else, so it's added
        here rather than left undone.

        Uses the `arch` package's maximum-likelihood estimator (industry-
        standard for this exact model; MLE convergence/parameter-constraint
        handling for GARCH has real numerical subtlety not worth
        re-deriving, same "use the real library" discipline as
        statsmodels' adfuller/coint above) to fit
        sigma_t^2 = omega + alpha*eps_{t-1}^2 + beta*sigma_{t-1}^2, then
        reports BOTH the current in-sample conditional volatility and a
        genuine multi-step-ahead forecast -- the actual point of GARCH
        (today's volatility clustering predicts tomorrow's) that a flat
        historical-std estimate (e.g. compute_risk_metrics' std_ret above)
        cannot capture. persistence = alpha+beta is reported raw, not
        classified into a label, so a caller can judge shock-decay speed
        directly (>=1 means non-stationary variance -- long_run_volatility
        is None in that case rather than a fabricated number from dividing
        by a non-positive denominator).

        Args:
            returns: Periodic fractional returns (same convention as
                compute_risk_metrics -- NOT a price series).
            horizon: Number of periods ahead to forecast.
            periods_per_year: Annualization factor (252 for daily, matching
                this engine's existing convention).
        """
        try:
            returns = np.asarray(returns, dtype=float)
            returns = returns[~np.isnan(returns)]
            if len(returns) < 100:
                return EngineResult(success=False, message="Need at least 100 return observations for a meaningful GARCH fit")
            if horizon < 1:
                return EngineResult(success=False, message="horizon must be >= 1")

            from arch import arch_model

            # arch's optimizer is numerically most stable on returns scaled
            # to roughly O(1)-O(10) in magnitude, not raw fractional returns
            # (e.g. 0.01) -- a documented arch-package convention (rescale
            # warns/can silently rescale itself otherwise), not a hack.
            # Converted back to fractional terms in every reported number
            # below.
            scaled_returns = returns * 100
            model = arch_model(scaled_returns, vol="Garch", p=1, q=1, mean="Zero", rescale=False)
            fit = model.fit(disp="off")

            omega = float(fit.params["omega"])
            alpha = float(fit.params["alpha[1]"])
            beta = float(fit.params["beta[1]"])
            persistence = alpha + beta

            current_daily = float(fit.conditional_volatility[-1]) / 100
            current_annualized_pct = current_daily * np.sqrt(periods_per_year) * 100

            forecast = fit.forecast(horizon=horizon, reindex=False)
            forecast_daily = np.sqrt(forecast.variance.values[-1]) / 100
            forecast_annualized_pct = (forecast_daily * np.sqrt(periods_per_year) * 100).tolist()

            if persistence < 1:
                long_run_daily = np.sqrt(omega / (1 - persistence)) / 100
                long_run_annualized_pct = round(float(long_run_daily * np.sqrt(periods_per_year) * 100), 3)
            else:
                long_run_annualized_pct = None

            result = GARCHVolatilityResult(
                omega=round(omega, 6),
                alpha=round(alpha, 4),
                beta=round(beta, 4),
                persistence=round(persistence, 4),
                current_conditional_volatility_pct=round(current_annualized_pct, 3),
                forecast_volatility_pct=[round(float(v), 3) for v in forecast_annualized_pct],
                forecast_horizon=horizon,
                long_run_volatility_pct=long_run_annualized_pct,
                converged=bool(fit.convergence_flag == 0),
            )
            return EngineResult(
                success=True,
                data=result,
                message=f"GARCH(1,1) fit: persistence={persistence:.3f}, {horizon}-period volatility forecast computed",
            )
        except Exception as e:
            logger.error("GARCH volatility forecast failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    # ---- Confidence calibration ----

    def bayesian_win_rate_update(
        self, wins: int, losses: int, prior_alpha: float = 1.0, prior_beta: float = 1.0
    ) -> EngineResult:
        """
        Beta-Binomial Bayesian update of a strategy's TRUE win rate given
        observed wins/losses. Default prior (alpha=1, beta=1) is uniform --
        no assumption before seeing data. Returns the posterior mean and a
        90% credible interval: a small sample should show a WIDE interval,
        which is the point -- this platform's confidence-calibration
        principle depends on knowing how uncertain a win-rate estimate still
        is, not just trusting its raw point value.

        Args:
            wins: Observed winning trades.
            losses: Observed losing trades.
            prior_alpha: Beta distribution prior alpha (successes).
            prior_beta: Beta distribution prior beta (failures).
        """
        try:
            if wins < 0 or losses < 0:
                return EngineResult(success=False, message="wins and losses must be non-negative")
            if prior_alpha <= 0 or prior_beta <= 0:
                return EngineResult(success=False, message="prior_alpha and prior_beta must be positive")

            posterior_alpha = prior_alpha + wins
            posterior_beta = prior_beta + losses
            posterior_mean = posterior_alpha / (posterior_alpha + posterior_beta)

            lower = float(scipy_stats.beta.ppf(0.05, posterior_alpha, posterior_beta))
            upper = float(scipy_stats.beta.ppf(0.95, posterior_alpha, posterior_beta))

            result = BayesianWinRateResult(
                prior_alpha=prior_alpha,
                prior_beta=prior_beta,
                posterior_alpha=posterior_alpha,
                posterior_beta=posterior_beta,
                posterior_mean=round(posterior_mean, 4),
                credible_interval_90pct=(round(lower, 4), round(upper, 4)),
            )
            return EngineResult(success=True, data=result, message="Bayesian win-rate update complete")
        except Exception as e:
            return EngineResult(success=False, message=str(e), errors=[str(e)])
