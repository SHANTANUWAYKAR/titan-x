# High-Profile Setup — the published ORB, measured here

16 assets · 5m · opening range 5 min · entry **stop_order** · stop **orb_opposite** · exit **eod** (cap 10R) · round-trip cost **30 bps**.

## The claim under test

Zarattini, Barbon & Aziz report the SAME breakout rules at Sharpe 0.48
unfiltered and **2.81** once the universe is cut to the top 20 by opening
relative volume. Both columns below are the same trades; the only
difference is the filter.

| | Trades | Win% gross | Win% net | Net expectancy | Sharpe/trade | Break-even cost |
|---|---|---|---|---|---|---|
| **Unfiltered** | 19,663 | 17.2% | 12.6% | -1.0750 R | -0.6669 | -4.5 bps |
| **RVOL-filtered** | 7,235 | 21.2% | 15.7% | -0.9195 R | -0.5482 | -2.3 bps |

The filter keeps **36.8%** of trades and moves Sharpe per trade by **+0.1187**.

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
| 2003 | 294 | 12.6% | -1.4372 | -1.4151 |
| 2004 | 481 | 12.3% | -1.4146 | -1.3078 |
| 2005 | 469 | 11.9% | -1.4948 | -1.3061 |
| 2006 | 632 | 10.0% | -1.3082 | -1.0544 |
| 2007 | 484 | 10.1% | -1.4123 | -1.2011 |
| 2008 | 711 | 13.2% | -1.1871 | -0.9918 |
| 2009 | 649 | 12.2% | -1.3050 | -1.2954 |
| 2010 | 632 | 10.6% | -1.3308 | -1.2109 |
| 2011 | 589 | 14.3% | -1.2154 | -0.9752 |
| 2012 | 503 | 11.7% | -1.3656 | -1.2077 |
| 2013 | 614 | 15.3% | -1.3376 | -1.0949 |
| 2014 | 390 | 13.8% | -1.3358 | -1.1943 |
| 2015 | 468 | 12.2% | -1.3659 | -1.2535 |
| 2016 | 491 | 14.1% | -1.3228 | -1.2749 |
| 2017 | 632 | 14.7% | -1.1562 | -1.0192 |
| 2018 | 833 | 14.2% | -1.0200 | -0.9546 |
| 2019 | 735 | 10.9% | -1.1963 | -0.9409 |
| 2020 | 1,149 | 16.4% | -1.0088 | -0.8265 |
| 2021 | 1,128 | 18.8% | -0.8521 | -0.5371 |
| 2022 | 1,517 | 20.4% | -0.7910 | -0.6719 |
| 2023 | 1,417 | 20.6% | -1.0394 | -0.9150 |
| 2024 | 1,637 | 22.9% | -0.8789 | -0.7079 |
| 2025 | 1,660 | 22.2% | -0.8769 | -0.7919 |
| 2026 | 1,548 | 27.2% | -0.7169 | -0.5642 |

**0 of 24 years net-positive unfiltered · 0 of 24 filtered.**

## By asset

| Asset | Trades | Win% gross | Net R | Break-even cost |
|---|---|---|---|---|
| TSLA | 398 | 40.5% | -0.0413 | 25.0 bps |
| NVDA | 541 | 37.9% | -0.2053 | 9.8 bps |
| MSFT | 175 | 44.0% | -0.3641 | 6.9 bps |
| JPM | 50 | 40.0% | -0.4372 | -4.0 bps |
| AMZN | 145 | 38.6% | -0.4550 | -10.8 bps |
| AAPL | 587 | 37.0% | -0.4602 | 1.7 bps |
| GOOGL | 77 | 31.2% | -0.5302 | -19.6 bps |
| META | 121 | 32.2% | -0.5321 | -20.1 bps |
| ETHUSD | 2,295 | 17.7% | -0.7507 | 3.8 bps |
| CRUDE | 45 | 22.2% | -0.7608 | -0.5 bps |
| BTCUSD | 2,745 | 16.8% | -0.8859 | 2.2 bps |
| SILVER | 2,349 | 18.8% | -0.9369 | -12.8 bps |
| USDJPY | 4,384 | 18.8% | -1.2070 | -0.6 bps |
| SP500 | 49 | 30.6% | -1.2166 | -2.3 bps |
| US10Y | 12 | 8.3% | -1.3426 | -3.6 bps |
| GOLD | 5,690 | 7.4% | -1.5336 | -12.3 bps |

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
