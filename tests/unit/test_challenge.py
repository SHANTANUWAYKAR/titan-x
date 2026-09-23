"""Correctness guards for the growth-challenge ladder and the high-profile setup.

Every property pinned here is one whose failure would be INVISIBLE -- it would
not raise, it would just produce a friendlier number. A challenge simulator that
quietly ignores the minimum ticket, or a setup whose cost term drops the
leverage cap, reports a survivable plan for an account that cannot place the
trade. That is the specific failure mode these tests exist to catch.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from project_titan_x.setups.challenge import (
    MIN_RISK_USD, kelly_fraction, run_ladder, simulate_rung,
)
from project_titan_x.setups.high_profile_setup import (
    HighProfileConfig, apply_rvol_selection, daily_context, extract_hp_signals,
    hp_economics,
)
from project_titan_x.setups.hp_scanner import scan_symbol


def _binary_pool(win_rate: float, rr: float, n: int = 4000) -> np.ndarray:
    wins = int(round(n * win_rate))
    return np.concatenate([np.full(wins, rr), np.full(n - wins, -1.0)])


# ---------------------------------------------------------------------------
# The minimum ticket -- the constraint the whole module exists to expose
# ---------------------------------------------------------------------------

def test_rung_is_impossible_when_the_balance_cannot_fund_one_ticket() -> None:
    """Catches a $1 account being simulated as though it could trade futures.

    A $20 minimum risk on a $1 balance is 2,000% of the account. That is not an
    unlikely outcome to be simulated into a small pass rate, it is arithmetic --
    and reporting 0.0% instead of IMPOSSIBLE reads as bad luck.
    """
    r = simulate_rung(_binary_pool(0.50, 2.0), start=1.0, target=100.0,
                      risk_frac=0.01, instrument="mnq", n_sims=200)
    assert r is not None
    assert r.possible is False
    assert r.pass_rate == 0.0
    assert r.forced_risk_frac_at_start == pytest.approx(MIN_RISK_USD["mnq"] / 1.0)
    assert "FUNDING problem" in r.reason


def test_forced_risk_is_reported_above_the_intended_risk() -> None:
    """Catches the plan on paper being reported instead of the plan executed.

    $50 at a nominal 1% risk is $0.50 -- below any futures or options ticket.
    The account is really risking the floor, and the result must say so.
    """
    r = simulate_rung(_binary_pool(0.40, 2.0), start=50.0, target=500.0,
                      risk_frac=0.01, instrument="mnq", n_sims=300)
    assert r is not None and r.possible
    assert r.intended_risk_frac == pytest.approx(0.01)
    assert r.forced_risk_frac_at_start == pytest.approx(20.0 / 50.0)
    assert r.forced_risk_frac_at_start > r.intended_risk_frac * 10


def test_no_minimum_ticket_leaves_the_intended_risk_alone() -> None:
    """The floor must not move anything when there is no floor."""
    r = simulate_rung(_binary_pool(0.40, 2.0), start=100.0, target=200.0,
                      risk_frac=0.02, instrument="none", n_sims=300)
    assert r is not None and r.possible
    assert r.forced_risk_frac_at_start == pytest.approx(0.02)


# ---------------------------------------------------------------------------
# Edge, null and ruin must behave like edge, null and ruin
# ---------------------------------------------------------------------------

def test_a_real_edge_beats_its_own_zero_edge_null() -> None:
    """Catches the null being built wrong -- e.g. resampled from the same pool.

    A 60% win rate at 2R is a large edge. If `edge_lift` does not come out
    clearly positive, the null is not actually at zero expectancy and every
    lift number in the reports is meaningless.
    """
    r = simulate_rung(_binary_pool(0.60, 2.0), start=1000.0, target=2000.0,
                      risk_frac=0.02, instrument="none", n_sims=1500, max_trades=400)
    assert r is not None and r.possible
    assert r.edge_lift > 0.10, f"edge lift only {r.edge_lift:.4f}"
    assert r.pass_rate > r.null_pass_rate


def test_a_negative_edge_does_not_beat_its_null() -> None:
    """The claim this whole audit rests on, stated as a test.

    Below breakeven the pass rate must not exceed the zero-edge baseline by any
    meaningful margin. If it does, the simulator is rewarding something other
    than expectancy.
    """
    # 25% at 2R is below the 33.3% breakeven.
    r = simulate_rung(_binary_pool(0.25, 2.0), start=1000.0, target=2000.0,
                      risk_frac=0.02, instrument="none", n_sims=1500, max_trades=400)
    assert r is not None and r.possible
    assert r.edge_lift < 0.02, f"a losing edge showed lift {r.edge_lift:+.4f}"
    assert r.pass_rate < r.null_pass_rate + 0.02


def test_outcomes_are_exhaustive() -> None:
    """Every path must end reached, ruined or timed out -- nothing lost."""
    r = simulate_rung(_binary_pool(0.35, 2.0), start=1000.0, target=5000.0,
                      risk_frac=0.02, instrument="none", n_sims=600, max_trades=300)
    assert r is not None
    assert r.pass_rate + r.ruin_rate + r.timeout_rate == pytest.approx(1.0, abs=1e-9)


def test_bigger_risk_destroys_the_account_faster_at_a_losing_edge() -> None:
    """Catches sizing having no effect -- the most common simulator bug.

    Deliberately NOT asserted on the ruin rate with no minimum ticket. Pure
    fractional sizing multiplies the balance by (1 + r * f), which decays
    toward zero without ever reaching it, so ruin is 0% however hard the
    account is losing. That is arithmetic, not survival, and the median ending
    balance is what actually carries the damage.
    """
    pool = _binary_pool(0.30, 2.0)
    small = simulate_rung(pool, start=1000.0, target=3000.0, risk_frac=0.01,
                          instrument="none", n_sims=800, max_trades=500)
    large = simulate_rung(pool, start=1000.0, target=3000.0, risk_frac=0.10,
                          instrument="none", n_sims=800, max_trades=500)
    assert large.median_final < small.median_final
    assert large.median_final < 0.25 * small.median_final


def test_a_minimum_ticket_turns_decay_into_actual_ruin() -> None:
    """The floor is what makes ruin real, and bigger risk must reach it sooner.

    With a $10 ticket the account dies the moment it cannot fund one. This is
    the case that matters, because it is the one every real account is in.
    """
    pool = _binary_pool(0.30, 2.0)
    small = simulate_rung(pool, start=2000.0, target=6000.0, risk_frac=0.01,
                          instrument="mes", n_sims=800, max_trades=500)
    large = simulate_rung(pool, start=2000.0, target=6000.0, risk_frac=0.10,
                          instrument="mes", n_sims=800, max_trades=500)
    assert large.ruin_rate > small.ruin_rate
    assert large.ruin_rate > 0.0


def test_ladder_orders_rungs_and_keeps_pool_stats() -> None:
    res = run_ladder(_binary_pool(0.40, 2.0), risk_frac=0.02,
                     instrument="none", n_sims=300, max_trades=300)
    assert res is not None
    assert [r.start for r in res.rungs] == sorted(r.start for r in res.rungs)
    assert res.win_rate == pytest.approx(0.40, abs=0.01)
    assert res.reward_risk == pytest.approx(2.0, abs=1e-6)
    assert res.notes, "the ladder must carry its own caveats"


def test_too_few_trades_returns_none_rather_than_a_number() -> None:
    assert simulate_rung([1.0, -1.0] * 5, start=100.0, target=200.0) is None
    assert run_ladder([1.0, -1.0] * 5) is None


@pytest.mark.parametrize("wr,rr,sign", [(0.60, 2.0, 1), (0.3333, 2.0, 0), (0.25, 2.0, -1)])
def test_kelly_sign_tracks_breakeven(wr: float, rr: float, sign: int) -> None:
    """Kelly must be negative exactly when the edge is below breakeven."""
    f = kelly_fraction(wr, rr)
    if sign > 0:
        assert f > 0
    elif sign == 0:
        assert abs(f) < 1e-3
    else:
        assert f < 0


# ---------------------------------------------------------------------------
# The high-profile setup: causality and the leverage cap
# ---------------------------------------------------------------------------

def _intraday_5m(days: int = 40, seed: int = 5) -> pd.DataFrame:
    """5m bars inside the NY session, deep enough for the 14-day lookbacks."""
    rng = np.random.default_rng(seed)
    rows = []
    price = 100.0
    for d in range(days):
        day = pd.Timestamp("2024-03-04", tz="UTC") + pd.Timedelta(days=d)
        for k in range(78):                       # 13:30 -> 20:00 UTC
            ts = day + pd.Timedelta(minutes=13 * 60 + 30 + 5 * k)
            o = price
            price *= float(np.exp(rng.normal(0, 0.0015)))
            hi = max(o, price) * (1 + abs(rng.normal(0, 0.0008)))
            lo = min(o, price) * (1 - abs(rng.normal(0, 0.0008)))
            rows.append({"timestamp": ts, "open": o, "high": hi, "low": lo,
                         "close": price, "volume": float(rng.integers(1_000, 9_000))})
    return pd.DataFrame(rows)


def test_daily_context_never_sees_the_current_session() -> None:
    """Catches the classic leak: today's own volume inside its own RVOL base.

    With today included in the average it is compared against, every relative
    volume is pulled toward 1.0 and the selection filter silently stops
    selecting. The first sessions must therefore have NO atr14 and NO rvol.
    """
    cfg = HighProfileConfig(min_daily_atr=0.0, min_price=0.0)
    from project_titan_x.setups.high_profile_setup import _session_frame
    ctx = daily_context(_session_frame(_intraday_5m(), cfg), cfg)
    assert ctx["atr14"].iloc[:cfg.atr_lookback_days].isna().all()
    assert ctx["rvol"].iloc[:cfg.rvol_lookback_days].isna().all()
    assert ctx["atr14"].iloc[-1] == ctx["atr14"].iloc[-1]        # not NaN later


def test_signals_are_unchanged_when_later_sessions_arrive() -> None:
    """Catches any future-peeking in the extraction.

    A signal produced for a session must be identical whether or not the data
    continues past it. Anything using a full-sample statistic fails here.
    """
    cfg = HighProfileConfig(min_daily_atr=0.0, min_price=0.0)
    df = _intraday_5m(days=40)
    full = extract_hp_signals(df, cfg, symbol="T")
    prefix = extract_hp_signals(df[df["timestamp"] < "2024-03-29"], cfg, symbol="T")
    if prefix.empty:
        pytest.skip("fixture produced no early signals")
    merged = full.merge(prefix, on="_day", suffixes=("_f", "_p"))
    assert not merged.empty
    np.testing.assert_allclose(merged["_r_gross_f"], merged["_r_gross_p"], rtol=1e-9)
    np.testing.assert_allclose(merged["_entry_f"], merged["_entry_p"], rtol=1e-12)


def test_cost_and_gross_carry_the_same_leverage_cap() -> None:
    """Catches the bug this module shipped with: cost ignoring the size cap.

    `_notional` is capped at `max_leverage`, so a tight stop buys LESS than the
    size a full 1R needs. Both the realised R and the cost paid must shrink by
    the same factor -- applying the cap to one and not the other reported >6 R
    of cost per trade on tight ranges, which is an artefact, not a measurement.
    """
    cfg = HighProfileConfig(min_daily_atr=0.0, min_price=0.0, max_leverage=4.0)
    sig = extract_hp_signals(_intraday_5m(days=40), cfg, symbol="T")
    if sig.empty:
        pytest.skip("fixture produced no signals")
    assert (sig["_notional"] <= cfg.max_leverage + 1e-9).all()
    assert (sig["_size_ratio"] <= 1.0 + 1e-9).all()
    assert (sig["_size_ratio"] > 0).all()
    # net = size_ratio * (gross - cost/stop_frac), exactly.
    expect = sig["_size_ratio"] * (
        sig["_r_gross"] - (cfg.cost_bps_round_trip / 10_000.0) / sig["_stop_frac"])
    np.testing.assert_allclose(sig["_r_net"], expect, rtol=1e-9)
    # and the cost term itself must never exceed what the cap can buy
    cap_cost = (cfg.cost_bps_round_trip / 10_000.0) * cfg.max_leverage / cfg.risk_pct
    assert (sig["_cost_r"] <= cap_cost + 1e-9).all()


def test_breakeven_cost_is_the_cost_that_zeroes_expectancy() -> None:
    """Pins the headline metric to its own definition.

    Re-running economics AT the reported break-even must give an expectancy of
    ~0. If it does not, the number quoted in every report is not break-even.
    """
    cfg = HighProfileConfig(min_daily_atr=0.0, min_price=0.0)
    sig = extract_hp_signals(_intraday_5m(days=40), cfg, symbol="T")
    if sig.empty:
        pytest.skip("fixture produced no signals")
    e = hp_economics(sig, cfg)
    at_be = HighProfileConfig(min_daily_atr=0.0, min_price=0.0,
                              cost_bps_round_trip=e["breakeven_cost_bps"])
    sig2 = extract_hp_signals(_intraday_5m(days=40), at_be, symbol="T")
    assert hp_economics(sig2, at_be)["expectancy_r_net"] == pytest.approx(0.0, abs=1e-6)


def test_doji_sessions_are_never_traded() -> None:
    """No direction means no trade -- not a coin flip."""
    cfg = HighProfileConfig(min_daily_atr=0.0, min_price=0.0)
    from project_titan_x.setups.high_profile_setup import _session_frame
    d = _session_frame(_intraday_5m(days=40), cfg)
    ctx = daily_context(d, cfg)
    sig = extract_hp_signals(_intraday_5m(days=40), cfg, symbol="T")
    doji_days = set(ctx.index[ctx["direction"] == 0])
    assert not (set(sig["_day"]) & doji_days)


def test_rvol_selection_keeps_at_most_top_n_per_day() -> None:
    """Catches the cross-sectional cut silently keeping everything."""
    cfg = HighProfileConfig(rvol_top_n=2, rvol_min=0.0)
    sig = pd.DataFrame({
        "_sym": list("ABCD") * 2,
        "_day": [pd.Timestamp("2024-01-01")] * 4 + [pd.Timestamp("2024-01-02")] * 4,
        "_ts": pd.date_range("2024-01-01", periods=8, freq="h", tz="UTC"),
        "_rvol": [1.0, 4.0, 3.0, 2.0, 5.0, 1.5, 2.5, 3.5],
    })
    kept = apply_rvol_selection(sig, cfg)
    assert kept.groupby("_day").size().max() <= 2
    # and it must keep the HIGHEST, not just the first two rows
    day1 = kept[kept["_day"] == pd.Timestamp("2024-01-01")]
    assert set(day1["_rvol"]) == {4.0, 3.0}


# ---------------------------------------------------------------------------
# The scanner must never out-claim its own measurement
# ---------------------------------------------------------------------------

def test_confidence_is_capped_when_the_measurement_is_negative() -> None:
    """Catches a scanner advertising a setup its own backtest scored below zero."""
    cfg = HighProfileConfig(min_daily_atr=0.0, min_price=0.0)
    measured = {"T": {"trades": 5000, "win_rate_gross": 0.17,
                      "expectancy_r_net": -0.40, "breakeven_cost_bps": -1.0}}
    sig = scan_symbol(_intraday_5m(days=40), "T", cfg=cfg, measured=measured)
    if sig is None:
        pytest.skip("fixture produced no scannable session")
    assert sig["confidence_score"] <= 25
    assert sig["expected_value"] < 0
    assert "NEGATIVE" in " ".join(sig["supporting_evidence"])


def test_unmeasured_asset_is_capped_and_says_so() -> None:
    cfg = HighProfileConfig(min_daily_atr=0.0, min_price=0.0)
    sig = scan_symbol(_intraday_5m(days=40), "T", cfg=cfg, measured={})
    if sig is None:
        pytest.skip("fixture produced no scannable session")
    assert sig["confidence_score"] <= 20
    assert "No backtest exists" in " ".join(sig["supporting_evidence"])


def test_scanner_levels_match_the_backtest_for_the_same_session() -> None:
    """Catches the scanner and the backtest drifting into different setups.

    The scanner publishes the entry it expects; the backtest scores the entry it
    got. For a `stop_order` entry those must agree on the LEVEL, or the thing
    being measured is not the thing being signalled.
    """
    cfg = HighProfileConfig(min_daily_atr=0.0, min_price=0.0)
    df = _intraday_5m(days=40)
    sig = extract_hp_signals(df, cfg, symbol="T")
    if sig.empty:
        pytest.skip("fixture produced no signals")
    row = sig.iloc[len(sig) // 2]
    scanned = scan_symbol(df, "T", cfg=cfg, measured={}, as_of=row["_day"])
    assert scanned is not None
    level = row["_orb_high"] if row["_dir"] > 0 else row["_orb_low"]
    assert scanned["entry"] == pytest.approx(level, rel=1e-6)
    assert scanned["direction"] == ("LONG" if row["_dir"] > 0 else "SHORT")
