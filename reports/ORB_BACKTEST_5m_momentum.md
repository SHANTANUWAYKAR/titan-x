# 5-Minute ORB — Backtest (momentum entry)

19 assets · 5m · NY session 13:30-20:00 UTC · opening range 5 min · entry **momentum** · reward:risk 2.0:1 · breakeven 33.3% · VWAP filter OFF.

**Pooled: 59,623 trades · win 32.22% · net -0.8748%/trade**

## Year by year

The cut that killed five previous leads. A setup that only works in some years
is regime exposure, not edge.

| Year | Trades | Win% | Net %/trade |
|---|---|---|---|
| 2003 | 1,166 | 26.3% | -1.0525% |
| 2004 | 1,790 | 28.6% | -0.9866% |
| 2005 | 1,801 | 28.5% | -0.9993% |
| 2006 | 1,886 | 31.1% | -0.8882% |
| 2007 | 1,874 | 29.3% | -0.9456% |
| 2008 | 1,983 | 33.4% | -0.7765% |
| 2009 | 1,985 | 30.6% | -0.8850% |
| 2010 | 2,021 | 31.8% | -0.8736% |
| 2011 | 2,147 | 33.3% | -0.8749% |
| 2012 | 2,104 | 31.8% | -0.9410% |
| 2013 | 2,081 | 34.0% | -0.8715% |
| 2014 | 2,066 | 31.8% | -0.9432% |
| 2015 | 2,044 | 33.5% | -0.8911% |
| 2016 | 2,088 | 30.7% | -0.9743% |
| 2017 | 2,370 | 31.6% | -0.9131% |
| 2018 | 2,897 | 33.5% | -0.8315% |
| 2019 | 2,853 | 33.8% | -0.8264% |
| 2020 | 3,286 | 34.2% | -0.7925% |
| 2021 | 3,371 | 33.3% | -0.8139% |
| 2022 | 3,682 | 33.7% | -0.7855% |
| 2023 | 3,600 | 32.6% | -0.8856% |
| 2024 | 3,642 | 32.2% | -0.8734% |
| 2025 | 3,680 | 33.3% | -0.8349% |
| 2026 | 3,206 | 31.7% | -0.8630% |

**0 of 24 years net-positive.**

## By asset

| Asset | Trades | Win% | Net %/trade |
|---|---|---|---|
| TSLA | 591 | 31.5% | -0.6150% |
| NVDA | 822 | 33.0% | -0.6441% |
| ETHUSD | 4,100 | 34.9% | -0.6535% |
| GOOGL | 114 | 34.2% | -0.7067% |
| AAPL | 875 | 35.9% | -0.7351% |
| BTCUSD | 5,134 | 34.1% | -0.7509% |
| CRUDE | 77 | 33.8% | -0.7529% |
| SILVER | 7,683 | 29.6% | -0.8505% |
| US10Y | 73 | 34.2% | -0.8726% |
| META | 175 | 27.4% | -0.9074% |
| MSFT | 246 | 30.9% | -0.9149% |
| EURUSD | 9,707 | 32.8% | -0.9157% |
| GOLD | 10,351 | 32.1% | -0.9199% |
| SP500 | 68 | 32.4% | -0.9294% |
| USDJPY | 9,561 | 32.0% | -0.9400% |
| GBPUSD | 9,771 | 31.8% | -0.9447% |
| AMZN | 196 | 25.5% | -0.9537% |
| USDINR | 10 | 30.0% | -1.0000% |
| JPM | 69 | 24.6% | -1.1293% |

## Reading this

- ORB levels are fixed once the opening window closes; VWAP is cumulative to
  date; the volume profile used is the PREVIOUS session's. All causal.
- Entry is the next bar's open, never the close that revealed the break.
- Bars containing both stop and target are scored LOSSES.
- A 24-hour instrument has no natural open, so the NY session is imposed. Read
  those rows as 'does the NY open matter here', not as a true opening range.
- Delta and liquidity-heatmap confluence are NOT included: neither can be
  computed from OHLCV bars, and approximating them would invent a signal.
