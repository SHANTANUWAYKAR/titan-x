"""Point-in-time causality guards.

WHY THIS FILE EXISTS. A function that derives a signal from a price series is
CAUSAL when its value at bar i depends only on bars <= i. The operational test:

    anything computed on the first k bars must still hold on the full series.

Prefix SILENCE is allowed -- a causal detector legitimately refuses to judge
bars it cannot confirm yet. What is never allowed is a prefix ASSERTION that
the full series later retracts, because that means bar i's answer depended on
bars after i. Stating it as "assertions survive, silence is free" is what makes
the check sharp: an earlier draft of this file excluded the last `lookback`
bars from the comparison and therefore caught nothing, because every realistic
leak in this codebase manifests exactly AT that boundary rather than in the
middle of the series.

This project's actual state when these were written (audited 2026-09-20):

  * E26 fill timing is correct: `execution_signals = signals.shift(1)` with
    fills at the next bar's OPEN, fixed 2026-08-20.
  * The IS/OOS split is chronological, not shuffled.
  * The SMC strategy plugins use centered windows but immediately `.shift(k)`
    them, which is causal and is commented as such at the call site.
  * `e07_technical.structure.find_swing_points` uses a centered window and does
    NOT shift it. It is causal anyway -- but only by accident: pandas defaults
    `min_periods` to the full window, so the final `lookback` bars are NaN and
    nothing can be reported there. Pass `min_periods=1` and that protection
    disappears silently, with no test to catch it.

That last case is the reason this file exists: it pins a property that
currently holds by luck, so breaking it fails loudly instead of quietly
improving every backtest in the repo.

Both guards carry a negative control. A check that nothing can fail is not a
check, and the controls here have already earned their place by rejecting two
earlier, weaker versions of these tests.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from project_titan_x.engines.e07_technical.structure import SwingKind, find_swing_points

LOOKBACKS = [3, 5, 8]


def _ohlc(n: int = 220, seed: int = 7) -> pd.DataFrame:
    """Deterministic OHLC ending on a decisive new high.

    The trailing ramp is deliberate. Both leak classes below only misbehave on
    the final bars, so a fixture that happens to end mid-range would let a
    broken implementation pass by luck -- which is how the first version of
    these controls failed.
    """
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 1.0, n))
    high = close + np.abs(rng.normal(0, 0.6, n))
    low = close - np.abs(rng.normal(0, 0.6, n))
    # Force the last 3 bars to print successive highs above everything prior.
    high[-3:] = high.max() + np.array([1.0, 2.0, 3.0])
    close[-3:] = high[-3:] - 0.2
    low[-3:] = high[-3:] - 1.0
    open_ = close + rng.normal(0, 0.3, n)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close,
         "volume": rng.integers(1_000, 10_000, n)},
        index=pd.date_range("2020-01-01", periods=n, freq="D"),
    )


def _swings(df: pd.DataFrame, lookback: int) -> set[tuple[int, str]]:
    return {(p.index, p.kind.value) for p in find_swing_points(df, lookback)}


# ---------------------------------------------------------------------------
# The guards
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("lookback", LOOKBACKS)
@pytest.mark.parametrize("k", [120, 160, 200])
def test_prefix_assertions_survive_more_data(lookback: int, k: int) -> None:
    """Every swing reported on the first k bars must survive the full series.

    No tail exclusion: silence costs nothing, so a causal detector passes
    trivially, while any detector that spoke about a bar it could not yet
    confirm is caught the moment the later bars contradict it.
    """
    df = _ohlc()
    retracted = _swings(df.iloc[:k], lookback) - _swings(df, lookback)
    assert not retracted, (
        f"lookback={lookback}, prefix={k}: {sorted(retracted)[:5]} were reported "
        f"on the first {k} bars but are absent once the rest of the series is "
        f"known. An answer that changes when future bars arrive was reading them."
    )


@pytest.mark.parametrize("lookback", LOOKBACKS)
def test_nothing_reported_in_the_unconfirmable_tail(lookback: int) -> None:
    """Nothing may be reported in the final `lookback` bars.

    Confirming a swing at index i needs data through i+lookback, so any report
    past n-1-lookback could not have been known at the time. This is the exact
    invariant that `min_periods=1` would destroy.
    """
    df = _ohlc()
    n = len(df)
    late = sorted(i for (i, _kind) in _swings(df, lookback) if i > n - 1 - lookback)
    assert not late, (
        f"lookback={lookback}: swings at {late} lie inside the final {lookback} "
        f"bars (indices > {n - 1 - lookback}) and could not have been confirmed yet."
    )


def test_fixture_actually_produces_swings() -> None:
    """Stops both guards above from passing vacuously on an empty result."""
    df = _ohlc()
    pts = find_swing_points(df, 5)
    assert len(pts) >= 5, f"only {len(pts)} swings -- the guards would be vacuous"
    assert {p.kind for p in pts} <= {SwingKind.HIGH, SwingKind.LOW}
    assert pts == sorted(pts, key=lambda p: p.index), "swing points must be index-ordered"


# ---------------------------------------------------------------------------
# Negative controls -- each guard must reject a real leak
# ---------------------------------------------------------------------------

def _leak_min_periods(df: pd.DataFrame, lookback: int) -> set[int]:
    """The one-keyword regression: center=True with min_periods=1.

    The window shrinks at the edge instead of going NaN, so the final bars get
    judged against past data alone and are reported as swings they have not
    earned.
    """
    w = lookback * 2 + 1
    roll = df["high"].rolling(w, center=True, min_periods=1).max()
    return {i for i in range(len(df)) if df["high"].iloc[i] == roll.iloc[i]}


def test_tail_guard_rejects_min_periods_leak() -> None:
    df, lookback = _ohlc(), 5
    n = len(df)
    late = [i for i in _leak_min_periods(df, lookback) if i > n - 1 - lookback]
    assert late, "min_periods=1 stayed silent in the tail -- the tail guard is too weak"
    real_late = [i for (i, _k) in _swings(df, lookback) if i > n - 1 - lookback]
    assert not real_late, "the real implementation leaked into the tail"


def _leak_full_sample_threshold(high: pd.Series) -> set[int]:
    """Non-causal via a FULL-SAMPLE statistic: threshold on the series' own mean.

    The tail guard cannot see this -- it reports nothing unusual at the edge --
    but every assertion depends on bars that had not happened yet, so answers
    move as soon as the series is truncated. The classic normalise-then-split
    mistake, and the reason the two guards here are complementary.
    """
    thresh = high.mean()
    return {i for i in range(len(high)) if high.iloc[i] > thresh}


def test_prefix_guard_rejects_full_sample_leak() -> None:
    """The prefix guard must catch a leak the tail guard structurally cannot.

    Uses a strictly ASCENDING series rather than the shared OHLC fixture, on
    purpose: with a random walk the truncated mean can land either side of the
    full-sample mean, so the control would pass or fail by luck rather than by
    logic. Ascending data makes the direction provable -- the prefix mean is
    necessarily below the full mean, so the prefix necessarily over-reports and
    must retract.
    """
    high = pd.Series(np.arange(200, dtype=float))
    k = 120

    full = _leak_full_sample_threshold(high)
    prefix = _leak_full_sample_threshold(high.iloc[:k])
    retracted = prefix - full
    assert retracted, (
        "the full-sample leak survived truncation unchanged -- the prefix "
        "comparison is too weak to catch it"
    )
    # Exactly the bars between the two means: above the prefix mean (59.5),
    # below the full mean (99.5).
    assert min(retracted) == 60 and max(retracted) == 99, sorted(retracted)[:5]

    # The real implementation retracts nothing under the same style of check.
    df = _ohlc()
    assert not (_swings(df.iloc[:160], 5) - _swings(df, 5))
