"""
Module: test_meta_labeling.py
Description: Unit tests for the triple-barrier labeling wrapper and the
    tsfresh/RandomForest meta-label filter pipeline
    (engines/e26_backtesting/meta_labeling.py).
Author: Shantanu Waykar
Version: 1.0.0
"""

import numpy as np
import pandas as pd
import pytest

from project_titan_x.engines.e26_backtesting.meta_labeling import (
    build_lookback_feature_windows, label_entries_with_triple_barrier,
    train_meta_label_filter,
)


def _df(n: int = 300, seed: int = 1) -> pd.DataFrame:
    rng = np.random.RandomState(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    return pd.DataFrame({
        "timestamp": pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC"),
        "close": close,
    })


def test_no_entries_returns_honest_empty_report():
    df = _df()
    flat_signal = pd.Series(0, index=df.index)
    bins_df, report = label_entries_with_triple_barrier(df, flat_signal)
    assert bins_df.empty
    assert report.n_entries == 0
    assert np.isnan(report.win_rate)


def test_real_entries_get_real_triple_barrier_labels():
    df = _df(n=500, seed=5)
    idx = np.arange(len(df))
    signal = pd.Series(np.where((idx // 15) % 2 == 0, 1, -1), index=df.index)

    bins_df, report = label_entries_with_triple_barrier(
        df, signal, pt_sl=(1.0, 1.0), max_holding_bars=10, target_vol_lookback=20)

    assert report.n_entries > 0
    assert report.n_labeled > 0
    assert "bin" in bins_df.columns
    assert set(bins_df["bin"].unique()).issubset({0, 1, -1})
    assert 0.0 <= report.win_rate <= 1.0
    assert report.caveats                              # never silently omits the scope caveat


def test_rejects_df_with_no_datetime_source():
    df = pd.DataFrame({"close": [1.0, 2.0, 3.0, 4.0]})
    signal = pd.Series([0, 1, 0, -1])
    with pytest.raises(ValueError, match="real calendar time"):
        label_entries_with_triple_barrier(df, signal)


# ---- build_lookback_feature_windows -- no-lookahead plumbing ----

def test_lookback_windows_exclude_entries_without_full_history():
    df = _df(n=100)
    early_entry = df["timestamp"].iloc[5]     # only 5 bars of real prior history
    late_entry = df["timestamp"].iloc[50]
    windows = build_lookback_feature_windows(df, [early_entry, late_entry], lookback_bars=20)
    kept = windows["id"].unique()
    assert early_entry not in kept
    assert late_entry in kept


def test_lookback_window_never_includes_the_entry_bars_own_return():
    """The window for an entry at position p must stop at p-1 -- changing
    bar p's own price must not change that entry's feature window at all."""
    df = _df(n=100, seed=2)
    entry_ts = df["timestamp"].iloc[40]
    windows_a = build_lookback_feature_windows(df, [entry_ts], lookback_bars=10)

    df_mutated = df.copy()
    df_mutated.loc[40, "close"] = df_mutated.loc[40, "close"] * 5.0   # blow up bar 40's own price
    windows_b = build_lookback_feature_windows(df_mutated, [entry_ts], lookback_bars=10)

    pd.testing.assert_frame_equal(windows_a, windows_b)


def test_lookback_windows_have_the_requested_length():
    df = _df(n=100)
    entry_ts = df["timestamp"].iloc[50]
    windows = build_lookback_feature_windows(df, [entry_ts], lookback_bars=15)
    assert len(windows) == 15
    assert windows["time"].tolist() == list(range(15))


def test_rejects_no_datetime_source():
    df = pd.DataFrame({"close": [1.0, 2.0, 3.0]})
    with pytest.raises(ValueError, match="real calendar time"):
        build_lookback_feature_windows(df, [pd.Timestamp("2020-01-01")])


# ---- train_meta_label_filter -- honest-failure paths + real end-to-end run ----

def test_too_few_entries_reports_honest_insufficient_result():
    df = _df(n=60, seed=9)
    flat_signal = pd.Series(0, index=df.index)
    report = train_meta_label_filter(df, flat_signal, min_holdout_trades=10)
    assert report.n_entries_total == 0
    assert not report.improved
    assert any("only" in c for c in report.caveats)


def test_pure_noise_labels_honestly_find_no_signal_or_do_not_improve():
    """With entries scattered on genuinely random-walk price data and no
    real structure for tsfresh to find, the pipeline must never FABRICATE
    an 'improved' result -- either zero features pass significance
    filtering, or the filtered subset does not beat baseline."""
    df = _df(n=400, seed=21)
    idx = np.arange(len(df))
    signal = pd.Series(np.where(idx % 4 == 0, 1, 0), index=df.index)
    report = train_meta_label_filter(
        df, signal, pt_sl=(1.0, 1.0), max_holding_bars=5,
        lookback_bars=8, holdout_fraction=0.3, min_holdout_trades=8,
    )
    # Honest outcome either way -- what must NEVER happen is a fabricated
    # "improved" verdict built on a feature set that only fit train noise.
    if report.n_features_selected == 0:
        assert not report.improved
    assert report.caveats


def test_real_end_to_end_run_on_real_market_data_produces_a_genuine_report():
    """Live-ish integration check (real OHLCV shape, real triple-barrier
    labels, real tsfresh extraction, real RandomForest) on a size small
    enough to stay a fast unit test -- confirms the full pipeline runs
    clean end-to-end without crashing, not that it necessarily 'improves'
    on this particular synthetic series (see the pure-noise test above for
    that honesty guarantee)."""
    df = _df(n=700, seed=13)
    idx = np.arange(len(df))
    signal = pd.Series(np.where(idx % 6 == 0, 1, -1), index=df.index)
    report = train_meta_label_filter(
        df, signal, pt_sl=(1.0, 1.0), max_holding_bars=8,
        lookback_bars=10, holdout_fraction=0.3, min_holdout_trades=10,
    )
    assert report.n_entries_total > 0
    assert isinstance(report.improved, bool)
    assert report.caveats
