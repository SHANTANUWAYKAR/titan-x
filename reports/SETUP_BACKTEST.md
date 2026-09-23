# Titan Setup — Walk-Forward Backtest

**26 asset/timeframe pairs** · 6 anchored folds on the POOLED panel · meta filter ON (p >= 0.5).

Pooled out-of-sample: **2,306 trades · win 36.08% · net -0.1503%/trade · WFE -0.14**

Per-fold net: [-0.1757, -0.0065, -0.3318, -0.1087, 0.1363, -0.1038]

The skip filter is refit inside every fold on data strictly before that fold.
`WFE` is out-of-sample net divided by in-sample net — above ~0.5 means the
setup kept more than half its in-sample edge when it met new data.

| Asset | TF | Folds | Trades | Win% | Net %/trade | WFE |
|---|---|---|---|---|---|---|
| CRUDE | 1d | 6 | 3 | 66.7% | **+0.9255%** | -0.14 |
| NVDA | 1d | 6 | 22 | 59.1% | **+0.6973%** | -0.14 |
| AMZN | 1d | 6 | 13 | 53.8% | **+0.4531%** | -0.14 |
| TSLA | 1d | 6 | 18 | 50.0% | **+0.4358%** | -0.14 |
| BTCUSD | 1d | 6 | 55 | 49.1% | **+0.3735%** | -0.14 |
| ETHUSD | 1d | 6 | 33 | 48.5% | **+0.3722%** | -0.14 |
| SBIN | 1d | 6 | 61 | 44.3% | **+0.2212%** | -0.14 |
| JPM | 1d | 6 | 9 | 44.4% | **+0.1757%** | -0.14 |
| HDFCBANK | 1d | 6 | 18 | 44.4% | **+0.1669%** | -0.14 |
| GOOGL | 1d | 6 | 61 | 42.6% | **+0.1120%** | -0.14 |
| AAPL | 1d | 6 | 214 | 41.1% | **+0.0956%** | -0.14 |
| BANKNIFTY | 1d | 6 | 63 | 41.3% | **+0.0825%** | -0.14 |
| ICICIBANK | 1d | 6 | 88 | 38.6% | **+0.0463%** | -0.14 |
| RELIANCE | 1d | 6 | 232 | 37.1% | -0.0096% | -0.14 |
| TCS | 1d | 6 | 279 | 33.7% | -0.1007% | -0.14 |
| INFY | 1d | 6 | 87 | 34.5% | -0.1068% | -0.14 |
| BHARTIARTL | 1d | 6 | 9 | 33.3% | -0.1095% | -0.14 |
| ITC | 1d | 6 | 18 | 33.3% | -0.1726% | -0.14 |
| META | 1d | 6 | 66 | 30.3% | -0.1863% | -0.14 |
| SILVER | 1d | 6 | 33 | 36.4% | -0.1920% | -0.14 |
| GOLD | 1d | 6 | 142 | 35.2% | -0.2144% | -0.14 |
| MSFT | 1d | 6 | 67 | 29.9% | -0.2678% | -0.14 |
| NIFTY50 | 1d | 6 | 40 | 32.5% | -0.3057% | -0.14 |
| USDJPY | 1d | 6 | 575 | 31.3% | -0.4443% | -0.14 |
| US10Y | 1d | 6 | 98 | 31.6% | -0.8698% | -0.14 |
| SP500 | 1d | 6 | 2 | 0.0% | -1.1348% | -0.14 |

**13 of 26 pairs net-positive** · 2,306 out-of-sample trades · trade-weighted net **-0.1503%/trade**.

## Reading this

- Every number is out-of-sample by construction: each fold is scored by a
  filter that never saw it.
- A pair that is positive on one fold and negative on five is noise. Check
  `per_fold_net` in the JSON before trusting any single row.
- Signals whose time barrier expires unresolved are excluded from the win
  rate. That exclusion silently flattered an earlier result in this audit.
- Costs are E26's 0.30% round trip on the notional risk-sizing actually
  deploys. Real spreads widen exactly when these signals fire.
