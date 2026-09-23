"""
Module: strategy_tom_hougaard_situational_analysis.py
Source document(s): TOM HAUGAARD TRADING STRATEGY.txt
Description: "Situational Analysis" (the document body spells the trader's name "Hougaard"; the
source filename spells it "HAUGAARD" -- both refer to the same document) -- compares a completed
prior session's high against an earlier reference session's high; a weaker high implies the
market is likely to revisit the weaker session's low before its next real move. Implemented as a
short-only, session-anchored mean-reversion-to-liquidity trade: Monday shorts targeting Friday's
low (triggered when Friday's High < Thursday's High), and Thursday shorts targeting Wednesday's
low (triggered when Wednesday's High < Monday's High), both using only fully-completed prior
calendar days.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_tom_hougaard_situational_analysis(enriched: pd.DataFrame) -> pd.Series:
    """Weak-high -> revisit-the-low situational trade (Tom Hougaard, TOM HAUGAARD TRADING
    STRATEGY.txt).

    Source document rule: if a session's High fails to exceed an earlier reference session's
    High, the market "often revisits" the weaker session's Low before its next real move. Two
    explicit setups are given:
      1. Friday vs Thursday: if Friday's High < Thursday's High -> during Monday, expect a
         revisit of Friday's Low.
      2. Wednesday vs Monday: if Wednesday's High < Monday's High -> during Thursday, expect a
         revisit of Wednesday's Low.

    Interpretation: "revisit the low" is implemented as a SHORT bias for the qualifying session
    day, targeting that prior day's low. This is a short-only, direction-specific rule per the
    document (no long/bullish mirror is described) -- when neither condition holds the function
    is flat, which is intentional, not a placeholder.

    No-lookahead construction: each weekday's High/Low is aggregated per calendar day
    (`groupby(date)`), then read back only via a `.where(weekday==target).ffill().shift(1)`
    day-level lag so a later day's bars only ever see FULLY COMPLETED earlier days' extremes
    (the extra `.shift(1)` is defense-in-depth on top of the fact that Thursday/Friday are
    already strictly earlier than Monday, and Monday/Wednesday strictly earlier than Thursday).

    Entry (short): current bar's weekday matches the qualifying trigger day (Monday for setup 1,
    Thursday for setup 2), the corresponding High-comparison condition is true using the most
    recently completed relevant days, and price has not yet reached the target low this session.
    Exit: price closes at/below the target low (revisit achieved), or the first bar of a new
    calendar day arrives where the setup condition is no longer active (handles both setups
    generically without needing to track which one is currently open, since Monday and Thursday
    triggers are never adjacent calendar days).
    """
    close = enriched["close"]
    ts = pd.to_datetime(enriched["timestamp"], utc=True)
    day = ts.dt.floor("D")
    weekday = ts.dt.weekday  # Monday=0 ... Sunday=6

    daily_high = enriched.groupby(day)["high"].max()
    daily_low = enriched.groupby(day)["low"].min()
    daily_weekday = daily_high.index.to_series().dt.weekday

    def _last_completed_weekday_value(daily_series: pd.Series, target_weekday: int) -> pd.Series:
        masked = daily_series.where(daily_weekday == target_weekday)
        return masked.ffill().shift(1)

    thursday_high_daily = _last_completed_weekday_value(daily_high, 3)
    friday_high_daily = _last_completed_weekday_value(daily_high, 4)
    friday_low_daily = _last_completed_weekday_value(daily_low, 4)
    monday_high_daily = _last_completed_weekday_value(daily_high, 0)
    wednesday_high_daily = _last_completed_weekday_value(daily_high, 2)
    wednesday_low_daily = _last_completed_weekday_value(daily_low, 2)

    thursday_high = day.map(thursday_high_daily)
    friday_high = day.map(friday_high_daily)
    friday_low = day.map(friday_low_daily)
    monday_high = day.map(monday_high_daily)
    wednesday_high = day.map(wednesday_high_daily)
    wednesday_low = day.map(wednesday_low_daily)

    is_first_bar_of_day = enriched.groupby(day).cumcount() == 0

    setup1_condition = (friday_high < thursday_high) & weekday.eq(0)
    setup2_condition = (wednesday_high < monday_high) & weekday.eq(3)

    target_low = pd.Series(np.nan, index=enriched.index)
    target_low = target_low.where(~setup1_condition, friday_low)
    target_low = target_low.where(~setup2_condition, wednesday_low)

    active_setup = (setup1_condition | setup2_condition) & target_low.notna()

    entry_short = active_setup & (close > target_low)
    reached_target = target_low.notna() & (close <= target_low)
    exit_short = reached_target | (is_first_bar_of_day & ~active_setup)

    entry_long = pd.Series(False, index=enriched.index)
    exit_long = pd.Series(False, index=enriched.index)

    entry_short = entry_short.fillna(False)
    exit_short = exit_short.fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
