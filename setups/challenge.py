"""
Module: challenge.py
Description: Account-growth challenges -- $1 -> $100, $100 -> $1,000 and so on
    -- answered as a probability instead of a promise.

    WHY THIS IS NOT THE SAME AS prop_challenge.py. That module models a funded
    evaluation: a fixed 8% target against a 10% drawdown limit, scored on an
    ADDITIVE equity curve because the account size never changes. A growth
    challenge is the opposite problem. Turning $1 into $100 is a 100x compound,
    so the equity curve MUST be multiplicative, and the binding constraint is
    not a drawdown rule -- it is that a small enough balance cannot place a
    trade at all.

    THE CONSTRAINT NOBODY QUOTES: MINIMUM TICKET. Every instrument has a
    smallest position it will accept -- one micro contract, one option, one
    share, an exchange minimum notional. Below that, "risk 1% of the account"
    is not a plan that exists. With a $50 balance and a $20 minimum ticket, a
    "1% risk" trade would be $0.50 and cannot be placed; the actual risk taken
    is 40% of the account, whatever the plan said. `min_risk_usd` makes that
    visible, and the simulator reports the risk fraction the trader was FORCED
    into rather than the one they intended.

    This is why the bottom rungs of a challenge ladder are usually not a
    trading problem. A rung whose starting balance cannot fund a single
    minimum ticket is reported IMPOSSIBLE, not merely unlikely.

    RUIN IS "CANNOT PLACE A TRADE", NOT "BALANCE HIT ZERO". A balance of $3
    with a $20 minimum ticket is finished even though the number is positive.
    Modelling ruin as balance <= 0 would report survival for accounts that are
    functionally dead, which flatters every pass rate on the ladder.

    THE NULL BASELINE IS THE POINT, same as in prop_challenge.py. A target is
    a level you only have to touch once, so variance alone carries some paths
    there. `null_pass_rate` re-runs the identical simulation with expectancy
    recentred to exactly zero, keeping the win rate and the R:R shape intact.
    `edge_lift` is the difference -- the only part the edge earned. A 30% pass
    rate means nothing until you know that noise scores 28%.

    WHAT THIS DOES NOT MODEL. Trades are resampled i.i.d., so losing streaks
    never cluster the way a real regime makes them; every pass rate here is an
    UPPER bound. Costs are assumed to be inside the R multiples that go in, so
    passing GROSS R multiples silently removes the thing that decides the
    answer.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional, Sequence

import numpy as np

logger = logging.getLogger(__name__)

# The ladder the question is usually asked as. Each rung is (start, target).
DEFAULT_LADDER: tuple[tuple[float, float], ...] = (
    (1.0, 10.0),
    (10.0, 100.0),
    (100.0, 1_000.0),
    (1_000.0, 10_000.0),
    (10_000.0, 100_000.0),
)

# Smallest amount of money that can actually be put at risk in one trade, by
# instrument. These are the REAL floors a small account runs into, and they are
# why the bottom of the ladder is a funding problem rather than a trading one.
#
#   mnq     micro Nasdaq futures, ~$2/point; a 10-point stop is ~$20 of risk
#   mes     micro S&P futures, ~$1.25/point; an 8-point stop is ~$10 of risk
#   option  the cheapest liquid contract at $0.20 is $20 of premium, all at risk
#   crypto  exchange minimum notional ~$5 with a 2% stop is ~$0.10 of risk
#   equity  one $50 share with a 2% stop is ~$1 of risk
MIN_RISK_USD: dict[str, float] = {
    "mnq": 20.0,
    "mes": 10.0,
    "option": 20.0,
    "crypto": 0.10,
    "equity": 1.00,
    "none": 0.0,
}


@dataclass
class RungResult:
    """One rung of the ladder: start -> target."""

    start: float
    target: float
    multiple: float
    possible: bool                 # can the starting balance fund one ticket?
    pass_rate: float
    null_pass_rate: float
    edge_lift: float
    ruin_rate: float
    timeout_rate: float
    median_trades_to_target: Optional[float]
    p10_final: float
    median_final: float
    p90_final: float
    intended_risk_frac: float
    forced_risk_frac_at_start: float   # what the FIRST trade actually risks
    min_risk_usd: float
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "start": self.start,
            "target": self.target,
            "multiple": round(self.multiple, 2),
            "possible": self.possible,
            "pass_rate": round(self.pass_rate, 4),
            "null_pass_rate": round(self.null_pass_rate, 4),
            "edge_lift": round(self.edge_lift, 4),
            "ruin_rate": round(self.ruin_rate, 4),
            "timeout_rate": round(self.timeout_rate, 4),
            "median_trades_to_target": self.median_trades_to_target,
            "p10_final": round(self.p10_final, 2),
            "median_final": round(self.median_final, 2),
            "p90_final": round(self.p90_final, 2),
            "intended_risk_frac": round(self.intended_risk_frac, 4),
            "forced_risk_frac_at_start": round(self.forced_risk_frac_at_start, 4),
            "min_risk_usd": self.min_risk_usd,
            "reason": self.reason,
        }


@dataclass
class LadderResult:
    rungs: list[RungResult] = field(default_factory=list)
    win_rate: float = 0.0
    reward_risk: float = 0.0
    expectancy_r: float = 0.0
    n_trades_in_pool: int = 0
    instrument: str = "none"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "win_rate": round(self.win_rate, 4),
            "reward_risk": round(self.reward_risk, 4),
            "expectancy_r": round(self.expectancy_r, 4),
            "n_trades_in_pool": self.n_trades_in_pool,
            "instrument": self.instrument,
            "rungs": [r.to_dict() for r in self.rungs],
            "notes": self.notes,
        }


def _paths(
    pool: np.ndarray,
    *,
    start: float,
    target: float,
    risk_frac: float,
    min_risk_usd: float,
    max_forced_risk_frac: float,
    max_trades: int,
    n_sims: int,
    rng: np.random.Generator,
) -> tuple[float, float, float, list[int], np.ndarray]:
    """Compound `pool` (per-trade R multiples) into balance paths.

    Returns (reach_rate, ruin_rate, timeout_rate, trades_to_target, finals).

    A trade's risk is `balance * risk_frac`, floored at `min_risk_usd`: below
    the floor the position cannot be placed at the intended size, so the
    trader either takes the bigger ticket or does not trade. Taking it is the
    charitable assumption -- it is what people actually do -- and it is why
    small balances show a risk fraction far above the one they planned.
    """
    draws = rng.choice(pool, size=(n_sims, max_trades), replace=True)
    reached = ruined = 0
    to_target: list[int] = []
    finals = np.empty(n_sims, dtype=float)

    for s in range(n_sims):
        bal = start
        outcome = None
        for i in range(max_trades):
            risk_usd = max(bal * risk_frac, min_risk_usd)
            frac = (risk_usd / bal) if bal > 0 else float("inf")
            # Cannot fund the smallest ticket without betting more of the
            # account than allowed: functionally dead, positive balance or not.
            if frac > max_forced_risk_frac:
                outcome = "ruin"
                break
            bal += float(draws[s, i]) * risk_usd
            if bal <= 0:
                bal = 0.0
                outcome = "ruin"
                break
            if bal >= target:
                outcome = "reach"
                to_target.append(i + 1)
                break
        finals[s] = bal
        if outcome == "reach":
            reached += 1
        elif outcome == "ruin":
            ruined += 1

    n = float(n_sims)
    timeout = (n_sims - reached - ruined) / n
    return reached / n, ruined / n, timeout, to_target, finals


def simulate_rung(
    trade_r: Sequence[float],
    *,
    start: float,
    target: float,
    risk_frac: float = 0.01,
    instrument: str = "none",
    min_risk_usd: Optional[float] = None,
    max_forced_risk_frac: float = 1.0,
    max_trades: int = 2000,
    n_sims: int = 4000,
    seed: int = 7,
) -> Optional[RungResult]:
    """Probability of turning `start` into `target` before going broke.

    Args:
        trade_r: realised per-trade results in R multiples, NET of costs.
        risk_frac: intended fraction of the CURRENT balance risked per trade.
        instrument: keys `MIN_RISK_USD`; sets the minimum ticket floor.
        max_forced_risk_frac: the most of the account a forced minimum ticket
            may consume before the rung counts as unfundable. 1.0 means "the
            whole account on one trade is still technically a trade".

    Returns None when the trade pool is too small to say anything (<30).
    """
    r = np.asarray([float(x) for x in trade_r if x is not None], dtype=float)
    if r.size < 30:
        return None
    if start <= 0 or target <= start:
        raise ValueError(f"need 0 < start < target, got {start} -> {target}")

    floor = MIN_RISK_USD.get(instrument.lower(), 0.0) if min_risk_usd is None else min_risk_usd
    forced_at_start = max(risk_frac, floor / start)

    # A rung whose first trade would need more than the whole account is not
    # unlikely, it is arithmetically impossible. Reported as such rather than
    # simulated into a 0.0% that reads like bad luck.
    if forced_at_start > max_forced_risk_frac:
        return RungResult(
            start=start, target=target, multiple=target / start, possible=False,
            pass_rate=0.0, null_pass_rate=0.0, edge_lift=0.0,
            ruin_rate=0.0, timeout_rate=0.0, median_trades_to_target=None,
            p10_final=start, median_final=start, p90_final=start,
            intended_risk_frac=risk_frac, forced_risk_frac_at_start=forced_at_start,
            min_risk_usd=floor,
            reason=(f"${start:,.2f} cannot fund the smallest ticket: minimum risk "
                    f"is ${floor:,.2f}, which is {forced_at_start * 100:.0f}% of the "
                    f"account. No trade is placeable, so this rung is a FUNDING "
                    f"problem, not a strategy problem."),
        )

    reach, ruin, timeout, to_t, finals = _paths(
        r, start=start, target=target, risk_frac=risk_frac, min_risk_usd=floor,
        max_forced_risk_frac=max_forced_risk_frac, max_trades=max_trades,
        n_sims=n_sims, rng=np.random.default_rng(seed))

    # Same null convention as prop_challenge.simulate: recentre the pool so
    # expectancy is exactly zero while the win rate and R:R shape survive.
    null_reach, _, _, _, _ = _paths(
        r - r.mean(), start=start, target=target, risk_frac=risk_frac,
        min_risk_usd=floor, max_forced_risk_frac=max_forced_risk_frac,
        max_trades=max_trades, n_sims=n_sims, rng=np.random.default_rng(seed + 1))

    return RungResult(
        start=start, target=target, multiple=target / start, possible=True,
        pass_rate=reach, null_pass_rate=null_reach, edge_lift=reach - null_reach,
        ruin_rate=ruin, timeout_rate=timeout,
        median_trades_to_target=(float(np.median(to_t)) if to_t else None),
        p10_final=float(np.percentile(finals, 10)),
        median_final=float(np.median(finals)),
        p90_final=float(np.percentile(finals, 90)),
        intended_risk_frac=risk_frac, forced_risk_frac_at_start=forced_at_start,
        min_risk_usd=floor,
    )


def run_ladder(
    trade_r: Sequence[float],
    *,
    ladder: Sequence[tuple[float, float]] = DEFAULT_LADDER,
    risk_frac: float = 0.01,
    instrument: str = "none",
    min_risk_usd: Optional[float] = None,
    n_sims: int = 4000,
    max_trades: int = 2000,
    seed: int = 7,
) -> Optional[LadderResult]:
    """Every rung of a growth ladder against one measured trade distribution."""
    r = np.asarray([float(x) for x in trade_r if x is not None], dtype=float)
    if r.size < 30:
        return None
    wins, losses = r[r > 0], r[r <= 0]
    wr = float(wins.size) / float(r.size)
    avg_w = float(wins.mean()) if wins.size else 0.0
    avg_l = float(abs(losses.mean())) if losses.size else 0.0
    rr = (avg_w / avg_l) if avg_l > 0 else float("nan")

    out = LadderResult(
        win_rate=wr, reward_risk=rr, expectancy_r=float(r.mean()),
        n_trades_in_pool=int(r.size), instrument=instrument,
    )
    for i, (start, target) in enumerate(ladder):
        res = simulate_rung(
            r, start=start, target=target, risk_frac=risk_frac,
            instrument=instrument, min_risk_usd=min_risk_usd,
            n_sims=n_sims, max_trades=max_trades, seed=seed + 10 * i)
        if res is not None:
            out.rungs.append(res)

    out.notes = [
        "Trades are resampled i.i.d.; real losing streaks cluster, so every "
        "pass rate here is an UPPER bound.",
        "R multiples must already be NET of commission and slippage. Feeding "
        "gross R in removes the cost that decides the answer.",
        "`edge_lift` is pass_rate minus the same simulation at exactly zero "
        "expectancy. A pass rate at or below its null was bought with variance, "
        "not with edge -- and variance is symmetric, so the paths that reach "
        "the target on noise reach zero just as readily.",
        "With a negative expectancy the honest headline is the ruin rate, not "
        "the pass rate: the question stops being whether the account arrives "
        "and becomes how long it survives.",
    ]
    floor = (MIN_RISK_USD.get(instrument.lower(), 0.0)
             if min_risk_usd is None else min_risk_usd)
    if floor <= 0:
        # Without a floor the ruin column is structurally 0% and says nothing.
        # Left visible rather than hidden, with the reason attached, because a
        # reader who does not know this will read 0% as safety.
        out.notes.insert(0, (
            "NO MINIMUM TICKET IS SET, so the ruin column is structurally 0%: "
            "multiplying a balance by (1 + r x f) decays it toward zero without "
            "ever reaching zero. Read the p10 and median ending balances "
            "instead, and set --instrument to get a real ruin rate."))
    return out


def kelly_fraction(win_rate: float, reward_risk: float) -> float:
    """Kelly bet size for a two-outcome trade. Negative when there is no edge.

    f* = (p * b - q) / b, with b the reward:risk. Returned unclamped and
    unscaled on purpose: a negative value is the useful answer, because it
    says the only size that does not lose money is zero.
    """
    if reward_risk <= 0:
        return float("nan")
    q = 1.0 - win_rate
    return (win_rate * reward_risk - q) / reward_risk
