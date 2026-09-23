# High-Profile Setup — the published ORB, measured here

> **Read the sweeps in `HIGH_PROFILE_SETUP_orbstop_cost30.md` before this page.**
> This run moves TWO knobs at once (top-N 20 → 3 *and* the relative-volume
> threshold 1.0× → 2.0×), so its headline −0.0312 R cannot be attributed to
> either. Sweeping them separately showed the top-N ranking does nothing and
> the threshold curve is not ordered above 1×. Kept as a measurement; it is
> not evidence for a harder cut.

16 assets · 5m · opening range 5 min · entry **stop_order** · stop **orb_opposite** · exit **eod** (cap 10R) · round-trip cost **30 bps**.

## The claim under test

Zarattini, Barbon & Aziz report the SAME breakout rules at Sharpe 0.48
unfiltered and **2.81** once the universe is cut to the top 3 by opening
relative volume. Both columns below are the same trades; the only
difference is the filter.

| | Trades | Win% gross | Win% net | Net expectancy | Sharpe/trade | Break-even cost |
|---|---|---|---|---|---|---|
| **Unfiltered** | 19,663 | 17.2% | 12.6% | -1.0750 R | -0.6669 | -4.5 bps |
| **RVOL-filtered** | 2,070 | 18.2% | 14.7% | -0.9540 R | -0.5390 | -1.0 bps |

The filter keeps **10.5%** of trades and moves Sharpe per trade by **+0.1278**.

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
| 2003 | 294 | 12.6% | -1.4372 | — |
| 2004 | 481 | 12.3% | -1.4146 | -1.4629 |
| 2005 | 469 | 11.9% | -1.4948 | -1.6173 |
| 2006 | 632 | 10.0% | -1.3082 | -1.0807 |
| 2007 | 484 | 10.1% | -1.4123 | -1.2135 |
| 2008 | 711 | 13.2% | -1.1871 | -1.0587 |
| 2009 | 649 | 12.2% | -1.3050 | -1.3976 |
| 2010 | 632 | 10.6% | -1.3308 | -1.2814 |
| 2011 | 589 | 14.3% | -1.2154 | -1.0745 |
| 2012 | 503 | 11.7% | -1.3656 | -1.4233 |
| 2013 | 614 | 15.3% | -1.3376 | -1.1441 |
| 2014 | 390 | 13.8% | -1.3358 | -1.2771 |
| 2015 | 468 | 12.2% | -1.3659 | -1.2149 |
| 2016 | 491 | 14.1% | -1.3228 | -1.3541 |
| 2017 | 632 | 14.7% | -1.1562 | -0.9608 |
| 2018 | 833 | 14.2% | -1.0200 | -0.7594 |
| 2019 | 735 | 10.9% | -1.1963 | -0.8674 |
| 2020 | 1,149 | 16.4% | -1.0088 | -0.7689 |
| 2021 | 1,128 | 18.8% | -0.8521 | -0.5203 |
| 2022 | 1,517 | 20.4% | -0.7910 | -0.7804 |
| 2023 | 1,417 | 20.6% | -1.0394 | -1.0997 |
| 2024 | 1,637 | 22.9% | -0.8789 | -0.9153 |
| 2025 | 1,660 | 22.2% | -0.8769 | -0.7535 |
| 2026 | 1,548 | 27.2% | -0.7169 | -0.6543 |

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
