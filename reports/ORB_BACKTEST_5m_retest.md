# 5-Minute ORB — Backtest (retest entry)

18 assets · 5m · NY session 13:30-20:00 UTC · opening range 5 min · entry **retest** · reward:risk 2.0:1 · breakeven 33.3% · VWAP filter OFF.

**Pooled: 48,425 trades · win 31.94% · net -0.8849%/trade**

## Year by year

The cut that killed five previous leads. A setup that only works in some years
is regime exposure, not edge.

| Year | Trades | Win% | Net %/trade |
|---|---|---|---|
| 2003 | 980 | 27.4% | -1.0280% |
| 2004 | 1,469 | 27.4% | -1.0306% |
| 2005 | 1,434 | 27.8% | -1.0377% |
| 2006 | 1,503 | 27.9% | -0.9764% |
| 2007 | 1,548 | 29.1% | -0.9509% |
| 2008 | 1,626 | 32.0% | -0.8076% |
| 2009 | 1,602 | 30.9% | -0.8734% |
| 2010 | 1,655 | 30.3% | -0.9141% |
| 2011 | 1,761 | 32.8% | -0.8898% |
| 2012 | 1,704 | 31.5% | -0.9491% |
| 2013 | 1,666 | 33.3% | -0.8874% |
| 2014 | 1,660 | 32.0% | -0.9353% |
| 2015 | 1,646 | 32.6% | -0.9160% |
| 2016 | 1,724 | 31.8% | -0.9420% |
| 2017 | 1,976 | 33.5% | -0.8605% |
| 2018 | 2,406 | 32.6% | -0.8722% |
| 2019 | 2,356 | 32.7% | -0.8569% |
| 2020 | 2,642 | 33.3% | -0.8267% |
| 2021 | 2,691 | 32.3% | -0.8512% |
| 2022 | 2,995 | 33.8% | -0.7882% |
| 2023 | 2,876 | 33.9% | -0.8481% |
| 2024 | 2,904 | 33.4% | -0.8388% |
| 2025 | 2,972 | 32.9% | -0.8464% |
| 2026 | 2,629 | 31.4% | -0.8690% |

**0 of 24 years net-positive.**

## By asset

| Asset | Trades | Win% | Net %/trade |
|---|---|---|---|
| NVDA | 629 | 32.4% | -0.6560% |
| ETHUSD | 3,440 | 34.7% | -0.6761% |
| GOOGL | 95 | 34.7% | -0.7115% |
| TSLA | 454 | 28.4% | -0.7322% |
| BTCUSD | 4,228 | 34.5% | -0.7539% |
| META | 141 | 31.9% | -0.7867% |
| AAPL | 662 | 33.7% | -0.8050% |
| AMZN | 164 | 29.9% | -0.8241% |
| JPM | 55 | 34.5% | -0.8400% |
| SILVER | 6,224 | 29.5% | -0.8523% |
| EURUSD | 7,863 | 33.2% | -0.9034% |
| GBPUSD | 8,006 | 33.1% | -0.9076% |
| USDJPY | 7,813 | 32.9% | -0.9124% |
| CRUDE | 61 | 27.9% | -0.9304% |
| SP500 | 63 | 30.2% | -0.9950% |
| MSFT | 181 | 27.6% | -0.9997% |
| GOLD | 8,282 | 28.2% | -1.0296% |
| US10Y | 64 | 28.1% | -1.0563% |

## Reading this

- ORB levels are fixed once the opening window closes; VWAP is cumulative to
  date; the volume profile used is the PREVIOUS session's. All causal.
- Entry is the next bar's open, never the close that revealed the break.
- Bars containing both stop and target are scored LOSSES.
- A 24-hour instrument has no natural open, so the NY session is imposed. Read
  those rows as 'does the NY open matter here', not as a true opening range.
- Delta and liquidity-heatmap confluence are NOT included: neither can be
  computed from OHLCV bars, and approximating them would invent a signal.
