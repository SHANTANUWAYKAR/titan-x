"""
Module: strategy_usman_noah_fvg_displacement.py
Source document(s): PDF FVG x Edgeful (1).txt (also titled "Usman Noah -- From 1H-4H FVG To 15
    MIN FVG")
Description: Fair Value Gap (FVG) displacement-continuation entry. An FVG is the 3-candle
    imbalance pattern where candle 1's range and candle 3's range don't overlap. The higher-
    timeframe FVG sets bias; price is expected to retrace into a LOWER-timeframe FVG formed by
    a displacement move in the same direction, and the entry triggers on that lower-timeframe
    FVG's formation/retest.

    Interpretive assumptions:
    - "1H-4H FVG into 15-min FVG" collapsed onto a single timeframe per the interface spec (no
      true multi-timeframe data available inside one `enriched` call) -- implemented as: an
      OLDER, larger FVG (`htf_fvg_lookback` bars back) sets directional bias, and a fresh,
      smaller FVG within the last few bars in the SAME direction is the actual trigger.
    - "Displacement" = the candle creating the FVG has body_ratio >= displacement_body_ratio
      (a strong, decisive move, not a weak drift).
    - Entry: price retraces into the recent (lower-timeframe-proxy) FVG and closes back in the
      bias direction (continuation, not fade).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_usman_noah_fvg_displacement(
    enriched: pd.DataFrame,
    htf_fvg_lookback: int = 40,
    ltf_fvg_lookback: int = 8,
    displacement_body_ratio: float = 0.6,
) -> pd.Series:
    """Multi-scale FVG displacement-continuation entry (Usman Noah / Edgeful FVG concept).

    See module docstring for full source attribution and interpretive assumptions.
    """
    high, low, close, open_ = enriched["high"], enriched["low"], enriched["close"], enriched["open"]

    body = (close - open_).abs()
    rng = (high - low).replace(0, np.nan)
    displacement = (body / rng) >= displacement_body_ratio

    # Bullish FVG at bar i: low[i] > high[i-2] (gap between candle i-2's high and candle i's low)
    bull_fvg = (low > high.shift(2)) & displacement.shift(1).fillna(False)
    bear_fvg = (high < low.shift(2)) & displacement.shift(1).fillna(False)

    # HTF-proxy bias: any bullish/bearish FVG within the OLDER, larger lookback window (excludes
    # the most recent ltf_fvg_lookback bars so bias and trigger don't share the same evidence).
    htf_bull_bias = bull_fvg.shift(1 + ltf_fvg_lookback).rolling(htf_fvg_lookback).max().fillna(0).astype(bool)
    htf_bear_bias = bear_fvg.shift(1 + ltf_fvg_lookback).rolling(htf_fvg_lookback).max().fillna(0).astype(bool)

    # LTF-proxy trigger: a fresh, same-direction FVG within the recent window.
    ltf_bull_trigger = bull_fvg.shift(1).rolling(ltf_fvg_lookback).max().fillna(0).astype(bool)
    ltf_bear_trigger = bear_fvg.shift(1).rolling(ltf_fvg_lookback).max().fillna(0).astype(bool)

    entry_long = (htf_bull_bias & ltf_bull_trigger & (close > open_)).fillna(False)
    entry_short = (htf_bear_bias & ltf_bear_trigger & (close < open_)).fillna(False)

    exit_long = (~htf_bull_bias).fillna(False)
    exit_short = (~htf_bear_bias).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
