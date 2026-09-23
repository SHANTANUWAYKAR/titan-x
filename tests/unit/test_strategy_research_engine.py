"""
Module: test_strategy_research_engine.py
Description: Unit tests for Engine 24 (Strategy Research).
Author: Shantanu Waykar
Version: 1.0.0
"""

import json

import numpy as np
import pandas as pd
import pytest

from project_titan_x.engines.e24_strategy_research.engine import (
    PROMOTABLE_STRATEGIES,
    StrategyCandidateResult,
    StrategyResearchEngine,
    _run_one_candidate_worker,
)
from project_titan_x.engines.e26_backtesting.engine import BacktestingEngine
from project_titan_x.engines.e07_technical.engine import TechnicalAnalysisEngine


@pytest.fixture
def engine() -> StrategyResearchEngine:
    e = StrategyResearchEngine()
    e.initialize()
    return e


def test_health_check(engine):
    assert engine.health_check().success


def _write_fake_report(report_dir, symbol, timeframe, **overrides):
    report = {
        "symbol": symbol, "timeframe": timeframe, "generated_at": "2026-09-13T00:00:00+00:00",
        "n_candidates": 2, "validation_bar": {}, "passed": [], "best": None,
        "promoted": False, "promotion_note": None,
        "all_candidates": [
            {"strategy": "rsi_mean_reversion", "params": {"oversold": 15}, "is_sharpe": 0.1},
            {"strategy": "dual_thrust", "params": {"lookback": 10}, "is_sharpe": 0.2},
        ],
    }
    report.update(overrides)
    (report_dir / f"{symbol}_{timeframe}_report.json").write_text(json.dumps(report))
    return report


def test_list_reports_summarizes_without_all_candidates(engine, monkeypatch, tmp_path):
    import project_titan_x.engines.e24_strategy_research.engine as e24_module

    monkeypatch.setattr(e24_module, "_REPORT_DIR", tmp_path)
    _write_fake_report(tmp_path, "GOLD", "1d")
    _write_fake_report(tmp_path, "BTCUSD", "1d", promoted=True, passed=[{"strategy": "dual_thrust"}],
                        best={"strategy": "dual_thrust", "is_sharpe": 0.9})

    result = engine.list_reports()
    assert result.success
    assert len(result.data) == 2
    by_symbol = {r["symbol"]: r for r in result.data}
    assert "all_candidates" not in by_symbol["GOLD"]
    assert by_symbol["GOLD"]["n_passed"] == 0
    assert by_symbol["BTCUSD"]["promoted"] is True
    assert by_symbol["BTCUSD"]["n_passed"] == 1
    assert by_symbol["BTCUSD"]["best"]["strategy"] == "dual_thrust"


def test_list_reports_empty_dir_returns_empty_list(engine, monkeypatch, tmp_path):
    import project_titan_x.engines.e24_strategy_research.engine as e24_module

    monkeypatch.setattr(e24_module, "_REPORT_DIR", tmp_path / "does_not_exist")
    result = engine.list_reports()
    assert result.success
    assert result.data == []


def test_list_reports_skips_unreadable_file_without_failing(engine, monkeypatch, tmp_path):
    import project_titan_x.engines.e24_strategy_research.engine as e24_module

    monkeypatch.setattr(e24_module, "_REPORT_DIR", tmp_path)
    _write_fake_report(tmp_path, "GOLD", "1d")
    (tmp_path / "CORRUPT_1d_report.json").write_text("{not valid json")

    result = engine.list_reports()
    assert result.success
    assert len(result.data) == 1


def test_get_report_returns_full_candidate_list(engine, monkeypatch, tmp_path):
    import project_titan_x.engines.e24_strategy_research.engine as e24_module

    monkeypatch.setattr(e24_module, "_REPORT_DIR", tmp_path)
    _write_fake_report(tmp_path, "GOLD", "1d")

    result = engine.get_report("GOLD", "1d")
    assert result.success
    assert len(result.data["all_candidates"]) == 2


def test_get_report_missing_symbol_fails_honestly(engine, monkeypatch, tmp_path):
    import project_titan_x.engines.e24_strategy_research.engine as e24_module

    monkeypatch.setattr(e24_module, "_REPORT_DIR", tmp_path)
    result = engine.get_report("NOSUCHSYMBOL", "1d")
    assert not result.success


def test_defaults_construct_real_collaborators(engine):
    assert isinstance(engine._technical_engine, TechnicalAnalysisEngine)
    assert isinstance(engine._backtesting_engine, BacktestingEngine)


def test_research_unknown_asset_fails(engine):
    result = engine.research("NOT_A_REAL_ASSET")
    assert not result.success


def test_promotable_strategies_matches_what_e51_can_drive():
    """e51_signals._determine_direction_from_override (since 2026-08-21) dispatches
    generically through STRATEGIES, computing the enriched frame on demand when a
    strategy needs indicator columns -- so every registered archetype is now
    genuinely drivable live, and promotion is scoped to exactly that set."""
    from project_titan_x.engines.e24_strategy_research.strategies import STRATEGIES

    assert PROMOTABLE_STRATEGIES == set(STRATEGIES.keys())


def test_promote_writes_override_file_only_for_promotable_strategy(tmp_path, monkeypatch):
    import project_titan_x.engines.e24_strategy_research.engine as e24_module

    monkeypatch.setattr(e24_module, "_OVERRIDE_DIR", tmp_path)
    engine = StrategyResearchEngine()

    class _FakeAsset:
        symbol = "TESTSYM"
        yahoo_symbol = "TEST=X"

    candidate = StrategyCandidateResult(
        strategy="donchian_breakout", params={"entry_n": 20, "exit_n": 10},
        is_trades=30, is_sharpe=0.8, is_max_dd=5.0, oos_sharpe=0.5, win_rate=0.6, robustness=0.9, passed_validation=True,
    )
    promoted, note = engine._promote(_FakeAsset(), "1d", candidate)
    assert promoted is True
    path = tmp_path / "TEST=X_1d_strategy_override.json"
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["strategy"] == "donchian_breakout"
    assert data["params"] == {"entry_n": 20, "exit_n": 10}
    assert data["min_confidence"] == 60


def test_promote_declines_non_promotable_strategy(tmp_path, monkeypatch):
    import project_titan_x.engines.e24_strategy_research.engine as e24_module

    monkeypatch.setattr(e24_module, "_OVERRIDE_DIR", tmp_path)
    engine = StrategyResearchEngine()

    class _FakeAsset:
        symbol = "TESTSYM"
        yahoo_symbol = "TEST=X"

    candidate = StrategyCandidateResult(
        strategy="totally_unknown_archetype", params={}, is_trades=30, is_sharpe=0.8, is_max_dd=5.0,
        oos_sharpe=0.5, win_rate=0.6, robustness=0.9, passed_validation=True,
    )
    promoted, note = engine._promote(_FakeAsset(), "1d", candidate)
    assert promoted is False
    assert "not yet a promotable archetype" in note
    assert not (tmp_path / "TEST=X_1d_strategy_override.json").exists()


def test_run_one_returns_none_on_strategy_computation_failure(engine):
    def broken_strategy(_df, **kwargs):
        raise ValueError("broken")

    enriched = pd.DataFrame({"close": np.arange(10.0)})
    result = engine._run_one(enriched, "broken", broken_strategy, {})
    assert result is None


@pytest.mark.network
def test_research_sp500_donchian_now_shows_real_bidirectional_trades(engine):
    """Real regression guard, live: SP500 (MES=F) donchian_breakout at
    entry_n=15/exit_n=7 was PREVIOUSLY (wrongly) recorded as a validated
    override with 31 trades and a positive OOS Sharpe -- an artifact of
    the real _stateful_from_entries_exits bug fixed 2026-08-21 (see
    strategies.py's own docstring and CLAUDE.md): entry_short was
    silently cancelled by a structurally-coincident exit_long condition
    on essentially every real short-breakout bar for this
    entry_n>exit_n parameterization, making the strategy long-only in
    practice despite being labeled bidirectional. With the fix, the SAME
    grid point on the SAME real data now shows is_trades roughly
    doubling (31 -> 57, confirmed live before writing this test) and a
    NEGATIVE OOS Sharpe -- it no longer clears E26's validation bar.
    MES=F_1d_strategy_override.json was withdrawn (deleted, not
    silently left stale) as a direct consequence -- nothing in the full
    default grid currently validates for SP500 (52 candidates checked
    live, 0 passed), so E51 now correctly falls back to the baseline
    composite rule for this symbol (_load_strategy_override returns None
    for a missing file by design).

    This test no longer asserts a specific pass/fail outcome (that's
    inherently sensitive to future market data updates, the same trap
    the OLD version of this test fell into by asserting a since-proven-
    wrong "validated" premise) -- it asserts the property that actually
    matters: real short-side trading is genuinely happening now, not
    silently suppressed. is_trades >= 45 sits comfortably between the
    old (bugged, 31) and new (fixed, 57) counts, so a regression back to
    long-only-in-practice would fail this deterministically."""
    small_grid = {"donchian_breakout": [{"entry_n": 15, "exit_n": 7}]}
    result = engine.research("SP500", timeframe="1d", strategy_grid=small_grid, years=8)
    assert result.success
    assert result.data.n_candidates == 1
    candidate = result.data.candidates[0]
    assert candidate.is_trades >= 45  # was 31 under the bug; real shorts roughly double this


# ---- parallel search (added 2026-08-20) ----


def test_run_one_candidate_worker_matches_run_one_on_synthetic_data(engine):
    """The module-level parallel-path worker must compute the IDENTICAL
    result as the instance-method sequential path for the same inputs --
    this is the whole safety argument for parallelizing (same computation,
    different process), so it must be verified directly, not assumed."""
    rng = np.random.RandomState(7)
    n = 300
    close = 100 * (1 + np.linspace(0, 0.3, n) + rng.normal(0, 0.01, n).cumsum() * 0.1)
    enriched = pd.DataFrame({
        "timestamp": pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC"),
        "open": close, "high": close * 1.01, "low": close * 0.99, "close": close,
        "volume": [1000] * n,
    })

    def alternating(_df, **kwargs):
        idx = np.arange(len(_df))
        return pd.Series(np.where((idx // 10) % 2 == 0, 1, -1), index=_df.index)

    from project_titan_x.engines.e24_strategy_research import strategies as strategies_mod
    monkeypatched = "test_alternating_strategy_for_parity"
    strategies_mod.STRATEGIES[monkeypatched] = alternating
    try:
        sequential = engine._run_one(
            enriched, monkeypatched, alternating, {}, periods_per_year=252,
            slippage_pct=0.0005, commission_pct=0.001,
        )
        parallel_dict = _run_one_candidate_worker(
            enriched, monkeypatched, {}, None, 252, 0.0005, 0.001,
        )
    finally:
        del strategies_mod.STRATEGIES[monkeypatched]

    assert sequential is not None
    assert parallel_dict is not None
    assert parallel_dict["is_trades"] == sequential.is_trades
    assert parallel_dict["is_sharpe"] == pytest.approx(sequential.is_sharpe)
    assert parallel_dict["passed_validation"] == sequential.passed_validation


def test_run_one_candidate_worker_returns_none_for_unknown_strategy():
    enriched = pd.DataFrame({"close": np.arange(10.0)})
    result = _run_one_candidate_worker(enriched, "not_a_real_strategy", {}, None, 252, 0.0005, 0.001)
    assert result is None


def test_parallel_with_caller_supplied_executor_does_not_close_it(engine, monkeypatch):
    """research() must NEVER shut down an executor it didn't create --
    that's the caller's responsibility for reuse across multiple calls
    (the real payoff case, see research()'s own docstring). Verified by
    patching shutdown to detect any close attempt, using a synthetic
    strategy so this test needs no network access."""
    from concurrent.futures import ProcessPoolExecutor
    from project_titan_x.engines.e24_strategy_research import strategies as strategies_mod

    def flat_signal(_df, **kwargs):
        return pd.Series(1, index=_df.index)

    strategies_mod.STRATEGIES["test_flat_for_executor_reuse"] = flat_signal
    n = 300
    enriched = pd.DataFrame({
        "timestamp": pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC"),
        "open": [100.0] * n, "high": [101.0] * n, "low": [99.0] * n, "close": [100.0] * n,
        "volume": [1000] * n,
    })

    shutdown_calls = []
    pool = ProcessPoolExecutor(max_workers=2)
    original_shutdown = pool.shutdown
    monkeypatch.setattr(pool, "shutdown", lambda *a, **kw: shutdown_calls.append((a, kw)))
    try:
        grid = {"test_flat_for_executor_reuse": [{}, {}]}

        def fake_fetch(*_a, **_kw):
            from project_titan_x.engines.base import EngineResult
            return EngineResult(success=True, data=enriched)

        monkeypatch.setattr(engine._market_data_engine, "fetch_ohlcv", fake_fetch)
        monkeypatch.setattr(
            engine._technical_engine, "analyze",
            lambda *_a, **_kw: __import__("project_titan_x.engines.base", fromlist=["EngineResult"]).EngineResult(
                success=True, data={"df": enriched}
            ),
        )
        result = engine.research("BTCUSD", strategy_grid=grid, parallel=True, executor=pool)
        assert result.success
        assert shutdown_calls == []  # never closed by research() itself
    finally:
        del strategies_mod.STRATEGIES["test_flat_for_executor_reuse"]
        original_shutdown(wait=True)


@pytest.mark.network
def test_parallel_search_matches_sequential_search_on_real_data(engine):
    """Real, live confirmation that parallel=True produces the SAME
    candidate set as parallel=False -- not just same-process synthetic
    parity above, but the actual ProcessPoolExecutor path against real
    OHLCV/E26/E07 collaborators, same discipline as this file's own
    'reproduces known validated result' test above."""
    grid = {"donchian_breakout": [{"entry_n": 15, "exit_n": 7}, {"entry_n": 20, "exit_n": 10}]}
    sequential_result = engine.research("SP500", timeframe="1d", strategy_grid=grid, years=8, parallel=False)
    parallel_result = engine.research("SP500", timeframe="1d", strategy_grid=grid, years=8, parallel=True)
    assert sequential_result.success and parallel_result.success

    def _key(c):
        return (c.strategy, tuple(sorted(c.params.items())))

    seq_by_key = {_key(c): c for c in sequential_result.data.candidates}
    par_by_key = {_key(c): c for c in parallel_result.data.candidates}
    assert set(seq_by_key.keys()) == set(par_by_key.keys())
    for key, seq_c in seq_by_key.items():
        par_c = par_by_key[key]
        assert par_c.is_trades == seq_c.is_trades
        assert par_c.is_sharpe == pytest.approx(seq_c.is_sharpe)
        assert par_c.passed_validation == seq_c.passed_validation


def test_selection_score_prefers_consistency_over_a_lucky_oos_spike():
    """Real case from this platform's own 4h sweep: RELIANCE's top-OOS
    candidate had IS 0.59 / OOS 4.92 (an 8x gap -- a kind OOS window),
    while MSFT-style candidates run IS 1.02 / OOS 0.84. Pure max-OOS
    ranking picks the spike; min(IS, OOS) picks the consistent one."""
    from project_titan_x.engines.e24_strategy_research.engine import _selection_score

    spike = StrategyCandidateResult(
        strategy="a", params={}, is_trades=33, is_sharpe=0.59, is_max_dd=5.0,
        oos_sharpe=4.92, win_rate=0.33, robustness=0.95, passed_validation=True,
    )
    consistent = StrategyCandidateResult(
        strategy="b", params={}, is_trades=118, is_sharpe=1.02, is_max_dd=5.0,
        oos_sharpe=0.84, win_rate=0.48, robustness=0.92, passed_validation=True,
    )
    assert _selection_score(consistent) > _selection_score(spike)
    assert max([spike, consistent], key=_selection_score) is consistent


def test_selection_score_accepts_both_dataclass_and_dict_forms():
    from project_titan_x.engines.e24_strategy_research.engine import _selection_score

    candidate = StrategyCandidateResult(
        strategy="a", params={}, is_trades=40, is_sharpe=1.5, is_max_dd=5.0,
        oos_sharpe=0.7, win_rate=0.5, robustness=0.9, passed_validation=True,
    )
    assert _selection_score(candidate) == pytest.approx(0.7)
    assert _selection_score(candidate.to_dict()) == pytest.approx(0.7)
