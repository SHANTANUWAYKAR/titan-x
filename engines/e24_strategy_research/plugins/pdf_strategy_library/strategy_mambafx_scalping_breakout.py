"""
Module: strategy_mambafx_scalping_breakout.py
Source document(s): Mamba_FX_1_Min_Scalping_Strategy.txt, MAMBAFX PREMIUM STRATEGY.txt
Description: Both documents describe the same MambaFX-inspired scalping setup -- find a
support/resistance zone that price has repeatedly reacted to, form a directional bias
from it, then enter on a breakout of the immediately preceding bar's high/low in that
bias direction. Consolidated per the interface spec's near-duplicate rule; the only
material difference between the two documents is which session filter each names, both
captured with the `session_mode` parameter below.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_mambafx_scalping_breakout(
    enriched: pd.DataFrame,
    zone_lookback: int = 20,
    touch_atr_mult: float = 0.25,
    min_touches: int = 2,
    choppy_adx_threshold: float = 20.0,
    session_mode: str = "london_ny",
    session_start_hour_utc: int = 4,
    session_end_hour_utc: int = 10,
) -> pd.Series:
    """MambaFX support/resistance-zone breakout scalping strategy.

    Consolidates: Mamba_FX_1_Min_Scalping_Strategy.txt ("Mamba FX - 1 Minute Scalping
    Strategy") and MAMBAFX PREMIUM STRATEGY.txt ("MambaFX Premium Scalping Strategy") --
    same author/concept (5-minute-timeframe zone identification, 1-minute-timeframe
    breakout entry, 1:3 R:R), differing only in which session filter is emphasized: the
    1-Min doc says "trade after 9:30 AM Indian markets"; the Premium doc says "trade only
    during London or New York sessions". `session_mode` ("india" vs "london_ny") selects
    between them.

    Rule (plain English): on a higher timeframe, find a level price has repeatedly
    reacted to (a "strong" support/resistance zone). If support is being respected, look
    only for long breakouts; if resistance is being respected, look only for short
    breakouts. Drop to a lower timeframe and enter once price breaks and closes beyond
    the immediately preceding bar's high/low in the bias direction. Stop = breakout
    candle's low/high; target = 1:3 R:R (sizing, not implemented here per the interface
    spec).

    Multi-timeframe substitution: the platform passes one `enriched` DataFrame per call
    at a single fixed `timeframe`, so the document's 5-minute-context / 1-minute-entry
    split cannot be implemented literally. Both the zone identification and the entry
    trigger are computed on the SAME (whatever is passed in) timeframe: the zone is a
    rolling `zone_lookback`-bar extreme that price has touched (come within
    `touch_atr_mult` * ATR of) at least `min_touches` times, and the entry trigger is a
    break of the single immediately-preceding bar's high/low -- the closest honest
    mechanical approximation using only the available single-timeframe columns.
    "Choppy/sideways" avoidance is operationalized as `adx > choppy_adx_threshold`.

    No lookahead: the zone level, its touch count, and the ATR-based tolerance are all
    built from `.shift(1)`-ed rolling windows (bars strictly before the current one);
    only the final breakout comparison and the ADX filter use the current bar's own
    values, which is legitimate since that is the signal bar itself.
    """
    high = enriched["high"]
    low = enriched["low"]
    close = enriched["close"]
    atr = enriched["atr"]
    ts = enriched["timestamp"]
    hour = ts.dt.hour

    support_level = low.shift(1).rolling(zone_lookback).min()
    resistance_level = high.shift(1).rolling(zone_lookback).max()
    tol = atr.shift(1) * touch_atr_mult

    near_support = (low.shift(1) - support_level).abs() <= tol
    near_resistance = (high.shift(1) - resistance_level).abs() <= tol
    touches_support = near_support.rolling(zone_lookback).sum()
    touches_resistance = near_resistance.rolling(zone_lookback).sum()

    support_respected = touches_support >= min_touches
    resistance_respected = touches_resistance >= min_touches

    not_choppy = enriched["adx"] > choppy_adx_threshold

    if session_mode == "india":
        session_mask = (hour >= session_start_hour_utc) & (hour < session_end_hour_utc)
    elif session_mode == "london_ny":
        session_mask = ((hour >= 7) & (hour < 16)) | ((hour >= 12) & (hour < 21))
    else:
        session_mask = pd.Series(True, index=enriched.index)

    prior_high = high.shift(1)
    prior_low = low.shift(1)
    breakout_up = close > prior_high
    breakout_down = close < prior_low

    entry_long = support_respected & breakout_up & not_choppy & session_mask
    entry_short = resistance_respected & breakout_down & not_choppy & session_mask

    exit_long = close < support_level
    exit_short = close > resistance_level

    return _stateful_from_entries_exits(
        entry_long.fillna(False),
        exit_long.fillna(False),
        entry_short.fillna(False),
        exit_short.fillna(False),
    )
