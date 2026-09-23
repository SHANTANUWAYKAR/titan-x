# ML Audit — leakage, and whether the model is the limit

101,517 signals · 1d · 32 features · 6 anchored folds · base win rate 34.87%.

## 1. How much was label leakage?

These labels overlap: a 20-bar horizon means the signal at bar *i+1* shares 19
bars with the one at *i*. Training rows next to a split boundary are therefore
labelled by price action **inside** the test block. Purging drops those rows;
the embargo drops a buffer after the test block too.

| Validation | ROC-AUC |
|---|---|
| naive chronological | 0.5296 |
| **purged + embargoed** | **0.5283** |
| leakage | **+0.0013** |

Purging dropped ~20 training rows per fold.

## 2. Is the model the limit, or the data?

Five learners spanning linear to deep boosted trees, on identical purged folds.

| Model | ROC-AUC | sd across folds |
|---|---|---|
| logistic (linear) | 0.5352 | 0.0264 |
| gbt depth2 (weak) | 0.5390 | 0.0267 |
| gbt depth4 (base) | 0.5283 | 0.0194 |
| gbt depth8 (big) | 0.5199 | 0.0141 |
| random forest | 0.5346 | 0.0305 |

**Spread across all five: 0.0191 AUC.**

A spread this small means capacity is not the constraint — a linear model and a 600-tree forest extract the same amount, so the ceiling is the information in the features. More architecture cannot fix that.

## Reading this

- 0.50 AUC is a coin flip. These are probabilities of a signal WINNING, on a
  base rate near 35%, so accuracy is meaningless here — predicting 'loss'
  always would score 65%.
- Purging and embargo make results worse by design. The gap is the size of the
  lie the naive split was telling.
