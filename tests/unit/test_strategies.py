"""
Module: test_strategies.py
Description: Unit tests for engines/e24_strategy_research/strategies.py --
    no dedicated test file existed for this module before (only via
    test_strategy_research_engine.py's integration-level checks). Covers
    donchian_breakout_buffer_confirmed (new, 2026-08-21) specifically,
    not a retroactive full backfill of every pre-existing strategy
    function -- same scope discipline as test_smart_money.py/
    test_order_flow.py earlier this session.
Author: Shantanu Waykar
Version: 1.0.0
"""

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.strategies import (
    STRATEGIES,
    _stateful_from_entries_exits,
    donchian_breakout,
    donchian_breakout_buffer_confirmed,
    rsi_mean_reversion,
)


def _bars(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    """rows: (open, high, low, close). atr filled with a constant for
    deterministic buffer math in these tests."""
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df["atr"] = 1.0
    return df


# ---- _stateful_from_entries_exits: real bug regression (found + fixed 2026-08-21) ----


def test_stateful_from_entries_exits_entry_short_wins_over_coincident_exit_long():
    """The exact real bug: exit_long is a raw price-condition mask (true
    regardless of whether a long position is actually open), so it can
    coincide with entry_short on the SAME bar -- a fresh short entry must
    still win, not get silently cancelled back to 0. Real, not
    hypothetical: for donchian_breakout's own entry_n>exit_n
    parameterization, this coincidence is structurally guaranteed on
    every genuine short-breakout bar (see the function's own docstring)."""
    idx = range(3)
    entry_long = pd.Series([False, False, False], index=idx)
    exit_long = pd.Series([False, True, False], index=idx)   # coincides with entry_short at bar 1
    entry_short = pd.Series([False, True, False], index=idx)
    exit_short = pd.Series([False, False, False], index=idx)
    result = _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
    assert result.iloc[1] == -1  # entry wins, not silently cancelled to 0


def test_stateful_from_entries_exits_entry_long_wins_over_coincident_exit_short():
    idx = range(3)
    entry_long = pd.Series([False, True, False], index=idx)
    exit_long = pd.Series([False, False, False], index=idx)
    entry_short = pd.Series([False, False, False], index=idx)
    exit_short = pd.Series([False, True, False], index=idx)  # coincides with entry_long at bar 1
    result = _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
    assert result.iloc[1] == 1


def test_stateful_from_entries_exits_genuine_exit_with_no_coincident_entry_still_works():
    """The fix must not break the ordinary, far more common case: an exit
    with no new entry on the same bar must still correctly flatten the
    position."""
    idx = range(4)
    entry_long = pd.Series([False, True, False, False], index=idx)
    exit_long = pd.Series([False, False, True, False], index=idx)
    entry_short = pd.Series([False, False, False, False], index=idx)
    exit_short = pd.Series([False, False, False, False], index=idx)
    result = _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
    assert list(result) == [0, 1, 0, 0]


def test_donchian_breakout_produces_real_short_entries_on_a_clean_downtrend():
    """Direct regression test for the real, live bug: on a clean 500-bar
    downtrend with the standard entry_n>exit_n parameterization, this
    MUST produce a substantial number of real short (-1) entries -- before
    the fix, this was unconditionally zero regardless of how strong or
    clean the downtrend was (confirmed live before writing this fix)."""
    rng = np.random.RandomState(5)
    n = 500
    close = 200 - np.linspace(0, 100, n) + rng.normal(0, 1, n).cumsum() * 0.3
    df = pd.DataFrame({"open": close, "high": close * 1.005, "low": close * 0.995, "close": close})
    signal = donchian_breakout(df, entry_n=20, exit_n=10)
    assert (signal == -1).sum() > 100  # was 0 before the fix; a clean downtrend should be overwhelmingly short


def test_rsi_mean_reversion_produces_real_short_entries_on_an_oscillating_series():
    rng = np.random.RandomState(1)
    n = 300
    rsi_vals = np.clip(50 + 40 * np.sin(np.linspace(0, 20, n)) + rng.normal(0, 2, n), 0, 100)
    df = pd.DataFrame({"rsi": rsi_vals})
    signal = rsi_mean_reversion(df)
    assert (signal == -1).sum() > 50  # was 0 before the fix


def test_donchian_breakout_buffer_confirmed_registered_in_strategies_dict():
    assert STRATEGIES["donchian_breakout_buffer_confirmed"] is donchian_breakout_buffer_confirmed


def test_rejects_a_breakout_that_only_barely_clears_the_level():
    # 20 flat bars establish entry_high = 100 (the shifted 20-bar rolling max).
    rows = [(99.0, 100.0, 98.0, 99.5) for _ in range(20)]
    # Bar 20: closes at 100.05 -- clears the raw level (100) but NOT the
    # atr_buffer_mult=0.1 * atr=1.0 = 0.1 required margin (needs > 100.1).
    rows.append((99.5, 100.2, 99.0, 100.05))
    df = _bars(rows)
    signal = donchian_breakout_buffer_confirmed(df, entry_n=20, exit_n=10, atr_buffer_mult=0.1, min_body_pct=0.2)
    assert signal.iloc[20] == 0  # no entry -- didn't clear the buffer


def test_enters_a_breakout_that_clears_buffer_with_a_strong_body():
    rows = [(99.0, 100.0, 98.0, 99.5) for _ in range(20)]
    # Clears 100 + 0.1 buffer comfortably (close=101), and has a strong
    # body: |close-open| = |101-99.5| = 1.5 over a range of 101.5-99=2.5 -> 60% body.
    rows.append((99.5, 101.5, 99.0, 101.0))
    df = _bars(rows)
    signal = donchian_breakout_buffer_confirmed(df, entry_n=20, exit_n=10, atr_buffer_mult=0.1, min_body_pct=0.2)
    assert signal.iloc[20] == 1


def test_rejects_a_breakout_with_a_weak_indecisive_body():
    rows = [(99.0, 100.0, 98.0, 99.5) for _ in range(20)]
    # Clears the buffer easily (close=101, well past 100.1), but the body
    # is tiny relative to its range: open=100.9, close=101.0 -> body=0.1
    # over a range of 101.5-99=2.5 -> 4% body, well under min_body_pct=0.2.
    rows.append((100.9, 101.5, 99.0, 101.0))
    df = _bars(rows)
    signal = donchian_breakout_buffer_confirmed(df, entry_n=20, exit_n=10, atr_buffer_mult=0.1, min_body_pct=0.2)
    assert signal.iloc[20] == 0  # no entry -- body too weak despite clearing the level


def test_short_side_mirrors_long_side_logic():
    rows = [(101.0, 102.0, 100.0, 101.5) for _ in range(20)]  # entry_low (20-bar min) = 100
    # Strong bearish breakout: clears 100 - 0.1 buffer (close=99), strong body.
    rows.append((100.5, 101.0, 98.5, 99.0))
    df = _bars(rows)
    signal = donchian_breakout_buffer_confirmed(df, entry_n=20, exit_n=10, atr_buffer_mult=0.1, min_body_pct=0.2)
    assert signal.iloc[20] == -1


def test_flat_candle_range_does_not_raise_division_error():
    rows = [(100.0, 100.0, 100.0, 100.0) for _ in range(25)]  # every bar has zero range
    df = _bars(rows)
    signal = donchian_breakout_buffer_confirmed(df, entry_n=20, exit_n=10)
    assert (signal == 0).all()


# ---- liquidity_sweep_reversal (new, 2026-08-21, knowledge-corpus-grounded) ----


def test_liquidity_sweep_strategies_registered_in_strategies_dict():
    from project_titan_x.engines.e24_strategy_research.strategies import (
        liquidity_sweep_reversal,
        liquidity_sweep_reversal_trend_filtered,
    )

    assert STRATEGIES["liquidity_sweep_reversal"] is liquidity_sweep_reversal
    assert STRATEGIES["liquidity_sweep_reversal_trend_filtered"] is liquidity_sweep_reversal_trend_filtered


def test_liquidity_sweep_goes_long_on_swept_low():
    """A bar that wicks below the prior 10-bar low but closes back above
    it is the corpus-described stop hunt -- must enter LONG at that bar's
    close, per 'enter at the candle close just below the liquidity zone'."""
    from project_titan_x.engines.e24_strategy_research.strategies import liquidity_sweep_reversal

    rows = [(100.0, 101.0, 99.0, 100.0) for _ in range(10)]  # prior low = 99
    rows.append((100.0, 100.5, 98.0, 100.2))  # wick to 98 (< 99), close back above 99
    df = _bars(rows)
    signal = liquidity_sweep_reversal(df, lookback=10)
    assert signal.iloc[10] == 1


def test_liquidity_sweep_goes_short_on_swept_high():
    from project_titan_x.engines.e24_strategy_research.strategies import liquidity_sweep_reversal

    rows = [(100.0, 101.0, 99.0, 100.0) for _ in range(10)]  # prior high = 101
    rows.append((100.0, 102.0, 99.5, 100.3))  # wick to 102 (> 101), close back below 101
    df = _bars(rows)
    signal = liquidity_sweep_reversal(df, lookback=10)
    assert signal.iloc[10] == -1


def test_liquidity_sweep_stays_flat_on_genuine_breakout():
    """A close BEYOND the prior extreme is a real breakout, not a sweep --
    no reversal entry (and it exits any open position instead)."""
    from project_titan_x.engines.e24_strategy_research.strategies import liquidity_sweep_reversal

    rows = [(100.0, 101.0, 99.0, 100.0) for _ in range(10)]
    rows.append((100.0, 103.0, 99.5, 102.5))  # closes ABOVE prior high 101
    df = _bars(rows)
    signal = liquidity_sweep_reversal(df, lookback=10)
    assert signal.iloc[10] == 0


def test_liquidity_sweep_long_exits_when_target_high_reached():
    from project_titan_x.engines.e24_strategy_research.strategies import liquidity_sweep_reversal

    rows = [(100.0, 101.0, 99.0, 100.0) for _ in range(10)]
    rows.append((100.0, 100.5, 98.0, 100.2))   # sweep of the low -> LONG
    rows.append((100.2, 100.8, 100.0, 100.5))  # holds
    rows.append((100.5, 103.0, 100.4, 102.5))  # closes above rolling prior high -> exit
    df = _bars(rows)
    signal = liquidity_sweep_reversal(df, lookback=10)
    assert signal.iloc[10] == 1
    assert signal.iloc[11] == 1
    assert signal.iloc[12] == 0


def test_liquidity_sweep_trend_filter_blocks_counter_trend_entry():
    """Same swept-low bar, but price is far BELOW the 200-EMA (downtrend):
    the trend-filtered variant must NOT take the counter-trend long the
    unfiltered variant takes."""
    from project_titan_x.engines.e24_strategy_research.strategies import (
        liquidity_sweep_reversal,
        liquidity_sweep_reversal_trend_filtered,
    )

    rows = [(100.0, 101.0, 99.0, 100.0) for _ in range(10)]
    rows.append((100.0, 100.5, 98.0, 100.2))
    df = _bars(rows)
    df["ema_200"] = 150.0  # price well below the 200-EMA -> downtrend
    assert liquidity_sweep_reversal(df, lookback=10).iloc[10] == 1
    assert liquidity_sweep_reversal_trend_filtered(df, lookback=10).iloc[10] == 0


def test_liquidity_sweep_trend_filter_allows_with_trend_entry():
    from project_titan_x.engines.e24_strategy_research.strategies import (
        liquidity_sweep_reversal_trend_filtered,
    )

    rows = [(100.0, 101.0, 99.0, 100.0) for _ in range(10)]
    rows.append((100.0, 100.5, 98.0, 100.2))
    df = _bars(rows)
    df["ema_200"] = 90.0  # price above the 200-EMA -> uptrend, buy-the-sweep allowed
    assert liquidity_sweep_reversal_trend_filtered(df, lookback=10).iloc[10] == 1


def test_liquidity_sweep_no_lookahead():
    """Truncating the future must never change past signal values."""
    from project_titan_x.engines.e24_strategy_research.strategies import liquidity_sweep_reversal

    rng = np.random.RandomState(9)
    n = 200
    close = 100 + rng.normal(0, 1, n).cumsum()
    df = pd.DataFrame({
        "open": close, "high": close + rng.rand(n) * 2, "low": close - rng.rand(n) * 2, "close": close,
    })
    full = liquidity_sweep_reversal(df, lookback=20)
    truncated = liquidity_sweep_reversal(df.iloc[:150], lookback=20)
    assert (full.iloc[:150].values == truncated.values).all()


def test_exit_level_actually_controls_the_long_exit():
    """Regression for the 2026-08-22 stateful-position bug.

    exit_short ("rsi < exit_level") is True across most of the region a
    LONG is meant to be held, and the old ffill-mask implementation had no
    idea which side was open, so raw[exit_short]=0 closed longs the moment
    price left the long entry zone. The visible symptom was that
    `exit_level` became a DEAD parameter: on real ETHUSD 1d data, sweeping
    it 35..70 produced byte-identical metrics for every value.

    Asserts the parameter has real, monotonic effect: a higher exit_level
    must hold the long strictly longer."""
    rsi = pd.Series(list(np.linspace(20, 80, 40)))
    df = pd.DataFrame({"rsi": rsi, "close": np.arange(40.0)})

    def first_long_exit(exit_level):
        s = rsi_mean_reversion(df, oversold=30, overbought=70, exit_level=exit_level)
        return next((i for i, v in enumerate(s) if i > 0 and s.iloc[i - 1] == 1 and v != 1), None)

    tight, mid, wide = first_long_exit(35), first_long_exit(50), first_long_exit(65)
    assert tight is not None and mid is not None and wide is not None
    assert tight < mid < wide, f"exit_level has no effect: {tight}, {mid}, {wide}"
    # And the exit must happen at the level it was told to, not earlier.
    assert rsi.iloc[wide] > 65


def test_exit_condition_never_closes_the_opposite_side():
    """The general invariant behind the bug: an exit mask belonging to one
    direction must never close a position on the other side."""
    n = 30
    # Long entry on bar 0 only; exit_long never fires; exit_short fires
    # constantly. The long must survive regardless.
    entry_long = pd.Series([True] + [False] * (n - 1))
    exit_long = pd.Series([False] * n)
    entry_short = pd.Series([False] * n)
    exit_short = pd.Series([True] * n)
    sig = _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
    assert (sig == 1).all(), "exit_short closed a long position"
