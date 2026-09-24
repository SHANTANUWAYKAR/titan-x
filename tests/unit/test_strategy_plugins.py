"""
Module: test_strategy_plugins.py
Description: Unit tests for engines/e24_strategy_research/plugins/ -- the
    external-repo strategy ports (see plugins/__init__.py for the audited-
    repo registry). Same scope discipline as test_strategies.py: covers
    the new plugin strategies, not a retroactive backfill of everything.
Author: Shantanu Waykar
Version: 1.0.0
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from project_titan_x.engines.e24_strategy_research.engine import DEFAULT_STRATEGY_GRID
from project_titan_x.engines.e24_strategy_research.plugins import PLUGIN_STRATEGIES
from project_titan_x.engines.e24_strategy_research.plugins.freqtrade_sample import freqtrade_rsi_tema_bb
from project_titan_x.engines.e24_strategy_research.plugins.ict_star_ea import (
    ict_fvg_retrace,
    ict_fvg_retrace_killzone,
)
from project_titan_x.engines.e24_strategy_research.plugins.smc_sniper import smc_bos_ob_confluence
from project_titan_x.engines.e24_strategy_research.strategies import STRATEGIES

_AAPL_1D = Path(__file__).resolve().parents[2] / "data" / "processed" / "AAPL_1d.parquet"


def test_plugin_strategies_registered_and_grid_keys_resolve():
    for name in PLUGIN_STRATEGIES:
        assert STRATEGIES[name] is PLUGIN_STRATEGIES[name]
    # Every grid key must resolve to a real strategy -- a typo'd grid
    # entry would otherwise silently evaluate nothing in a sweep.
    assert set(DEFAULT_STRATEGY_GRID.keys()) <= set(STRATEGIES.keys())


# ---- smc_bos_ob_confluence (profittown-sniper-smc port) ----


@pytest.fixture(scope="module")
def aapl_1d() -> pd.DataFrame:
    # Guarded in the fixture rather than on each test: nine tests depend on this
    # frame, and without the guard a fresh clone (where data/ ships empty) errors
    # all nine at setup with a FileNotFoundError that looks like nine bugs.
    if not _AAPL_1D.is_file():
        pytest.skip(
            "needs data/processed/AAPL_1d.parquet, not shipped in this "
            "repository -- regenerate with scripts/fetch_all_data.py"
        )
    return pd.read_parquet(_AAPL_1D).tail(3000).reset_index(drop=True)


def test_smc_produces_real_two_sided_signals_on_real_data(aapl_1d):
    """Regression for the real np.bool_ bug found during the port: numpy
    boolean '+' is logical OR, so summing the confluence checks raw caps
    the score at 1 and min_score>=2 could NEVER pass -- confirmed live as
    all-zero output over 15k real bars before the int() casts."""
    signal = smc_bos_ob_confluence(aapl_1d, min_score=3)
    assert (signal == 1).sum() > 0
    assert (signal == -1).sum() > 0


def test_smc_higher_min_score_is_strictly_more_selective(aapl_1d):
    loose = smc_bos_ob_confluence(aapl_1d, min_score=3)
    strict = smc_bos_ob_confluence(aapl_1d, min_score=4)
    assert (strict != 0).sum() < (loose != 0).sum()


def test_smc_impossible_min_score_never_trades(aapl_1d):
    # The score scale is 0-4 (four confluence checks) -- 5 must be
    # unreachable, not silently clamped.
    assert (smc_bos_ob_confluence(aapl_1d, min_score=5) == 0).all()


def test_smc_no_lookahead(aapl_1d):
    full = smc_bos_ob_confluence(aapl_1d, min_score=3)
    half = smc_bos_ob_confluence(aapl_1d.iloc[:1500], min_score=3)
    assert (full.iloc[:1500].values == half.values).all()


# ---- ict_fvg_retrace (STAR-EA-v11.20 concept port) ----


def _fvg_scenario_df(hour_utc: int = 21) -> pd.DataFrame:
    """Deterministic bullish-FVG-then-retrace: gap forms at bar 2
    (low 103.2 > bar-0 high 101, zone [101, 103.2], impulse high 105),
    bar 3 closes back inside the zone at 102 (entry), bar 4 closes at 106
    above the impulse high (target reached, exit)."""
    rows = [
        (100.0, 101.0, 99.0, 100.0),
        (100.0, 103.5, 99.5, 103.0),
        (103.0, 105.0, 103.2, 104.8),
        (104.0, 104.5, 101.8, 102.0),
        (105.0, 106.5, 104.9, 106.0),
    ]
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df["timestamp"] = pd.date_range(f"2024-01-01 {hour_utc:02d}:00", periods=len(df), freq="D", tz="UTC")
    return df


def test_fvg_retrace_enters_on_zone_touch_and_exits_at_impulse_high():
    signal = ict_fvg_retrace(_fvg_scenario_df(), max_age=10)
    assert list(signal) == [0, 0, 0, 1, 0]


def test_fvg_retrace_gap_expires_after_max_age():
    df = _fvg_scenario_df()
    # Push the retrace bar far past the gap's max_age by inserting quiet
    # bars (inside the zone's top edge is never touched) between gap and
    # retrace -- with max_age=2 the gap must be forgotten, no entry.
    quiet = pd.DataFrame(
        [(104.5, 104.9, 103.6, 104.6)] * 4, columns=["open", "high", "low", "close"]
    )
    df2 = pd.concat([df.iloc[:3], quiet, df.iloc[3:]], ignore_index=True)
    df2["timestamp"] = pd.date_range("2024-01-01 21:00", periods=len(df2), freq="D", tz="UTC")
    signal = ict_fvg_retrace(df2, max_age=2)
    assert (signal == 0).all()


def test_fvg_killzone_variant_blocks_entries_outside_killzones():
    """21:00 UTC sits in the dead window between NY close and the Asian
    open (verified against e07 killzones' own window table) -- the same
    scenario that enters unfiltered must stay flat when killzone-gated."""
    df = _fvg_scenario_df(hour_utc=21)
    assert (ict_fvg_retrace(df, max_age=10) != 0).any()
    assert (ict_fvg_retrace_killzone(df, max_age=10) == 0).all()


def test_fvg_killzone_variant_allows_entries_inside_killzone():
    # 14:00 UTC = 09:00/10:00 New York -> inside the NY_OPEN killzone.
    df = _fvg_scenario_df(hour_utc=14)
    assert list(ict_fvg_retrace_killzone(df, max_age=10)) == [0, 0, 0, 1, 0]


# ---- freqtrade_rsi_tema_bb (freqtrade sample_strategy port) ----


def test_freqtrade_port_enters_on_rsi_cross_and_exits_on_rsi70_cross():
    n = 10
    df = pd.DataFrame({
        "close": [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 90.0, 80.0, 70.0, 60.0],
        "rsi": [40.0, 25.0, 35.0, 50.0, 50.0, 50.0, 65.0, 75.0, 50.0, 50.0],
        # High early (TEMA below it -> entry guard passes), zero late
        # (TEMA above it -> exit guard passes).
        "bb_middle": [1000.0] * 6 + [0.0] * 4,
        "volume": [1.0] * n,
    })
    signal = freqtrade_rsi_tema_bb(df)
    # Entry at bar 2 (RSI 25->35 crosses above 30, TEMA rising below the
    # band), exit at bar 7 (RSI 65->75 crosses above 70, TEMA falling
    # above the band).
    assert list(signal) == [0, 0, 1, 1, 1, 1, 1, 0, 0, 0]


def test_freqtrade_port_is_long_only_like_the_source():
    rng = np.random.RandomState(11)
    n = 300
    close = 100 + rng.normal(0, 1, n).cumsum()
    df = pd.DataFrame({
        "close": close,
        "rsi": np.clip(50 + 40 * np.sin(np.linspace(0, 30, n)), 0, 100),
        "bb_middle": close,
        "volume": np.ones(n),
    })
    signal = freqtrade_rsi_tema_bb(df)
    assert set(signal.unique()).issubset({0, 1})


# ---- dual_thrust / heikin_ashi (ported from je-suis-tm/quant-trading) ----


def test_dual_thrust_range_uses_closes_not_lows(aapl_1d):
    """The whole reason this is not another Donchian: the range mixes
    highs against CLOSES, so a single spike wick cannot inflate it the way
    it widens a high-low channel for a full lookback."""
    from project_titan_x.engines.e24_strategy_research.plugins.dual_thrust import dual_thrust

    spiked = aapl_1d.copy()
    # One enormous low wick, close untouched.
    spiked.loc[spiked.index[500], "low"] = spiked.loc[spiked.index[500], "low"] * 0.5
    base_sig = dual_thrust(aapl_1d)
    spike_sig = dual_thrust(spiked)
    # A high-low range would shift the band for `lookback` bars after the
    # spike; the close-based leg bounds that, so most bars are unaffected.
    changed = (base_sig != spike_sig).sum()
    assert changed < len(aapl_1d) * 0.05, f"{changed} bars moved -- range is wick-sensitive"


def test_dual_thrust_asymmetric_thresholds_differ(aapl_1d):
    """k1 and k2 are separate on purpose -- an asymmetric threshold is the
    strategy's own idea. If they were being collapsed internally, these
    would be identical."""
    from project_titan_x.engines.e24_strategy_research.plugins.dual_thrust import dual_thrust

    sym = dual_thrust(aapl_1d, k1=0.5, k2=0.5)
    asym = dual_thrust(aapl_1d, k1=0.3, k2=0.9)
    assert not sym.equals(asym)


def test_dual_thrust_no_lookahead(aapl_1d):
    from project_titan_x.engines.e24_strategy_research.plugins.dual_thrust import dual_thrust

    full = dual_thrust(aapl_1d)
    for frac in (0.4, 0.6, 0.8, 0.93):
        cut = int(len(aapl_1d) * frac)
        assert (full.iloc[:cut].to_numpy() == dual_thrust(aapl_1d.iloc[:cut]).to_numpy()).all()


def test_heikin_ashi_matches_its_definition(aapl_1d):
    from project_titan_x.engines.e24_strategy_research.plugins.dual_thrust import heikin_ashi_frame

    ha = heikin_ashi_frame(aapl_1d)
    expected_close = (aapl_1d["open"] + aapl_1d["high"] + aapl_1d["low"] + aapl_1d["close"]) / 4
    assert np.allclose(ha["close"], expected_close)
    # HA high/low must contain the HA body, or the bars are not drawable.
    assert (ha["high"] >= ha[["open", "close"]].max(axis=1) - 1e-9).all()
    assert (ha["low"] <= ha[["open", "close"]].min(axis=1) + 1e-9).all()
    # The recursive HA open: each bar is the midpoint of the PREVIOUS HA bar.
    mid_prev = (ha["open"].shift(1) + ha["close"].shift(1)) / 2
    assert np.allclose(ha["open"].iloc[1:], mid_prev.iloc[1:])


def test_heikin_ashi_trend_confirm_reduces_flips(aapl_1d):
    """Requiring consecutive same-colour bars is what makes HA useful
    rather than another close-vs-open rule -- a higher confirm count must
    produce strictly fewer direction changes."""
    from project_titan_x.engines.e24_strategy_research.plugins.dual_thrust import heikin_ashi_trend

    flips = [int((heikin_ashi_trend(aapl_1d, confirm=c).diff() != 0).sum()) for c in (1, 2, 3)]
    assert flips[0] > flips[1] > flips[2], flips
