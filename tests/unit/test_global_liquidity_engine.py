"""
Module: test_global_liquidity_engine.py
Description: Unit tests for Engine 19 (Global Liquidity). No real network
    calls -- a fake FredClient stands in for series_observations_csv, same
    convention as test_economic_calendar_engine.py's _FakeFinnhubClient.

    UPDATE 2026-08-02: the engine no longer gates on FRED_API_KEY -- it
    fetches via FredClient.series_observations_csv, a verified-live no-key
    endpoint (see core/data_providers/fred.py's module docstring). The
    is_configured / "unconfigured" honest-gap tests this file used to have
    are gone along with that gate; a genuine fetch failure (FredError) is
    now the only way analyze() falls back to "unconfigured".
Author: Shantanu Waykar
Version: 1.0.0
"""

import pandas as pd

from project_titan_x.engines.e19_global_liquidity.engine import (
    BALANCE_SHEET_CHANGE_THRESHOLD_PCT,
    GlobalLiquidityEngine,
)


class _FakeFredClient:
    def __init__(self, series_data=None, raises=None):
        self._series_data = series_data or {}
        self._raises = raises

    def series_observations_csv(self, series_id):
        if self._raises:
            raise self._raises
        return self._series_data.get(series_id, [])


def _obs(values: list[float]) -> list[dict]:
    return [{"date": f"2026-01-{i+1:02d}", "value": str(v)} for i, v in enumerate(values)]


def _weekly_obs(values: list[float]) -> list[dict]:
    """Weekly-spaced dates so the engine's real ~91-day calendar-date
    lookback lands on index 0 when len(values) == 14 (13 * 7 == 91 days) --
    matches the shape train_e19_global_liquidity.py calibrates against,
    unlike the engine's old fixed-13-observations-back approximation."""
    dates = pd.date_range("2026-01-01", periods=len(values), freq="7D")
    return [{"date": str(d.date()), "value": str(v)} for d, v in zip(dates, values)]


def test_health_check_healthy_when_csv_reachable():
    engine = GlobalLiquidityEngine(fred_client=_FakeFredClient(series_data={"DFII10": _obs([1.5])}))
    engine.initialize()
    result = engine.health_check()
    assert result.success


def test_health_check_unhealthy_when_fetch_fails():
    from project_titan_x.core.data_providers.fred import FredError

    engine = GlobalLiquidityEngine(fred_client=_FakeFredClient(raises=FredError("boom")))
    result = engine.health_check()
    assert not result.success


def test_analyze_expanding_balance_sheet_and_m2():
    values = [100.0] * 13 + [100.0 * (1 + BALANCE_SHEET_CHANGE_THRESHOLD_PCT / 100 + 0.01)]
    fake = _FakeFredClient(series_data={
        "WALCL": _weekly_obs(values),
        "M2SL": _weekly_obs(values),
        "DFII10": _obs([1.5]),
    })
    engine = GlobalLiquidityEngine(fred_client=fake)
    # Force fallback thresholds so this test stays deterministic regardless
    # of whatever real threshold train_e19_global_liquidity.py happens to
    # have calibrated on disk -- calibration selection itself has its own
    # dedicated tests below.
    engine._calibration = None
    result = engine.analyze()
    assert result.success
    snapshot = result.data
    assert snapshot.fed_balance_sheet.regime == "expanding"
    assert snapshot.m2_money_supply.regime == "expanding"
    assert snapshot.overall_regime == "expanding"


def test_analyze_contracting_balance_sheet():
    values = [100.0] * 13 + [100.0 * (1 - BALANCE_SHEET_CHANGE_THRESHOLD_PCT / 100 - 0.01)]
    fake = _FakeFredClient(series_data={
        "WALCL": _weekly_obs(values),
        "M2SL": _weekly_obs(values),
        "DFII10": _obs([-0.5]),
    })
    engine = GlobalLiquidityEngine(fred_client=fake)
    engine._calibration = None  # see comment in test_analyze_expanding_balance_sheet_and_m2
    result = engine.analyze()
    assert result.success
    snapshot = result.data
    assert snapshot.fed_balance_sheet.regime == "contracting"
    assert snapshot.overall_regime == "contracting"


def test_analyze_mixed_regime_when_series_disagree():
    expanding = [100.0] * 13 + [100.0 * 1.05]
    contracting = [100.0] * 13 + [100.0 * 0.95]
    fake = _FakeFredClient(series_data={
        "WALCL": _weekly_obs(expanding),
        "M2SL": _weekly_obs(contracting),
        "DFII10": _obs([0.5]),
    })
    engine = GlobalLiquidityEngine(fred_client=fake)
    result = engine.analyze()
    assert result.success
    assert result.data.overall_regime == "mixed"


def test_real_yield_restrictive_when_positive():
    fake = _FakeFredClient(series_data={"WALCL": [], "M2SL": [], "DFII10": _obs([1.8])})
    engine = GlobalLiquidityEngine(fred_client=fake)
    result = engine.analyze()
    assert result.success
    assert result.data.real_yield_10y.regime == "restrictive"


def test_real_yield_accommodative_when_negative():
    fake = _FakeFredClient(series_data={"WALCL": [], "M2SL": [], "DFII10": _obs([-1.2])})
    engine = GlobalLiquidityEngine(fred_client=fake)
    result = engine.analyze()
    assert result.success
    assert result.data.real_yield_10y.regime == "accommodative"


def test_analyze_handles_fetch_error_gracefully():
    from project_titan_x.core.data_providers.fred import FredError

    fake = _FakeFredClient(raises=FredError("boom"))
    engine = GlobalLiquidityEngine(fred_client=fake)
    result = engine.analyze()
    assert result.success
    assert result.data.overall_regime == "unconfigured"


def test_threshold_for_uses_calibration_when_present():
    engine = GlobalLiquidityEngine(fred_client=_FakeFredClient())
    engine._calibration = {"WALCL": {"threshold_pct": 3.27}}
    assert engine._threshold_for("WALCL", BALANCE_SHEET_CHANGE_THRESHOLD_PCT) == 3.27
    assert engine._threshold_for("M2SL", BALANCE_SHEET_CHANGE_THRESHOLD_PCT) == BALANCE_SHEET_CHANGE_THRESHOLD_PCT


def test_threshold_for_falls_back_without_calibration():
    engine = GlobalLiquidityEngine(fred_client=_FakeFredClient())
    engine._calibration = None
    assert engine._threshold_for("WALCL", BALANCE_SHEET_CHANGE_THRESHOLD_PCT) == BALANCE_SHEET_CHANGE_THRESHOLD_PCT


# ---- knowledge_context ----


def test_build_knowledge_context_none_without_engine():
    engine = GlobalLiquidityEngine(fred_client=_FakeFredClient())
    assert engine._build_knowledge_context("expanding") is None


def test_build_knowledge_context_none_when_not_notable():
    class _StubKnowledge:
        document_store = None

    engine = GlobalLiquidityEngine(fred_client=_FakeFredClient(), knowledge_engine=_StubKnowledge())
    assert engine._build_knowledge_context("mixed") is None
    assert engine._build_knowledge_context("unconfigured") is None


# ---- reference (point-in-time, added 2026-09-13 for research/
# global_liquidity_ic_analysis.py's IC backtest -- see analyze()'s own
# docstring for why this exists and its FRED-revision caveat) ----


def test_reference_none_matches_current_default_behavior():
    """The whole point of defaulting reference=None is that every
    existing live caller (e51_signals._confluence_global_liquidity among
    them) is completely unaffected -- confirms analyze() and
    analyze(reference=None) agree exactly."""
    fred = _FakeFredClient(series_data={
        "WALCL": _weekly_obs([100.0] * 13 + [105.0]),
        "M2SL": _weekly_obs([100.0] * 13 + [100.2]),
        "DFII10": _obs([1.2]),
    })
    engine = GlobalLiquidityEngine(fred_client=fred)
    a = engine.analyze()
    b = engine.analyze(reference=None)
    assert a.data.overall_regime == b.data.overall_regime
    assert a.data.fed_balance_sheet.pct_change_3m == b.data.fed_balance_sheet.pct_change_3m


def test_reference_restricts_to_observations_on_or_before_it():
    """14 weekly obs spanning 2026-01-01..2026-04-02: the last value
    jumps from 100 to 200 only in the FINAL observation. Asking as-of the
    second-to-last date must NOT see that jump."""
    values = [100.0] * 13 + [200.0]
    obs = _weekly_obs(values)
    last_date = pd.Timestamp(obs[-1]["date"])
    second_to_last_date = pd.Timestamp(obs[-2]["date"])
    fred = _FakeFredClient(series_data={"WALCL": obs, "M2SL": _weekly_obs([100.0] * 14), "DFII10": _obs([1.0])})
    engine = GlobalLiquidityEngine(fred_client=fred)

    live = engine.analyze()
    assert live.data.fed_balance_sheet.latest_value == 200.0

    as_of_past = engine.analyze(reference=second_to_last_date.to_pydatetime())
    assert as_of_past.data.fed_balance_sheet.latest_value == 100.0
    assert as_of_past.data.fed_balance_sheet.latest_date == str(second_to_last_date.date())

    # Sanity: the reference date itself IS included (<=, not <).
    as_of_last = engine.analyze(reference=last_date.to_pydatetime())
    assert as_of_last.data.fed_balance_sheet.latest_value == 200.0


def test_reference_before_all_observations_gives_no_reading():
    fred = _FakeFredClient(series_data={
        "WALCL": _weekly_obs([100.0] * 14),
        "M2SL": _weekly_obs([100.0] * 14),
        "DFII10": _obs([1.0]),
    })
    engine = GlobalLiquidityEngine(fred_client=fred)
    result = engine.analyze(reference=pd.Timestamp("2020-01-01").to_pydatetime())
    assert result.data.fed_balance_sheet.latest_value is None
    assert result.data.overall_regime == "unconfigured"


def test_reference_skips_knowledge_lookup_for_backtest_efficiency():
    """A backtest calling analyze(reference=...) hundreds of times per
    symbol must never hit the knowledge engine -- that's an unbounded,
    unnecessary cost this same fake would silently blow up if it were
    ever actually invoked here."""
    class _ExplodingKnowledge:
        document_store = None

        def __getattr__(self, name):
            raise AssertionError("knowledge engine must not be touched when reference is set")

    fred = _FakeFredClient(series_data={
        "WALCL": _weekly_obs([100.0] * 13 + [110.0]),
        "M2SL": _weekly_obs([100.0] * 14),
        "DFII10": _obs([1.0]),
    })
    engine = GlobalLiquidityEngine(fred_client=fred, knowledge_engine=_ExplodingKnowledge())
    result = engine.analyze(reference=pd.Timestamp("2026-04-02").to_pydatetime())
    assert result.success
    assert result.data.knowledge_context is None
