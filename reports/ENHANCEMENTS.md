# Enhancements — what actually reduces drawdown

29 assets · 1d · 2.0:1 at 1.0 ATR · 20-bar limit · 30 bps round trip.

Four variants on **identical signals**. Volatility targeting changes only
SIZE; the regime filter changes only WHETHER. Neither can create a signal,
so neither can manufacture edge — they can only redistribute risk.

> **Read the R/DD column, not the DD column.** Halving drawdown by halving
> size is not an improvement — it is the same curve drawn smaller, and it
> leaves return-over-drawdown unchanged. Only a variant that raises R/DD has
> improved anything.

Drawdown is computed on trades sorted **chronologically**. Sorted by asset
instead — which is how the pooled rows arrive — it reports the sum of
unrelated losing tails glued together.

| Setup | Variant | Trades | Win% | Expectancy R | Max DD (R) | Streak | Total R | **R/DD** |
|---|---|---|---|---|---|---|---|---|
| `round_number` | baseline | 107,103 | 37.9% | -0.0511 | 5,493.1 | 71 | -5,472.6 | -0.996 |
| `round_number` | vol_target | 107,103 | 37.9% | -0.0717 | 7,750.2 | 71 | -7,681.1 | -0.991 |
| `round_number` | regime | 97,215 | 38.0% | -0.0490 | 4,844.6 | 70 | -4,761.3 | -0.983 |
| `round_number` | both | 97,215 | 38.0% | -0.0705 | 6,986.5 | 70 | -6,852.2 | -0.981 |
| `trend_pullback` | baseline | 15,443 | 37.0% | -0.1090 | 1,786.5 | 27 | -1,683.8 | -0.943 |
| `trend_pullback` | vol_target | 15,443 | 37.0% | -0.1247 | 2,025.4 | 27 | -1,926.5 | -0.951 |
| `trend_pullback` | regime | 14,502 | 37.0% | -0.1089 | 1,675.1 | 27 | -1,579.5 | -0.943 |
| `trend_pullback` | both | 14,502 | 37.0% | -0.1235 | 1,880.3 | 27 | -1,790.4 | -0.952 |
| `failure_test` | baseline | 7,440 | 38.4% | -0.0681 | 560.8 | 20 | -506.7 | -0.904 |
| `failure_test` | vol_target | 7,440 | 38.4% | -0.0632 | 526.9 | 20 | -470.5 | -0.893 |
| `failure_test` | regime | 6,904 | 38.4% | -0.0666 | 527.0 | 22 | -459.7 | -0.872 |
| `failure_test` | both | 6,904 | 38.4% | -0.0604 | 489.7 | 22 | -417.1 | -0.852 |
| `liquidity_sweep` | baseline | 14,292 | 36.7% | -0.1188 | 1,770.2 | 26 | -1,697.8 | -0.959 |
| `liquidity_sweep` | vol_target | 14,292 | 36.7% | -0.1350 | 2,006.8 | 26 | -1,929.1 | -0.961 |
| `liquidity_sweep` | regime | 13,233 | 36.9% | -0.1132 | 1,577.6 | 33 | -1,498.4 | -0.950 |
| `liquidity_sweep` | both | 13,233 | 36.9% | -0.1295 | 1,795.1 | 33 | -1,714.0 | -0.955 |

## Verdict

**All 4 baselines lose money, so return-over-drawdown says nothing
here.** When the curve only descends, max drawdown converges on the total
loss and R/DD pins near −1 for every variant; ranking −0.983 above −0.996
would be dressing up "loses fractionally less" as a fix.

The only question left is whether an enhancement moved EXPECTANCY toward
positive:

| Variant | Improved expectancy |
|---|---|
| regime | 4 / 4 |
| vol_target | 1 / 4 |
| both | 1 / 4 |

Neither enhancement can create edge — by construction they change only
SIZE and WHETHER, never which bars fire. A setup with negative expectancy
stays negative; volatility targeting merely re-weights the losses, and
where it sized up into quiet periods that then moved against the
position it made them larger.


## What this cannot tell you

- In-sample. A variant that wins here still needs a walk-forward test.
- The regime filter uses FIXED conventional thresholds and was not tuned.
  Tuning it until the curve looks good is the standard way to produce an
  in-sample-only result, and is the reason the thresholds are frozen.
- Pooling assets scores concurrent positions as sequential, so the pooled
  drawdown UNDERSTATES what a real book would take when several instruments
  draw down together. Per-pair drawdown is the honest per-instrument figure.

## Sources

- Volatility targeting cut the S&P 500's 2008 drawdown from −37.0% to −21.4%,
  and roughly 15pp off the 2020 crash.
- Regime filters improve risk-adjusted returns in aggregate, and are also
  "the easiest component of a trading system to mess up" — which is why the
  thresholds here are conventional and frozen rather than fitted.
