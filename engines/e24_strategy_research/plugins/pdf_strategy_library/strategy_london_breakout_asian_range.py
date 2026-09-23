"""
Module: strategy_london_breakout_asian_range.py
Source document(s): london_breakout_strategy.txt
Description: Classic Asian-range London-open breakout. Marks the Asian session's high/low,
then trades a breakout of that range once the London session begins, entering on the
confirmation candle that follows the break; flattens automatically once the London
window ends for the day.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_london_breakout_asian_range(
    enriched: pd.DataFrame,
    asian_start_hour: int = 0,
    asian_end_hour: int = 7,
    london_start_hour: int = 7,
    london_end_hour: int = 16,
) -> pd.Series:
    """Asian-range breakout traded at London open.

    Source: london_breakout_strategy.txt (mixed Hindi/English "London Breakout Strategy"
    teaching guide).

    Rule (plain English): the Asian session trades in a tight range; mark its high and
    low. Once London opens, volatility picks up and price often breaks that range --
    trade the breakout direction, entering on the confirmation candle after the break.
    Stop goes on the opposite side of the Asian range; target is 1:2-1:3 R:R (sizing,
    not implemented here per the interface spec -- only entry/exit direction is).

    Interpretive assumptions: the document names sessions ("Asian", "London") without
    UTC times, so hours are approximated as UTC [asian_start_hour, asian_end_hour) =
    [0, 7) for the Asian range and [london_start_hour, london_end_hour) = [7, 16) for
    the tradeable London window (standard, widely-used session conventions). "Confirmation
    candle" = a candle that itself closes in the breakout direction (bullish after an
    upside break, bearish after a downside break). The document implies one
    breakout-and-hold per day, so any open position is flattened once the London window
    ends for the day (see `exit_long`/`exit_short`).

    No lookahead: the Asian high/low is built with `.groupby(date).cummax()`/`cummin()`
    (a running extreme that, at any bar, only reflects bars up to AND including that
    bar, never a future bar) restricted to the Asian-hour window, then forward-filled
    for the rest of that calendar date. The breakout flag is `.shift(1)`-ed before the
    confirmation-candle check, so entry at bar i only ever depends on bars <= i.
    """
    ts = enriched["timestamp"]
    date = ts.dt.date
    hour = ts.dt.hour
    high = enriched["high"]
    low = enriched["low"]
    open_ = enriched["open"]
    close = enriched["close"]

    is_asian = (hour >= asian_start_hour) & (hour < asian_end_hour)

    asian_high_masked = high.where(is_asian)
    asian_low_masked = low.where(is_asian)

    asian_high_running = asian_high_masked.groupby(date).cummax()
    asian_low_running = asian_low_masked.groupby(date).cummin()
    asian_high_level = asian_high_running.groupby(date).ffill()
    asian_low_level = asian_low_running.groupby(date).ffill()

    level_ready = asian_high_level.notna() & asian_low_level.notna()
    london_mask = (hour >= london_start_hour) & (hour < london_end_hour)

    breakout_up = close > asian_high_level
    breakout_down = close < asian_low_level
    breakout_up_prev = breakout_up.shift(1, fill_value=False)
    breakout_down_prev = breakout_down.shift(1, fill_value=False)

    confirm_bull = close > open_
    confirm_bear = close < open_

    entry_long = london_mask & level_ready & breakout_up_prev & confirm_bull
    entry_short = london_mask & level_ready & breakout_down_prev & confirm_bear

    exit_long = (~london_mask) | (close < asian_high_level) | (~level_ready)
    exit_short = (~london_mask) | (close > asian_low_level) | (~level_ready)

    return _stateful_from_entries_exits(
        entry_long.fillna(False),
        exit_long.fillna(False),
        entry_short.fillna(False),
        exit_short.fillna(False),
    )
