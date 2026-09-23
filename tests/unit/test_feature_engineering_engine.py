"""
Module: test_feature_engineering_engine.py
Description: Unit tests for Engine 21 (Feature Engineering) -- focused on
    the new distributional (rolling statistical shape) feature group
    added 2026-08-20 (see engine.py's own docstring for provenance), plus
    basic compute_features() wiring. No test file existed for this engine
    before -- these tests cover what this session added; they don't
    retroactively backfill full coverage for the pre-existing technical/
    macro/volatility assembly paths, which are otherwise only exercised
    via scripts/training/validate_e21_feature_engineering.py's own live
    sanity check.
Author: Shantanu Waykar
Version: 1.0.0
"""

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from project_titan_x.engines.e21_feature_engineering.engine import (
    DISTRIBUTIONAL_WINDOW,
    FeatureEngineeringEngine,
    _distributional_features,
)


def _make_ohlcv(closes: list[float]) -> pd.DataFrame:
    """Same shape as e02_market_data.fetch_ohlcv's real output -- plain
    RangeIndex, tz-aware UTC 'timestamp' column, not a datetime index."""
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    timestamps = [start + timedelta(days=i) for i in range(len(closes))]
    return pd.DataFrame({"timestamp": timestamps, "close": closes})


@pytest.fixture
def engine() -> FeatureEngineeringEngine:
    e = FeatureEngineeringEngine()
    e.initialize()
    return e


# ---- _distributional_features ----


def test_distributional_features_none_with_too_few_bars():
    df = _make_ohlcv([100.0] * 5)
    assert _distributional_features(df, window=DISTRIBUTIONAL_WINDOW) is None


def _closes_from_returns(returns: list[float], start: float = 100.0) -> list[float]:
    closes = [start]
    for r in returns:
        closes.append(closes[-1] * (1 + r))
    return closes


def test_distributional_features_positive_slope_for_accelerating_gains():
    """A constant % growth rate gives CONSTANT (non-trending) returns --
    it's the PRICE that trends, not the return series. To get a genuine
    positive slope in the returns series itself, returns must themselves
    increase bar to bar (accelerating gains)."""
    returns = np.linspace(0.001, 0.02, DISTRIBUTIONAL_WINDOW).tolist()
    df = _make_ohlcv(_closes_from_returns(returns))
    feats = _distributional_features(df)
    assert feats is not None
    assert feats["linear_trend_slope"] > 0


def test_distributional_features_negative_slope_for_decelerating_gains():
    returns = np.linspace(0.02, 0.001, DISTRIBUTIONAL_WINDOW).tolist()
    df = _make_ohlcv(_closes_from_returns(returns))
    feats = _distributional_features(df)
    assert feats["linear_trend_slope"] < 0


def test_distributional_features_max_location_at_the_single_spike():
    """A flat series with ONE sharp spike at a known bar -- max_return_location_frac
    should land right where that spike's return actually is."""
    n = DISTRIBUTIONAL_WINDOW + 1
    closes = [100.0] * n
    spike_bar = 10  # the spike's price move lands in returns[spike_bar - 1] (pct_change shifts by one)
    closes[spike_bar] = 130.0
    df = _make_ohlcv(closes)
    feats = _distributional_features(df)
    assert feats is not None
    # returns has DISTRIBUTIONAL_WINDOW entries (bars 1..n-1); the spike's
    # return is at position (spike_bar - 1) in that returns array.
    expected_frac = round((spike_bar - 1) / DISTRIBUTIONAL_WINDOW, 4)
    assert feats["max_return_location_frac"] == pytest.approx(expected_frac, abs=1e-9)


def test_distributional_features_area_ratio_bounds():
    rng = np.random.default_rng(0)
    closes = list(100.0 + np.cumsum(rng.normal(0, 1, DISTRIBUTIONAL_WINDOW + 1)))
    df = _make_ohlcv(closes)
    feats = _distributional_features(df)
    assert -1.0 <= feats["area_ratio"] <= 1.0


def test_distributional_features_longest_strike_below_mean_bounds():
    rng = np.random.default_rng(1)
    closes = list(100.0 + np.cumsum(rng.normal(0, 1, DISTRIBUTIONAL_WINDOW + 1)))
    df = _make_ohlcv(closes)
    feats = _distributional_features(df)
    assert 0.0 <= feats["longest_strike_below_mean_frac"] <= 1.0


# ---- compute_features wiring ----


def test_compute_features_includes_distributional_group_and_source(engine: FeatureEngineeringEngine):
    rng = np.random.default_rng(2)
    closes = list(100.0 + np.cumsum(rng.normal(0, 1, DISTRIBUTIONAL_WINDOW + 5)))
    df = _make_ohlcv(closes)
    result = engine.compute_features("EURUSD", df)
    assert result.success
    vector = result.data
    assert vector.sources["distributional"] == "computed"
    assert "skewness" in vector.distributional
    assert "linear_trend_slope" in vector.distributional
    flat = vector.to_flat_dict()
    assert "dist_skewness" in flat


def test_compute_features_distributional_unavailable_with_too_few_bars(engine: FeatureEngineeringEngine):
    df = _make_ohlcv([100.0, 101.0, 100.5])
    result = engine.compute_features("EURUSD", df)
    assert result.success  # engine still succeeds -- time features alone are always available
    assert result.data.sources["distributional"] == "unavailable"
    assert result.data.distributional == {}
