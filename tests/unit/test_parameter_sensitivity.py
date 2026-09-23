"""
Module: test_parameter_sensitivity.py
Description: Unit tests for strategy_parameter_sensitivity (Engine 24) --
    extends E26's existing risk/commission-only _parameter_sensitivity to
    the strategy's own numeric parameters (docs/UPGRADE_BRIEF.md Phase 7
    item 5). Confirms int-rounding correctness, one-parameter-at-a-time
    isolation (perturbing param A must never change the value used for
    param B), the honest None-on-untradeable/unknown-strategy paths, and a
    real-data smoke test against BTC-USD_1d's actual shipped params (Rule 4:
    at least one test per integration point uses the real collaborator, not
    a stub).
Author: Shantanu Waykar
Version: 1.0.0
"""

import numpy as np
import pandas as pd
import pytest

from project_titan_x.engines.e24_strategy_research import engine as e24_engine
from project_titan_x.engines.e24_strategy_research.engine import (
    strategy_parameter_sensitivity,
)
from project_titan_x.engines.e02_market_data.engine import MarketDataEngine
from project_titan_x.engines.e07_technical.engine import TechnicalAnalysisEngine
from project_titan_x.engines.e26_backtesting.engine import BacktestingEngine


@pytest.fixture
def backtesting_engine() -> BacktestingEngine:
    e = BacktestingEngine()
    e.initialize()
    return e


def _trending_df(n: int = 500, seed: int = 3) -> pd.DataFrame:
    rng = np.random.RandomState(seed)
    idx = np.arange(n)
    drift = np.linspace(0, 0.4, n)
    noise = rng.normal(0, 0.01, n).cumsum()
    close = 100 * (1 + drift + noise * 0.1)
    close = np.clip(close, 1, None)
    return pd.DataFrame({
        "timestamp": pd.date_range("2015-01-01", periods=n, freq="D", tz="UTC"),
        "open": close, "high": close * 1.01, "low": close * 0.99, "close": close,
        "volume": [1000] * n,
    }, index=idx)


def test_unknown_strategy_returns_none(backtesting_engine):
    df = _trending_df()
    report = strategy_parameter_sensitivity(df, "not_a_real_strategy", {"a": 1}, backtesting_engine)
    assert report is None


def test_zero_numeric_params_returns_none(backtesting_engine, monkeypatch):
    df = _trending_df()

    def string_only_strategy(_df, mode="up"):
        return pd.Series(1, index=_df.index)

    monkeypatch.setitem(e24_engine.STRATEGIES, "test_string_only", string_only_strategy)
    report = strategy_parameter_sensitivity(df, "test_string_only", {"mode": "up"}, backtesting_engine)
    assert report is None


def test_untradeable_base_case_returns_none(backtesting_engine, monkeypatch):
    df = _trending_df()

    def flat_strategy(_df, level=1):
        return pd.Series(0, index=_df.index)

    monkeypatch.setitem(e24_engine.STRATEGIES, "test_flat", flat_strategy)
    report = strategy_parameter_sensitivity(df, "test_flat", {"level": 1}, backtesting_engine)
    assert report is None


def test_int_params_perturb_to_rounded_ints_never_floats(backtesting_engine, monkeypatch):
    df = _trending_df()
    seen_values = []

    def probe_strategy(_df, entry_n=15, exit_n=7):
        seen_values.append((entry_n, exit_n))
        idx = np.arange(len(_df))
        return pd.Series(np.where((idx // entry_n) % 2 == 0, 1, -1), index=_df.index)

    monkeypatch.setitem(e24_engine.STRATEGIES, "test_probe", probe_strategy)
    report = strategy_parameter_sensitivity(
        df, "test_probe", {"entry_n": 15, "exit_n": 7}, backtesting_engine,
    )
    assert report is not None
    for entry in report.perturbed:
        assert isinstance(entry["value"], int), f"expected an int perturbation, got {entry}"


def test_one_parameter_at_a_time_isolation(backtesting_engine, monkeypatch):
    """Perturbing param A must never change the value passed for param B --
    exactly the property that distinguishes this from a joint perturbation."""
    df = _trending_df()
    calls: list[dict] = []

    def probe_strategy(_df, entry_n=15, exit_n=7):
        calls.append({"entry_n": entry_n, "exit_n": exit_n})
        idx = np.arange(len(_df))
        return pd.Series(np.where((idx // max(entry_n, 2)) % 2 == 0, 1, -1), index=_df.index)

    monkeypatch.setitem(e24_engine.STRATEGIES, "test_isolation", probe_strategy)
    base_params = {"entry_n": 15, "exit_n": 7}
    report = strategy_parameter_sensitivity(df, "test_isolation", base_params, backtesting_engine)
    assert report is not None

    # Every call after the base case must differ from base_params in
    # EXACTLY one key.
    base_call = calls[0]
    assert base_call == base_params
    for call in calls[1:]:
        diffs = [k for k in base_params if call[k] != base_params[k]]
        assert len(diffs) == 1, f"expected exactly one changed param, got {diffs} in call {call}"


def test_perturbation_round_tripping_to_base_is_skipped_not_faked(backtesting_engine, monkeypatch):
    df = _trending_df()

    def probe_strategy(_df, tiny_int=1, entry_n=15):
        idx = np.arange(len(_df))
        return pd.Series(np.where((idx // entry_n) % 2 == 0, 1, -1), index=_df.index)

    monkeypatch.setitem(e24_engine.STRATEGIES, "test_tiny", probe_strategy)
    report = strategy_parameter_sensitivity(
        df, "test_tiny", {"tiny_int": 1, "entry_n": 15}, backtesting_engine,
    )
    assert report is not None
    # tiny_int=1 at +-20% rounds back to 1 both directions -- must never
    # appear as a fake "no change" perturbation entry.
    tiny_int_entries = [p for p in report.perturbed if p["param"] == "tiny_int"]
    assert tiny_int_entries == []
    entry_n_entries = [p for p in report.perturbed if p["param"] == "entry_n"]
    assert len(entry_n_entries) == 2


def test_most_fragile_param_is_the_largest_absolute_delta(backtesting_engine, monkeypatch):
    df = _trending_df()

    def probe_strategy(_df, stable_param=100, fragile_param=15):
        # fragile_param controls entry frequency (a real behavioral change);
        # stable_param is read but never used, so perturbing it can't move
        # Sharpe at all.
        idx = np.arange(len(_df))
        return pd.Series(np.where((idx // fragile_param) % 2 == 0, 1, -1), index=_df.index)

    monkeypatch.setitem(e24_engine.STRATEGIES, "test_fragility", probe_strategy)
    report = strategy_parameter_sensitivity(
        df, "test_fragility", {"stable_param": 100, "fragile_param": 15}, backtesting_engine,
    )
    assert report is not None
    assert report.most_fragile_param == "fragile_param"


@pytest.mark.network
def test_real_data_smoke_test_against_btc_usd_1d_shipped_params(backtesting_engine):
    """Rule 4: at least one test per integration point uses the REAL
    collaborator, not a stub -- runs against BTC-USD_1d's actual live
    override strategy+params on real fetched data."""
    import json
    from pathlib import Path

    override_path = (
        Path(__file__).resolve().parents[2]
        / "data" / "models" / "e51_signals" / "BTC-USD_1d_strategy_override.json"
    )
    if not override_path.exists():
        pytest.skip("no BTC-USD_1d override on disk")
    ov = json.loads(override_path.read_text(encoding="utf-8"))
    strat_name, params = ov["strategy"], ov.get("params", ov.get("parameters", {}))

    market = MarketDataEngine()
    market.initialize()
    fetch = market.fetch_ohlcv("BTC-USD", "1d")
    if not fetch.success:
        pytest.skip(f"could not fetch real BTC-USD data: {fetch.message}")
    df = fetch.data.reset_index(drop=True)

    ta = TechnicalAnalysisEngine()
    ta.initialize()
    enriched = ta.analyze(df).data["df"]

    report = strategy_parameter_sensitivity(enriched, strat_name, params, backtesting_engine)
    assert report is not None
    assert report.strategy == strat_name
    assert 0.0 <= report.stability_score <= 1.0
