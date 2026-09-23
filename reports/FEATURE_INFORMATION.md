# Feature Information Test

**101,516 resolved signals** · reward:risk 2.0:1 · base win rate **34.9%** against a 33.3% breakeven.

`spread` = win rate in the feature's top quintile minus its bottom quintile.
`shuffled` is the same computation against randomly permuted outcomes — the
largest shuffled spread across all features is **0.7 pt**, so anything
below that is indistinguishable from noise no matter how it ranks.

| Feature | Spread | Top Q win% | Bottom Q win% | n | Shuffled | Beats noise? |
|---|---|---|---|---|---|---|
| `cci` | +8.5 pt | 39.2% | 30.7% | 101,348 | -0.4 pt | **yes** |
| `ema_50` | -8.4 pt | 29.7% | 38.2% | 101,516 | +0.1 pt | **yes** |
| `ema_21` | -8.4 pt | 30.0% | 38.4% | 101,516 | -0.0 pt | **yes** |
| `ichimoku_senkou_a` | -8.4 pt | 29.9% | 38.3% | 100,717 | +0.3 pt | **yes** |
| `macd` | +8.3 pt | 37.6% | 29.3% | 101,516 | -0.1 pt | **yes** |
| `ichimoku_senkou_b` | -8.1 pt | 30.4% | 38.6% | 100,088 | +0.0 pt | **yes** |
| `ichimoku_kijun` | -8.1 pt | 29.8% | 37.9% | 101,359 | -0.3 pt | **yes** |
| `bb_middle` | -8.1 pt | 30.3% | 38.4% | 101,424 | +0.2 pt | **yes** |
| `plus_di` | +8.1 pt | 39.0% | 30.9% | 101,516 | -0.2 pt | **yes** |
| `macd_signal` | +7.9 pt | 37.4% | 29.4% | 101,516 | -0.1 pt | **yes** |
| `rsi` | +7.8 pt | 38.1% | 30.3% | 101,516 | +0.2 pt | **yes** |
| `stoch_k` | +7.6 pt | 37.5% | 29.9% | 101,481 | -0.6 pt | **yes** |
| `bb_upper` | -7.6 pt | 31.0% | 38.6% | 101,424 | +0.3 pt | **yes** |
| `stoch_d` | +7.5 pt | 37.3% | 29.8% | 101,448 | -0.5 pt | **yes** |
| `_dir` | +7.2 pt | 37.9% | 30.6% | 101,516 | +0.3 pt | **yes** |
| `ema_8` | -6.8 pt | 31.2% | 38.0% | 101,516 | +0.3 pt | **yes** |
| `williams_r` | +6.7 pt | 37.7% | 31.0% | 101,516 | +0.0 pt | **yes** |
| `minus_di` | -6.6 pt | 30.6% | 37.2% | 101,516 | -0.3 pt | **yes** |
| `ichimoku_tenkan` | -6.1 pt | 31.7% | 37.8% | 101,516 | +0.1 pt | **yes** |
| `bb_lower` | -5.7 pt | 31.8% | 37.5% | 101,424 | -0.2 pt | **yes** |

**30 of 34 features beat the shuffled control.**

## Reading this honestly

- A feature clearing the control has separated outcomes IN SAMPLE, on the same
  history everything else here was fitted to. It is a candidate to test, not an edge.
- The control is the largest spread random noise produced across the same feature
  set, which is the right bar precisely because 37 features were searched.
- Bars containing both stop and target are scored LOSSES; real results are never
  worse than shown.
