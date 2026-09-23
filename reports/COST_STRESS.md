# Execution-Cost Stress

Generated: 2026-09-19T15:34:13.261890+00:00

PHASE 11 of `reports/upgrade statergy.txt`. Each live strategy is re-priced at multiples of E26's assumed fill quality (0.1% commission + 0.05% slippage per side = **0.30% round trip** at 1.0x). Everything else is held fixed.

The number that matters is **breakeven multiple**: how much worse than assumed your fills can be before the strategy stops making money. A strategy that dies at 1.5x is not robust — a volatile open, a wide spread, or a partial fill can cost that much on a single trade.

## BTC-USD 1d — `dual_thrust`

Params: `{'lookback': 10, 'k1': 0.5, 'k2': 0.5}`

| Cost multiple | Round trip | Trades | Win% | Expectancy | IS Sharpe | Passed E26 |
|---|---|---|---|---|---|---|
| 0.0x | 0.00% | 88 | 55.7% | 10.020 | 0.92 | True |
| 0.5x | 0.15% | 88 | 54.5% | 9.966 | 0.91 | True |
| 1.0x | 0.30% | 88 | 53.4% | 9.912 | 0.89 | False |
| 1.5x | 0.45% | 88 | 53.4% | 9.858 | 0.88 | False |
| 2.0x | 0.60% | 88 | 53.4% | 9.804 | 0.87 | False |
| 3.0x | 0.90% | 88 | 51.1% | 9.696 | 0.84 | False |
| 5.0x | 1.50% | 88 | 50.0% | 9.480 | 0.78 | False |
| 10.0x | 3.00% | 88 | 48.9% | 8.939 | 0.64 | False |

**Breakeven at 10.0x** — the edge survives fills 10 times worse than assumed. That is real headroom, though it says nothing about whether the edge itself is real; this re-prices an in-sample result, it does not re-validate it.

## ETH-USD 1d — `mss_trend_hold`

Params: `{'hold_bars': 5, 'atr_mult': 1.0}`

| Cost multiple | Round trip | Trades | Win% | Expectancy | IS Sharpe | Passed E26 |
|---|---|---|---|---|---|---|
| 0.0x | 0.00% | 71 | 67.6% | 8.017 | 1.5 | True |
| 0.5x | 0.15% | 71 | 67.6% | 7.964 | 1.47 | True |
| 1.0x | 0.30% | 71 | 67.6% | 7.911 | 1.44 | True |
| 1.5x | 0.45% | 71 | 67.6% | 7.858 | 1.42 | True |
| 2.0x | 0.60% | 71 | 67.6% | 7.806 | 1.39 | True |
| 3.0x | 0.90% | 71 | 67.6% | 7.700 | 1.33 | True |
| 5.0x | 1.50% | 71 | 67.6% | 7.489 | 1.22 | True |
| 10.0x | 3.00% | 71 | 66.2% | 6.963 | 0.93 | False |

**Breakeven at 10.0x** — the edge survives fills 10 times worse than assumed. That is real headroom, though it says nothing about whether the edge itself is real; this re-prices an in-sample result, it does not re-validate it.

## What this does not establish

- This sweeps ONE axis on an ALREADY-SELECTED strategy. Surviving 5x cost is not validation — it is the same in-sample result, priced differently.
- Costs are modelled as a flat percentage. Real spreads widen exactly when these strategies want to trade (breakouts fire on volatility), so a flat multiple understates the correlation between bad fills and trade timing.
- Partial fills, latency and market impact are still not modelled anywhere in E26.
