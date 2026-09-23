# Concept Lab — every retail concept, one evaluator

29 assets · 1d · triple barrier 2.0:1 at 1.0 ATR · 20-bar time limit · round-trip cost 30 bps · entry at the NEXT bar's open.

Every concept below emits the same thing — a direction at a bar — and is
scored by the same rules, so the rows are comparable to each other. They
are **not** comparable to numbers from anyone else's backtest.

| Concept | Trades | Win% | Gross R | Cost R | **Net R** | vs null | Beats null p95 | t | Years + |
|---|---|---|---|---|---|---|---|---|---|
| `round_number` | 107,103 | 38.2% | +0.1162 | 0.1673 | **-0.0511** | -0.0906 | no | -2.13 | 185/469 |
| `failure_test` | 7,440 | 38.8% | +0.1313 | 0.1994 | **-0.0681** | -0.1902 | no | -0.79 | 21/117 |
| `engulfing_at_level` | 1,042 | 36.3% | +0.0693 | 0.1706 | **-0.1013** | -0.0887 | no | -1.04 | 1/1 |
| `trend_pullback` | 15,443 | 37.4% | +0.0927 | 0.2017 | **-0.1090** | -0.1306 | no | -1.96 | 153/400 |
| `liquidity_sweep` | 14,292 | 37.0% | +0.0821 | 0.2009 | **-0.1188** | -0.1728 | no | -2.05 | 135/379 |
| `momentum_breakout` | 25,957 | 37.6% | +0.0956 | 0.2237 | **-0.1282** | -0.1287 | no | -3.24 | 158/446 |
| `sr_bounce` | 26,227 | 36.7% | +0.0691 | 0.1996 | **-0.1305** | -0.1558 | no | -3.08 | 172/454 |
| `fvg_fill` | 90,430 | 36.2% | +0.0602 | 0.1935 | **-0.1333** | -0.1645 | no | -5.74 | 144/466 |
| `fib_zone` | 19,998 | 36.1% | +0.0500 | 0.1954 | **-0.1454** | -0.1957 | no | -3.10 | 154/437 |
| `engulfing_anywhere` | 8,829 | 34.6% | +0.0142 | 0.1757 | **-0.1615** | -0.1716 | no | -2.32 | 58/212 |

## Stop-width sweep — the only lever that moves cost

`cost_R = cost / stop_frac`, so a wider stop mechanically pays less cost
per unit of risk. It also changes the trades: a wider stop is hit less
often, and a 2R target sits further away. The net effect is measured,
not assumed.

### `failure_test`

| Stop (ATR) | Trades | Unres. | Gross R | Cost R | Net R | Null | Null p95 | Beats p95 | Longs | Shorts |
|---|---|---|---|---|---|---|---|---|---|---|
| 1.0 | 7,440 | 4% | +0.1313 | 0.1994 | -0.0681 | -0.1634 | +0.0592 | no | +0.0312 | -0.1362 |
| 2.0 | 7,440 | 13% | +0.0939 | 0.1005 | -0.0065 | -0.0398 | +0.1386 | no | +0.1758 | -0.2195 |
| 4.0 | 7,440 | 29% | +0.0987 | 0.0502 | +0.0485 | +0.0286 | +0.2257 | no | +0.3407 | -0.2592 |

Best net at **4.0 ATR**: +0.0485 R.

**It does not clear its own null.** Random entries at the same settings score +0.0286 R (p95 +0.2257). A wide stop with a long horizon captures drift wherever you enter, so a positive net R here is the exit structure, not the concept.
**And it is directional.** Longs +0.3407 R against shorts -0.2592 R — near-equal and opposite, which is beta wearing a costume, not an edge.

### `round_number`

| Stop (ATR) | Trades | Unres. | Gross R | Cost R | Net R | Null | Null p95 | Beats p95 | Longs | Shorts |
|---|---|---|---|---|---|---|---|---|---|---|
| 1.0 | 107,103 | 4% | +0.1162 | 0.1673 | -0.0511 | -0.0854 | +0.0785 | no | -0.0269 | -0.3735 |
| 2.0 | 107,103 | 14% | +0.2134 | 0.0841 | +0.1293 | +0.1044 | +0.3386 | no | +0.1599 | -0.2669 |
| 4.0 | 107,103 | 32% | +0.3171 | 0.0421 | +0.2750 | +0.2549 | +0.5585 | no | +0.3185 | -0.2870 |

Best net at **4.0 ATR**: +0.2750 R.

**It does not clear its own null.** Random entries at the same settings score +0.2549 R (p95 +0.5585). A wide stop with a long horizon captures drift wherever you enter, so a positive net R here is the exit structure, not the concept.
**And it is directional.** Longs +0.3185 R against shorts -0.2870 R — near-equal and opposite, which is beta wearing a costume, not an edge.

### `momentum_breakout`

| Stop (ATR) | Trades | Unres. | Gross R | Cost R | Net R | Null | Null p95 | Beats p95 | Longs | Shorts |
|---|---|---|---|---|---|---|---|---|---|---|
| 1.0 | 25,957 | 4% | +0.0956 | 0.2237 | -0.1282 | -0.1333 | +0.0377 | no | -0.0874 | -0.2310 |
| 2.0 | 25,957 | 13% | +0.1340 | 0.1148 | +0.0191 | +0.0267 | +0.2289 | no | +0.1150 | -0.2276 |
| 4.0 | 25,957 | 30% | +0.1979 | 0.0576 | +0.1402 | +0.1310 | +0.3531 | no | +0.2954 | -0.2663 |

Best net at **4.0 ATR**: +0.1402 R.

**It does not clear its own null.** Random entries at the same settings score +0.1310 R (p95 +0.3531). A wide stop with a long horizon captures drift wherever you enter, so a positive net R here is the exit structure, not the concept.
**And it is directional.** Longs +0.2954 R against shorts -0.2663 R — near-equal and opposite, which is beta wearing a costume, not an edge.

### `trend_pullback`

| Stop (ATR) | Trades | Unres. | Gross R | Cost R | Net R | Null | Null p95 | Beats p95 | Longs | Shorts |
|---|---|---|---|---|---|---|---|---|---|---|
| 1.0 | 15,443 | 4% | +0.0927 | 0.2017 | -0.1090 | -0.1261 | +0.0782 | no | -0.0680 | -0.1819 |
| 2.0 | 15,443 | 13% | +0.1237 | 0.1021 | +0.0216 | +0.0170 | +0.2093 | no | +0.1253 | -0.1686 |
| 4.0 | 15,443 | 31% | +0.1915 | 0.0511 | +0.1404 | +0.1298 | +0.3831 | no | +0.3052 | -0.1501 |

Best net at **4.0 ATR**: +0.1404 R.

**It does not clear its own null.** Random entries at the same settings score +0.1298 R (p95 +0.3831). A wide stop with a long horizon captures drift wherever you enter, so a positive net R here is the exit structure, not the concept.


## The control that matters most

The corpus's most repeated claim is that **a pattern only means something
at a level**. That is a testable prediction, and this is the test:

| | Trades | Win% | Net R |
|---|---|---|---|
| engulfing **at a level** | 1,042 | 36.3% | -0.1013 |
| engulfing **anywhere** | 8,829 | 34.6% | -0.1615 |

**The level filter is worth +0.0602 R per trade.** The claim holds in the direction it was stated.

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
