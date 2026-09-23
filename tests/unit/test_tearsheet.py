"""
Module: test_tearsheet.py
Description: Unit tests for the quantstats-based tear sheet generator
    (engines/e26_backtesting/tearsheet.py) -- REPO_REFERENCE.md Tier 1.
    Covers the real integration seam (aligning BacktestResult.equity_curve
    with df's own timestamps) and the honest-failure paths (flat equity,
    mismatched lengths), not quantstats' own internals.
Author: Shantanu Waykar
Version: 1.0.0
"""

import numpy as np
import pandas as pd
import pytest

from project_titan_x.engines.e26_backtesting.engine import BacktestingEngine
from project_titan_x.engines.e26_backtesting.tearsheet import (
    equity_curve_to_returns, generate_tearsheet,
)


@pytest.fixture
def engine() -> BacktestingEngine:
    e = BacktestingEngine()
    e.initialize()
    return e


def _trending_df(n: int = 400, seed: int = 3) -> pd.DataFrame:
    rng = np.random.RandomState(seed)
    drift = np.linspace(0, 0.4, n)
    noise = rng.normal(0, 0.01, n).cumsum()
    close = 100 * (1 + drift + noise * 0.1)
    close = np.clip(close, 1, None)
    return pd.DataFrame({
        "timestamp": pd.date_range("2015-01-01", periods=n, freq="D", tz="UTC"),
        "open": close, "high": close * 1.01, "low": close * 0.99, "close": close,
        "volume": [1000] * n,
    })


def _alternating_strategy(df: pd.DataFrame) -> pd.Series:
    idx = np.arange(len(df))
    return pd.Series(np.where((idx // 10) % 2 == 0, 1, -1), index=df.index)


def test_equity_curve_to_returns_uses_real_timestamps_and_aligns_length(engine):
    df = _trending_df()
    result = engine.run_backtest(df, _alternating_strategy).data
    returns = equity_curve_to_returns(result, df)
    assert len(returns) == len(result.equity_curve)
    assert isinstance(returns.index, pd.DatetimeIndex)
    assert returns.index.tz is None                      # quantstats wants tz-naive
    # First real returns value must be a genuine pct_change, not a placeholder.
    expected_first = result.equity_curve.iloc[1] / result.equity_curve.iloc[0] - 1
    assert returns.iloc[1] == pytest.approx(expected_first)


def test_equity_curve_to_returns_rejects_length_mismatch(engine):
    df = _trending_df()
    result = engine.run_backtest(df, _alternating_strategy).data
    truncated = df.iloc[: len(result.equity_curve) - 5]
    with pytest.raises(ValueError, match="pass the SAME df"):
        equity_curve_to_returns(result, truncated)


def test_equity_curve_to_returns_rejects_no_datetime_source():
    from project_titan_x.engines.e26_backtesting.engine import BacktestMetrics, BacktestResult
    result = BacktestResult(metrics=BacktestMetrics(), equity_curve=pd.Series([100.0, 101.0, 99.0]))
    no_ts = pd.DataFrame({"close": [1, 2, 3]})
    with pytest.raises(ValueError, match="real calendar time"):
        equity_curve_to_returns(result, no_ts)


def test_generate_tearsheet_writes_real_html_from_a_real_backtest(engine, tmp_path):
    df = _trending_df()
    result = engine.run_backtest(df, _alternating_strategy).data
    assert result.metrics.total_trades > 0          # sanity: real trades happened

    out = generate_tearsheet(result, df, tmp_path / "report.html", title="Test Strategy")
    assert out.exists()
    html = out.read_text(encoding="utf-8")
    assert "Test Strategy" in html
    assert len(html) > 5000                          # a real tear sheet, not a stub


def test_generate_tearsheet_rejects_flat_equity_curve(tmp_path):
    from project_titan_x.engines.e26_backtesting.engine import BacktestMetrics, BacktestResult
    flat = BacktestResult(metrics=BacktestMetrics(), equity_curve=pd.Series([10_000.0] * 50))
    df = pd.DataFrame({"timestamp": pd.date_range("2020-01-01", periods=50, freq="D", tz="UTC")})
    with pytest.raises(ValueError, match="no real trades"):
        generate_tearsheet(flat, df, tmp_path / "flat.html")
