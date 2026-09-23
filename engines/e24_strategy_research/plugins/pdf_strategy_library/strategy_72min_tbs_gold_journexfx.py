"""
Module: strategy_72min_tbs_gold_journexfx.py
Source document(s): 72MIN TBS GOLD STRATEGY BY JOURNEXFX (1).txt
Description: Time-Based-Strategy (TBS) breakout for Gold/XAUUSD. A fixed daily time window
(17:54-19:06 India/Kolkata time) marks a "TBS" high/low range on the execution chart; once the
window closes, a candle CLOSE beyond the TBS high (if price is above the 200 EMA "directional
filter") or below the TBS low (if price is below the 200 EMA) triggers entry in that direction.
Document's 200 EMA filter is read off a separate 15-minute chart while entries execute on a
3-minute chart; this platform passes one single-timeframe DataFrame per call, so the filter is
approximated using the `ema_200` already computed on the SAME timeframe the function receives,
documented here as an honest approximation of the original multi-timeframe design.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_72min_tbs_gold_journexfx(
    enriched: pd.DataFrame,
    window_start_hm: tuple[int, int] = (17, 54),
    window_end_hm: tuple[int, int] = (19, 6),
) -> pd.Series:
    """72-minute Time-Based-Strategy (TBS) gold breakout (72MIN TBS GOLD STRATEGY BY
    JOURNEXFX (1).txt).

    Source rule: mark two vertical time lines each day at 17:54 and 19:06 India/Kolkata time;
    the high/low printed between them is the "TBS range". Use the 200 EMA (15m chart in the
    original doc) as a directional filter: price above it -> only take TBS-high breakouts
    (long); price below it -> only take TBS-low breakdowns (short). Entry only on a candle
    CLOSE beyond the level (never on a mere touch), target 2x the stop distance (1:2 R:R,
    sizing out of scope for this function).

    Interpretive assumptions:
      - 200 EMA directional filter approximated using this call's own `ema_200` column (see
        module docstring: original doc reads it off a separate, higher timeframe).
      - The TBS range for a given calendar day is only considered "known" once the window
        closes; entries are only evaluated on bars strictly after `window_end_hm` on the same
        calendar day (Kolkata time), and the range itself is built with a causal
        (expanding-cumulative) max/min so no future bar ever leaks into it.
      - No explicit stop/target-based exit rule exists for the entry-DIRECTION signal itself
        (sizing is the platform's job); price closing back through the TBS level it broke, or
        the start of a new trading day, is used as the mechanical exit trigger.

    Args:
        enriched: platform OHLCV + indicator DataFrame; `timestamp` must be tz-aware UTC.
        window_start_hm: (hour, minute) TBS window start, India/Kolkata local time.
        window_end_hm: (hour, minute) TBS window end, India/Kolkata local time.

    Returns:
        pd.Series[int] in {-1, 0, 1}, same index as `enriched`.
    """
    close = enriched["close"]; high = enriched["high"]; low = enriched["low"]
    ema200 = enriched["ema_200"]

    kolkata_ts = enriched["timestamp"].dt.tz_convert("Asia/Kolkata")
    date = kolkata_ts.dt.date
    minute_of_day = kolkata_ts.dt.hour * 60 + kolkata_ts.dt.minute

    start_min = window_start_hm[0] * 60 + window_start_hm[1]
    end_min = window_end_hm[0] * 60 + window_end_hm[1]
    in_window = (minute_of_day >= start_min) & (minute_of_day <= end_min)
    after_window = minute_of_day > end_min

    high_in_window = high.where(in_window)
    low_in_window = low.where(in_window)
    # causal, expanding (backward-looking) per-day high/low: only ever sees bars <= current bar
    tbs_high = high_in_window.groupby(date).cummax().groupby(date).ffill()
    tbs_low = low_in_window.groupby(date).cummin().groupby(date).ffill()

    new_day = date.ne(date.shift(1)).fillna(True)

    bullish_bias = close > ema200
    bearish_bias = close < ema200

    entry_long = (after_window & bullish_bias & tbs_high.notna() & (close > tbs_high)).fillna(False)
    entry_short = (after_window & bearish_bias & tbs_low.notna() & (close < tbs_low)).fillna(False)

    exit_long = ((close < tbs_high) | new_day).fillna(False)
    exit_short = ((close > tbs_low) | new_day).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
