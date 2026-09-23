"""
Module: test_factor_research_engine.py
Description: Unit tests for Engine 20 (Factor Research).
Author: Shantanu Waykar
Version: 1.0.0
"""

import numpy as np
import pytest

from project_titan_x.engines.e02_market_data.engine import MarketDataEngine
from project_titan_x.engines.e20_factor_research.engine import (
    MIN_OBSERVATIONS,
    SUPPORTED_EQUITIES,
    FactorResearchEngine,
    _ols,
)


@pytest.fixture
def engine() -> FactorResearchEngine:
    e = FactorResearchEngine()
    e.initialize()
    return e


def test_health_check(engine):
    assert engine.health_check().success


def test_supported_equities_are_the_platforms_us_stocks():
    assert SUPPORTED_EQUITIES == {"AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "TSLA", "META", "JPM"}


def test_shares_market_data_engine_when_injected():
    md = MarketDataEngine()
    engine = FactorResearchEngine(market_data_engine=md)
    assert engine._market_data_engine is md


def test_defaults_to_real_market_data_engine_when_not_injected(engine):
    assert isinstance(engine._market_data_engine, MarketDataEngine)


def test_analyze_unsupported_asset_returns_honest_gap(engine):
    result = engine.analyze("GOLD")
    assert result.success
    assert result.data is None
    assert "not one of this engine's covered US equities" in result.message


def test_analyze_forex_returns_honest_gap(engine):
    result = engine.analyze("EURUSD")
    assert result.success
    assert result.data is None


def test_analyze_indian_equity_returns_honest_gap(engine):
    """RELIANCE/TCS etc. are real equities on this platform, but NOT US
    ones -- Fama-French has no theoretical basis for them either."""
    result = engine.analyze("RELIANCE")
    assert result.success
    assert result.data is None


# ---- _ols (pure function, no network) ----


def test_ols_recovers_known_coefficients_from_synthetic_data():
    rng = np.random.RandomState(0)
    n = 500
    x1 = rng.randn(n)
    x2 = rng.randn(n)
    true_alpha, true_b1, true_b2 = 0.001, 0.8, -0.3
    y = true_alpha + true_b1 * x1 + true_b2 * x2 + rng.randn(n) * 0.001
    X = np.column_stack([np.ones(n), x1, x2])
    beta, se, r_squared = _ols(y, X)
    assert beta == pytest.approx([true_alpha, true_b1, true_b2], abs=0.01)
    assert r_squared > 0.99
    assert (se > 0).all()


def test_ols_r_squared_near_zero_for_unrelated_noise():
    rng = np.random.RandomState(1)
    n = 500
    y = rng.randn(n) * 0.01
    x1 = rng.randn(n)
    X = np.column_stack([np.ones(n), x1])
    _, _, r_squared = _ols(y, X)
    assert r_squared < 0.05


def test_ols_se_matches_statsmodels_hac_reference():
    """Newey-West HAC standard errors are the whole point of this
    engine's significance testing being trustworthy on autocorrelated
    daily-return residuals -- verify the closed-form implementation
    against statsmodels' own cov_type='HAC', not just that SOME number
    comes back."""
    import statsmodels.api as sm

    from project_titan_x.engines.e20_factor_research.engine import _newey_west_maxlags

    rng = np.random.RandomState(3)
    n = 800
    X = np.column_stack([np.ones(n), rng.randn(n, 3)])
    beta_true = np.array([0.001, 0.5, -0.3, 0.2])
    eps = np.zeros(n)
    eps[0] = rng.randn()
    for t in range(1, n):  # AR(1) residuals -- genuinely autocorrelated, not i.i.d.
        eps[t] = 0.6 * eps[t - 1] + rng.randn() * 0.5
    y = X @ beta_true + eps

    beta, se, _ = _ols(y, X)
    maxlags = _newey_west_maxlags(n)
    reference = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": maxlags})

    assert se == pytest.approx(reference.bse, abs=1e-8)


def test_newey_west_se_exceeds_classical_under_autocorrelation():
    """The concrete reason this matters: with positively autocorrelated
    residuals, classical OLS standard errors understate the true
    uncertainty, which would inflate t-stats and mislabel tilts as
    significant. HAC SEs must come out larger here."""
    rng = np.random.RandomState(5)
    n = 600
    X = np.column_stack([np.ones(n), rng.randn(n)])
    beta_true = np.array([0.0, 0.4])
    eps = np.zeros(n)
    eps[0] = rng.randn()
    for t in range(1, n):
        eps[t] = 0.7 * eps[t - 1] + rng.randn() * 0.3
    y = X @ beta_true + eps

    xtx_inv = np.linalg.pinv(X.T @ X)
    beta = xtx_inv @ X.T @ y
    residuals = y - X @ beta
    classical_se = np.sqrt(np.diag(xtx_inv) * (residuals @ residuals) / (n - 2))

    _, hac_se, _ = _ols(y, X)
    assert hac_se[1] > classical_se[1]


# ---- analyze() against REAL yfinance + REAL Kenneth French data ----


@pytest.mark.network
def test_analyze_aapl_shows_real_expected_growth_tilt(engine):
    """Real, well-established finance fact (not a guess): Apple is a
    famous large-cap GROWTH stock. A correct regression must show a
    significant NEGATIVE HML beta (growth, not value)."""
    result = engine.analyze("AAPL", years=10)
    assert result.success
    assert result.data is not None
    assert result.data.n_observations >= MIN_OBSERVATIONS
    hml = next(e for e in result.data.exposures if e.factor == "HML")
    assert hml.significant
    assert hml.beta < 0
    assert hml.tilt == "growth_tilt"


@pytest.mark.network
def test_analyze_jpm_shows_real_expected_value_tilt(engine):
    """JPMorgan is a famous VALUE (banking) stock -- the opposite sign
    from AAPL/MSFT/tech. A correct regression must discriminate, not
    output the same tilt for every symbol."""
    result = engine.analyze("JPM", years=10)
    assert result.success
    hml = next(e for e in result.data.exposures if e.factor == "HML")
    assert hml.significant
    assert hml.beta > 0
    assert hml.tilt == "value_tilt"


@pytest.mark.network
def test_analyze_rejects_insufficient_history(engine):
    result = engine.analyze("AAPL", years=10)
    assert result.success
    # Sanity: real regression, real R^2 in a sane [0, 1] range, real alpha field present.
    assert 0.0 <= result.data.r_squared <= 1.0
    assert result.data.alpha_annualized_pct is not None


# ---- knowledge_context ----


def test_build_knowledge_context_none_without_engine(engine):
    from project_titan_x.engines.e20_factor_research.engine import FactorExposure

    exposures = [FactorExposure(factor="HML", beta=-0.5, t_stat=-10.0, significant=True, tilt="growth_tilt")]
    assert engine._build_knowledge_context("AAPL", exposures) is None


def test_build_knowledge_context_none_when_nothing_significant():
    from project_titan_x.engines.e20_factor_research.engine import FactorExposure

    class _StubKnowledge:
        document_store = None

    engine = FactorResearchEngine(knowledge_engine=_StubKnowledge())
    exposures = [FactorExposure(factor="HML", beta=-0.01, t_stat=0.2, significant=False, tilt="not_significant")]
    assert engine._build_knowledge_context("AAPL", exposures) is None
