# Challenges — $1 to $100, $100 to $1,000, and up

**Edge under test:** CLAIMED edge: 40.0% win rate at 2.0R, cost 0.0000 R/trade -- not measured on this book

Win rate **40.00%** · reward:risk **2.00** · expectancy **+0.2000 R** · pool 20,000 trades.

Intended risk **1.00%** of balance per trade · instrument **mnq** · minimum ticket risk **$20.00** · 4,000 simulations per rung · at most 2,000 trades per path.

**Kelly fraction at this edge: +10.00%.** Risking 1.00% is below full Kelly.

| Rung | x | Reach | Null | **Lift** | Ruin | Timeout | Median trades | Median end | Forced risk |
|---|---|---|---|---|---|---|---|---|---|
| $1 to $10 | 10x | **IMPOSSIBLE** | — | — | — | — | — | — | 2000% |
| $10 to $100 | 10x | **IMPOSSIBLE** | — | — | — | — | — | — | 200% |
| $100 to $1,000 | 10x | 63.68% | 9.85% | **+53.83 pt** | 36.33% | 0.00% | 179 | $1,000.00 | 20.00% |
| $1,000 to $10,000 | 10x | 99.78% | 0.10% | **+99.67 pt** | 0.00% | 0.22% | 1,065 | $10,073.24 | 2.00% |
| $10,000 to $100,000 | 10x | 99.10% | 0.03% | **+99.08 pt** | 0.00% | 0.90% | 1,192 | $100,742.54 | 1.00% |

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
