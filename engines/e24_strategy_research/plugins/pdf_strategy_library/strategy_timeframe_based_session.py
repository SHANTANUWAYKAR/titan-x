"""
Module: strategy_timeframe_based_session.py
Source document(s): TIMEFRAME BASED STRATEGY.txt
Description: Session-time-filtered multi-window breakout. The source document describes a
discretionary multi-timeframe (45m/15m major zones, 5m/3m minor zones, 1m entries) session
trading plan restricted to Asia/London/NY windows (times given in IST). Since `enriched` is
single-resolution, "major" and "minor" zones are approximated as two different rolling-lookback
N-bar extremes on the SAME series (a longer window for "major" structure, a shorter window for
"minor" structure), and the entry trigger is a minor-zone breakout in the direction of the major
zone, gated to the three specified session windows (converted from IST, UTC+5:30, to UTC).
"""
from __future__ import annotations
import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_timeframe_based_session(
    enriched: pd.DataFrame,
    major_window: int = 45,
    minor_window: int = 15,
    adx_trend_min: float = 25.0,
) -> pd.Series:
    """Session-gated major/minor structure breakout (TIMEFRAME BASED STRATEGY.txt).

    Source document: TIMEFRAME BASED STRATEGY.txt -- a discretionary plan that marks "major"
    S/R zones on 45m/15m charts, "minor" zones inside them on 5m/3m charts, and enters on the
    1m chart only during the Asia/London/NY sessions (times given in IST).

    Interpretation / approximation: `enriched` is a single-resolution DataFrame, so true
    multi-timeframe zone marking is not possible. "Major zone" is approximated by the prior
    `major_window`-bar rolling high/low on the current timeframe; "minor zone" by the prior
    `minor_window`-bar rolling high/low (minor_window < major_window, so it is the tighter,
    more local structure "inside" the major zone). "Proper confirmation" before entry is
    approximated with an ADX trend filter (adx > adx_trend_min, default 25 to match this
    platform's own documented "strong trend = ADX > 25" convention) since the document does not
    specify a mechanical confirmation candle pattern.

    Session windows: document times are IST (UTC+5:30, no DST). Converted to UTC:
      Asia   06:00-10:30 IST -> 00:30-05:00 UTC
      London 13:30-16:30 IST -> 08:00-11:00 UTC
      NY     17:30-22:00 IST -> 12:00-16:30 UTC
    Only bars whose `timestamp` falls in one of these UTC windows are eligible to enter.

    Entry (long): within a session window, close breaks above the prior minor-zone high AND
    that minor high is within (at or below) the prior major-zone high (i.e. breaking out of the
    inner/minor structure while still inside or at the edge of the outer/major range) AND
    adx > adx_trend_min (trend confirmation). Entry (short) is the symmetric mirror image.
    Exit: opposite-direction minor-zone breakout, or ADX trend confirmation is lost
    (adx <= adx_trend_min), whichever comes first, via the shared stateful position helper.

    No-lookahead: major/minor levels use `.shift(1)` before `.rolling()`, so both are fixed
    using bars strictly before the current bar; session/ADX filters are pointwise (current bar
    only). No stop-loss/target/position-sizing logic is implemented here (platform's backtester
    handles that) -- only entry/exit direction.
    """
    close = enriched["close"]
    high = enriched["high"]
    low = enriched["low"]
    adx = enriched["adx"]
    ts = pd.to_datetime(enriched["timestamp"], utc=True)

    major_high = high.shift(1).rolling(major_window).max()
    major_low = low.shift(1).rolling(major_window).min()
    minor_high = high.shift(1).rolling(minor_window).max()
    minor_low = low.shift(1).rolling(minor_window).min()

    hour = ts.dt.hour
    minute = ts.dt.minute
    hm = hour + minute / 60.0

    asia = (hm >= 0.5) & (hm < 5.0)
    london = (hm >= 8.0) & (hm < 11.0)
    ny = (hm >= 12.0) & (hm < 16.5)
    in_session = asia | london | ny

    trend_ok = adx > adx_trend_min

    breakout_up = close > minor_high
    breakout_down = close < minor_low
    within_major_up = minor_high <= major_high
    within_major_down = minor_low >= major_low

    entry_long = in_session & trend_ok & breakout_up & within_major_up
    entry_short = in_session & trend_ok & breakout_down & within_major_down

    exit_long = breakout_down | (~trend_ok)
    exit_short = breakout_up | (~trend_ok)

    entry_long = entry_long.fillna(False)
    entry_short = entry_short.fillna(False)
    exit_long = exit_long.fillna(False)
    exit_short = exit_short.fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
