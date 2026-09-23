"""
Module: strategy_anish_singh_vwap_stochrsi_pivot.py
Source document(s): ANISH SINGH VWAP STRATEGY.txt
Description: VWAP + Stochastic + daily pivot intraday strategy (credited to Anish Singh Thakur /
Boombing Bulls in the source doc). Trades only in the direction of VWAP, requires the
stochastic oscillator to confirm the same direction, and triggers on a candle close crossing
the prior day's floor pivot. Document specifies "Stochastic RSI"; the platform only provides a
standard stochastic oscillator (`stoch_k`/`stoch_d`), used as the closest available
approximation and documented here explicitly.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_anish_singh_vwap_stochrsi_pivot(
    enriched: pd.DataFrame,
    stoch_bull_level: float = 50.0,
    apply_market_open_filter: bool = True,
    market_open_hour: int = 9,
    market_open_minute: int = 30,
    market_tz: str = "America/New_York",
) -> pd.Series:
    """VWAP + Stochastic + prior-day pivot intraday trigger (ANISH SINGH VWAP STRATEGY.txt).

    Source rule (5m chart): BUY when price is above VWAP, the Stochastic RSI is bullish, and a
    candle crosses above a pivot level. SELL is the mirror: price below VWAP, Stochastic RSI
    bearish, candle crosses below a pivot level. Stop beyond VWAP, target 0.75% (sizing out of
    scope per interface-spec rule 7). Trade only after 9:30 AM; avoid range-bound markets.

    Interpretive assumptions:
      - "Stochastic RSI" -> approximated with the platform's standard stochastic oscillator
        (`stoch_k`/`stoch_d`); "bullish" = stoch_k > stoch_d and stoch_k > `stoch_bull_level`,
        "bearish" = stoch_k < stoch_d and stoch_k < (100 - `stoch_bull_level`).
      - "Pivot Levels" is not a platform column; computed inline as the classic floor pivot
        (prior COMPLETE day's (H+L+C)/3), which is fully known before the current trading day
        starts -- no lookahead (built from a per-date aggregate table shifted by one day, then
        broadcast back onto every row of the following day).
      - "Cross a pivot level" = candle CLOSE crosses the pivot (this project's standard
        resolution of ambiguous "break of" language).
      - "Trade only after 9:30 AM" is read as the classic US-equity open; implemented as an
        optional filter (`apply_market_open_filter`, default on) converting the UTC timestamp to
        `market_tz` and requiring local time >= 9:30. Disable for non-US-equity instruments.
      - Exit: the doc's own stated stop placement (beyond VWAP) is used as the exit trigger --
        closing back through VWAP exits the position.

    Returns:
        pd.Series[int] in {-1, 0, 1}, same index as `enriched`.
    """
    close = enriched["close"]
    vwap = enriched["vwap"]
    stoch_k = enriched["stoch_k"]; stoch_d = enriched["stoch_d"]

    date = enriched["timestamp"].dt.date
    daily_high = enriched.groupby(date)["high"].max()
    daily_low = enriched.groupby(date)["low"].min()
    daily_close = enriched.groupby(date)["close"].last()
    daily_pivot = (daily_high + daily_low + daily_close) / 3.0
    prev_day_pivot = daily_pivot.shift(1)  # indexed by date; only prior COMPLETE day's data
    pivot = date.map(prev_day_pivot)
    pivot.index = enriched.index

    cross_above_pivot = (close.shift(1) <= pivot) & (close > pivot)
    cross_below_pivot = (close.shift(1) >= pivot) & (close < pivot)

    stoch_bullish = (stoch_k > stoch_d) & (stoch_k > stoch_bull_level)
    stoch_bearish = (stoch_k < stoch_d) & (stoch_k < (100.0 - stoch_bull_level))

    entry_long = ((close > vwap) & stoch_bullish & cross_above_pivot).fillna(False)
    entry_short = ((close < vwap) & stoch_bearish & cross_below_pivot).fillna(False)

    if apply_market_open_filter:
        local_ts = enriched["timestamp"].dt.tz_convert(market_tz)
        minute_of_day = local_ts.dt.hour * 60 + local_ts.dt.minute
        open_minute = market_open_hour * 60 + market_open_minute
        after_open = (minute_of_day >= open_minute).fillna(False)
        entry_long = entry_long & after_open
        entry_short = entry_short & after_open

    exit_long = (close < vwap).fillna(False)
    exit_short = (close > vwap).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
