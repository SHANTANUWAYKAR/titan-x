# Challenges — $1 to $100, $100 to $1,000, and up

**Edge under test:** high-profile ORB (RVOL top-N), 5-min range, orb_opposite stop, 30.0 bps round-trip cost

Win rate **15.72%** · reward:risk **1.44** · expectancy **-0.9195 R** · pool 7,235 trades.

Intended risk **1.00%** of balance per trade · instrument **mnq** · minimum ticket risk **$20.00** · 4,000 simulations per rung · at most 2,000 trades per path.

**Kelly fraction at this edge: -42.88%.** Negative, which means the size that loses least is zero -- every rung below is a measurement of how fast the account dies, not of how it grows.

| Rung | x | Reach | Null | **Lift** | Ruin | Timeout | Median trades | Median end | Forced risk |
|---|---|---|---|---|---|---|---|---|---|
| $1 to $10 | 10x | **IMPOSSIBLE** | — | — | — | — | — | — | 2000% |
| $10 to $100 | 10x | **IMPOSSIBLE** | — | — | — | — | — | — | 200% |
| $100 to $1,000 | 10x | 0.00% | 8.35% | **-8.35 pt** | 100.00% | 0.00% | — | $5.00 | 20.00% |
| $1,000 to $10,000 | 10x | 0.00% | 0.12% | **-0.12 pt** | 100.00% | 0.00% | — | $4.56 | 2.00% |
| $10,000 to $100,000 | 10x | 0.00% | 0.07% | **-0.07 pt** | 100.00% | 0.00% | — | $5.22 | 1.00% |

## Rungs that are a funding problem, not a trading problem

- **$1.00 to $10.00** — $1.00 cannot fund the smallest ticket: minimum risk is $20.00, which is 2000% of the account. No trade is placeable, so this rung is a FUNDING problem, not a strategy problem.
- **$10.00 to $100.00** — $10.00 cannot fund the smallest ticket: minimum risk is $20.00, which is 200% of the account. No trade is placeable, so this rung is a FUNDING problem, not a strategy problem.

## How to read this

- **Reach** is the share of simulated accounts that touched the target before
  they could no longer place a trade. **Null** is the same simulation with the
  expectancy recentred to exactly zero and the win rate and R:R shape left
  intact. **Lift** is the difference — the only part the edge earned.
- **Forced risk** is what the FIRST trade actually risks once the minimum
  ticket is applied. When it is far above the intended risk, the plan on paper
  is not the plan being executed.
- Trades are resampled i.i.d., so losing streaks never cluster the way a real
  regime makes them. Every reach rate here is an **upper bound**.
- Timeout means the path neither arrived nor died inside the trade budget.
  A high timeout rate at a negative expectancy is not survival; it is an
  account grinding down slowly enough to run out of simulation first.

## Caveats carried from the simulator

- Trades are resampled i.i.d.; real losing streaks cluster, so every pass rate here is an UPPER bound.
- R multiples must already be NET of commission and slippage. Feeding gross R in removes the cost that decides the answer.
- `edge_lift` is pass_rate minus the same simulation at exactly zero expectancy. A pass rate at or below its null was bought with variance, not with edge -- and variance is symmetric, so the paths that reach the target on noise reach zero just as readily.
- With a negative expectancy the honest headline is the ruin rate, not the pass rate: the question stops being whether the account arrives and becomes how long it survives.
