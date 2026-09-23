"""
Module: prop_challenge.py
Description: Probability a strategy reaches a profit target before breaching a
    drawdown limit -- and the same probability for a ZERO-EDGE strategy with
    identical shape.

    WHY THE NULL BASELINE IS THE POINT. A Monte Carlo run on a backtest's own
    trades answers "IF this edge is real and stationary, how often does it pass?"
    It cannot answer "is the edge real?", because the edge is its input. Quoting
    the output as a pass probability is precision about the wrong question --
    and it is the same failure this project already measured directly, when 137
    of 150 pure-noise paths cleared its legacy selection bar.

    A prop challenge makes that failure worse, not better, because the pass
    criterion is ASYMMETRIC: a profit target is a level you only have to touch
    once, while a drawdown limit is a level you must avoid at every point. Under
    the right target/limit ratio a strategy with NO edge at all passes a large
    fraction of the time on variance alone. So a raw pass probability of 98.7%
    means nothing until you know what 0% edge scores on the same rules -- if
    noise passes 90%, the strategy contributed 8 points, not 98.

    `simulate` returns both numbers and their difference. The difference is the
    only part attributable to edge.

    WHAT THIS DOES NOT MODEL. Trades are resampled i.i.d., so serial
    correlation -- losing streaks clustering in a regime -- is absent, which
    makes every pass probability here OPTIMISTIC. Consecutive-loss clustering is
    exactly what breaches daily limits. Treat these as an upper bound.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional, Sequence

import numpy as np

logger = logging.getLogger(__name__)

# Typical one-phase/two-phase retail prop terms. Deliberately explicit rather
# than hidden defaults: the target/limit RATIO is what decides how much of the
# pass rate is luck, so it must be visible at every call site.
DEFAULT_PROFIT_TARGET_PCT = 8.0
DEFAULT_MAX_TOTAL_DD_PCT = 10.0
DEFAULT_MAX_DAILY_DD_PCT = 5.0


@dataclass
class ChallengeResult:
    pass_rate: float
    null_pass_rate: float
    edge_lift: float                      # pass_rate - null_pass_rate
    median_trades_to_pass: Optional[float]
    fail_total_dd: float
    fail_daily_dd: float
    fail_timeout: float
    expectancy_r: float
    win_rate: float
    reward_risk: float
    n_sims: int
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "pass_rate": round(self.pass_rate, 4),
            "null_pass_rate": round(self.null_pass_rate, 4),
            "edge_lift": round(self.edge_lift, 4),
            "median_trades_to_pass": self.median_trades_to_pass,
            "fail_total_dd": round(self.fail_total_dd, 4),
            "fail_daily_dd": round(self.fail_daily_dd, 4),
            "fail_timeout": round(self.fail_timeout, 4),
            "expectancy_r": round(self.expectancy_r, 4),
            "win_rate": round(self.win_rate, 4),
            "reward_risk": round(self.reward_risk, 4),
            "n_sims": self.n_sims,
            "notes": self.notes,
        }


def _run_paths(
    pool: np.ndarray,
    *,
    risk_pct: float,
    profit_target_pct: float,
    max_total_dd_pct: float,
    max_daily_dd_pct: float,
    trades_per_day: float,
    max_trades: int,
    n_sims: int,
    rng: np.random.Generator,
) -> tuple[float, list[int], float, float, float]:
    """Resample `pool` (per-trade R multiples) into equity paths.

    Returns (pass_rate, trades_to_pass, fail_total, fail_daily, fail_timeout).
    """
    per_day = max(int(round(trades_per_day)), 1)
    passed = 0
    fail_total = fail_daily = fail_timeout = 0
    to_pass: list[int] = []

    draws = rng.choice(pool, size=(n_sims, max_trades), replace=True)
    for s in range(n_sims):
        equity = 0.0          # percent of starting balance
        peak = 0.0
        day_start = 0.0
        outcome = None
        for i in range(max_trades):
            equity += float(draws[s, i]) * risk_pct
            peak = max(peak, equity)

            # Daily limit is measured from the day's OPENING balance, which is
            # how prop firms actually score it -- not from the running peak.
            if (day_start - equity) >= max_daily_dd_pct:
                outcome = "daily"
                break
            # Total drawdown from peak equity.
            if (peak - equity) >= max_total_dd_pct:
                outcome = "total"
                break
            if equity >= profit_target_pct:
                outcome = "pass"
                to_pass.append(i + 1)
                break
            if (i + 1) % per_day == 0:
                day_start = equity

        if outcome == "pass":
            passed += 1
        elif outcome == "daily":
            fail_daily += 1
        elif outcome == "total":
            fail_total += 1
        else:
            fail_timeout += 1

    n = float(n_sims)
    return passed / n, to_pass, fail_total / n, fail_daily / n, fail_timeout / n


def simulate(
    trade_r: Sequence[float],
    *,
    risk_pct: float = 0.5,
    profit_target_pct: float = DEFAULT_PROFIT_TARGET_PCT,
    max_total_dd_pct: float = DEFAULT_MAX_TOTAL_DD_PCT,
    max_daily_dd_pct: float = DEFAULT_MAX_DAILY_DD_PCT,
    trades_per_day: float = 3.0,
    max_trades: int = 600,
    n_sims: int = 5000,
    seed: int = 7,
) -> Optional[ChallengeResult]:
    """Pass probability for a challenge, beside the same figure at zero edge.

    Args:
        trade_r: realised per-trade results in R multiples (+2.0 = a 2R winner).
        risk_pct: percent of the account risked per trade.
        trades_per_day: only affects WHERE the daily limit resets, not the
            expectancy; more trades per day means fewer resets and so a
            slightly higher daily-breach rate.

    Returns None when the sample is too small to say anything.
    """
    r = np.asarray([float(x) for x in trade_r if x is not None], dtype=float)
    if r.size < 30:
        return None

    wins = r[r > 0]
    losses = r[r <= 0]
    win_rate = float(wins.size) / float(r.size)
    avg_win = float(wins.mean()) if wins.size else 0.0
    avg_loss = float(abs(losses.mean())) if losses.size else 0.0
    rr = (avg_win / avg_loss) if avg_loss > 0 else float("nan")
    expectancy = float(r.mean())

    rng = np.random.default_rng(seed)
    pass_rate, to_pass, f_tot, f_day, f_time = _run_paths(
        r, risk_pct=risk_pct, profit_target_pct=profit_target_pct,
        max_total_dd_pct=max_total_dd_pct, max_daily_dd_pct=max_daily_dd_pct,
        trades_per_day=trades_per_day, max_trades=max_trades,
        n_sims=n_sims, rng=rng,
    )

    # THE NULL: same win rate, same R:R, expectancy forced to exactly zero by
    # recentring. This keeps the SHAPE of the distribution -- the thing that
    # drives drawdown clustering -- and removes only the edge, so the
    # difference is attributable to edge and nothing else.
    null_pool = r - r.mean()
    null_rate, _, _, _, _ = _run_paths(
        null_pool, risk_pct=risk_pct, profit_target_pct=profit_target_pct,
        max_total_dd_pct=max_total_dd_pct, max_daily_dd_pct=max_daily_dd_pct,
        trades_per_day=trades_per_day, max_trades=max_trades,
        n_sims=n_sims, rng=np.random.default_rng(seed + 1),
    )

    notes = [
        "Trades are resampled i.i.d., so losing streaks never cluster the way "
        "they do in a real regime -- every pass rate here is an UPPER bound.",
        f"Null keeps win rate {win_rate:.1%} and R:R {rr:.2f} and sets expectancy "
        f"to 0, so `edge_lift` is the only part the edge earned.",
    ]
    if r.size < 100:
        notes.append(f"Only {r.size} trades in the pool -- the resample cannot "
                     f"invent variety the sample does not contain.")

    return ChallengeResult(
        pass_rate=pass_rate,
        null_pass_rate=null_rate,
        edge_lift=pass_rate - null_rate,
        median_trades_to_pass=(float(np.median(to_pass)) if to_pass else None),
        fail_total_dd=f_tot, fail_daily_dd=f_day, fail_timeout=f_time,
        expectancy_r=expectancy, win_rate=win_rate, reward_risk=rr,
        n_sims=n_sims, notes=notes,
    )


def synthetic_pool(
    win_rate: float, reward_risk: float, n: int = 1000, seed: int = 7
) -> np.ndarray:
    """A trade pool with an exact win rate and R:R, for checking a CLAIM.

    Lets a published "60% win rate, profit factor 1.83" be simulated without
    the underlying trades, which is the only form such claims ever arrive in.
    """
    rng = np.random.default_rng(seed)
    wins = int(round(n * win_rate))
    pool = np.concatenate([np.full(wins, float(reward_risk)), np.full(n - wins, -1.0)])
    rng.shuffle(pool)
    return pool
