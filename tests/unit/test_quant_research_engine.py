"""
Module: test_quant_research_engine.py
Description: Unit tests for Quantitative Research Engine (E08).
Author: Shantanu Waykar
Version: 1.0.0
"""

import numpy as np
import pytest

from project_titan_x.engines.e12_quant_research import QuantResearchEngine


@pytest.fixture
def engine() -> QuantResearchEngine:
    """Create quant research engine instance."""
    e = QuantResearchEngine()
    e.initialize()
    return e


# ---- Risk metrics ----


def test_risk_metrics_positive_trend(engine: QuantResearchEngine):
    """A steady, modestly volatile uptrend should show a positive Sharpe and low drawdown."""
    rng = np.random.default_rng(42)
    returns = rng.normal(loc=0.001, scale=0.005, size=500)
    result = engine.compute_risk_metrics(returns)
    assert result.success
    m = result.data
    assert m.sharpe_ratio > 0
    assert m.cagr_pct > 0
    assert m.max_drawdown_pct >= 0
    assert m.n_periods == 500
    assert m.value_at_risk_pct > 0  # VaR reported as a positive loss magnitude


def test_risk_metrics_rejects_too_few_observations(engine: QuantResearchEngine):
    result = engine.compute_risk_metrics(np.array([0.01]))
    assert not result.success


def test_risk_metrics_handles_nan(engine: QuantResearchEngine):
    returns = np.array([0.01, np.nan, 0.02, -0.01, 0.015, -0.005, 0.02, 0.01])
    result = engine.compute_risk_metrics(returns)
    assert result.success
    assert result.data.n_periods == 7


def test_parametric_var_matches_normal_distribution_shape(engine: QuantResearchEngine):
    rng = np.random.default_rng(1)
    returns = rng.normal(loc=0.0, scale=0.01, size=1000)
    result = engine.parametric_var(returns, confidence=0.95)
    assert result.success
    # For a zero-mean, 1% std series, 95% VaR should be roughly 1.645 * std.
    assert result.data["parametric_var_pct"] == pytest.approx(1.645, abs=0.3)


# ---- Kelly Criterion ----


def test_kelly_positive_edge(engine: QuantResearchEngine):
    result = engine.kelly_criterion(win_rate=0.5, avg_win=2.0, avg_loss=1.0)
    assert result.success
    k = result.data
    # Kelly f* = W - (1-W)/R = 0.5 - 0.5/2 = 0.25
    assert k.kelly_fraction == pytest.approx(0.25, abs=0.001)
    assert k.half_kelly_fraction == pytest.approx(0.125, abs=0.001)
    assert k.edge > 0


def test_kelly_no_edge_returns_zero_fraction(engine: QuantResearchEngine):
    result = engine.kelly_criterion(win_rate=0.3, avg_win=1.0, avg_loss=1.0)
    assert result.success
    assert result.data.kelly_fraction == 0.0
    assert "No positive edge" in result.data.recommendation


def test_kelly_rejects_invalid_win_rate(engine: QuantResearchEngine):
    result = engine.kelly_criterion(win_rate=1.5, avg_win=1.0, avg_loss=1.0)
    assert not result.success


def test_kelly_caps_aggressive_full_kelly(engine: QuantResearchEngine):
    # Extreme edge would otherwise suggest an unreasonably large fraction.
    result = engine.kelly_criterion(win_rate=0.9, avg_win=5.0, avg_loss=1.0, fraction_cap=0.25)
    assert result.success
    assert result.data.kelly_fraction <= 0.25
    assert "sanity cap" in result.data.recommendation


# ---- Correlation clustering / PCA ----


def test_correlation_clustering_flags_highly_correlated_pair(engine: QuantResearchEngine):
    rng = np.random.default_rng(7)
    base = rng.normal(0, 0.01, size=200)
    returns = {
        "A": base,
        "B": base + rng.normal(0, 0.0005, size=200),  # near-identical to A
        "C": rng.normal(0, 0.01, size=200),  # independent
    }
    result = engine.correlation_clustering(returns, high_correlation_threshold=0.7)
    assert result.success
    pairs = result.data.highly_correlated_pairs
    assert any({p["symbol_a"], p["symbol_b"]} == {"A", "B"} for p in pairs)
    assert result.data.diversification_ratio <= 1.0


def test_correlation_clustering_requires_at_least_two_symbols(engine: QuantResearchEngine):
    result = engine.correlation_clustering({"A": np.array([0.01, 0.02, 0.03])})
    assert not result.success


def test_correlation_clustering_requires_aligned_lengths(engine: QuantResearchEngine):
    result = engine.correlation_clustering({"A": np.array([0.01, 0.02]), "B": np.array([0.01, 0.02, 0.03])})
    assert not result.success


# ---- Rolling correlation (cross-asset regime shifts) ----


def test_rolling_correlation_flags_regime_shift(engine: QuantResearchEngine):
    rng = np.random.default_rng(11)
    n = 200
    a = rng.normal(0, 0.01, size=n)
    b = rng.normal(0, 0.01, size=n)  # independent for most of history...
    b[-30:] = a[-30:] + rng.normal(0, 0.0005, size=30)  # ...but converges with A recently
    result = engine.rolling_correlation({"A": a, "B": b}, window=30, shift_threshold=0.3)
    assert result.success
    shifts = result.data.correlation_regime_shifts
    assert any({s["symbol_a"], s["symbol_b"]} == {"A", "B"} for s in shifts)


def test_rolling_correlation_requires_at_least_two_symbols(engine: QuantResearchEngine):
    result = engine.rolling_correlation({"A": np.random.default_rng(0).normal(size=50)})
    assert not result.success


def test_rolling_correlation_requires_enough_periods_for_window(engine: QuantResearchEngine):
    result = engine.rolling_correlation(
        {"A": np.array([0.01, 0.02, 0.03]), "B": np.array([0.02, 0.01, 0.03])}, window=30
    )
    assert not result.success


# ---- Cointegration ----


def test_cointegration_detects_cointegrated_pair(engine: QuantResearchEngine):
    rng = np.random.default_rng(3)
    common_walk = np.cumsum(rng.normal(0, 1, size=300)) + 100
    series_a = common_walk
    series_b = common_walk * 1.5 + rng.normal(0, 0.5, size=300)  # tightly tied to A
    result = engine.test_cointegration(series_a, series_b)
    assert result.success
    assert result.data.p_value < 0.05
    assert result.data.is_cointegrated


def test_cointegration_rejects_mismatched_lengths(engine: QuantResearchEngine):
    result = engine.test_cointegration(np.array([1.0, 2.0, 3.0]), np.array([1.0, 2.0]))
    assert not result.success


def test_cointegration_rejects_too_few_observations(engine: QuantResearchEngine):
    result = engine.test_cointegration(np.arange(10, dtype=float), np.arange(10, dtype=float))
    assert not result.success


# ---- Bayesian win-rate updating ----


def test_bayesian_update_small_sample_has_wide_interval(engine: QuantResearchEngine):
    result = engine.bayesian_win_rate_update(wins=3, losses=2)
    assert result.success
    r = result.data
    lower, upper = r.credible_interval_90pct
    assert lower < r.posterior_mean < upper
    assert (upper - lower) > 0.3  # 5 observations -> genuinely wide uncertainty


def test_bayesian_update_large_sample_has_narrow_interval(engine: QuantResearchEngine):
    result = engine.bayesian_win_rate_update(wins=550, losses=450)
    assert result.success
    r = result.data
    lower, upper = r.credible_interval_90pct
    assert (upper - lower) < 0.1  # 1000 observations -> tight estimate
    assert r.posterior_mean == pytest.approx(0.55, abs=0.02)


def test_bayesian_update_rejects_negative_counts(engine: QuantResearchEngine):
    result = engine.bayesian_win_rate_update(wins=-1, losses=5)
    assert not result.success


# ---- GARCH volatility forecasting ----


def _synthetic_garch_returns(rng, n: int, omega: float, alpha: float, beta: float) -> np.ndarray:
    """Real GARCH(1,1)-generated returns with KNOWN true parameters -- lets
    tests assert the fitted parameters land in the right neighborhood,
    not just that the call didn't crash."""
    returns = np.zeros(n)
    sigma2 = omega / (1 - alpha - beta)  # start at the long-run variance
    for t in range(n):
        returns[t] = rng.normal(0, np.sqrt(sigma2))
        sigma2 = omega + alpha * returns[t] ** 2 + beta * sigma2
    return returns


def test_garch_recovers_known_parameters_from_synthetic_series(engine: QuantResearchEngine):
    rng = np.random.default_rng(7)
    returns = _synthetic_garch_returns(rng, n=1500, omega=0.05, alpha=0.1, beta=0.85)
    result = engine.garch_volatility_forecast(returns, horizon=5)
    assert result.success
    r = result.data
    assert r.converged
    # True persistence is 0.95; a 1500-obs MLE fit should land in a wide
    # but genuinely diagnostic neighborhood of it, not anywhere at all.
    assert 0.80 < r.persistence < 0.999
    assert r.long_run_volatility_pct is not None
    assert r.long_run_volatility_pct > 0
    assert r.current_conditional_volatility_pct > 0


def test_garch_forecast_length_matches_horizon(engine: QuantResearchEngine):
    rng = np.random.default_rng(11)
    returns = _synthetic_garch_returns(rng, n=500, omega=0.05, alpha=0.05, beta=0.9)
    result = engine.garch_volatility_forecast(returns, horizon=10)
    assert result.success
    assert len(result.data.forecast_volatility_pct) == 10
    assert result.data.forecast_horizon == 10
    assert all(v > 0 for v in result.data.forecast_volatility_pct)


def test_garch_rejects_too_few_observations(engine: QuantResearchEngine):
    result = engine.garch_volatility_forecast(np.random.default_rng(0).normal(0, 0.01, size=50))
    assert not result.success


def test_garch_rejects_invalid_horizon(engine: QuantResearchEngine):
    returns = np.random.default_rng(0).normal(0, 0.01, size=200)
    result = engine.garch_volatility_forecast(returns, horizon=0)
    assert not result.success


def test_health_check_always_healthy(engine: QuantResearchEngine):
    assert engine.health_check().success


# ---- knowledge_context (E01 integration) ----


def _real_knowledge_engine(tmp_path, note_text: str):
    from project_titan_x.engines.e01_knowledge.document_store import DocumentStore
    from project_titan_x.engines.e01_knowledge.engine import KnowledgeEngine

    store = DocumentStore(persist_dir=tmp_path / "chroma")
    knowledge_engine = KnowledgeEngine(knowledge_dir=tmp_path / "kd", data_root=tmp_path / "data", document_store=store)
    notes = tmp_path / "data" / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    (notes / "doc.txt").write_text(note_text, encoding="utf-8")
    knowledge_engine.ingestion.ingest_all()
    return knowledge_engine


def test_kelly_criterion_attaches_knowledge_context_when_injected(tmp_path):
    knowledge_engine = _real_knowledge_engine(
        tmp_path,
        "Chapter 1: Position Sizing\n\nThe Kelly criterion balances win rate against payoff ratio to size bets optimally.",
    )
    engine = QuantResearchEngine(knowledge_engine=knowledge_engine)
    engine.initialize()
    result = engine.kelly_criterion(win_rate=0.55, avg_win=1.5, avg_loss=1.0)
    assert result.success
    assert result.data.knowledge_context is not None
    assert result.data.knowledge_context["results"]


def test_kelly_criterion_knowledge_context_none_without_engine(engine: QuantResearchEngine):
    result = engine.kelly_criterion(win_rate=0.55, avg_win=1.5, avg_loss=1.0)
    assert result.success
    assert result.data.knowledge_context is None
