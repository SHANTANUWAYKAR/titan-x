"""
Module: ml_validation.py
Description: Purged, embargoed walk-forward -- and a test of whether the model
    is the limit or the data is.

    THE LEAK A CHRONOLOGICAL SPLIT DOES NOT CLOSE. These labels overlap. A
    signal at bar i is labelled by what happens over the next 20 bars, and the
    signal at bar i+1 shares 19 of those bars. So a training sample taken just
    before the split boundary is labelled by price action that happens INSIDE
    the test period. The split looks clean by timestamp and is not clean by
    information.

    Lopez de Prado's remedy, implemented here:

      PURGE   drop any training sample whose label window overlaps the test
              window at all. With a 20-bar horizon that is the last 20 bars of
              every training block.
      EMBARGO drop a further buffer immediately AFTER the test block before
              training resumes, because serial correlation means bars just past
              the test set still carry its information.

    Both make results WORSE, not better. That is the point -- the gap between
    the naive and purged numbers is the size of the lie the naive split was
    telling.

    IS IT THE MODEL OR THE DATA? A second question this answers. If a bigger
    model, a smaller model and a linear model all land on the same ROC-AUC, the
    ceiling is the information in the features, not the learner -- and no amount
    of architecture fixes a data problem. Measured here rather than asserted.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def purged_indices(
    n: int, train_end: int, test_start: int, test_end: int,
    *, horizon: int, embargo: int,
) -> np.ndarray:
    """Training rows that are safe to use for a given test block.

    Everything before `train_end` minus the final `horizon` rows (their labels
    reach into the test block), and everything after `test_end` plus `embargo`
    rows of buffer.
    """
    left = np.arange(0, max(train_end - horizon, 0))
    right = np.arange(min(test_end + embargo, n), n)
    return np.concatenate([left, right])


def purged_walk_forward(
    X: pd.DataFrame, y: np.ndarray, *, folds: int, horizon: int,
    embargo: Optional[int] = None, model_fn=None,
) -> dict[str, Any]:
    """Anchored folds with purge + embargo. Returns per-fold AUC and pooled.

    `model_fn()` must return a fresh unfitted sklearn-style classifier; a new
    one is built per fold so nothing carries across.
    """
    from sklearn.metrics import roc_auc_score

    n = len(y)
    if embargo is None:
        embargo = horizon
    bounds = [int(n * (i + 1) / (folds + 1)) for i in range(folds)]
    aucs, sizes, dropped = [], [], []
    preds = np.full(n, np.nan)

    for k, cut in enumerate(bounds):
        end = bounds[k + 1] if k + 1 < len(bounds) else n
        tr_idx = purged_indices(n, cut, cut, end, horizon=horizon, embargo=embargo)
        # Anchored: only history, never the future block.
        tr_idx = tr_idx[tr_idx < cut]
        te_idx = np.arange(cut, end)
        if len(tr_idx) < 500 or len(te_idx) < 100:
            continue
        naive_train = cut
        dropped.append(naive_train - len(tr_idx))

        clf = model_fn()
        clf.fit(X.iloc[tr_idx], y[tr_idx])
        p = clf.predict_proba(X.iloc[te_idx])[:, 1]
        preds[te_idx] = p
        if len(np.unique(y[te_idx])) > 1:
            aucs.append(float(roc_auc_score(y[te_idx], p)))
            sizes.append(len(te_idx))

    if not aucs:
        return {"folds": 0}
    return {
        "folds": len(aucs),
        "auc_per_fold": aucs,
        "auc_weighted": float(np.average(aucs, weights=sizes)),
        "auc_std": float(np.std(aucs)),
        "rows_purged_per_fold": dropped,
        "preds": preds,
    }


def model_zoo() -> dict[str, Any]:
    """Deliberately spans capacity, to separate a model limit from a data limit.

    If a 6-deep boosted forest, a depth-2 stump ensemble and a plain logistic
    regression all land in the same place, the features are the ceiling.
    """
    from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    return {
        "logistic (linear)": lambda: make_pipeline(
            StandardScaler(), LogisticRegression(max_iter=1000, C=0.1)),
        "gbt depth2 (weak)": lambda: HistGradientBoostingClassifier(
            max_depth=2, max_iter=150, learning_rate=0.05, random_state=7),
        "gbt depth4 (base)": lambda: HistGradientBoostingClassifier(
            max_depth=4, max_iter=250, learning_rate=0.05, random_state=7),
        "gbt depth8 (big)": lambda: HistGradientBoostingClassifier(
            max_depth=8, max_iter=600, learning_rate=0.05, random_state=7),
        "random forest": lambda: RandomForestClassifier(
            n_estimators=300, max_depth=10, n_jobs=-1, random_state=7),
    }
