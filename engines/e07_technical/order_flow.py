"""
Module: order_flow.py
Description: OHLCV-based order-flow PROXY for e07_technical -- cumulative
    volume delta (CVD), CVD/price divergence, and absorption detection.

    Adapted from mahmoud20138/OrderFlow-Analysis-Pro's real delta/
    absorption methodology (itself built on Fabio Nardo's order-flow
    trading approach -- see that repo's own analytics/delta.py and
    patterns/absorption.py docstrings, fetched and read directly, not
    assumed). That repo's delta engine uses GENUINE trade-by-trade
    buy/sell-tagged ticks (Bybit's real WebSocket trade feed, or MT5 tick
    data) -- this platform has no such feed for its OHLCV-sourced assets
    (yfinance/Dukascopy bars carry no aggressor-side info at all, same
    honest gap E11 Microstructure's own docstring already states: "no
    free order book/Level 2 feed exists").

    So every function here computes an HONEST APPROXIMATION of buy/sell
    delta from each bar's Close Location Value (CLV) -- the same
    "distribute volume across the bar" honesty standard as this engine's
    own volume_profile.py (see compute_volume_profile's docstring): a
    candle closing near its high is read as more buyer-dominated, near
    its low as more seller-dominated. This is the same core idea behind
    the Chaikin Money Flow indicator's Money Flow Multiplier -- a
    standard, recognized OHLCV-only proxy, but genuinely NOT a substitute
    for real tape reading. Never call this "order flow" without the
    caveat; it's an order-flow-INFORMED read on bars, not ticks.

    Real order flow (true buy/sell-tagged delta, no approximation) IS
    freely available for this platform's 2 crypto assets via Bybit's
    public trade WebSocket -- flagged in CLAUDE.md as a real, bigger
    future upgrade, not built here since it needs a live-streaming
    ingestion architecture this platform doesn't currently have (E02 is
    REST/batch-fetch only, no persistent WebSocket consumer anywhere in
    the codebase).
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import numpy as np
import pandas as pd

from project_titan_x.engines.e07_technical.structure import SwingKind, SwingPoint
from project_titan_x.engines.e07_technical.volume_profile import _resolve_volume


def bar_delta_approx(df: pd.DataFrame) -> pd.Series:
    """Close Location Value (CLV)-based per-bar delta:
    delta = volume * (2*(close-low)/(high-low) - 1), ranging from
    -volume (closed at the low -- read as all selling pressure) to
    +volume (closed at the high -- read as all buying pressure). Flat
    bars (high == low) get delta=0, not a divide-by-zero. Returns an
    all-zero Series (not None) when no usable volume column exists, so
    callers can sum/compare it without a None-check at every call site --
    matches this module's own compute_cumulative_delta and
    detect_absorption, which both treat an all-zero delta series as "no
    real signal available" rather than raising."""
    volume = _resolve_volume(df)
    if volume is None:
        return pd.Series(0.0, index=df.index)
    high, low, close = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    rng = high - low
    safe_rng = np.where(rng > 0, rng, 1.0)  # avoids a real (if harmless) divide-by-zero warning; result discarded below anyway
    clv = np.where(rng > 0, (2 * (close - low) / safe_rng) - 1, 0.0)
    delta = clv * volume.to_numpy()
    return pd.Series(delta, index=df.index)


def compute_cumulative_delta(df: pd.DataFrame) -> pd.Series:
    """Running sum of bar_delta_approx -- CVD. Rising CVD = net
    buying-pressure proxy accumulating; falling = net selling-pressure
    proxy accumulating."""
    return bar_delta_approx(df).cumsum()


class CVDDivergenceKind(str, Enum):
    BULLISH = "bullish"  # price lower low, CVD higher low -- selling pressure proxy fading despite the lower price, reversal-up read
    BEARISH = "bearish"  # price higher high, CVD lower high -- buying pressure proxy fading despite the higher price, reversal-down read


@dataclass
class CVDDivergence:
    first_index: int
    second_index: int
    kind: CVDDivergenceKind
    price_first: float
    price_second: float
    cvd_first: float
    cvd_second: float


def detect_cvd_divergences(
    df: pd.DataFrame, swings: list[SwingPoint], cvd: Optional[pd.Series] = None,
) -> list[CVDDivergence]:
    """Same consecutive-same-kind-swing-pair comparison as
    divergence.detect_rsi_divergences (same swing infrastructure,
    structure.find_swing_points + alternate_swings, so a "swing high/low"
    means the same thing everywhere in this engine), applied to CVD
    instead of RSI -- a genuinely distinct read: RSI divergence compares
    price against a MOMENTUM oscillator, CVD divergence compares price
    against a net BUY/SELL PRESSURE proxy. Different information, not a
    duplicate of the existing RSI check.

    Only regular divergences (reversal reads) are reported -- hidden/
    continuation CVD divergence isn't a standard, independently
    documented concept the way hidden RSI divergence is (see
    divergence.py's own docstring for that provenance), so it's
    deliberately not claimed here rather than invented by analogy."""
    if cvd is None:
        cvd = compute_cumulative_delta(df)
    cvd_arr = cvd.to_numpy()
    divergences: list[CVDDivergence] = []

    for kind in (SwingKind.LOW, SwingKind.HIGH):
        same_kind = [p for p in swings if p.kind == kind]
        for prev, curr in zip(same_kind, same_kind[1:]):
            c_prev, c_curr = float(cvd_arr[prev.index]), float(cvd_arr[curr.index])
            if kind == SwingKind.LOW and curr.price < prev.price and c_curr > c_prev:
                divergences.append(CVDDivergence(
                    prev.index, curr.index, CVDDivergenceKind.BULLISH,
                    float(prev.price), float(curr.price), c_prev, c_curr,
                ))
            elif kind == SwingKind.HIGH and curr.price > prev.price and c_curr < c_prev:
                divergences.append(CVDDivergence(
                    prev.index, curr.index, CVDDivergenceKind.BEARISH,
                    float(prev.price), float(curr.price), c_prev, c_curr,
                ))

    return divergences


@dataclass
class AbsorptionEvent:
    index: int
    direction: str  # "buyers_absorbed" (positive delta, price failed to rise) or "sellers_absorbed" (negative delta, price failed to fall)
    delta: float
    price_change_pct: float
    relative_volume: float


def detect_absorption(
    df: pd.DataFrame,
    delta: Optional[pd.Series] = None,
    lookback: int = 20,
    min_relative_volume: float = 1.5,
) -> list[AbsorptionEvent]:
    """"Effort vs result" mismatch -- the core absorption concept, per
    OrderFlow-Analysis-Pro's own real AbsorptionDetector (fetched and
    read directly): a bar with unusually HIGH volume (effort) and a
    strong directional delta, whose close still barely moved -- or moved
    AGAINST the delta's own direction -- signals the aggressive side got
    absorbed by passive liquidity rather than actually moving price.
    Only flags bars with relative_volume >= min_relative_volume (a real,
    elevated-effort bar relative to its own recent history, not every
    small wiggle)."""
    if delta is None:
        delta = bar_delta_approx(df)
    volume = _resolve_volume(df)
    if volume is None or len(df) < lookback + 1:
        return []

    delta_arr = delta.to_numpy()
    vol_arr = volume.to_numpy()
    close = df["close"].to_numpy()
    open_ = df["open"].to_numpy()

    events: list[AbsorptionEvent] = []
    for i in range(lookback, len(df)):
        window_vol = vol_arr[i - lookback:i]
        avg_vol = window_vol.mean()
        if avg_vol <= 0:
            continue
        rel_vol = vol_arr[i] / avg_vol
        if rel_vol < min_relative_volume:
            continue
        price_change_pct = (close[i] - open_[i]) / open_[i] * 100 if open_[i] != 0 else 0.0
        d = delta_arr[i]

        if d > 0 and price_change_pct <= 0:
            events.append(AbsorptionEvent(i, "buyers_absorbed", float(d), float(price_change_pct), float(rel_vol)))
        elif d < 0 and price_change_pct >= 0:
            events.append(AbsorptionEvent(i, "sellers_absorbed", float(d), float(price_change_pct), float(rel_vol)))

    return events
