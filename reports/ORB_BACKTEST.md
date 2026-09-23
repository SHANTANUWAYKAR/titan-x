# 15-Minute ORB — Backtest

18 assets · 15m · NY session 13:30-20:00 UTC · opening range 15 min · reward:risk 2.0:1 · breakeven 33.3% · VWAP filter ON.

**Pooled: 45,764 trades · win 31.44% · net -0.8605%/trade**

With the VWAP filter OFF: 46,024 trades · win 31.41% · net -0.8615%. The filter removes 1% of signals and moves the win rate +0.02 pt.

## Year by year

The cut that killed five previous leads. A setup that only works in some years
is regime exposure, not edge.

| Year | Trades | Win% | Net %/trade |
|---|---|---|---|
| 2003 | 841 | 29.0% | -0.9884% |
| 2004 | 1,314 | 30.7% | -0.9426% |
| 2005 | 1,346 | 27.0% | -1.0659% |
| 2006 | 1,398 | 32.7% | -0.8385% |
| 2007 | 1,365 | 28.6% | -0.9815% |
| 2008 | 1,469 | 32.8% | -0.7865% |
| 2009 | 1,475 | 31.8% | -0.8519% |
| 2010 | 1,478 | 29.4% | -0.9470% |
| 2011 | 1,681 | 32.2% | -0.8573% |
| 2012 | 1,642 | 30.0% | -0.9755% |
| 2013 | 1,627 | 31.9% | -0.9172% |
| 2014 | 1,564 | 29.5% | -1.0044% |
| 2015 | 1,570 | 32.5% | -0.9136% |
| 2016 | 1,620 | 32.2% | -0.9180% |
| 2017 | 1,838 | 30.1% | -0.9404% |
| 2018 | 2,252 | 31.6% | -0.8444% |
| 2019 | 2,196 | 30.4% | -0.8915% |
| 2020 | 2,588 | 30.8% | -0.8252% |
| 2021 | 2,590 | 31.5% | -0.7866% |
| 2022 | 2,852 | 31.9% | -0.7574% |
| 2023 | 2,791 | 33.4% | -0.8112% |
| 2024 | 2,764 | 33.6% | -0.7566% |
| 2025 | 2,855 | 32.8% | -0.7731% |
| 2026 | 2,648 | 31.9% | -0.7703% |

**0 of 24 years net-positive.**

## By asset

| Asset | Trades | Win% | Net %/trade |
|---|---|---|---|
| TSLA | 447 | 34.5% | -0.3759% |
| NVDA | 616 | 35.2% | -0.4314% |
| CRUDE | 77 | 37.7% | -0.4586% |
| ETHUSD | 3,229 | 34.6% | -0.4903% |
| GOOGL | 96 | 35.4% | -0.5525% |
| AMZN | 158 | 34.2% | -0.5767% |
| BTCUSD | 4,102 | 32.6% | -0.6598% |
| AAPL | 637 | 35.3% | -0.6599% |
| USDINR | 17 | 41.2% | -0.6647% |
| META | 127 | 30.7% | -0.6666% |
| MSFT | 177 | 32.8% | -0.7717% |
| SILVER | 5,479 | 29.1% | -0.8356% |
| EURUSD | 7,574 | 33.0% | -0.9109% |
| GBPUSD | 7,718 | 32.3% | -0.9286% |
| SP500 | 76 | 31.6% | -0.9431% |
| USDJPY | 7,302 | 31.0% | -0.9688% |
| US10Y | 59 | 30.5% | -0.9847% |
| GOLD | 7,873 | 28.2% | -1.0129% |

## Reading this

- ORB levels are fixed once the opening window closes; VWAP is cumulative to
  date; the volume profile used is the PREVIOUS session's. All causal.
- Entry is the next bar's open, never the close that revealed the break.
- Bars containing both stop and target are scored LOSSES.
- A 24-hour instrument has no natural open, so the NY session is imposed. Read
  those rows as 'does the NY open matter here', not as a true opening range.
- Delta and liquidity-heatmap confluence are NOT included: neither can be
  computed from OHLCV bars, and approximating them would invent a signal.
