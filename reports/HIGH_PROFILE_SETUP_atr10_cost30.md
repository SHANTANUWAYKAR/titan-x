# High-Profile Setup — the published ORB, measured here

15 assets · 5m · opening range 5 min · entry **stop_order** · stop **atr_pct** (10% of 14-day ATR) · exit **eod** (cap 10R) · round-trip cost **30 bps**.

## The claim under test

Zarattini, Barbon & Aziz report the SAME breakout rules at Sharpe 0.48
unfiltered and **2.81** once the universe is cut to the top 20 by opening
relative volume. Both columns below are the same trades; the only
difference is the filter.

| | Trades | Win% gross | Win% net | Net expectancy | Sharpe/trade | Break-even cost |
|---|---|---|---|---|---|---|
| **Unfiltered** | 19,535 | 14.2% | 9.8% | -1.1757 R | -0.6745 | -4.6 bps |
| **RVOL-filtered** | 7,235 | 13.7% | 10.0% | -1.1507 R | -0.6400 | -4.6 bps |

The filter keeps **37.0%** of trades and moves Sharpe per trade by **+0.0345**.

## Break-even cost is the number to read first

`breakeven_cost_bps` is the round-trip cost at which this setup's expectancy
is exactly zero. A tight stop buys more notional per unit of risk, so cost in
R units is `cost / stop_frac` — which is why a 10%-of-ATR stop is fragile on a
retail cost base however good the entry is.

The independent replication of this strategy on QQQ put its break-even at
~2.2¢/share against a ~1¢ spread, and its bootstrap 95% CI on Sharpe at
[0.05, 1.41] versus buy-and-hold QQQ's [−0.03, 1.47] — overlapping.

## Year by year

| Year | Trades | Win% gross | Net R (all) | Net R (RVOL top-N) |
|---|---|---|---|---|
| 2003 | 269 | 7.4% | -1.4756 | -1.4812 |
| 2004 | 481 | 7.5% | -1.4375 | -1.4424 |
| 2005 | 469 | 8.7% | -1.4188 | -1.2879 |
| 2006 | 632 | 6.5% | -1.5528 | -1.4444 |
| 2007 | 484 | 8.9% | -1.4847 | -1.3739 |
| 2008 | 711 | 6.5% | -1.5150 | -1.4995 |
| 2009 | 649 | 8.9% | -1.5388 | -1.4905 |
| 2010 | 632 | 8.9% | -1.5228 | -1.5623 |
| 2011 | 589 | 12.6% | -1.3067 | -1.1562 |
| 2012 | 503 | 10.1% | -1.4195 | -1.4534 |
| 2013 | 614 | 14.3% | -1.4422 | -1.4105 |
| 2014 | 390 | 12.1% | -1.3747 | -1.3658 |
| 2015 | 468 | 12.2% | -1.3999 | -1.3301 |
| 2016 | 491 | 14.9% | -1.3661 | -1.3280 |
| 2017 | 614 | 13.4% | -1.1515 | -1.1134 |
| 2018 | 830 | 19.5% | -0.8217 | -0.8265 |
| 2019 | 735 | 15.0% | -1.1152 | -1.0504 |
| 2020 | 1,145 | 16.3% | -0.9923 | -0.9127 |
| 2021 | 1,114 | 17.5% | -0.8302 | -0.7250 |
| 2022 | 1,514 | 17.4% | -0.8848 | -0.9156 |
| 2023 | 1,417 | 14.7% | -1.2006 | -1.2137 |
| 2024 | 1,625 | 18.3% | -0.9853 | -0.9390 |
| 2025 | 1,660 | 17.2% | -1.0079 | -1.0145 |
| 2026 | 1,499 | 16.5% | -1.1066 | -1.1488 |

**0 of 24 years net-positive unfiltered · 0 of 24 filtered.**

## By asset

| Asset | Trades | Win% gross | Net R | Break-even cost |
|---|---|---|---|---|
| ETHUSD | 2,285 | 23.4% | -0.4969 | 8.4 bps |
| TSLA | 394 | 21.6% | -0.4980 | 2.0 bps |
| NVDA | 527 | 14.2% | -0.8428 | -4.7 bps |
| BTCUSD | 2,734 | 19.8% | -0.8493 | 0.5 bps |
| AMZN | 145 | 22.1% | -0.9545 | -10.0 bps |
| CRUDE | 32 | 15.6% | -1.0340 | -12.8 bps |
| AAPL | 587 | 16.0% | -1.0976 | -2.1 bps |
| GOOGL | 74 | 18.9% | -1.1360 | -23.0 bps |
| MSFT | 175 | 14.3% | -1.1973 | -3.7 bps |
| SP500 | 36 | 16.7% | -1.2007 | -0.0 bps |
| USDJPY | 4,371 | 19.0% | -1.2253 | -0.6 bps |
| SILVER | 2,349 | 10.7% | -1.3698 | -13.7 bps |
| META | 109 | 8.3% | -1.4828 | -24.8 bps |
| GOLD | 5,678 | 4.7% | -1.5681 | -9.5 bps |
| JPM | 39 | 2.6% | -1.9970 | -19.9 bps |

## What this does not establish

- The paper's universe is US equities screened to >$5, >1M shares/day and
  >$0.50 ATR, then ranked daily across ~1,000 names. This book holds 29
  instruments, so the cross-sectional 'top 20' is a much weaker cut than
  the one that produced the published number. A null result here is
  evidence about THIS universe, not a refutation of theirs.
- A 24-hour instrument has no natural open. Those rows answer 'does the NY
  open matter here', not 'what does the opening range do'.
- Exit is at the session's last close. Real end-of-day exits pay the
  closing auction, which is not modelled.
