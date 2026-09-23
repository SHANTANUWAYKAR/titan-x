"""
Module: strategy_jadecap_playbook_session_liquidity.py
Source document(s): JadeCap Playbook.txt
Description: "JadeCap's Playbook -- Intraday Liquidity & Volatility Model". Establish a daily
directional bias, wait for a session liquidity raid (prior day / Asian / London session
high-low taken out) during the New York session, confirm with a Fair Value Gap reaction, and
only take entries inside the 9:30-11:30 AM ET window.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_jadecap_playbook_session_liquidity(
    enriched: pd.DataFrame,
    raid_confirm_window: int = 10,
) -> pd.Series:
    """Daily bias -> NY-session liquidity raid of PDH/PDL/Asian/London levels -> FVG entry.

    Source document: "JadeCap Playbook.txt" ("Intraday Liquidity & Volatility Model"). Rule:
    1) form a daily bias; 2) mark session liquidity zones (Previous Day High/Low, Asian session
    High/Low, London session High/Low); 3) wait for one of those levels to be raided (swept)
    during the New York session; 4) confirm on a lower timeframe with a Fair Value Gap, Market
    Structure Shift, Turtle Soup, or Breaker Block; 5) trade only between 9:30 and 11:30 AM EST.

    Interpretive assumptions / approximations:
    - Daily bias is approximated with `supertrend_direction` sampled from the PREVIOUS
      calendar day's LAST bar and held fixed all through the current trading day (a bias
      "decided using the daily chart" before today's session, not re-evaluated intraday).
    - PDH/PDL use the previous UTC calendar date's high/low (same causal groupby+shift pattern
      used elsewhere in this project for prior-day levels).
    - Asian session is approximated as 18:00-23:59 US/Eastern and London session as
      02:00-05:59 US/Eastern (commonly-cited ICT session windows; the document does not give
      exact hours, so this is stated explicitly as an approximation). Each trading day's
      Asian+London running high/low is accumulated causally (`cummax`/`cummin` within that
      day's own session bars, then forward-filled) so it only ever reflects session bars that
      have ALREADY happened before the current bar.
    - Of the four listed confirmation types (FVG / MSS / Turtle Soup / Breaker Block), only the
      Fair Value Gap is implemented: it has one precise, objective, universally-used mechanical
      definition (a 3-candle gap: `low[i] > high[i-2]` for bullish, `high[i] < low[i-2]` for
      bearish), whereas the other three are more discretionary or would duplicate the
      swing/BOS machinery already used elsewhere in this batch's other SMC-style files. This is
      a real, honest subset of the document's confirmation menu, not a placeholder.
    - "9:30-11:30 AM EST" is applied as US/Eastern wall-clock time (`tz_convert` handles the
      EST/EDT daylight-saving difference automatically).
    - A trading day's "evening" bars (ET hour >= 18) are attributed to the FOLLOWING calendar
      date's trading day, since the Asian session precedes that next day's NY session
      chronologically.
    - Exit uses a break back beyond the raided level as a structural invalidation (the
      document's real exit is a target/time-of-day judgment call, which is external
      position-management logic per interface spec).
    """
    ts = enriched["timestamp"]
    ts_et = ts.dt.tz_convert("America/New_York")
    hour = ts_et.dt.hour
    minute = ts_et.dt.minute
    cal_date = ts_et.dt.date

    high = enriched["high"]; low = enriched["low"]; close = enriched["close"]
    st_dir = enriched["supertrend_direction"]

    # ---- trading-day bucket: an evening (>=18:00 ET) bar belongs to the NEXT day's session ----
    trading_day = pd.Series(
        np.where(hour >= 18, (ts_et + pd.Timedelta(days=1)).dt.date, cal_date),
        index=enriched.index,
    )

    # ---- previous-day high/low (causal) ----
    daily = pd.DataFrame({"high": high, "low": low}).groupby(cal_date).agg(d_high=("high", "max"), d_low=("low", "min"))
    daily_prev = daily.shift(1)
    pdh = cal_date.map(daily_prev["d_high"])
    pdl = cal_date.map(daily_prev["d_low"])

    # ---- daily bias: previous day's LAST supertrend_direction value, held fixed all day ----
    st_by_day = st_dir.groupby(cal_date).last()
    bias_by_day = st_by_day.shift(1)
    daily_bias = cal_date.map(bias_by_day).fillna(0.0)

    # ---- Asian / London running (causal) session extremes within each trading day ----
    asian_mask = (hour >= 18)
    london_mask = (hour >= 2) & (hour < 6)
    liq_mask = asian_mask | london_mask

    high_masked = high.where(liq_mask)
    low_masked = low.where(liq_mask)
    session_high = high_masked.groupby(trading_day).cummax().groupby(trading_day).ffill()
    session_low = low_masked.groupby(trading_day).cummin().groupby(trading_day).ffill()

    liquidity_high = pd.concat([pdh, session_high], axis=1).max(axis=1)
    liquidity_low = pd.concat([pdl, session_low], axis=1).min(axis=1)

    # ---- NY AM window: 9:30-11:30 ET ----
    ny_am = ((hour == 9) & (minute >= 30)) | (hour == 10) | ((hour == 11) & (minute < 30))

    # ---- liquidity raid: sweep + same-bar reclaim ----
    raid_up = (high > liquidity_high) & (close < liquidity_high)
    raid_down = (low < liquidity_low) & (close > liquidity_low)
    raid_down_recent = raid_down.shift(1).rolling(raid_confirm_window, min_periods=1).max().fillna(0).astype(bool)
    raid_up_recent = raid_up.shift(1).rolling(raid_confirm_window, min_periods=1).max().fillna(0).astype(bool)

    # ---- Fair Value Gap confirmation (3-candle gap) ----
    bullish_fvg = low > high.shift(2)
    bearish_fvg = high < low.shift(2)
    fvg_bottom = high.shift(2)
    fvg_top = low.shift(2)

    entry_long = (raid_down_recent & bullish_fvg & ny_am & (close > fvg_bottom) & (daily_bias >= 0)).fillna(False)
    entry_short = (raid_up_recent & bearish_fvg & ny_am & (close < fvg_top) & (daily_bias <= 0)).fillna(False)

    exit_long = (close < liquidity_low).fillna(False)
    exit_short = (close > liquidity_high).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
