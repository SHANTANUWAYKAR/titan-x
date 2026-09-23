# Challenges — $1 → $100, $100 → $1,000, and up

Generated 2026-09-22 by `setups/run_challenge.py`. Each scenario below has its
own full report; this page is the comparison.

Every rung is simulated 4,000 times on a **multiplicative** balance (a growth
challenge is a compound, not a fixed-size evaluation), against a **minimum
ticket floor**, and beside its own **zero-expectancy null**.

---

## The two bottom rungs are not trading problems

| Rung | Multiple | Minimum ticket | What the first trade really risks | Verdict |
|---|---|---|---|---|
| $1 → $10 | 10× | $20 (1 micro futures contract, 10-pt stop) | **2,000% of the account** | **IMPOSSIBLE** |
| $10 → $100 | 10× | $20 | **200% of the account** | **IMPOSSIBLE** |
| $100 → $1,000 | 10× | $20 | 20% of the account | tradeable |
| $1,000 → $10,000 | 10× | $20 | 2% of the account | tradeable |
| $10,000 → $100,000 | 10× | $20 | 1% (the intended risk) | tradeable |

The simulator reports these as IMPOSSIBLE rather than 0.0%, because 0.0% reads
like bad luck and this is arithmetic. **You cannot place a trade whose smallest
legal size is twenty times your balance.** No strategy changes that.

The floors used, and why:

| Instrument | Minimum risk per trade | Reasoning |
|---|---|---|
| Micro Nasdaq (MNQ) | $20 | ~$2/point, a 10-point stop |
| Micro S&P (MES) | $10 | ~$1.25/point, an 8-point stop |
| Options | $20 | cheapest liquid contract at $0.20 = $20 premium, all at risk |
| Crypto spot | $0.10 | ~$5 exchange minimum notional with a 2% stop |
| Equity | $1.00 | one $50 share with a 2% stop |

**What $50 can actually trade.** The floor is what decides it, not the
strategy. At a $50 balance:

| Vehicle | Forced risk on trade one | Usable? |
|---|---|---|
| Spot crypto ($0.10) | 0.2% | yes |
| Equity, 1 share ($1.00) | 2% | yes |
| Micro futures MES ($10) | 20% | no |
| Micro futures MNQ ($20) | 40% | no |
| Options ($20) | 40% | no |

So spot crypto and single shares are placeable at a sane risk fraction; futures
and options are not, and that is true regardless of how good the setup is. The
video recommends exactly the two vehicles a $50 account cannot size.

---

## $100 → $1,000 — the first rung that can be traded

| Edge under test | Win rate | Risk/trade | Reach | Null | **Lift** | Ruin | Kelly |
|---|---|---|---|---|---|---|---|
| **Claimed** — the video's 40% at 2R | 40.00% | 10% | 57.35% | 9.28% | **+48.08 pt** | 42.65% | +10.00% |
| **Claimed** — same edge, 1% risk | 40.00% | 1% | 63.68% | 9.85% | **+53.83 pt** | 36.33% | +10.00% |
| **Measured** — ORB 5-min retest, 2R | 31.94% | 10% | 4.78% | 8.97% | **−4.20 pt** | **95.23%** | −2.09% |
| **Measured** — high-profile ORB, RVOL-filtered | 15.72% | 1% | 0.00% | 8.35% | **−8.35 pt** | **100.00%** | −42.88% |

### What this table says

**An 8-point win-rate gap decides everything.** 40% at 2R reaches the target
57% of the time. 31.94% at 2R — the same structure, measured on 48,425 real
trades — is ruined 95% of the time. Both descriptions read as "a 2R strategy
that wins about a third of the time."

**Both measured rows fall below their own noise baseline.** A strategy with
exactly zero edge reaches $1,000 about **9%** of the time, because a target is
a level you only need to touch once. The measured edge does *worse than
nothing*. That is what a negative expectancy means, stated in the currency of
the question actually being asked.

**The 10%-risk rule is full Kelly at the claimed edge.** Kelly at 40% and 2R is
exactly 10.00%. So even taking the claim at face value, that rule sizes at the
theoretical maximum — where growth is fastest and drawdowns are deepest. It
costs **6 points of extra ruin** versus 1% risk (42.65% vs 36.33%) while
*lowering* the reach rate. At a negative edge it simply accelerates the ending.

---

## Higher rungs

| Rung | Claimed 40% @ 2R, 1% risk | Measured ORB 31.94%, 10% risk |
|---|---|---|
| $1,000 → $10,000 | reach **99.78%**, ruin 0.00% | reach 3.25%, ruin **96.75%** |
| $10,000 → $100,000 | reach **99.10%**, ruin 0.00% | reach 3.33%, ruin **96.67%** |

With a genuine edge, the higher rungs get *easier* — the minimum ticket stops
binding and compounding does the work. With a negative edge they get no easier
at any size, because the problem was never capital.

---

## How to read these numbers

- **Reach** — the share of simulated accounts that touched the target before
  they could no longer place a trade.
- **Null** — the identical simulation with expectancy recentred to exactly zero,
  win rate and R:R shape left intact.
- **Lift** — reach minus null. The only part the edge earned. Negative lift
  means the strategy underperformed pure variance.
- **Ruin** — the account could no longer fund one minimum ticket. Not
  "balance hit zero": a $3 balance with a $20 ticket is finished.
- **Forced risk** — what the first trade actually risks once the floor applies.
  Where it is far above the intended risk, the plan on paper is not the plan
  being executed.

**Limits of this simulation.** Trades are resampled i.i.d., so losing streaks
never cluster the way a real regime makes them — every reach rate here is an
**upper bound**. R multiples must already be net of commission and slippage;
feeding gross R in removes the term that decides the answer.

---

## Reproduce

```
# measured high-profile ORB, RVOL-filtered, micro futures, 1% risk
python setups/run_challenge.py --from-hp --hp-json orbstop_cost30 \
    --rvol-filtered --instrument mnq --risk 0.01 --out-suffix measured_mnq

# the video's claimed edge, at his own 10% sizing rule
python setups/run_challenge.py --win-rate 0.40 --rr 2.0 --risk 0.10 \
    --instrument mnq --out-suffix claim_10pct

# the same claim at 1% risk
python setups/run_challenge.py --win-rate 0.40 --rr 2.0 --risk 0.01 \
    --instrument mnq --out-suffix claim_1pct

# the measured ORB win rate at his sizing
python setups/run_challenge.py --win-rate 0.3194 --rr 2.0 --risk 0.10 \
    --instrument mnq --out-suffix measured_orb

# one custom rung, e.g. a real $50 account on spot crypto
python setups/run_challenge.py --from-hp --hp-json orbstop_cost30 \
    --instrument crypto --risk 0.02 --start 50 --target 500
```

Per-scenario reports: `CHALLENGES_measured_mnq.md`, `CHALLENGES_claim_10pct.md`,
`CHALLENGES_claim_1pct.md`, `CHALLENGES_measured_orb.md`.
Where the measured edges come from: `HIGH_PROFILE_RESEARCH.md`.
