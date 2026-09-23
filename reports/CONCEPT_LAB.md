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
| 0.5 | 7,426 | 36.8% | +0.1029 | 0.3708 | -0.2680 |
| 1.0 | 7,137 | 37.2% | +0.1164 | 0.2006 | -0.0842 |
| 1.5 | 6,109 | 34.8% | +0.0425 | 0.1347 | -0.0923 |
| 2.0 | 4,722 | 31.8% | -0.0458 | 0.1008 | -0.1466 |
| 3.0 | 1,888 | 24.9% | -0.2532 | 0.0645 | -0.3177 |
| 4.0 | 544 | 17.6% | -0.4706 | 0.0588 | -0.5294 |

Best at **1.0 ATR**: net -0.0842 R — still negative; widening the stop is not enough.

### `round_number`

| Stop (ATR) | Trades | Win% | Gross R | Cost R | **Net R** |
|---|---|---|---|---|---|
| 0.5 | 106,973 | 34.4% | +0.0336 | 0.3232 | -0.2896 |
| 1.0 | 102,830 | 36.7% | +0.1000 | 0.1682 | -0.0682 |
| 1.5 | 88,036 | 35.7% | +0.0714 | 0.1140 | -0.0426 |
| 2.0 | 69,588 | 33.0% | -0.0106 | 0.0867 | -0.0973 |
| 3.0 | 40,615 | 26.3% | -0.2119 | 0.0593 | -0.2711 |
| 4.0 | 23,765 | 21.4% | -0.3572 | 0.0452 | -0.4024 |
| 6.0 | 8,312 | 18.4% | -0.4485 | 0.0302 | -0.4787 |

Best at **1.5 ATR**: net -0.0426 R — still negative; widening the stop is not enough.

### `momentum_breakout`

| Stop (ATR) | Trades | Win% | Gross R | Cost R | **Net R** |
|---|---|---|---|---|---|
| 0.5 | 25,917 | 35.2% | +0.0553 | 0.4080 | -0.3527 |
| 1.0 | 24,932 | 36.0% | +0.0802 | 0.2234 | -0.1432 |
| 1.5 | 21,663 | 34.4% | +0.0317 | 0.1520 | -0.1203 |
| 2.0 | 17,478 | 31.8% | -0.0458 | 0.1163 | -0.1621 |
| 3.0 | 10,474 | 25.7% | -0.2293 | 0.0797 | -0.3091 |
| 4.0 | 5,895 | 22.1% | -0.3379 | 0.0583 | -0.3962 |
| 6.0 | 1,327 | 24.3% | -0.2698 | 0.0492 | -0.3190 |

Best at **1.5 ATR**: net -0.1203 R — still negative; widening the stop is not enough.

### `trend_pullback`

| Stop (ATR) | Trades | Win% | Gross R | Cost R | **Net R** |
|---|---|---|---|---|---|
| 0.5 | 15,427 | 34.8% | +0.0443 | 0.3741 | -0.3297 |
| 1.0 | 14,831 | 35.9% | +0.0761 | 0.2022 | -0.1261 |
| 1.5 | 12,669 | 33.7% | +0.0117 | 0.1367 | -0.1250 |
| 2.0 | 10,103 | 30.7% | -0.0780 | 0.1035 | -0.1815 |
| 3.0 | 5,603 | 23.4% | -0.2987 | 0.0699 | -0.3686 |
| 4.0 | 2,605 | 17.5% | -0.4737 | 0.0529 | -0.5266 |
| 6.0 | 109 | 9.2% | -0.7248 | 0.0193 | -0.7440 |

Best at **1.5 ATR**: net -0.1250 R — still negative; widening the stop is not enough.


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
