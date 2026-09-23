"""
Module: engine.py
Description: Engine 40 — Data Quality validation and repair.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-08-02
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus

logger = logging.getLogger(__name__)


def _bad_tick_mask(df: pd.DataFrame) -> pd.Series:
    """True for a row that's a bad tick: high<low, any negative OHLC
    price, or an OHLC-inconsistent bar (high must be >= both open and
    close; low must be <= both open and close -- a bar where the "high"
    or "low" doesn't actually bound the open/close is corrupted, not a
    real price bar). Single source of truth for what "bad tick" means --
    validate() and repair() must count/remove EXACTLY the same rows;
    before this was factored out, repair()'s own removal mask only
    checked high>=low and open/close>0, silently leaving OHLC-
    inconsistent rows (e.g. close > high) in the "repaired" output that
    validate() itself would still flag as bad (confirmed live: a
    close-exceeds-high row survived repair() untouched)."""
    bad_high_low = df["high"] < df["low"]
    bad_negative = (df[["open", "high", "low", "close"]] < 0).any(axis=1)
    bad_ohlc = (
        (df["high"] < df[["open", "close"]].max(axis=1))
        | (df["low"] > df[["open", "close"]].min(axis=1))
    )
    return bad_high_low | bad_negative | bad_ohlc


@dataclass
class DataQualityReport:
    """Data quality validation report."""

    total_rows: int = 0
    missing_candles: int = 0
    duplicate_rows: int = 0
    bad_ticks: int = 0
    gaps: list[dict] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    quality_score: float = 100.0
    repaired: bool = False


class DataQualityEngine(BaseEngine):
    """
    Data Quality Engine — validates, cleans, and repairs market data.

    Checks: missing candles, bad ticks, duplicates, timezone, gaps.
    """

    engine_id = "e40_data_quality"
    engine_name = "Data Quality Engine"
    version = "1.0.0"

    def initialize(self) -> EngineResult:
        """Initialize data quality engine."""
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Data Quality Engine initialized")

    def health_check(self) -> EngineResult:
        """Health check."""
        return EngineResult(success=True, message="Healthy")

    def validate(
        self,
        df: pd.DataFrame,
        expected_freq: Optional[str] = None,
    ) -> EngineResult:
        """
        Validate OHLCV DataFrame quality.

        Args:
            df: OHLCV DataFrame with timestamp column.
            expected_freq: Expected candle frequency (e.g., '1D', '1H').

        Returns:
            EngineResult with DataQualityReport in data field.
        """
        try:
            report = DataQualityReport(total_rows=len(df))
            issues: list[str] = []

            required_cols = {"timestamp", "open", "high", "low", "close"}
            missing_cols = required_cols - set(df.columns)
            if missing_cols:
                issues.append(f"Missing columns: {missing_cols}")
                report.quality_score = 0.0
                report.issues = issues
                return EngineResult(success=False, data=report, message="Missing columns")

            # Duplicates
            dupes = df.duplicated(subset=["timestamp"]).sum()
            report.duplicate_rows = int(dupes)
            if dupes > 0:
                issues.append(f"{dupes} duplicate timestamps")

            # Bad ticks: high < low, negative prices, OHLC-inconsistent bars
            # (see _bad_tick_mask -- shared with repair() so both methods
            # agree on exactly what counts as a bad tick).
            report.bad_ticks = int(_bad_tick_mask(df).sum())
            if report.bad_ticks > 0:
                issues.append(f"{report.bad_ticks} bad tick(s) detected")

            # Missing values
            null_count = df[["open", "high", "low", "close"]].isnull().sum().sum()
            if null_count > 0:
                issues.append(f"{null_count} null OHLC values")

            # Gap detection
            if expected_freq and len(df) > 1:
                # reset_index is load-bearing, not cosmetic: `idx - 1`
                # below is a LABEL lookup (.loc), and sort_values does NOT
                # reset the index -- for any caller passing a DataFrame
                # whose index isn't already a plain contiguous 0..n-1
                # RangeIndex in timestamp order (e.g. anything upstream
                # dropped/filtered rows, or rows simply arrived out of
                # order), `idx - 1` after sorting points at an arbitrary,
                # unrelated row label, not "the row before this one in
                # sorted time order" -- confirmed live: a DataFrame with
                # one dropped row plus shuffled row order raised a real
                # KeyError here (caught by this method's own try/except
                # and misreported as a generic "Validation failed"
                # message, not surfaced as the indexing bug it was).
                # Resetting to a clean positional index after sorting
                # makes `idx - 1` unambiguously "the previous row in
                # sorted order" regardless of what index the caller handed
                # in.
                df_sorted = df.sort_values("timestamp").reset_index(drop=True).copy()
                df_sorted["timestamp"] = pd.to_datetime(df_sorted["timestamp"], utc=True)
                expected_delta = pd.Timedelta(expected_freq)
                diffs = df_sorted["timestamp"].diff().dropna()
                gaps = diffs[diffs > expected_delta * 1.5]
                report.missing_candles = len(gaps)
                for idx, gap in gaps.items():
                    report.gaps.append({
                        "after": str(df_sorted.loc[idx - 1, "timestamp"]),
                        "gap_duration": str(gap),
                    })
                if report.missing_candles > 0:
                    issues.append(f"{report.missing_candles} gap(s) in time series")

            # Quality score
            penalty = (
                report.duplicate_rows * 2
                + report.bad_ticks * 5
                + report.missing_candles * 1
                + null_count * 3
            )
            report.quality_score = max(0.0, 100.0 - (penalty / max(len(df), 1)) * 100)
            report.issues = issues

            return EngineResult(
                success=report.quality_score >= 70.0,
                data=report,
                message=f"Quality score: {report.quality_score:.1f}/100",
                metadata={"quality_score": report.quality_score},
            )
        except Exception as e:
            logger.error("Validation failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def repair(self, df: pd.DataFrame) -> EngineResult:
        """
        Repair common data quality issues.

        Args:
            df: OHLCV DataFrame.

        Returns:
            EngineResult with cleaned DataFrame.
        """
        try:
            cleaned = df.copy()
            cleaned["timestamp"] = pd.to_datetime(cleaned["timestamp"], utc=True)

            # Sort by timestamp FIRST: drop_duplicates(keep="last") and
            # ffill() both operate on row order, not on timestamp order --
            # on an unsorted/out-of-order input (validate() documents this
            # is a real case, not hypothetical) they'd keep an arbitrary
            # duplicate and forward-fill from an unrelated row instead of
            # the true chronological predecessor.
            cleaned = cleaned.sort_values("timestamp").reset_index(drop=True)

            # Remove duplicates
            cleaned = cleaned.drop_duplicates(subset=["timestamp"], keep="last")

            # Remove bad ticks -- same criteria validate() flags them with
            # (see _bad_tick_mask); previously a weaker, inconsistent
            # inline check that missed OHLC-inconsistent bars (e.g.
            # close > high) and negative high/low specifically.
            cleaned = cleaned[~_bad_tick_mask(cleaned)]

            # Forward-fill small gaps in OHLC (not timestamps)
            cleaned[["open", "high", "low", "close"]] = (
                cleaned[["open", "high", "low", "close"]].ffill(limit=3)
            )

            cleaned = cleaned.reset_index(drop=True)

            report = DataQualityReport(
                total_rows=len(cleaned),
                repaired=True,
                quality_score=100.0,
            )

            return EngineResult(
                success=True,
                data=cleaned,
                message=f"Repaired data: {len(cleaned)} rows",
                metadata={"report": report},
            )
        except Exception as e:
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def filter_illiquid(
        self,
        df: pd.DataFrame,
        min_avg_volume: float = 1000,
        window: int = 20,
    ) -> EngineResult:
        """
        Flag or filter illiquid periods.

        Args:
            df: OHLCV DataFrame with volume column.
            min_avg_volume: Minimum average volume threshold.
            window: Rolling window for average.

        Returns:
            EngineResult with filtered DataFrame.
        """
        if "volume" not in df.columns:
            return EngineResult(success=True, data=df, message="No volume column, skipping")

        filtered = df.copy()
        filtered["avg_volume"] = filtered["volume"].rolling(window, min_periods=1).mean()
        filtered = filtered[filtered["avg_volume"] >= min_avg_volume]
        filtered = filtered.drop(columns=["avg_volume"])

        removed = len(df) - len(filtered)
        return EngineResult(
            success=True,
            data=filtered,
            message=f"Removed {removed} illiquid candles",
        )
