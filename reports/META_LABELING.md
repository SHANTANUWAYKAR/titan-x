# Meta-Labelling Test

101,517 signals · 1d · reward:risk 2.0:1 · breakeven 33.3% · **chronological** split (train to 2020-09, test from 2020-09).

The primary rule is unchanged and still picks direction. A gradient-boosted
tree predicts whether each signal WINS, and low-probability signals are
skipped. Test-set only — the model never saw these rows or their neighbours.

Taking every signal: **40,607 trades, 33.82% win, -0.0458% net/trade**

| Keep signals with p >= | Trades | % kept | Win% | Gross R | Net %/trade |
|---|---|---|---|---|---|
| 0.00 | 40,607 | 100% | 33.82% | +0.0145 | -0.0458% |
| 0.35 | 21,670 | 53% | 36.15% | +0.0844 | **+0.0241%** |
| 0.40 | 8,618 | 21% | 37.17% | +0.1150 | **+0.0547%** |
| 0.45 | 3,045 | 7% | 37.44% | +0.1232 | **+0.0629%** |
| 0.50 | 1,337 | 3% | 39.49% | +0.1847 | **+0.1244%** |
| 0.55 | 607 | 1% | 39.87% | +0.1960 | **+0.1357%** |
| 0.60 | 197 | 0% | 48.22% | +0.4467 | **+0.3864%** |

**Test ROC-AUC 0.5365.** 0.50 is a coin flip; this is the single
number that says whether the secondary model learned anything at all.

Most useful features (permutation importance on the test set):

- `vwap_upper_2` +0.02397
- `_dir` +0.01510
- `cci` +0.01291
- `bb_middle` +0.01277
- `vwap_lower_1` +0.01186
- `ema_200` +0.00979
- `plus_di` +0.00946
- `ema_50` +0.00788

## Reading this

- Accuracy is the wrong metric: predicting 'loss' every time scores 66%.
  What matters is the win rate ON TRADES TAKEN, beside the trade count.
- Chronological split, never shuffled — a random split on overlapping
  financial observations leaks neighbours into the test set.
- Bars containing both stop and target are scored LOSSES.
