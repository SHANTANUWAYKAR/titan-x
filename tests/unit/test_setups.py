"""Correctness guards for `setups/`.

This code was written fast and shipped with no tests, which is exactly where
silent bugs live. The properties pinned here are the ones whose failure would be
INVISIBLE in a backtest -- a leaky ORB level or an entry taken at the bar that
revealed the signal does not raise, it just produces a better number.

Each test states the failure it exists to catch, because a test whose purpose
cannot be read is a test nobody will maintain.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from project_titan_x.setups.ml_validation import purged_indices
from project_titan_x.setups.orb_setup import (
    ORBConfig, build_session_frame, extract_orb_signals, orb_economics,
    volume_profile,
)
from project_titan_x.setups.titan_setup import (
    SetupConfig, direction_score, economics, extract_signals,
)


def _intraday(days: int = 12, seed: int = 3) -> pd.DataFrame:
    """15m bars inside the NY session, several sessions deep."""
    rng = np.random.default_rng(seed)
    rows = []
    price = 100.0
    for d in range(days):
        day = pd.Timestamp("2024-03-04", tz="UTC") + pd.Timedelta(days=d)
        for k in range(26):                       # 13:30 -> 20:00 UTC
            ts = day + pd.Timedelta(minutes=13 * 60 + 30 + 15 * k)
            price *= float(np.exp(rng.normal(0, 0.002)))
            hi = price * (1 + abs(rng.normal(0, 0.001)))
            lo = price * (1 - abs(rng.normal(0, 0.001)))
            rows.append({"timestamp": ts, "open": price, "high": hi, "low": lo,
                         "close": price, "volume": float(rng.integers(1_000, 9_000))})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# ORB causality -- the failures here would be invisible, not loud
# ---------------------------------------------------------------------------

def test_orb_levels_are_constant_within_a_session() -> None:
    """Catches an ORB level that keeps updating after the opening window.

    The whole premise is a level FIXED by the first 15 minutes. A rolling
    high/low would quietly become "price vs its own recent extreme", which is a
    different and much easier-looking strategy.
    """
    d = build_session_frame(_intraday(), ORBConfig())
    assert d is not None and not d.empty
    for day, grp in d.groupby("_day"):
        hi = grp["_orb_high"].dropna().unique()
        lo = grp["_orb_low"].dropna().unique()
        assert len(hi) <= 1, f"{day}: ORB high changed within the session: {hi}"
        assert len(lo) <= 1, f"{day}: ORB low changed within the session: {lo}"


def test_no_trade_is_taken_during_the_opening_window() -> None:
    """Catches trading the range while it is still being formed."""
    cfg = ORBConfig()
    d = build_session_frame(_intraday(), cfg)
    early = d[d["_min_since_open"] < cfg.orb_minutes]
    assert not early.empty
    assert not early["_tradeable"].any(), "bars inside the opening window were tradeable"


def test_volume_profile_stays_inside_the_session_range() -> None:
    """Catches a POC/VAH/VAL computed at a price that never traded."""
    d = build_session_frame(_intraday(), ORBConfig())
    day = d[d["_day"] == d["_day"].unique()[1]]
    poc, vah, val = volume_profile(day)
    lo, hi = float(day["low"].min()), float(day["high"].max())
    for name, v in (("poc", poc), ("vah", vah), ("val", val)):
        assert lo <= v <= hi, f"{name}={v} outside the session range [{lo}, {hi}]"
    assert val <= poc <= vah, f"value area is inverted: {val} / {poc} / {vah}"


def test_previous_session_profile_is_used_not_todays() -> None:
    """Catches the classic look-ahead: using a profile the day has not finished.

    The first session cannot have a previous one, so its context must be NaN.
    A non-NaN value there means today's own profile leaked in.
    """
    d = build_session_frame(_intraday(), ORBConfig())
    first = d[d["_day"] == d["_day"].unique()[0]]
    assert first["_prev_poc"].isna().all(), "first session has a previous-day profile"
    later = d[d["_day"] == d["_day"].unique()[3]]
    assert later["_prev_poc"].notna().any(), "later sessions never got a profile"


# ---------------------------------------------------------------------------
# Sizing and economics
# ---------------------------------------------------------------------------

def test_notional_is_capped_at_max_leverage() -> None:
    """Catches risk/stop exploding on a tight stop.

    `notional = risk_pct / stop_distance`, so a very tight stop asks for
    unbounded size. Without the cap one quiet instrument would dominate the book.
    """
    cfg = ORBConfig(max_leverage=3.0)
    d = build_session_frame(_intraday(days=20), cfg)
    sig = extract_orb_signals(d, cfg)
    if sig.empty:
        pytest.skip("fixture produced no ORB signals")
    assert (sig["_notional"] <= cfg.max_leverage + 1e-9).all()
    assert (sig["_notional"] > 0).all()


def test_economics_net_equals_gross_minus_cost() -> None:
    """Catches the arithmetic silently drifting apart.

    Net is the number every decision rests on; if it stops being
    gross - cost, every report built on it is wrong and nothing raises.
    """
    cfg = SetupConfig()
    df = pd.DataFrame({"_win": [1, 0, 1, 0, 1] * 10,
                       "_notional": [0.2] * 50})
    e = economics(df, cfg)
    assert e["net_pct_per_trade"] == pytest.approx(
        e["gross_pct_per_trade"] - e["cost_pct_per_trade"])
    # Breakeven must match the reward:risk actually configured.
    assert e["breakeven_win_rate"] == pytest.approx(1.0 / (1.0 + cfg.reward_risk))


def test_win_rate_above_breakeven_implies_positive_gross() -> None:
    """Pins the relationship the whole audit rests on.

    expectancy > 0 <=> win_rate > 1/(1+RR). If these ever disagree, every
    'net-negative' conclusion in the reports is suspect.
    """
    cfg = SetupConfig(reward_risk=2.0)
    for wr in (0.20, 0.3333, 0.40, 0.60):
        n = 1000
        wins = int(round(n * wr))
        df = pd.DataFrame({"_win": [1] * wins + [0] * (n - wins),
                           "_notional": [0.0] * n})   # zero cost isolates gross
        e = economics(df, cfg)
        above_be = e["win_rate"] > e["breakeven_win_rate"]
        assert (e["gross_R"] > 0) == above_be, f"disagreement at win rate {wr}"


# ---------------------------------------------------------------------------
# Purged cross-validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("horizon,embargo", [(0, 0), (5, 5), (20, 20), (20, 50)])
def test_purged_indices_never_touch_the_test_block(horizon: int, embargo: int) -> None:
    """Catches the test block leaking into training."""
    n, tr_end, te_start, te_end = 500, 200, 200, 300
    idx = purged_indices(n, tr_end, te_start, te_end, horizon=horizon, embargo=embargo)
    assert not (set(idx.tolist()) & set(range(te_start, te_end)))


@pytest.mark.parametrize("horizon", [1, 5, 20])
def test_purge_removes_rows_whose_label_reaches_the_test_block(horizon: int) -> None:
    """Catches the leak a plain chronological split does NOT close.

    With a 20-bar horizon, the training row at index 199 is labelled by bars
    199..219 -- which is inside a test block starting at 200. Purging must drop
    exactly those.
    """
    n, tr_end, te_start, te_end = 500, 200, 200, 300
    idx = purged_indices(n, tr_end, te_start, te_end, horizon=horizon, embargo=0)
    left = idx[idx < te_start]
    assert left.max() + horizon <= te_start, (
        f"training row {left.max()} is labelled by bars reaching {left.max()+horizon}, "
        f"inside a test block starting at {te_start}")


def test_embargo_leaves_a_gap_after_the_test_block() -> None:
    """Catches resuming training immediately after the test set.

    Serial correlation means the bars just past a test block still carry its
    information; the embargo is what keeps them out.
    """
    n, tr_end, te_start, te_end, emb = 500, 200, 200, 300, 25
    idx = purged_indices(n, tr_end, te_start, te_end, horizon=10, embargo=emb)
    right = idx[idx >= te_end]
    if right.size:
        assert right.min() >= te_end + emb


# ---------------------------------------------------------------------------
# The direction rule must stay causal
# ---------------------------------------------------------------------------

def test_direction_score_is_causal_under_truncation() -> None:
    """Catches any future-peeking creeping into the primary rule.

    The score at bar i must not change when later bars arrive. Anything using a
    centered window or a full-sample statistic fails this immediately.
    """
    rng = np.random.default_rng(11)
    n = 400
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    e = pd.DataFrame({
        "ema_8": pd.Series(close).ewm(span=8).mean(),
        "ema_21": pd.Series(close).ewm(span=21).mean(),
        "macd": pd.Series(close).diff().rolling(5).mean(),
        "macd_signal": pd.Series(close).diff().rolling(9).mean(),
        "adx": pd.Series(np.abs(rng.normal(20, 5, n))),
        "rsi": pd.Series(50 + rng.normal(0, 10, n)),
    })
    cfg = SetupConfig()
    full = direction_score(e, cfg)
    for k in (150, 250, 350):
        prefix = direction_score(e.iloc[:k], cfg)
        np.testing.assert_allclose(
            prefix[-20:], full[k - 20:k], rtol=1e-9, atol=1e-12,
            err_msg=f"direction score at prefix {k} differs from the full series")
