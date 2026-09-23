# Concept Lab — every retail concept, one evaluator

29 assets · 1d · triple barrier 2.0:1 at 1.0 ATR · 20-bar time limit · round-trip cost 30 bps · entry at the NEXT bar's open.

Every concept below emits the same thing — a direction at a bar — and is
scored by the same rules, so the rows are comparable to each other. They
are **not** comparable to numbers from anyone else's backtest.

| Concept | Trades | Win% | Gross R | Cost R | **Net R** | vs null | Beats null p95 | t | Years + |
|---|---|---|---|---|---|---|---|---|---|
| `round_number` | 102,830 | 36.7% | +0.1000 | 0.1682 | **-0.0682** | -0.1100 | no | -2.79 | 175/469 |
| `failure_test` | 7,137 | 37.2% | +0.1164 | 0.2006 | **-0.0842** | -0.2091 | no | -0.95 | 16/97 |
| `trend_pullback` | 14,831 | 35.9% | +0.0761 | 0.2022 | **-0.1261** | -0.1483 | no | -2.15 | 152/398 |
| `liquidity_sweep` | 13,720 | 35.6% | +0.0665 | 0.2019 | **-0.1354** | -0.1927 | no | -2.24 | 126/374 |
| `momentum_breakout` | 24,932 | 36.0% | +0.0802 | 0.2234 | **-0.1432** | -0.1499 | no | -3.40 | 153/445 |
| `sr_bounce` | 25,156 | 35.1% | +0.0531 | 0.2008 | **-0.1476** | -0.1749 | no | -3.34 | 166/449 |
| `fvg_fill` | 87,017 | 34.8% | +0.0441 | 0.1947 | **-0.1506** | -0.1843 | no | -6.28 | 133/466 |
| `engulfing_at_level` | 906 | 34.4% | +0.0331 | 0.1846 | **-0.1515** | -0.0987 | no | -1.41 | 0/0 |
| `fib_zone` | 19,069 | 34.3% | +0.0300 | 0.1965 | **-0.1666** | -0.2149 | no | -3.39 | 145/437 |
| `engulfing_anywhere` | 8,530 | 33.3% | +0.0004 | 0.1773 | **-0.1770** | -0.1917 | no | -2.47 | 48/189 |

## Stop-width sweep — the only lever that moves cost

`cost_R = cost / stop_frac`, so a wider stop mechanically pays less cost
per unit of risk. It also changes the trades: a wider stop is hit less
often, and a 2R target sits further away. The net effect is measured,
not assumed.

### `failure_test`

| Stop (ATR) | Trades | Win% | Gross R | Cost R | **Net R** |
|---|---|---|---|---|---|
| 1.0 | 7,137 | 37.2% | +0.1164 | 0.2006 | -0.0842 |
| 1.5 | 6,861 | 36.1% | +0.0834 | 0.1346 | -0.0511 |
| 2.0 | 6,408 | 34.8% | +0.0440 | 0.1009 | -0.0569 |
| 3.0 | 5,666 | 33.1% | -0.0072 | 0.0663 | -0.0736 |
| 4.0 | 5,132 | 32.2% | -0.0337 | 0.0501 | -0.0838 |

Best at **1.5 ATR**: net -0.0511 R — still negative; widening the stop is not enough.

### `round_number`

| Stop (ATR) | Trades | Win% | Gross R | Cost R | **Net R** |
|---|---|---|---|---|---|
| 1.0 | 102,830 | 36.7% | +0.1000 | 0.1682 | -0.0682 |
| 1.5 | 97,909 | 37.9% | +0.1378 | 0.1133 | **+0.0245** |
| 2.0 | 92,224 | 38.7% | +0.1601 | 0.0855 | **+0.0746** |
| 3.0 | 81,741 | 39.8% | +0.1930 | 0.0578 | **+0.1352** |
| 4.0 | 72,831 | 41.0% | +0.2315 | 0.0436 | **+0.1879** |

Best at **4.0 ATR**: net +0.1879 R — **positive after costs.**

### `momentum_breakout`

| Stop (ATR) | Trades | Win% | Gross R | Cost R | **Net R** |
|---|---|---|---|---|---|
| 1.0 | 24,932 | 36.0% | +0.0802 | 0.2234 | -0.1432 |
| 1.5 | 23,881 | 36.0% | +0.0793 | 0.1526 | -0.0734 |
| 2.0 | 22,648 | 36.1% | +0.0820 | 0.1156 | -0.0335 |
| 3.0 | 20,226 | 36.0% | +0.0799 | 0.0774 | **+0.0025** |
| 4.0 | 18,212 | 36.6% | +0.0972 | 0.0580 | **+0.0392** |

Best at **4.0 ATR**: net +0.0392 R — **positive after costs.**

### `trend_pullback`

| Stop (ATR) | Trades | Win% | Gross R | Cost R | **Net R** |
|---|---|---|---|---|---|
| 1.0 | 14,831 | 35.9% | +0.0761 | 0.2022 | -0.1261 |
| 1.5 | 14,122 | 35.6% | +0.0690 | 0.1364 | -0.0674 |
| 2.0 | 13,373 | 35.5% | +0.0638 | 0.1025 | -0.0387 |
| 3.0 | 11,873 | 35.4% | +0.0617 | 0.0689 | -0.0072 |
| 4.0 | 10,657 | 35.3% | +0.0587 | 0.0518 | **+0.0070** |

Best at **4.0 ATR**: net +0.0070 R — **positive after costs.**


## The control that matters most

The corpus's most repeated claim is that **a pattern only means something
at a level**. That is a testable prediction, and this is the test:

| | Trades | Win% | Net R |
|---|---|---|---|
| engulfing **at a level** | 906 | 34.4% | -0.1515 |
| engulfing **anywhere** | 8,530 | 33.3% | -0.1770 |

**The level filter is worth +0.0255 R per trade.** The claim holds in the direction it was stated.

## How to read this

- **Net R** is after costs. It is the only column that decides anything.
- **vs null** is the same concept with its signal COUNT and direction mix held
  constant and its TIMING destroyed. A concept must beat its own null, not
  zero — a 2R target with a time barrier pays something even at random.
- **t** is on the mean net R. |t| > 2 is the conventional bar and it is a LOW
  bar here: ten concepts were tested at once, so the best row is selected and
  its t is inflated. Treat a single |t| just above 2 as noise.
- **Years +** counts asset-years with positive mean net R. A concept that only
  works in some years is regime exposure, not edge.

## What the published evidence said before this ran

- **Support/resistance** has the strongest academic backing of anything here.
  Osler ([J. Finance 2003](https://onlinelibrary.wiley.com/doi/abs/10.1111/1540-6261.00588),
  [FRBNY 2000](https://www.newyorkfed.org/medialibrary/media/research/epr/00v06n2/0007osle.pdf))
  showed take-profit orders cluster **at** round numbers and stop-loss orders
  cluster **just beyond** them — which predicts both reversal at a level and
  acceleration through it. `round_number` tests that mechanism directly.
- **Order blocks / SMC**: weak. One published backtest put order blocks on SPY
  at t = +1.22, below the |t| > 2 bar; a reported 648 ICT backtests failed to
  beat buy-and-hold. These are practitioner sources, not journals.
- **Fair value gaps**: "fill ~70% of the time" is a fill RATE, not an edge —
  it says nothing about what happens when they do not fill.
- **Candlestick patterns**: academic results mixed; most patterns' mean returns
  are not statistically distinguishable from zero.

## What this cannot tell you

- Ten concepts were tested. The best one is selected, so its apparent
  significance is overstated. A deflated-Sharpe style correction is the
  honest next step before anything here is traded.
- One timeframe, one exit, one cost assumption. A concept can be real and
  still die under a different exit.
- Nothing here is out-of-sample. These are in-sample rankings used to decide
  what is worth a walk-forward test, not results to trade.
