# Edge Lift — how much of the pass rate is earned

Risk per trade **0.5%** · 4000 simulations · 8% profit target, 10% max total drawdown, 5% max daily.

`null` is the SAME strategy with its expectancy forced to zero and its win rate
and R:R kept intact. `lift` is the difference — the only part the edge earned.
A high pass rate with a low lift means the challenge rules were generous, not
that the strategy was good.

| Strategy | Instrument | TF | Trades | Win% | R:R | Pass% | Null% | **Lift** |
|---|---|---|---|---|---|---|---|---|
| `mss_trend_hold` | GOLD | 4h | 65 | 59.7 | 1.44 | 100.0 | 42.6 | **+57.4 pt** |
| `mss_trend_hold` | GOLD | 1h | 141 | 49.6 | 1.61 | 99.9 | 43.1 | **+56.7 pt** |
| `mss_trend_hold` | ETHUSD | 1d | 64 | 67.6 | 2.76 | 83.5 | 31.3 | **+52.2 pt** |
| `mss_trend_hold` | CRUDE | 1h | 250 | 52.9 | 1.17 | 91.7 | 46.2 | **+45.5 pt** |
| `strategy_little_rizzy_trend_bos` | MSFT | 1h | 83 | 65.7 | 0.66 | 68.1 | 43.3 | **+24.9 pt** |
| `dual_thrust` | META | 1h | 110 | 46.2 | 1.76 | 62.3 | 38.4 | **+23.9 pt** |
| `strategy_tradewithsunil_opening_candle_reversal` | SILVER | 4h | 839 | 38.9 | 1.68 | 59.6 | 44.3 | **+15.2 pt** |
| `mss_trend_filtered` | GBPUSD | 4h | 73 | 44.1 | 1.03 | 0.4 | 12.2 | **-11.9 pt** |
| `strategy_btc_eth_relative_rotation__eth_leg` | EURUSD | 4h | 93 | 31.6 | 1.03 | 0.0 | 40.6 | **-40.6 pt** |

## What this does not establish

- Trades are resampled i.i.d., so losing streaks never cluster the way a real
  regime makes them. Every pass rate here is an **upper bound**.
- Passing a challenge is not the same as being profitable. The two objectives
  differ, and a strategy can be optimised for one at the other's expense.
- The pool cannot invent variety it does not contain; a thin trade count makes
  every figure in its row correspondingly thin.
