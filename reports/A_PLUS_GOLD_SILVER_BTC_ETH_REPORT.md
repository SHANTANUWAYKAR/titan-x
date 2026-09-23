# A+ Strategies -- GOLD, SILVER, BTCUSD, ETHUSD

Generated: 2026-09-12T15:18:01.823458+00:00

**Bar used:** Stage 0 timeframe-aware selection-score floor (`engines/e26_backtesting/engine.py::STAGE0_TIMEFRAME_THRESHOLDS`) -- measured as the 95th percentile of the best score a 200+ candidate grid manufactures from pure-noise (no-edge) synthetic data at that timeframe. See `docs/STAGE0_FINDINGS.md`. This is a materially stricter bar than "positive Sharpe" -- most candidates that look good on IS Sharpe alone do NOT clear it.

| Asset | TF | Candidates | Passed Stage0 | Best strategy | IS Sharpe | OOS Sharpe | Trades | Win% | AvgWinR | AvgLossR | PF | Promoted |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| GOLD | 1h | 214 | 7 | mss_trend_hold{'hold_bars': 15, 'atr_mult': 1.5} | 2.844 | 3.563 | 139 | 56.1% | 0.864 | -0.536 | 2.06 | YES |
| GOLD | 4h | 214 | 1 | mss_trend_hold{'hold_bars': 5, 'atr_mult': 1.0} | 2.549 | 3.41 | 66 | 63.6% | 0.803 | -0.511 | 2.749 | YES |
| GOLD | 1d | 214 | 0 | *none cleared Stage 0* | -- | -- | -- | -- | -- | -- | -- | no |
| SILVER | 1h | 214 | 0 | *none cleared Stage 0* | -- | -- | -- | -- | -- | -- | -- | no |
| SILVER | 4h | 214 | 0 | *none cleared Stage 0* | -- | -- | -- | -- | -- | -- | -- | no |
| SILVER | 1d | 214 | 0 | *none cleared Stage 0* | -- | -- | -- | -- | -- | -- | -- | no |
| BTCUSD | 1h | 214 | 0 | *none cleared Stage 0* | -- | -- | -- | -- | -- | -- | -- | no |
| BTCUSD | 4h | 214 | 0 | *none cleared Stage 0* | -- | -- | -- | -- | -- | -- | -- | no |
| BTCUSD | 1d | 214 | 10 | dual_thrust{'lookback': 10, 'k1': 0.5, 'k2': 0.5} | 0.876 | 0.893 | 79 | 51.9% | 26.034 | -8.446 | 3.326 | YES |
| ETHUSD | 1h | 214 | 0 | *none cleared Stage 0* | -- | -- | -- | -- | -- | -- | -- | no |
| ETHUSD | 4h | 214 | 0 | *none cleared Stage 0* | -- | -- | -- | -- | -- | -- | -- | no |
| ETHUSD | 1d | 214 | 4 | mss_trend_hold{'hold_bars': 5, 'atr_mult': 1.0} | 1.118 | 1.083 | 64 | 62.5% | 10.776 | -5.059 | 3.55 | YES |

**4 of 12 (asset, timeframe) combos produced a live-promotable A+ strategy.**

A zero-pass row is a real, honest result -- it means the grid found nothing at that timeframe that beats what pure noise already produces 95% of the time, not a bug.