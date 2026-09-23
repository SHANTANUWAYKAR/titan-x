"""
Module: volume_profile.py
Description: Volume Profile (Point of Control, Value Area, High/Low
    Volume Nodes) for e07_technical -- a price-by-volume distribution
    over a lookback window. Built for the Market Profile / Volume Profile
    topic cluster (492K + 75K tagged chunks in the ingested corpus -- the
    single largest and fourth-largest topics respectively), previously
    entirely unimplemented in this engine despite being its best-covered
    subject in the book corpus.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class VolumeProfile:
    poc_price: float  # Point of Control -- the price level with the most traded volume
    value_area_high: float
    value_area_low: float
    value_area_volume_pct: float  # actual % of total volume captured (target 70%, may differ slightly due to binning)
    high_volume_nodes: list[float]  # local volume peaks -- price levels of consolidation/acceptance
    low_volume_nodes: list[float]  # local volume troughs -- price levels of rejection/fast movement
    bin_prices: list[float]  # bin-center prices, for charting/debugging
    bin_volumes: list[float]


def _resolve_volume(df: pd.DataFrame) -> pd.Series | None:
    """Real MT5-sourced forex data in this project uses tick_volume
    (count of price changes per bar) rather than a literal traded-volume
    column -- a standard, reasonable proxy for real volume in FX, where
    no central exchange reports true traded size. Checked directly
    against this project's own real data files: EURUSD/USDJPY history
    has tick_volume+real_volume but no plain "volume"; GBPUSD and the
    commodity history do have "volume"/"Volume". Falls back through the
    column names actually seen in this project's data; returns None (not
    zeros) if nothing usable is present, so callers can tell "no volume
    data available" apart from "genuinely zero volume."
    """
    for col in ("volume", "Volume", "tick_volume", "real_volume"):
        if col in df.columns and df[col].sum() > 0:
            return df[col]
    return None


def compute_volume_profile(
    df: pd.DataFrame, lookback: int = 200, n_bins: int = 50, value_area_pct: float = 0.70
) -> VolumeProfile | None:
    """Builds a volume-by-price histogram over the last `lookback` candles:
    each candle's volume is distributed evenly across its own high-low
    range -- the standard volume-profile approximation used whenever only
    OHLCV bars (not tick-level data) are available, assuming uniform
    trading intensity within a single candle's range. Returns None if
    there's no usable volume column or insufficient/degenerate data,
    never a fabricated profile.
    """
    volume = _resolve_volume(df)
    if volume is None or len(df) < 10:
        return None

    n = min(lookback, len(df))
    window = df.tail(n)
    vol_window = volume.tail(n)

    price_min = float(window["low"].min())
    price_max = float(window["high"].max())
    if price_max <= price_min:
        return None

    bin_edges = np.linspace(price_min, price_max, n_bins + 1)
    bin_volumes = np.zeros(n_bins)

    highs = window["high"].to_numpy()
    lows = window["low"].to_numpy()
    vols = vol_window.to_numpy()

    for h, l, v in zip(highs, lows, vols):
        if v <= 0:
            continue
        if h <= l:
            idx = min(max(int(np.searchsorted(bin_edges, h, side="right")) - 1, 0), n_bins - 1)
            bin_volumes[idx] += v
            continue
        lo_idx = min(max(int(np.searchsorted(bin_edges, l, side="right")) - 1, 0), n_bins - 1)
        hi_idx = min(max(int(np.searchsorted(bin_edges, h, side="right")) - 1, 0), n_bins - 1)
        span = hi_idx - lo_idx + 1
        bin_volumes[lo_idx:hi_idx + 1] += v / span

    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
    total_volume = float(bin_volumes.sum())
    if total_volume <= 0:
        return None

    poc_idx = int(np.argmax(bin_volumes))

    # Value Area: grow outward from POC, greedily adding whichever
    # neighboring bin (above or below the current area) has more volume,
    # until the target percentage of total volume is captured -- the
    # standard Market/Volume Profile construction.
    lo, hi = poc_idx, poc_idx
    captured = float(bin_volumes[poc_idx])
    target = total_volume * value_area_pct
    while captured < target and (lo > 0 or hi < n_bins - 1):
        next_lo_vol = bin_volumes[lo - 1] if lo > 0 else -1.0
        next_hi_vol = bin_volumes[hi + 1] if hi < n_bins - 1 else -1.0
        if next_hi_vol >= next_lo_vol:
            hi += 1
            captured += float(bin_volumes[hi])
        else:
            lo -= 1
            captured += float(bin_volumes[lo])

    # High/Low Volume Nodes: local maxima/minima in the volume histogram
    # (immediate-neighbor comparison), restricted to bins with at least
    # 1% of total volume so near-empty tail bins don't get flagged as
    # nodes on pure noise.
    hvns: list[float] = []
    lvns: list[float] = []
    threshold = total_volume * 0.01
    for i in range(1, n_bins - 1):
        if bin_volumes[i] < threshold:
            continue
        v_here, v_prev, v_next = bin_volumes[i], bin_volumes[i - 1], bin_volumes[i + 1]
        is_local_max = v_here >= v_prev and v_here >= v_next and (v_here > v_prev or v_here > v_next)
        is_local_min = v_here <= v_prev and v_here <= v_next and (v_here < v_prev or v_here < v_next)
        if is_local_max:
            hvns.append(float(bin_centers[i]))
        if is_local_min:
            lvns.append(float(bin_centers[i]))

    return VolumeProfile(
        poc_price=float(bin_centers[poc_idx]),
        value_area_high=float(bin_centers[hi]),
        value_area_low=float(bin_centers[lo]),
        value_area_volume_pct=float(captured / total_volume),
        high_volume_nodes=hvns,
        low_volume_nodes=lvns,
        bin_prices=bin_centers.tolist(),
        bin_volumes=bin_volumes.tolist(),
    )
