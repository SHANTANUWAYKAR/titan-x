# Cross-Asset Feature Test

**101,516 resolved signals** · 1d · reward:risk 2.0:1 · base win rate **34.9%** vs 33.3% breakeven.

These features come from the OTHER instruments, so unlike ema/rsi/macd they are
not a transformation of the signal's own price. `pooled` mixes longs and shorts;
`long` and `short` are computed separately, because direction alone scored +7.2 pt
and turned out to be long-beta rather than signal.

Shuffled-outcome control across all features: **0.8 pt**.

| Feature | pooled | long | short | beats control? |
|---|---|---|---|---|
| `avg_corr` | +0.3 pt | +2.3 pt | -2.8 pt | **yes** |
| `breadth` | +3.4 pt | +2.3 pt | -1.3 pt | **yes** |
| `breadth_chg` | +2.7 pt | +0.3 pt | -1.1 pt | **yes** |
| `dispersion` | +0.5 pt | +2.6 pt | -3.3 pt | **yes** |
| `med_ret20` | +4.2 pt | -0.2 pt | +0.9 pt | **yes** |
| `rel_strength` | +6.9 pt | +0.2 pt | +2.4 pt | **yes** |

**At least one cross-asset feature separates outcomes within a direction.**

## Reading this honestly

- `long`/`short` are the columns that matter. A pooled spread can be produced
  entirely by directional bias, which this book already has.
- This is in-sample over the same decade everything else was fitted to.
- Bars containing both stop and target are scored LOSSES.
