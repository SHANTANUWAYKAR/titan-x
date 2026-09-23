"""
Module: strategy_usman_noah_pdh_pdl_engulfing.py
Source document(s): Usman Noah.txt (titled "From The Daily Bias To a 15 mins" -- a DIFFERENT
    Usman Noah document from "PDF FVG x Edgeful", which is implemented separately in
    strategy_usman_noah_fvg_displacement.py; this one's distinguishing mechanic is PDH/PDL +
    an engulfing confirmation candle, not the multi-scale FVG displacement concept)
Description: Daily bias (from PDH/PDL positioning) refined to a 15-min entry: price sweeps
    the Previous Day High or Low (a liquidity level), then a Bullish/Bearish Engulfing candle
    confirms the reversal back inside the prior day's range.

    Interpretive assumptions:
    - "Daily + 4H timeframe bias" collapsed onto ema_50 vs ema_200 trend read on the passed-in
      timeframe (per the interface spec's single-DataFrame constraint).
    - Engulfing candle = standard 2-candle body-engulf pattern (candle i's body fully contains
      candle i-1's body in the opposite direction).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_usman_noah_pdh_pdl_engulfing(
    enriched: pd.DataFrame,
    pdh_pdl_window: int = 24,
) -> pd.Series:
    """PDH/PDL liquidity sweep + engulfing confirmation, daily-bias filtered (Usman Noah concept).

    See module docstring for full source attribution and interpretive assumptions.
    """
    high, low, close, open_ = enriched["high"], enriched["low"], enriched["close"], enriched["open"]
    ema_50, ema_200 = enriched["ema_50"], enriched["ema_200"]

    pdh = high.shift(1).rolling(pdh_pdl_window).max()
    pdl = low.shift(1).rolling(pdh_pdl_window).min()

    swept_pdl = (low < pdl) & (low.shift(1) >= pdl.shift(1))
    swept_pdh = (high > pdh) & (high.shift(1) <= pdh.shift(1))

    bullish_engulf = (close > open_) & (close.shift(1) < open_.shift(1)) & (close >= open_.shift(1)) & (open_ <= close.shift(1))
    bearish_engulf = (close < open_) & (close.shift(1) > open_.shift(1)) & (close <= open_.shift(1)) & (open_ >= close.shift(1))

    bias_up = ema_50 > ema_200
    bias_down = ema_50 < ema_200

    entry_long = (swept_pdl.shift(1).fillna(False) & bullish_engulf & bias_up).fillna(False)
    entry_short = (swept_pdh.shift(1).fillna(False) & bearish_engulf & bias_down).fillna(False)

    exit_long = (close < pdl).fillna(False)
    exit_short = (close > pdh).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
