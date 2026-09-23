"""
Module: strategy_box_pdh_pdl_bounce.py
Source document(s): BOX TRADING STRATEGY.txt
Description: "Previous Day High-Low Box Strategy" -- treat the previous trading day's high and
low as a box; when price reaches the bottom of the box (PDL) and prints a green confirmation
candle, buy on the break of that candle's high, targeting the top of the box (PDH). Mirrored at
the top of the box for sells. Previous-day H/L are computed causally from the platform's own
`timestamp`/`high`/`low` columns (grouped by calendar day, shifted by one trading day).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_box_pdh_pdl_bounce(enriched: pd.DataFrame) -> pd.Series:
    """Previous-day-high/low box bounce with confirmation candle.

    Source document: "BOX TRADING STRATEGY.txt". Buy rule: price reaches the Previous Day Low,
    a green confirmation candle prints there, and the NEXT candle breaks that candle's high ->
    buy, targeting the Previous Day High. Sell rule is the mirror image at the Previous Day
    High.

    Interpretive assumptions:
    - "Previous day" = the previous calendar day present in the data (by UTC date from the
      `timestamp` column), computed via a per-day groupby shifted by one row, so a given day's
      PDH/PDL are entirely fixed before that day's own bars begin (no lookahead).
    - "Price reaches the box edge" = that bar's low/high touches or breaches PDL/PDH.
    - Target = PDH/PDL (the document's own explicitly stated level) is used as the exit, per
      the interface spec's guidance that structural, document-defined levels -- as opposed to
      generic R:R sizing -- belong in the signal function.
    """
    high, low, close, open_ = enriched["high"], enriched["low"], enriched["close"], enriched["open"]

    day = enriched["timestamp"].dt.date
    daily = pd.DataFrame({"high": high, "low": low}).groupby(day).agg(d_high=("high", "max"), d_low=("low", "min"))
    daily_prev = daily.shift(1)

    pdh = day.map(daily_prev["d_high"])
    pdl = day.map(daily_prev["d_low"])

    green_at_pdl = (low <= pdl) & (close > open_)
    red_at_pdh = (high >= pdh) & (close < open_)

    entry_long = (green_at_pdl.shift(1).fillna(False) & (close > high.shift(1))).fillna(False)
    entry_short = (red_at_pdh.shift(1).fillna(False) & (close < low.shift(1))).fillna(False)

    exit_long = (close >= pdh).fillna(False)
    exit_short = (close <= pdl).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
