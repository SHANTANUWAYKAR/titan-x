# Consensus Filter Test

29 instruments · 1d · **27 parameter variants** · reward:risk 2.0:1 · breakeven 33.3%.

Instead of taking the best parameterisation, require N of M to agree. The
question is not only whether the win rate rises — a filter that holds the win
rate while trading a tenth as often is already a large gain, because cost
scales with trade count.

| Agreement | Trades | vs base | Win% | Gross R | Net %/trade |
|---|---|---|---|---|---|
| 1/27 | 108,623 | 100% | 34.80% | +0.0440 | -0.0163% |
| 6/27 | 105,564 | 97% | 34.84% | +0.0452 | -0.0151% |
| 13/27 | 101,769 | 94% | 34.87% | +0.0460 | -0.0143% |
| 18/27 | 100,239 | 92% | 34.88% | +0.0464 | -0.0139% |
| 22/27 | 97,386 | 90% | 34.88% | +0.0465 | -0.0138% |
| 27/27 | 94,648 | 87% | 34.87% | +0.0460 | -0.0143% |

**Win rate monotone in strictness: yes.** A real consensus effect improves steadily as agreement tightens; a
single spiking cell in a scanned grid is selection, not signal.

## Reading this

- Net uses the measured median notional (0.201x equity) and E26's 0.30%
  round-trip assumption. Cost per trade is constant here; only the trade
  COUNT changes, which is the entire point.
- In-sample, on the decade everything else was fitted to.
- Bars containing both stop and target are scored LOSSES.
