"""
Module: strategy_liquidity_sweep_pdh_pdl.py
Source document(s): LIQUIDITY SWEEP STRATEGY.txt
Description: "Liquidity Sweep Strategy (Day 30)" -- marks Previous Day High (PDH) and
Previous Day Low (PDL), trades only during London/New York open-session hours, and looks
for a sweep-and-reject pattern: price pokes through PDH/PDL, prints a long rejection
wick back inside, and the following candle closes back inside that rejection candle's
range -- entering in the opposite direction of the sweep, targeting the other side of
the prior day's range.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_liquidity_sweep_pdh_pdl(
    enriched: pd.DataFrame,
    wick_ratio: float = 0.5,
    london_start_hour: int = 7,
    london_end_hour: int = 10,
    ny_start_hour: int = 12,
    ny_end_hour: int = 15,
) -> pd.Series:
    """Previous-Day-High/Low liquidity sweep reversal (Day 30 strategy).

    Source: LIQUIDITY SWEEP STRATEGY.txt.

    Rule (plain English): mark the previous trading day's high (PDH) and low (PDL).
    Only trade during the London-open or New-York-open windows. SHORT setup: price
    breaks above PDH, the breaking candle shows a long upper rejection wick, and the
    NEXT candle closes back inside that rejection candle's range -> sell. LONG setup:
    mirror image at PDL with a lower rejection wick -> buy. Stop is the sweep candle's
    high/low and target is the opposite prior-day level per the document; this
    function only emits the entry/exit DIRECTION signal, not position sizing, so the
    "target" is expressed purely as an exit condition (reaching the opposite level),
    not a stop-distance calculation.

    Interpretive assumptions: (1) "long rejection wick" = the wick beyond the body on
    the sweep side is >= `wick_ratio` (default 50%) of the candle's total high-low
    range. (2) London-open / New-York-open windows are approximated as UTC hour ranges
    [london_start_hour, london_end_hour) and [ny_start_hour, ny_end_hour) since the
    document names sessions but gives no explicit UTC boundary -- defaults approximate
    the opening 2-3 hours of each session.

    No lookahead: PDH/PDL are computed from the previous COMPLETE trading day only
    (aggregated per calendar date, then shifted one day before being broadcast back
    onto the following day's bars via a date->level mapping), and the sweep/rejection/
    confirmation pattern only ever references the current bar and the single bar
    immediately before it via `.shift(1)`.
    """
    ts = enriched["timestamp"]
    date = ts.dt.date
    high = enriched["high"]
    low = enriched["low"]
    open_ = enriched["open"]
    close = enriched["close"]

    # Previous COMPLETE trading day's high/low, broadcast onto the following day(s).
    # groupby(date) aggregates ONLY bars within that same calendar date; shift(1) on
    # the resulting one-row-per-date series moves each date's value to the NEXT date
    # present in the data (i.e. the previous *trading* day, correctly skipping
    # weekends/holidays with no data).
    day_high_by_date = high.groupby(date).max()
    day_low_by_date = low.groupby(date).min()
    prev_day_high_by_date = day_high_by_date.shift(1)
    prev_day_low_by_date = day_low_by_date.shift(1)
    pdh = date.map(prev_day_high_by_date)
    pdl = date.map(prev_day_low_by_date)

    hour = ts.dt.hour
    session_mask = ((hour >= london_start_hour) & (hour < london_end_hour)) | (
        (hour >= ny_start_hour) & (hour < ny_end_hour)
    )

    rng = (high - low).replace(0, np.nan)
    upper_body = pd.concat([open_, close], axis=1).max(axis=1)
    lower_body = pd.concat([open_, close], axis=1).min(axis=1)
    upper_wick_ratio = (high - upper_body) / rng
    lower_wick_ratio = (lower_body - low) / rng

    sweep_high = (high > pdh) & (upper_wick_ratio >= wick_ratio)
    sweep_low = (low < pdl) & (lower_wick_ratio >= wick_ratio)

    sweep_high_prev = sweep_high.shift(1, fill_value=False)
    sweep_low_prev = sweep_low.shift(1, fill_value=False)

    prior_high = high.shift(1)
    prior_low = low.shift(1)
    closes_inside_prior_range = (close < prior_high) & (close > prior_low)

    entry_short = sweep_high_prev & closes_inside_prior_range & session_mask
    entry_long = sweep_low_prev & closes_inside_prior_range & session_mask

    exit_long = close >= pdh
    exit_short = close <= pdl

    return _stateful_from_entries_exits(
        entry_long.fillna(False),
        exit_long.fillna(False),
        entry_short.fillna(False),
        exit_short.fillna(False),
    )
