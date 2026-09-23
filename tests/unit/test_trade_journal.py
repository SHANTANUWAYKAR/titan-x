"""Guards for setups/trade_journal.py.

Journal statistics are the numbers a trader makes decisions on, so an error
here is worse than a crash -- it is a confident wrong answer. Each test below
pins one statistic against a hand-computed case rather than asserting the code
agrees with itself.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from project_titan_x.setups.trade_journal import (
    JournalRow, build_journal, compute_stats, htf_bias, session_of,
)


def _row(r: float, *, pair: str = "X", session: str = "London",
         setup: str = "s") -> JournalRow:
    return JournalRow(
        date="2024-01-01 00:00:00", pair=pair, session=session, htf_bias="Neutral",
        setup=setup, entry=100.0, sl=99.0, tp=102.0, rr=2.0, result_r=r,
        screenshot="", reason_for_entry="", reason_for_failure="", mistake="",
    )


# ---------------------------------------------------------------------------
# statistics, against hand-computed values
# ---------------------------------------------------------------------------

def test_core_statistics_match_hand_computation() -> None:
    """Three wins of +2R and two losses of -1R.

    win rate 3/5 = 60% · avg win +2 · avg loss -1 · expectancy (6-2)/5 = +0.8
    profit factor 6/2 = 3.0
    """
    rows = [_row(2.0), _row(-1.0), _row(2.0), _row(-1.0), _row(2.0)]
    s = compute_stats(rows, min_group=1)
    assert s is not None
    assert s.trades == 5
    assert s.win_rate == pytest.approx(0.6)
    assert s.average_win_r == pytest.approx(2.0)
    assert s.average_loss_r == pytest.approx(-1.0)
    assert s.expectancy_r == pytest.approx(0.8)
    assert s.profit_factor == pytest.approx(3.0)
    assert s.total_r == pytest.approx(4.0)


def test_max_drawdown_is_measured_from_the_running_peak() -> None:
    """+3, -1, -1, -1, +2 -> equity 3,2,1,0,2; peak 3; deepest trough 0 -> DD 3."""
    rows = [_row(3.0), _row(-1.0), _row(-1.0), _row(-1.0), _row(2.0)]
    s = compute_stats(rows, min_group=1)
    assert s.max_drawdown_r == pytest.approx(3.0)


def test_drawdown_counts_a_losing_start_from_zero() -> None:
    """An account that only ever loses has a drawdown equal to its total loss.

    Seeding the peak at the first trade instead of at zero is a common bug and
    would report 0 here.
    """
    rows = [_row(-1.0), _row(-1.0), _row(-1.0)]
    s = compute_stats(rows, min_group=1)
    assert s.max_drawdown_r == pytest.approx(3.0)


def test_longest_losing_streak_counts_breakeven_as_a_loss() -> None:
    """A 0.0R trade is not a win; treating it as one understates the streak."""
    rows = [_row(1.0), _row(-1.0), _row(0.0), _row(-1.0), _row(1.0), _row(-1.0)]
    s = compute_stats(rows, min_group=1)
    assert s.longest_losing_streak == 3


def test_profit_factor_is_infinite_when_there_are_no_losses() -> None:
    """Reported as inf, not a large finite number.

    The honest statement is "this sample contains no losses", and a finite
    stand-in would let it be averaged into other numbers as if it were real.
    """
    s = compute_stats([_row(1.0), _row(2.0)], min_group=1)
    assert s.profit_factor == float("inf")


def test_best_and_worst_ignore_groups_below_the_minimum() -> None:
    """A 3-trade group must not be crowned 'best'.

    This is the easiest way for a journal to mislead its owner, so the guard
    is tested rather than trusted.
    """
    rows = [_row(-0.1, session="London") for _ in range(50)]
    rows += [_row(9.0, session="Tokyo") for _ in range(3)]
    s = compute_stats(rows, min_group=20)
    assert s.best_session[0] == "London", "a 3-trade group was ranked best"


def test_empty_journal_returns_none() -> None:
    assert compute_stats([]) is None


# ---------------------------------------------------------------------------
# record fields
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("hour,expected", [
    (3, "Tokyo"), (9, "London"), (13, "London/NY overlap"),
    (18, "New York"), (23, "Sydney"),
])
def test_session_windows(hour: int, expected: str) -> None:
    ts = pd.Timestamp(f"2024-03-05 {hour:02d}:30", tz="UTC")
    assert session_of(ts, "15m") == expected


def test_daily_bars_have_no_session() -> None:
    """Forcing a daily bar into an intraday session would be a fabrication."""
    ts = pd.Timestamp("2024-03-05 13:30", tz="UTC")
    assert session_of(ts, "1d").startswith("n/a")
    assert session_of(ts, "1wk").startswith("n/a")


def test_htf_bias_is_causal() -> None:
    """Bias at bar i must not change when later bars arrive."""
    rng = np.random.default_rng(3)
    close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 800))))
    for i in (300, 500, 700):
        assert htf_bias(close, i) == htf_bias(close.iloc[: i + 1], i)


def test_htf_bias_reports_insufficient_history_rather_than_guessing() -> None:
    close = pd.Series(np.linspace(100, 110, 50))
    assert htf_bias(close, 10) == "insufficient history"


def test_journal_row_result_is_net_of_cost() -> None:
    """A winner at exactly the target must book less than the raw R:R."""
    n = 80
    df = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC"),
        "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 1.0,
    })
    df.loc[41:, ["high", "close"]] = [200.0, 200.0]   # blow through the target
    atr = np.full(n, 1.0)
    sig = np.zeros(n, dtype=int)
    sig[40] = 1
    rows = build_journal(df, sig, symbol="X", timeframe="1d", setup_name="s",
                         atr=atr, atr_mult=1.0, reward_risk=2.0,
                         horizon_bars=20, cost_round_trip=0.003)
    assert len(rows) == 1
    assert rows[0].result_r < 2.0, "cost was not deducted from the result"
    assert rows[0].result_r > 1.0, "cost deduction is implausibly large"


def test_every_record_field_is_populated() -> None:
    """The journal's value is the columns; a silently blank one is a defect."""
    rng = np.random.default_rng(5)
    n = 600
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    df = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC"),
        "open": close, "high": close * 1.004, "low": close * 0.996,
        "close": close, "volume": 1.0,
    })
    sig = np.zeros(n, dtype=int)
    sig[250::40] = 1
    rows = build_journal(df, sig, symbol="EURUSD", timeframe="1h",
                         setup_name="demo", atr=np.full(n, 0.5))
    assert rows, "fixture produced no trades"
    for r in rows[:20]:
        d = r.to_dict()
        for f in ("date", "pair", "session", "htf_bias", "setup", "screenshot",
                  "reason_for_entry", "reason_for_failure", "mistake"):
            assert str(d[f]).strip(), f"{f} was blank"
        assert "mechanical" in d["mistake"]


def test_leverage_cap_scales_cost_and_result_together() -> None:
    """The omission that has appeared three times in this codebase.

    Risking a full 1R needs `risk_pct / stop_frac` of notional. When that
    exceeds `max_leverage` the position is forced SMALLER, so the realised R
    and the cost paid must both shrink by the same factor. Charging the
    uncapped cost against a capped position overstates cost by up to 1.7x on
    a 0.2% stop -- which is why intraday expectancy read -1.84R before it was
    fixed. Pinned here so it cannot come back a fourth time.
    """
    n = 120
    # a very tight stop: ATR is 0.1% of price, so stop_frac ~ 0.001 and the
    # 3x leverage cap binds hard
    px = 100.0
    df = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC"),
        "open": px, "high": px * 1.0005, "low": px * 0.9995,
        "close": px, "volume": 1.0,
    })
    atr = np.full(n, px * 0.001)
    sig = np.zeros(n, dtype=int)
    sig[50] = 1

    capped = build_journal(df, sig, symbol="X", timeframe="1d", setup_name="s",
                           atr=atr, atr_mult=1.0, reward_risk=2.0,
                           horizon_bars=20, cost_round_trip=0.003,
                           risk_pct=0.01, max_leverage=3.0)
    uncapped = build_journal(df, sig, symbol="X", timeframe="1d", setup_name="s",
                             atr=atr, atr_mult=1.0, reward_risk=2.0,
                             horizon_bars=20, cost_round_trip=0.003,
                             risk_pct=0.01, max_leverage=1e9)
    assert capped and uncapped
    # stop_frac ~ 0.001 -> want = 10x notional, capped to 3x -> k = 0.3
    assert abs(capped[0].result_r) < abs(uncapped[0].result_r), (
        "the leverage cap did not shrink the realised result")
    assert capped[0].result_r == pytest.approx(0.3 * uncapped[0].result_r, rel=0.02), (
        "result did not scale by the cap factor k = min(want, cap)/want")
