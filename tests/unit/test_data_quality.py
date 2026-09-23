"""
Module: test_data_quality.py
Description: Unit tests for Data Quality Engine.
Author: Shantanu Waykar
Version: 1.0.0
"""

import pandas as pd
import pytest

from project_titan_x.engines.e40_data_quality import DataQualityEngine


@pytest.fixture
def dq_engine() -> DataQualityEngine:
    engine = DataQualityEngine()
    engine.initialize()
    return engine


@pytest.fixture
def clean_df() -> pd.DataFrame:
    return pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=100, freq="D", tz="UTC"),
        "open": range(100, 200),
        "high": range(101, 201),
        "low": range(99, 199),
        "close": range(100, 200),
        "volume": [1000] * 100,
    })


def test_validate_clean_data(dq_engine: DataQualityEngine, clean_df: pd.DataFrame):
  result = dq_engine.validate(clean_df, expected_freq="1D")
  assert result.success
  assert result.data.quality_score >= 90


def test_detect_bad_ticks(dq_engine: DataQualityEngine, clean_df: pd.DataFrame):
  df = clean_df.copy()
  df.loc[5, "high"] = 50  # high < low
  result = dq_engine.validate(df)
  assert result.data.bad_ticks > 0


def test_repair_data(dq_engine: DataQualityEngine, clean_df: pd.DataFrame):
  df = clean_df.copy()
  df = pd.concat([df, df.iloc[[0]]])  # duplicate
  result = dq_engine.repair(df)
  assert result.success
  assert len(result.data) == len(clean_df)


def test_validate_gap_detection_survives_a_non_contiguous_index(dq_engine: DataQualityEngine):
    """Real regression test: sort_values() does not reset the index, and
    the gap-reporting code does a LABEL lookup (.loc[idx - 1]) on the
    sorted frame. For a DataFrame whose index isn't already a clean
    0..n-1 RangeIndex in timestamp order -- e.g. anything upstream
    dropped a row, or rows simply arrived out of order -- `idx - 1`
    pointed at an arbitrary, unrelated row label and raised a real
    KeyError (silently swallowed by validate()'s own try/except and
    misreported as a generic failure, not surfaced as the indexing bug it
    was)."""
    n = 20
    df = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC"),
        "open": range(100, 120), "high": range(101, 121),
        "low": range(99, 119), "close": range(100, 120),
    })
    df = df.drop(index=10)  # a real 2-day gap where row 10 used to be
    df = df.sample(frac=1.0, random_state=1)  # non-contiguous AND out-of-order index

    result = dq_engine.validate(df, expected_freq="1D")
    assert result.success
    assert result.data.missing_candles == 1
    assert result.data.gaps[0]["after"] == "2024-01-10 00:00:00+00:00"


def test_repair_removes_ohlc_inconsistent_bad_tick(dq_engine: DataQualityEngine):
    """Real regression test: repair()'s bad-tick removal mask used to only
    check high>=low and open/close>0 -- a row where close EXCEEDS high
    (physically impossible: the close price can never be above the bar's
    own high) passed that mask untouched, while validate() on the exact
    same row correctly flagged it as a bad tick. The two methods must
    agree on what a bad tick is."""
    df = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=3, freq="D", tz="UTC"),
        "open": [100.0, 100.0, 100.0],
        "high": [101.0, 100.0, 101.0],   # row 1's high (100) doesn't bound its own close (105) below
        "low": [99.0, 99.0, 99.0],
        "close": [100.5, 105.0, 100.5],
    })
    validated = dq_engine.validate(df)
    assert validated.data.bad_ticks == 1

    repaired = dq_engine.repair(df)
    assert repaired.success
    assert len(repaired.data) == 2
    assert 105.0 not in repaired.data["close"].values


def test_repair_removes_negative_low_even_with_positive_open_close(dq_engine: DataQualityEngine):
    """The old mask only checked open>0/close>0, missing a negative
    high/low specifically (e.g. corrupted low=-5 with high>=low still
    trivially true, and open/close both positive)."""
    df = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=2, freq="D", tz="UTC"),
        "open": [100.0, 100.0], "high": [101.0, 101.0],
        "low": [99.0, -5.0], "close": [100.5, 100.5],
    })
    repaired = dq_engine.repair(df)
    assert len(repaired.data) == 1
    assert (repaired.data["low"] >= 0).all()
