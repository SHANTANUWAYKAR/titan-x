"""
Module: meta_labeling.py
Description: Triple-barrier labeling of a REAL primary strategy's own
    entry signals, PLUS a real, validated secondary (meta) model trained
    on top of those labels -- REPO_REFERENCE.md Tier 1/2 (mlfinpy,
    tsfresh), explicitly framed there as "foundation for meta-labeling"
    (Tier 1) that Tier 2 says to build out "when you start meta-labeling".

    TWO STAGES, BOTH REAL.
      1. `label_entries_with_triple_barrier` -- did this primary signal's
         entry actually hit its profit target before its stop or a time
         limit, per Lopez de Prado's triple-barrier method.
      2. `train_meta_label_filter` -- tsfresh-extracted, hypothesis-test-
         filtered lookback-window features feeding a RandomForestClassifier,
         validated on a genuine chronological held-out split (see that
         function's own docstring for the full pipeline and honesty
         discipline). NOT wired into e51_signals or any live decision --
         that would need this same validation repeated per-asset/
         timeframe and a real design decision about how a filtered-out
         primary signal should be surfaced, deliberately left as a
         further, explicit next step.

    WHY mlfinpy AND NOT A HAND-ROLLED VERSION. Triple-barrier labeling
    has real edge cases (which barrier is touched first intrabar, how a
    vertical/time barrier interacts with price barriers, meta-label sign
    convention) that a paid, closed-source original (mlfinlab) exists
    specifically to get right; mlfinpy is the MIT-licensed reimplementation
    (see requirements.txt's own note: "mlfinlab relicensed closed/
    commercial, use mlfinpy"). Same "use the real library for real
    numerical subtlety" precedent as GARCH/statsmodels elsewhere in this
    project.

    VERTICAL BARRIER, BUILT BY BAR COUNT NOT CALENDAR TIME. mlfinpy's own
    `add_vertical_barrier` offsets by calendar days/hours -- this
    platform's own bars are irregular (weekends, exchange holidays,
    partial sessions), so a calendar-time offset does not reliably mean
    "N bars held". Built directly here instead: `max_holding_bars` steps
    forward through `close`'s own index, which is what "held for N bars"
    actually means regardless of the underlying calendar.

    TARGET (the pt_sl scale). Uses REAL trailing realized volatility
    (rolling std of close-to-close returns), not a fabricated constant --
    the same "no fixed lookback source" as `e13_derivatives`' own 30-day
    realized-vol convention.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class MetaLabelReport:
    n_entries: int
    n_labeled: int
    n_dropped: int
    win_rate: float                     # fraction of labeled entries with bin == 1
    mean_return: float                  # mean realized return across labeled entries
    label_counts: dict = field(default_factory=dict)
    caveats: list = field(default_factory=list)


CAVEATS = [
    "Labels only -- no secondary (meta) model has been trained or validated on "
    "them. Whether filtering the primary signal by a meta-model demonstrably "
    "improves precision on real held-out data is a separate, larger analysis "
    "(Rule 3), not answered by this label distribution alone.",
]


def label_entries_with_triple_barrier(
    df: pd.DataFrame,
    signal: pd.Series,
    pt_sl: tuple[float, float] = (1.0, 1.0),
    max_holding_bars: int = 10,
    target_vol_lookback: int = 20,
    min_ret: float = 0.0,
) -> tuple[pd.DataFrame, MetaLabelReport]:
    """Real triple-barrier labels for every real entry bar in `signal`.

    Args:
        df: OHLCV with a 'close' column, real DatetimeIndex or a
            'timestamp' column (mlfinpy needs a real, monotonically
            increasing index to reason about barrier order).
        signal: -1/0/1 direction series from a real strategy_fn, same
            convention as engines/e26_backtesting.run_backtest expects.
        pt_sl: (profit-take, stop-loss) multiples of the rolling target
            volatility -- (1.0, 1.0) means a symmetric barrier at
            +-1 sigma, matching the "no fabricated asymmetry" default.
        max_holding_bars: vertical (time) barrier, in BAR COUNT (see
            module docstring for why not calendar time).
        target_vol_lookback: window for the real trailing realized-vol
            estimate that scales the barriers.
        min_ret: mlfinpy's own minimum target return floor -- entries
            with a target below this are dropped as too illiquid/flat to
            label meaningfully. 0.0 (off) unless a caller has a reason.

    Returns:
        (bins_df, report) -- `bins_df` is mlfinpy's own real per-entry
        DataFrame (columns include `ret`, `trgt`, `bin`); `report`
        summarizes it. `bin == 1` means the primary signal's own stated
        direction hit its profit-take before its stop-loss or time
        limit -- the real meta-label a secondary model would train on.
    """
    import mlfinpy.labeling as lb

    close = df["close"]
    if not isinstance(close.index, pd.DatetimeIndex):
        if "timestamp" in df.columns:
            close = pd.Series(close.to_numpy(), index=pd.DatetimeIndex(df["timestamp"]))
        else:
            raise ValueError("df needs a DatetimeIndex or a 'timestamp' column -- "
                              "triple-barrier order depends on real calendar time")
    sig = pd.Series(signal.to_numpy(), index=close.index) if not isinstance(
        signal.index, pd.DatetimeIndex) else signal

    entry_mask = (sig != 0) & (sig != sig.shift(1).fillna(0))
    t_events = close.index[entry_mask.to_numpy()]
    n_entries = len(t_events)
    if n_entries == 0:
        return pd.DataFrame(), MetaLabelReport(
            n_entries=0, n_labeled=0, n_dropped=0, win_rate=float("nan"),
            mean_return=float("nan"), caveats=CAVEATS + ["no real entries in this signal"])

    target = close.pct_change().rolling(target_vol_lookback).std()
    target = target.reindex(t_events).dropna()
    t_events = target.index                     # drop entries with no warmed-up vol yet

    pos = close.index.get_indexer(t_events)
    vert_pos = np.clip(pos + max_holding_bars, 0, len(close) - 1)
    vertical_barrier_times = pd.Series(close.index[vert_pos], index=t_events)

    side_prediction = sig.reindex(t_events)

    events = lb.get_events(
        close=close, t_events=pd.Series(t_events, index=t_events), pt_sl=list(pt_sl),
        target=target, min_ret=min_ret, num_threads=1,
        vertical_barrier_times=vertical_barrier_times, side_prediction=side_prediction,
        verbose=False,
    )
    bins_df = lb.get_bins(events, close)

    n_labeled = len(bins_df)
    n_dropped = n_entries - n_labeled
    win_rate = float((bins_df["bin"] == 1).mean()) if n_labeled else float("nan")
    mean_return = float(bins_df["ret"].mean()) if n_labeled else float("nan")
    counts = bins_df["bin"].value_counts().to_dict() if n_labeled else {}

    report = MetaLabelReport(
        n_entries=n_entries, n_labeled=n_labeled, n_dropped=n_dropped,
        win_rate=win_rate, mean_return=mean_return,
        label_counts={str(k): int(v) for k, v in counts.items()}, caveats=list(CAVEATS),
    )
    return bins_df, report


def build_lookback_feature_windows(
    df: pd.DataFrame,
    entry_timestamps,
    lookback_bars: int = 20,
    value_col: str = "close",
) -> pd.DataFrame:
    """Long-format (id, time, value) window of real, STRICTLY-PAST returns
    before each real entry timestamp -- the shape tsfresh's
    `extract_features`/`extract_relevant_features` need.

    NO LOOKAHEAD: the window for entry at position `pos` covers bars
    `[pos - lookback_bars, pos - 1]` -- the entry bar's OWN close-to-close
    return is excluded, since a signal firing AT that bar's close could
    not have known that bar's own return in advance of firing. `id` is
    the real entry TIMESTAMP itself (not a synthetic counter), so the
    output aligns directly with `label_entries_with_triple_barrier`'s own
    `bins_df.index` -- no separate id<->timestamp mapping to keep in sync.

    Entries without a full `lookback_bars` of real prior history (too
    close to the start of `df`) are silently excluded, not padded with a
    fabricated value.
    """
    if isinstance(df.index, pd.DatetimeIndex):
        idx = df.index
    elif "timestamp" in df.columns:
        idx = pd.DatetimeIndex(df["timestamp"])
    else:
        raise ValueError("df needs a DatetimeIndex or a 'timestamp' column -- "
                          "window order depends on real calendar time")

    values = pd.Series(df[value_col].to_numpy(), index=idx).pct_change()
    entry_timestamps = pd.DatetimeIndex(entry_timestamps)
    positions = idx.get_indexer(entry_timestamps)

    rows = []
    for ts, pos in zip(entry_timestamps, positions):
        if pos < lookback_bars + 1:
            continue
        window = values.iloc[pos - lookback_bars: pos].to_numpy()
        for t, v in enumerate(window):
            rows.append((ts, t, float(v)))
    return pd.DataFrame(rows, columns=["id", "time", "value"])


@dataclass
class MetaLabelFilterReport:
    n_entries_total: int
    n_train: int
    n_holdout: int
    n_features_selected: int
    baseline_win_rate: float        # taking every held-out entry (the unfiltered primary signal)
    baseline_mean_return: float
    filtered_win_rate: float        # taking only held-out entries the secondary model predicts bin=1
    filtered_mean_return: float
    filtered_n_trades: int
    filtered_coverage: float        # fraction of held-out entries the filter would still take
    improved: bool                  # filtered beats baseline AND has enough trades to trust
    caveats: list = field(default_factory=list)


def train_meta_label_filter(
    df: pd.DataFrame,
    signal: pd.Series,
    pt_sl: tuple[float, float] = (1.0, 1.0),
    max_holding_bars: int = 10,
    target_vol_lookback: int = 20,
    lookback_bars: int = 20,
    holdout_fraction: float = 0.3,
    min_holdout_trades: int = 10,
    random_state: int = 42,
) -> MetaLabelFilterReport:
    """Train and VALIDATE a secondary (meta) model that filters a primary
    strategy's own real entries -- the follow-up this module's own earlier
    docstring flagged as deliberately deferred.

    PIPELINE, real at every step:
      1. Real triple-barrier labels from `label_entries_with_triple_barrier`.
      2. Real lookback-window RETURN features (`build_lookback_feature_windows`,
         no lookahead) per entry.
      3. tsfresh `extract_relevant_features` on the TRAIN split ONLY --
         its own built-in hypothesis-test filtering (Fisher-exact for a
         binary target/binary feature, Mann-Whitney otherwise) selects
         which of its ~750 candidate features are even worth keeping,
         computed exclusively from train data so the held-out split never
         leaks into feature selection.
      4. A RandomForestClassifier (shallow, class-balanced -- meta-labels
         are the AFML-textbook case for a simple, hard-to-overfit
         secondary model, not a deep one) fit on those selected features.
      5. The SAME selected features re-extracted on the held-out split
         (never re-selected there) and scored.

    CHRONOLOGICAL SPLIT, NEVER RANDOM. `holdout_fraction` of entries BY
    TIME are held out -- a random split would let the model see feature
    windows from AFTER some held-out entries during training (since
    lookback windows from nearby entries overlap in calendar time),
    which is the same class of walk-forward violation this project's
    own E26/E27 discipline exists to prevent everywhere else.

    HONEST VERDICT (Rule 3). `improved` is True only if the filtered
    subset's mean realized return beats the UNFILTERED baseline's AND
    clears `min_holdout_trades` -- a filter that only "wins" by taking 2
    trades is not a real result. This is reported, not wired into
    e51_signals or any live decision -- doing that would need this same
    validation repeated per-asset/per-timeframe and a real decision about
    how a filtered-out primary signal should be surfaced (silently
    dropped vs. shown with a lower confidence), which is a separate,
    larger design choice.
    """
    from sklearn.ensemble import RandomForestClassifier
    from tsfresh import extract_features, extract_relevant_features
    from tsfresh.utilities.dataframe_functions import impute

    insufficient = MetaLabelFilterReport(
        n_entries_total=0, n_train=0, n_holdout=0, n_features_selected=0,
        baseline_win_rate=float("nan"), baseline_mean_return=float("nan"),
        filtered_win_rate=float("nan"), filtered_mean_return=float("nan"),
        filtered_n_trades=0, filtered_coverage=float("nan"), improved=False,
    )

    bins_df, _ = label_entries_with_triple_barrier(
        df, signal, pt_sl=pt_sl, max_holding_bars=max_holding_bars,
        target_vol_lookback=target_vol_lookback)
    if len(bins_df) < min_holdout_trades * 2:
        insufficient.caveats = CAVEATS + [
            f"only {len(bins_df)} labeled entries; need at least {min_holdout_trades * 2}"]
        return insufficient

    windows = build_lookback_feature_windows(df, bins_df.index, lookback_bars=lookback_bars)
    kept_ids = pd.DatetimeIndex(windows["id"].unique()).sort_values()
    bins_df = bins_df.loc[bins_df.index.isin(kept_ids)].sort_index()
    n_total = len(bins_df)
    if n_total < min_holdout_trades * 2:
        insufficient.caveats = CAVEATS + [
            f"only {n_total} entries had a full {lookback_bars}-bar lookback window"]
        return insufficient

    n_holdout = max(min_holdout_trades, int(round(n_total * holdout_fraction)))
    n_train = n_total - n_holdout
    if n_train < min_holdout_trades:
        insufficient.caveats = CAVEATS + [
            f"only {n_train} train entries after reserving {n_holdout} for holdout"]
        return insufficient

    train_ids = bins_df.index[:n_train]
    holdout_ids = bins_df.index[n_train:]

    train_windows = windows[windows["id"].isin(train_ids)]
    y_train_full = bins_df.loc[train_ids, "bin"].astype(int)

    X_train = extract_relevant_features(
        train_windows, y_train_full, column_id="id", column_sort="time", column_value="value",
        n_jobs=1, disable_progressbar=True, show_warnings=False,
        fdr_level=0.05, ml_task="classification",
    )
    if X_train.shape[1] == 0 or X_train.empty:
        insufficient.n_entries_total = n_total
        insufficient.n_train = n_train
        insufficient.n_holdout = n_holdout
        insufficient.caveats = CAVEATS + [
            "no candidate feature passed tsfresh's significance filtering on the train split "
            "-- honest result: this lookback window carries no detectable signal for these "
            "labels, not a pipeline failure"]
        return insufficient
    X_train = impute(X_train)
    y_train = y_train_full.reindex(X_train.index)

    clf = RandomForestClassifier(
        n_estimators=200, max_depth=4, min_samples_leaf=5,
        class_weight="balanced", random_state=random_state, n_jobs=1,
    )
    clf.fit(X_train, y_train)

    holdout_windows = windows[windows["id"].isin(holdout_ids)]
    X_holdout_full = extract_features(
        holdout_windows, column_id="id", column_sort="time", column_value="value",
        n_jobs=1, disable_progressbar=True, show_warnings=False,
    )
    X_holdout_full = impute(X_holdout_full)
    X_holdout = X_holdout_full.reindex(columns=X_train.columns, fill_value=0.0)

    preds = pd.Series(clf.predict(X_holdout), index=X_holdout.index)
    y_holdout = bins_df.loc[X_holdout.index, "bin"].astype(int)
    ret_holdout = bins_df.loc[X_holdout.index, "ret"]

    baseline_win_rate = float((y_holdout == 1).mean())
    baseline_mean_return = float(ret_holdout.mean())

    take_mask = preds == 1
    filtered_n = int(take_mask.sum())
    if filtered_n > 0:
        filtered_win_rate = float((y_holdout[take_mask] == 1).mean())
        filtered_mean_return = float(ret_holdout[take_mask].mean())
    else:
        filtered_win_rate = float("nan")
        filtered_mean_return = float("nan")

    improved = filtered_n >= min_holdout_trades and filtered_mean_return > baseline_mean_return

    return MetaLabelFilterReport(
        n_entries_total=n_total, n_train=n_train, n_holdout=len(X_holdout),
        n_features_selected=X_train.shape[1],
        baseline_win_rate=baseline_win_rate, baseline_mean_return=baseline_mean_return,
        filtered_win_rate=filtered_win_rate, filtered_mean_return=filtered_mean_return,
        filtered_n_trades=filtered_n,
        filtered_coverage=float(filtered_n / len(X_holdout)) if len(X_holdout) else float("nan"),
        improved=improved,
        caveats=CAVEATS + [
            f"held-out result measured on a SINGLE chronological split of {len(X_holdout)} "
            "entries -- a first real signal, not a cross-validated final verdict. Re-running "
            "with a different holdout_fraction or on a different asset can legitimately move "
            "these numbers; treat consistency across several such runs as the real bar, not "
            "one run's result alone."],
    )
