# Instrument Research Profiles (PHASE 3)

Generated: 2026-09-15T07:15:18.465649+00:00 · 116 (instrument, timeframe) profiles

Per `reports/statergy.txt` PHASE 3. `suitable_families` are **hypotheses for the search to test**, not validated edges — nothing here promotes a strategy or substitutes for E26 validation and the Stage 0 null.

**cost/ATR** = one round trip's modelled cost (0.30% at E26 defaults) ÷ median bar range. At ≥1.0 the average bar cannot pay for the trade — a property of the instrument and timeframe, not of any strategy.

| Instrument | TF | Bars | Hurst | Character | Vol% | Bar range% | cost/ATR | Cost verdict | Top family prior |
|---|---|---|---|---|---|---|---|---|---|
| EURUSD | 15m | 5000 | 0.5361 | indistinguishable from random walk | 6.07 | 0.0328 | 9.146 | prohibitive | none_indicated (0.0) |
| EURUSD | 1h | 5000 | 0.5457 | indistinguishable from random walk | 6.86 | 0.0848 | 3.538 | prohibitive | none_indicated (0.0) |
| EURUSD | 4h | 5000 | 0.5591 | trending | 7.79 | 0.2057 | 1.458 | prohibitive | none_indicated (0.0) |
| EURUSD | 1d | 2625 | 0.5753 | trending | 7.13 | 0.7142 | 0.42 | workable | trend_pullback (0.6) |
| GBPUSD | 15m | 5000 | 0.5395 | indistinguishable from random walk | 6.23 | 0.0343 | 8.746 | prohibitive | none_indicated (0.0) |
| GBPUSD | 1h | 5000 | 0.5374 | indistinguishable from random walk | 7.73 | 0.0972 | 3.086 | prohibitive | none_indicated (0.0) |
| GBPUSD | 4h | 5000 | 0.5657 | trending | 8.06 | 0.2241 | 1.339 | prohibitive | none_indicated (0.0) |
| GBPUSD | 1d | 2626 | 0.5736 | trending | 8.62 | 0.8221 | 0.365 | workable | trend_pullback (0.6) |
| USDJPY | 15m | 5000 | 0.5911 | trending | 10.52 | 0.0461 | 6.508 | prohibitive | volatility_breakout (0.209) |
| USDJPY | 1h | 5000 | 0.5621 | trending | 9.11 | 0.1149 | 2.611 | prohibitive | none_indicated (0.0) |
| USDJPY | 4h | 5000 | 0.5556 | trending | 10.87 | 0.2893 | 1.037 | prohibitive | none_indicated (0.0) |
| USDJPY | 1d | 5000 | 0.5772 | trending | 8.28 | 0.7152 | 0.419 | workable | trend_pullback (0.6) |
| USDINR | 15m | 3810 | 0.5588 | trending | 9.54 | 0.0419 | 7.16 | prohibitive | none_indicated (0.0) |
| USDINR | 1h | 5000 | 0.5449 | indistinguishable from random walk | 7.3 | 0.071 | 4.225 | prohibitive | none_indicated (0.0) |
| USDINR | 4h | 4512 | 0.5225 | indistinguishable from random walk | 4.89 | 0.1074 | 2.793 | prohibitive | none_indicated (0.0) |
| USDINR | 1d | 2627 | 0.5351 | indistinguishable from random walk | 6.03 | 0.5836 | 0.514 | severe | volatility_breakout (0.41) |
| BTCUSD | 15m | 5000 | 0.5659 | trending | 34.66 | 0.1974 | 1.52 | prohibitive | none_indicated (0.0) |
| BTCUSD | 1h | 5000 | 0.5582 | trending | 41.54 | 0.5414 | 0.554 | severe | volatility_breakout (0.376) |
| BTCUSD | 4h | 5000 | 0.5749 | trending | 45.42 | 1.1908 | 0.252 | workable | trend_pullback (0.6) |
| BTCUSD | 1d | 4381 | 0.5907 | trending | 54.97 | 3.7363 | 0.08 | workable | volatility_breakout (0.613) |
| ETHUSD | 15m | 5000 | 0.5491 | indistinguishable from random walk | 47.97 | 0.2634 | 1.139 | prohibitive | none_indicated (0.0) |
| ETHUSD | 1h | 5000 | 0.5514 | trending | 54.96 | 0.6978 | 0.43 | workable | volatility_breakout (0.607) |
| ETHUSD | 4h | 5000 | 0.5782 | trending | 65.68 | 1.7611 | 0.17 | workable | trend_pullback (0.6) |
| ETHUSD | 1d | 3674 | 0.6009 | trending | 75.34 | 5.1862 | 0.058 | workable | volatility_breakout (0.607) |
| GOLD | 15m | 5000 | 0.4759 | indistinguishable from random walk | 68.22 | 0.2344 | 1.28 | prohibitive | volatility_breakout (0.206) |
| GOLD | 1h | 5000 | 0.5445 | indistinguishable from random walk | 36.66 | 0.4561 | 0.658 | severe | volatility_breakout (0.367) |
| GOLD | 4h | 3716 | 0.5475 | indistinguishable from random walk | 26.23 | 0.6818 | 0.44 | workable | volatility_breakout (0.62) |
| GOLD | 1d | 5000 | 0.5477 | indistinguishable from random walk | 19.6 | 1.1964 | 0.251 | workable | trend_pullback (0.6) |
| SILVER | 15m | 5000 | 0.5276 | indistinguishable from random walk | 63.22 | 0.3948 | 0.76 | severe | volatility_breakout (0.383) |
| SILVER | 1h | 5000 | 0.5576 | trending | 83.64 | 0.9595 | 0.313 | workable | volatility_breakout (0.649) |
| SILVER | 4h | 3716 | 0.562 | trending | 53.83 | 1.2578 | 0.239 | workable | volatility_breakout (0.635) |
| SILVER | 1d | 2529 | 0.5437 | indistinguishable from random walk | 34.51 | 1.7368 | 0.173 | workable | trend_pullback (0.6) |
| CRUDE | 15m | 5000 | 0.5545 | trending | 61.45 | 0.4132 | 0.726 | severe | trend_pullback (0.36) |
| CRUDE | 1h | 5000 | 0.5447 | indistinguishable from random walk | 77.87 | 0.814 | 0.369 | workable | trend_pullback (0.6) |
| CRUDE | 4h | 3789 | 0.545 | indistinguishable from random walk | 53.38 | 1.0814 | 0.277 | workable | volatility_breakout (0.658) |
| CRUDE | 1d | 2528 | 0.5436 | indistinguishable from random walk | 114.4 | 3.1032 | 0.097 | workable | volatility_breakout (0.799) |
| NIFTY50 | 15m | 2425 | 0.5436 | indistinguishable from random walk | 27.56 | 0.1502 | 1.997 | prohibitive | none_indicated (0.0) |
| NIFTY50 | 1h | 5000 | 0.5773 | trending | 28.77 | 0.3153 | 0.951 | severe | trend_pullback (0.36) |
| NIFTY50 | 4h | 2292 | 0.5717 | trending | 21.51 | 0.5155 | 0.582 | severe | trend_pullback (0.36) |
| NIFTY50 | 1d | 5000 | 0.5702 | trending | 14.77 | 1.1558 | 0.26 | workable | trend_pullback (0.6) |
| BANKNIFTY | 15m | 1850 | 0.5519 | trending | 31.52 | 0.1805 | 1.662 | prohibitive | none_indicated (0.0) |
| BANKNIFTY | 1h | 5000 | 0.5629 | trending | 34.51 | 0.3877 | 0.774 | severe | trend_pullback (0.36) |
| BANKNIFTY | 4h | 2217 | 0.5643 | trending | 26.37 | 0.6464 | 0.464 | workable | trend_pullback (0.6) |
| BANKNIFTY | 1d | 5000 | 0.5718 | trending | 20.38 | 1.5732 | 0.191 | workable | trend_pullback (0.6) |
| US10Y | 15m | 5000 | 0.5375 | indistinguishable from random walk | 5.7 | 0.0381 | 7.874 | prohibitive | none_indicated (0.0) |
| US10Y | 1h | 5000 | 0.5341 | indistinguishable from random walk | 5.47 | 0.0813 | 3.69 | prohibitive | none_indicated (0.0) |
| US10Y | 4h | 3795 | 0.5489 | indistinguishable from random walk | 6.35 | 0.1718 | 1.746 | prohibitive | none_indicated (0.0) |
| US10Y | 1d | 2528 | 0.5561 | trending | 5.44 | 0.4444 | 0.675 | severe | trend_pullback (0.36) |
| SP500 | 15m | 5000 | 0.5417 | indistinguishable from random walk | 14.11 | 0.0877 | 3.421 | prohibitive | none_indicated (0.0) |
| SP500 | 1h | 5000 | 0.5355 | indistinguishable from random walk | 18.23 | 0.2233 | 1.343 | prohibitive | none_indicated (0.0) |
| SP500 | 4h | 3820 | 0.5486 | indistinguishable from random walk | 19.69 | 0.4247 | 0.706 | severe | volatility_breakout (0.371) |
| SP500 | 1d | 1857 | 0.5585 | trending | 19.59 | 1.3349 | 0.225 | workable | volatility_breakout (0.745) |
| AAPL | 15m | 5000 | 0.5607 | trending | 65.71 | 0.3566 | 0.841 | severe | trend_pullback (0.36) |
| AAPL | 1h | 5000 | 0.5542 | trending | 51.11 | 0.7128 | 0.421 | workable | trend_pullback (0.6) |
| AAPL | 4h | 2976 | 0.5589 | trending | 93.37 | 1.3841 | 0.217 | workable | trend_pullback (0.6) |
| AAPL | 1d | 5000 | 0.5678 | trending | 31.21 | 2.1609 | 0.139 | workable | volatility_breakout (0.635) |
| MSFT | 15m | 5000 | 0.587 | trending | 80.85 | 0.3679 | 0.815 | severe | trend_pullback (0.36) |
| MSFT | 1h | 5000 | 0.5472 | indistinguishable from random walk | 55.21 | 0.6587 | 0.455 | workable | trend_pullback (0.6) |
| MSFT | 4h | 1736 | 0.574 | trending | 52.56 | 1.0998 | 0.273 | workable | trend_pullback (0.6) |
| MSFT | 1d | 3784 | 0.5131 | indistinguishable from random walk | 26.45 | 1.8987 | 0.158 | workable | volatility_breakout (0.619) |
| NVDA | 15m | 5000 | 0.5527 | trending | 91.2 | 0.5137 | 0.584 | severe | trend_pullback (0.36) |
| NVDA | 1h | 5000 | 0.527 | indistinguishable from random walk | 74.84 | 1.0588 | 0.283 | workable | trend_pullback (0.6) |
| NVDA | 4h | 2658 | 0.4976 | indistinguishable from random walk | 4560.87 | 2.6234 | 0.114 | workable | mean_reversion (0.7) |
| NVDA | 1d | 2527 | 0.5614 | trending | 49.99 | 3.5084 | 0.086 | workable | trend_pullback (0.6) |
| GOOGL | 15m | 3328 | 0.5495 | indistinguishable from random walk | 1139.73 | 0.4615 | 0.65 | severe | trend_pullback (0.36) |
| GOOGL | 1h | 5000 | 0.5719 | trending | 70.07 | 0.7589 | 0.395 | workable | trend_pullback (0.6) |
| GOOGL | 4h | 1866 | 0.5773 | trending | 133.5 | 1.4772 | 0.203 | workable | mean_reversion (0.7) |
| GOOGL | 1d | 3784 | 0.5213 | indistinguishable from random walk | 27.77 | 2.0883 | 0.144 | workable | trend_pullback (0.6) |
| AMZN | 15m | 5000 | 0.5483 | indistinguishable from random walk | 274.94 | 0.4226 | 0.71 | severe | trend_pullback (0.36) |
| AMZN | 1h | 5000 | 0.5525 | trending | 70.0 | 0.8062 | 0.372 | workable | trend_pullback (0.6) |
| AMZN | 4h | 1903 | 0.565 | trending | 142.31 | 1.4566 | 0.206 | workable | trend_pullback (0.6) |
| AMZN | 1d | 2527 | 0.5421 | indistinguishable from random walk | 33.05 | 2.3638 | 0.127 | workable | trend_pullback (0.6) |
| TSLA | 15m | 5000 | 0.5569 | trending | 105.22 | 0.5925 | 0.506 | severe | trend_pullback (0.36) |
| TSLA | 1h | 5000 | 0.5498 | indistinguishable from random walk | 95.58 | 1.335 | 0.225 | workable | trend_pullback (0.6) |
| TSLA | 4h | 2387 | 0.5594 | trending | 206.22 | 2.9458 | 0.102 | workable | mean_reversion (0.7) |
| TSLA | 1d | 2527 | 0.5639 | trending | 59.45 | 4.3002 | 0.07 | workable | trend_pullback (0.6) |
| META | 15m | 5000 | 0.5742 | trending | 138.95 | 0.4739 | 0.633 | severe | trend_pullback (0.36) |
| META | 1h | 5000 | 0.5615 | trending | 73.55 | 0.8785 | 0.341 | workable | trend_pullback (0.6) |
| META | 4h | 1735 | 0.5666 | trending | 73.72 | 1.5734 | 0.191 | workable | trend_pullback (0.6) |
| META | 1d | 3599 | 0.551 | trending | 39.85 | 2.7687 | 0.108 | workable | trend_pullback (0.6) |
| JPM | 15m | 1924 | 0.5207 | indistinguishable from random walk | 47.92 | 0.3192 | 0.94 | severe | trend_pullback (0.36) |
| JPM | 1h | 5000 | 0.5469 | indistinguishable from random walk | 53.42 | 0.5971 | 0.502 | severe | trend_pullback (0.36) |
| JPM | 4h | 1735 | 0.5525 | trending | 46.18 | 1.1558 | 0.26 | workable | trend_pullback (0.6) |
| JPM | 1d | 2527 | 0.5452 | indistinguishable from random walk | 27.28 | 1.8762 | 0.16 | workable | volatility_breakout (0.751) |
| RELIANCE | 15m | 1846 | 0.5745 | trending | 43.28 | 0.2587 | 1.16 | prohibitive | none_indicated (0.0) |
| RELIANCE | 1h | 5000 | 0.561 | trending | 44.31 | 0.5613 | 0.534 | severe | trend_pullback (0.36) |
| RELIANCE | 4h | 2216 | 0.5704 | trending | 33.67 | 0.9181 | 0.327 | workable | trend_pullback (0.6) |
| RELIANCE | 1d | 5000 | 0.5326 | indistinguishable from random walk | 24.3 | 2.1507 | 0.139 | workable | trend_pullback (0.6) |
| TCS | 15m | 1840 | 0.5701 | trending | 77.0 | 0.3611 | 0.831 | severe | trend_pullback (0.36) |
| TCS | 1h | 5000 | 0.5698 | trending | 51.67 | 0.6096 | 0.492 | workable | trend_pullback (0.6) |
| TCS | 4h | 2215 | 0.5674 | trending | 39.34 | 1.0101 | 0.297 | workable | trend_pullback (0.6) |
| TCS | 1d | 5000 | 0.5442 | indistinguishable from random walk | 22.48 | 2.1148 | 0.142 | workable | trend_pullback (0.6) |
| HDFCBANK | 15m | 1848 | 0.5401 | indistinguishable from random walk | 49.24 | 0.2627 | 1.142 | prohibitive | none_indicated (0.0) |
| HDFCBANK | 1h | 5000 | 0.5699 | trending | 43.91 | 0.5302 | 0.566 | severe | trend_pullback (0.36) |
| HDFCBANK | 4h | 2215 | 0.5797 | trending | 33.12 | 0.8695 | 0.345 | workable | trend_pullback (0.6) |
| HDFCBANK | 1d | 2488 | 0.5477 | indistinguishable from random walk | 22.96 | 1.7087 | 0.176 | workable | volatility_breakout (0.62) |
| INFY | 15m | 1846 | 0.586 | trending | 83.4 | 0.384 | 0.781 | severe | trend_pullback (0.36) |
| INFY | 1h | 5000 | 0.5644 | trending | 59.84 | 0.6674 | 0.45 | workable | trend_pullback (0.6) |
| INFY | 4h | 2215 | 0.5736 | trending | 44.93 | 1.1053 | 0.271 | workable | trend_pullback (0.6) |
| INFY | 1d | 4312 | 0.541 | indistinguishable from random walk | 25.59 | 2.1179 | 0.142 | workable | trend_pullback (0.6) |
| ICICIBANK | 15m | 1844 | 0.5557 | trending | 41.18 | 0.2687 | 1.116 | prohibitive | none_indicated (0.0) |
| ICICIBANK | 1h | 5000 | 0.5392 | indistinguishable from random walk | 43.92 | 0.57 | 0.526 | severe | trend_pullback (0.36) |
| ICICIBANK | 4h | 2215 | 0.5425 | indistinguishable from random walk | 33.15 | 0.9272 | 0.324 | workable | trend_pullback (0.6) |
| ICICIBANK | 1d | 4312 | 0.532 | indistinguishable from random walk | 28.51 | 2.375 | 0.126 | workable | trend_pullback (0.6) |
| SBIN | 15m | 1847 | 0.5677 | trending | 47.0 | 0.2989 | 1.004 | prohibitive | none_indicated (0.0) |
| SBIN | 1h | 5000 | 0.5655 | trending | 52.54 | 0.6243 | 0.481 | workable | trend_pullback (0.6) |
| SBIN | 4h | 2215 | 0.5639 | trending | 40.63 | 1.0129 | 0.296 | workable | trend_pullback (0.6) |
| SBIN | 1d | 4312 | 0.5467 | indistinguishable from random walk | 30.09 | 2.5404 | 0.118 | workable | trend_pullback (0.6) |
| BHARTIARTL | 15m | 1842 | 0.5646 | trending | 45.71 | 0.2766 | 1.085 | prohibitive | none_indicated (0.0) |
| BHARTIARTL | 1h | 5000 | 0.5393 | indistinguishable from random walk | 47.22 | 0.6359 | 0.472 | workable | trend_pullback (0.6) |
| BHARTIARTL | 4h | 2216 | 0.5267 | indistinguishable from random walk | 35.9 | 1.0406 | 0.288 | workable | trend_pullback (0.6) |
| BHARTIARTL | 1d | 2488 | 0.5489 | indistinguishable from random walk | 28.81 | 2.5308 | 0.119 | workable | trend_pullback (0.6) |
| ITC | 15m | 1846 | 0.5283 | indistinguishable from random walk | 39.53 | 0.2408 | 1.246 | prohibitive | none_indicated (0.0) |
| ITC | 1h | 5000 | 0.5735 | trending | 43.48 | 0.5315 | 0.564 | severe | trend_pullback (0.36) |
| ITC | 4h | 2215 | 0.5751 | trending | 32.95 | 0.8843 | 0.339 | workable | trend_pullback (0.6) |
| ITC | 1d | 2488 | 0.582 | trending | 23.73 | 1.9071 | 0.157 | workable | trend_pullback (0.6) |

## Cost-hurdle summary

- **prohibitive** (costs ≥ median bar range): 28 of 116
- **severe** (costs ≥ 50% of median bar range): 25
- **workable**: 63

Prohibitive combinations — trading these at this timeframe is arithmetically unattractive before any signal is considered:

- `EURUSD 15m` — cost/ATR 9.146
- `EURUSD 1h` — cost/ATR 3.538
- `EURUSD 4h` — cost/ATR 1.458
- `GBPUSD 15m` — cost/ATR 8.746
- `GBPUSD 1h` — cost/ATR 3.086
- `GBPUSD 4h` — cost/ATR 1.339
- `USDJPY 15m` — cost/ATR 6.508
- `USDJPY 1h` — cost/ATR 2.611
- `USDJPY 4h` — cost/ATR 1.037
- `USDINR 15m` — cost/ATR 7.16
- `USDINR 1h` — cost/ATR 4.225
- `USDINR 4h` — cost/ATR 2.793
- `BTCUSD 15m` — cost/ATR 1.52
- `ETHUSD 15m` — cost/ATR 1.139
- `GOLD 15m` — cost/ATR 1.28
- `NIFTY50 15m` — cost/ATR 1.997
- `BANKNIFTY 15m` — cost/ATR 1.662
- `US10Y 15m` — cost/ATR 7.874
- `US10Y 1h` — cost/ATR 3.69
- `US10Y 4h` — cost/ATR 1.746
- `SP500 15m` — cost/ATR 3.421
- `SP500 1h` — cost/ATR 1.343
- `RELIANCE 15m` — cost/ATR 1.16
- `HDFCBANK 15m` — cost/ATR 1.142
- `ICICIBANK 15m` — cost/ATR 1.116
- `SBIN 15m` — cost/ATR 1.004
- `BHARTIARTL 15m` — cost/ATR 1.085
- `ITC 15m` — cost/ATR 1.246
