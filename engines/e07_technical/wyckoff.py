"""
Module: wyckoff.py
Description: Wyckoff method detection for e07_technical -- trading range
    identification, springs and upthrusts, and a simplified phase read.
    Built for the Wyckoff topic cluster (167K tagged chunks in the
    ingested corpus), previously entirely unimplemented in this engine.

    Deliberately scoped: this does NOT attempt full Wyckoff Phase A-E
    schematic classification (accumulation/distribution sub-phases like
    Selling Climax, Automatic Rally, Secondary Test...) -- that level of
    detail is genuinely subjective even among professional Wyckoff
    analysts and isn't mechanically well-defined enough to implement
    honestly. What IS implemented -- trading range boundaries, springs,
    upthrusts, and a simplified top-level phase read -- are each backed
    by concrete, testable rules, not a claim to replicate the full
    method.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class TradingRange:
    support: float
    resistance: float
    start_index: int
    end_index: int


@dataclass
class WyckoffEvent:
    index: int
    kind: str  # "spring" or "upthrust"
    level: float  # the range boundary (support for spring, resistance for upthrust) that was swept
    wick_price: float


def detect_trading_range(df: pd.DataFrame, lookback: int = 50, atr_period: int = 14, max_atr_multiple: float = 6.0) -> TradingRange | None:
    """A trading range is identified over the most recent `lookback`
    candles if the window's total high-low span is no more than
    `max_atr_multiple` times the average true range -- Wyckoff's core
    precondition for accumulation/distribution before looking for
    springs/upthrusts.

    Deliberately ATR-relative rather than a fixed price percentage: a
    fixed cutoff (originally 5% of the window's own midpoint) turned out
    to be miscalibrated across asset/timeframe combinations -- directly
    measured on 3000 hours of real GBPUSD data, the true 50-bar
    range/midpoint ratio never exceeded 2%, so a 5% cutoff matched 100%
    of windows as "ranging," a meaningless signal. Re-measured the same
    real data in range/ATR terms instead: min=3.3x, median=8.1x,
    75th-pct=10.0x. max_atr_multiple=6.0 sits near the 20th percentile of
    that real distribution -- selective enough to flag genuinely tight
    consolidation instead of matching almost everything, without
    depending on any one asset's absolute volatility scale."""
    if len(df) < lookback + atr_period:
        return None
    window = df.tail(lookback)
    high = float(window["high"].max())
    low = float(window["low"].min())
    if high <= low:
        return None

    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift()).abs(),
        (df["low"] - df["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    atr = float(tr.rolling(atr_period).mean().iloc[-1])
    if not atr or atr <= 0:
        return None

    if (high - low) / atr > max_atr_multiple:
        return None
    return TradingRange(support=low, resistance=high, start_index=len(df) - len(window), end_index=len(df) - 1)


def detect_springs_and_upthrusts(
    df: pd.DataFrame, trading_range: TradingRange, grace_bars_after_range: int = 10
) -> tuple[list[WyckoffEvent], list[WyckoffEvent]]:
    """Within (and shortly after) a detected trading range, a Spring is a
    candle whose low wicks below the range's support but closes back
    above it -- Wyckoff's classic accumulation-phase shakeout of late
    sellers / stop-hunt below support. An Upthrust is the mirror at
    resistance.

    BUG FIX 2026-08-02: trading_range.support/resistance are the literal
    min/max low/high over the SAME bars [start_index, end_index] this
    function used to scan for springs/upthrusts -- by construction, no bar
    within that window can ever have a low below that min or a high above
    that max, making a spring/upthrust mathematically impossible to find
    there (confirmed directly: zero springs/upthrusts across thousands of
    real detected ranges on GBPUSD/EURUSD/BTC-USD/AAPL before this fix).
    A real spring necessarily undercuts a level ESTABLISHED by EARLIER
    bars and then TESTED by a LATER one -- so this now splits the range's
    own bars into an "established" portion (all but the most recent
    `grace_bars_after_range` bars, which sets the level actually being
    tested) and scans only the remaining bars (those last bars, plus any
    real bars after end_index) against that established level.
    trading_range.support/resistance themselves are unchanged (still the
    full-window min/max reported to callers, e.g. classify_phase's
    breakout check) -- only the level used for spring/upthrust testing,
    and reported on the returned WyckoffEvent, is refined."""
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    closes = df["close"].to_numpy()

    established_end = max(trading_range.start_index, trading_range.end_index - grace_bars_after_range)
    established_support = float(lows[trading_range.start_index: established_end + 1].min())
    established_resistance = float(highs[trading_range.start_index: established_end + 1].max())

    scan_start = established_end + 1
    scan_end = min(trading_range.end_index + grace_bars_after_range, len(df) - 1)

    springs: list[WyckoffEvent] = []
    upthrusts: list[WyckoffEvent] = []
    for i in range(scan_start, scan_end + 1):
        if lows[i] < established_support and closes[i] > established_support:
            springs.append(WyckoffEvent(index=i, kind="spring", level=established_support, wick_price=float(lows[i])))
        if highs[i] > established_resistance and closes[i] < established_resistance:
            upthrusts.append(WyckoffEvent(index=i, kind="upthrust", level=established_resistance, wick_price=float(highs[i])))

    return springs, upthrusts


def classify_phase(
    df: pd.DataFrame,
    trading_range: TradingRange | None,
    springs: list[WyckoffEvent],
    upthrusts: list[WyckoffEvent],
    prior_trend_lookback: int = 100,
) -> str:
    """Simplified Wyckoff phase read -- NOT a full Phase A-E schematic
    classification (see module docstring), just the mechanically
    defensible top-level read: is price currently ranging after a prior
    downtrend with a spring (accumulation-like), ranging after a prior
    uptrend with an upthrust (distribution-like), breaking out of the
    range with strength (markup/markdown), or none of the above
    ("undefined" -- no claim, deliberately the default rather than a
    forced guess)."""
    if trading_range is None:
        return "undefined"

    prior_window = df.iloc[max(0, trading_range.start_index - prior_trend_lookback):trading_range.start_index]
    if len(prior_window) < 10:
        return "undefined"
    prior_trend_up = bool(prior_window["close"].iloc[-1] > prior_window["close"].iloc[0])

    last_close = float(df["close"].iloc[-1])
    broke_up = last_close > trading_range.resistance
    broke_down = last_close < trading_range.support

    if broke_up and not prior_trend_up:
        return "markup"
    if broke_down and prior_trend_up:
        return "markdown"
    if not prior_trend_up and springs:
        return "accumulation"
    if prior_trend_up and upthrusts:
        return "distribution"
    return "undefined"
