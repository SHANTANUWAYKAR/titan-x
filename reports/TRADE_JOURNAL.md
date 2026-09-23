# Trade Journal — every setup, every timeframe, every asset

29 assets · timeframes 1d · 2 setups · 2.0:1 at 1.0 ATR · 20-bar limit · 30 bps round trip · entry at the NEXT bar's open.

**33,667 journalled trades.**

## Record format

| Field | Source |
|---|---|
| Date / Pair / Setup | the trade |
| Session | bar's UTC hour → Sydney / Tokyo / London / London-NY overlap / New York. `n/a` on daily+ |
| HTF bias | 50 vs 200 EMA **computed on bars up to entry only** |
| Entry / SL / TP / R:R | ATR-derived, fixed before entry |
| Result in R | net of cost |
| Screenshot | a backtest has none — a deterministic TradingView link is given instead |
| Reason for entry | which rule fired, and the direction |
| Reason for failure | the exit that actually happened + worst excursion |
| Mistake | always *no mistake (mechanical)* — a rule-follower cannot make a discretionary error. The column matters for MANUAL trades. |

## Sample records

| Date | Pair | Session | HTF bias | Setup | Entry | SL | TP | R:R | Result R | Reason for entry | Reason for failure | Mistake |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2016-09-13 00:00:00 | EURUSD | n/a (daily+) | insufficient history | `sr_bounce` | 1.12413 | 1.11591 | 1.14056 | 2 | **-1.410** | sr_bounce fired long; stop 1.0xATR, target 2.0R. | Stop hit. Worst excursion 1.04R against the entry before it triggered. | no mistake (mechanical — rule followed exactly) |
| 2016-09-14 00:00:00 | EURUSD | n/a (daily+) | insufficient history | `sr_bounce` | 1.12196 | 1.11397 | 1.13792 | 2 | **-1.422** | sr_bounce fired long; stop 1.0xATR, target 2.0R. | Stop hit. Worst excursion 1.17R against the entry before it triggered. | no mistake (mechanical — rule followed exactly) |
| 2016-09-16 00:00:00 | EURUSD | n/a (daily+) | insufficient history | `sr_bounce` | 1.1248 | 1.11698 | 1.14044 | 2 | **-1.431** | sr_bounce fired long; stop 1.0xATR, target 2.0R. | Stop hit. Worst excursion 1.18R against the entry before it triggered. | no mistake (mechanical — rule followed exactly) |
| 2016-09-19 00:00:00 | EURUSD | n/a (daily+) | insufficient history | `sr_bounce` | 1.11607 | 1.10851 | 1.1312 | 2 | **-1.443** | sr_bounce fired long; stop 1.0xATR, target 2.0R. | Stop hit. Worst excursion 1.38R against the entry before it triggered. | no mistake (mechanical — rule followed exactly) |
| 2016-09-27 00:00:00 | EURUSD | n/a (daily+) | insufficient history | `sr_bounce` | 1.12508 | 1.11787 | 1.13948 | 2 | **-1.468** | sr_bounce fired long; stop 1.0xATR, target 2.0R. | Stop hit. Worst excursion 1.34R against the entry before it triggered. | no mistake (mechanical — rule followed exactly) |

## Statistics — all journalled trades pooled

| Metric | Value |
|---|---|
| Trades | 33,667 |
| Win rate | 36.72% |
| Average win | +1.7156 R |
| Average loss | -1.1838 R |
| **Expectancy** | **-0.1191 R** |
| Profit factor | 0.841 |
| Maximum drawdown | 4,025.5 R |
| Longest losing streak | 41 |
| Best session | n/a (daily+) (-0.1191 R) |
| Worst session | n/a (daily+) (-0.1191 R) |
| Best pair | ETHUSD (+0.1962 R) |
| Worst pair | USDINR (-0.6309 R) |
| Total | -4,009.4 R |

### By session

| Session | Trades | Win% | Expectancy R | Total R |
|---|---|---|---|---|
| n/a (daily+) | 33,667 | 36.7% | -0.1191 | -4,009.4 |

### By pair

| Pair | Trades | Win% | Expectancy R | Total R |
|---|---|---|---|---|
| ETHUSD | 961 | 43.8% | +0.1962 | 188.5 |
| TSLA | 664 | 40.2% | +0.1217 | 80.8 |
| AMZN | 665 | 41.7% | +0.0999 | 66.5 |
| AAPL | 2,970 | 39.7% | +0.0682 | 202.7 |
| BTCUSD | 1,147 | 38.4% | +0.0376 | 43.2 |
| SILVER | 509 | 40.9% | +0.0219 | 11.1 |
| BANKNIFTY | 1,474 | 40.8% | +0.0193 | 28.5 |
| SBIN | 1,308 | 39.2% | +0.0090 | 11.7 |
| HDFCBANK | 718 | 39.3% | -0.0379 | -27.2 |
| NVDA | 642 | 35.5% | -0.0381 | -24.4 |
| MSFT | 1,101 | 37.5% | -0.0513 | -56.5 |
| NIFTY50 | 1,564 | 40.2% | -0.0544 | -85.1 |
| TCS | 1,915 | 36.6% | -0.0650 | -124.5 |
| INFY | 1,300 | 36.4% | -0.0789 | -102.6 |
| GOOGL | 1,122 | 36.2% | -0.0869 | -97.5 |
| RELIANCE | 2,462 | 34.9% | -0.1024 | -252.2 |
| CRUDE | 830 | 34.6% | -0.1037 | -86.0 |
| ICICIBANK | 1,328 | 34.8% | -0.1197 | -158.9 |
| ITC | 698 | 35.7% | -0.1209 | -84.4 |
| GOLD | 1,442 | 36.8% | -0.1588 | -229.0 |
| META | 971 | 31.9% | -0.1849 | -179.6 |
| JPM | 657 | 32.7% | -0.1918 | -126.0 |
| SP500 | 531 | 33.9% | -0.2024 | -107.5 |
| BHARTIARTL | 860 | 29.4% | -0.2556 | -219.8 |
| GBPUSD | 724 | 34.3% | -0.3473 | -251.5 |
| USDJPY | 2,618 | 34.6% | -0.3753 | -982.7 |
| EURUSD | 745 | 30.3% | -0.5370 | -400.1 |
| US10Y | 767 | 38.2% | -0.5638 | -432.4 |
| USDINR | 974 | 31.2% | -0.6309 | -614.5 |

## Setup × timeframe — expectancy in R

| Setup | 1d (Posi) |
|---|---|
| `sr_bounce` | -0.1332 |
| `failure_test` | -0.0692 |

## Style assignment

Each setup is assigned to the style band where it measured best — **not**
to the band its timeframe label implies. `Tradeable` requires all three:
positive expectancy, ≥100 trades, and beating its own shuffled null.

| Setup | Assigned style | Best TF | Trades | Win% | Expectancy R | PF | Beats null | **Tradeable** |
|---|---|---|---|---|---|---|---|---|
| `failure_test` | **Positional** | 1d | 7,440 | 38.4% | -0.0692 | 0.91 | no | no |
| `sr_bounce` | **Positional** | 1d | 26,227 | 36.3% | -0.1332 | 0.82 | no | no |

**0 of 2 setups are tradeable by all three gates.**

Nothing clears the gates. That is a result, not a gap in the testing:
every setup here has positive GROSS edge and is turned negative by the
~0.19 R cost term. See `reports/CONCEPT_LAB.md` for the decomposition and
`reports/TRADING_ROADMAP.md` §5.1 for the arithmetic.

## What this cannot tell you

- In-sample. These rankings decide what deserves a walk-forward test; they
  are not out-of-sample results.
- Many setups × many timeframes were tested at once, so the best row is
  selected and its apparent significance is overstated.
- One exit model and one cost assumption. A setup can be real and still die
  under a different exit.
- `Mistake` is mechanical here by construction. In a manual journal it is the
  most valuable column; filling it with invented judgements would destroy that.
