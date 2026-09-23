"""
Module: killzones.py
Description: ICT killzone / high-probability-session time-window
    classification for e07_technical -- Asian, London Open/Close, NY
    Open/Lunch/Close, and the London/NY Silver Bullet sub-windows.

    Added 2026-08-21. Concept and window set cross-checked against a
    real, working implementation found while auditing
    NadirAliOfficial/STAR-EA-v11.20 (MIT-licensed MQL5 EA,
    InitializeKillzones/IsInKillzone ~L13762-14331) during a 9-repo ICT/
    SMC deep-dive -- confirmed genuinely useful and a real gap in this
    module (smart_money.py had BOS/CHoCH/order-blocks/FVG but nothing
    time-of-day-aware). No MQL5 code was copied; this is a from-scratch
    Python implementation in this codebase's own conventions, reusing
    the tz-aware `df["timestamp"]` pattern already established by
    e24_strategy_research.strategies.session_mask.

    Deliberate design improvement over the source: STAR-EA defines every
    window on a UTC clock and then hand-maintains a separate EU-DST/
    US-DST offset per zone -- real, error-prone bookkeeping, since EU and
    US shift their clocks on different calendar dates each year (a ~1-2
    week gap every spring/fall where a manually-offset UTC window is
    wrong by an hour). This module instead defines each window directly
    in its OWN market's local wall-clock time (e.g. "07:00-10:00 London
    time" for the London killzones) using Python's `zoneinfo`, which
    carries the IANA tz database's authoritative DST transition dates --
    every window is correct year-round with no manual offset table and
    no gap-week bug class to maintain.

    Window-to-timezone assignment is an interpretive choice (STAR-EA's
    own per-zone EU/US DST assignment wasn't re-derived line-by-line):
    Asian -> Asia/Tokyo (no DST, so this choice is DST-irrelevant
    either way); London Open/Close and the London Silver Bullet ->
    Europe/London; NY Open/Lunch/Close and both NY Silver Bullets ->
    America/New_York -- the standard convention in ICT teaching
    material (Silver Bullet windows are always described in NY local
    time; London killzones in London local time).
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from zoneinfo import ZoneInfo

import pandas as pd


class Killzone(str, Enum):
    ASIAN = "asian"
    LONDON_OPEN = "london_open"
    LONDON_CLOSE = "london_close"
    NY_OPEN = "ny_open"
    NY_LUNCH = "ny_lunch"
    NY_CLOSE = "ny_close"
    LONDON_SILVER_BULLET = "london_silver_bullet"
    NY_AM_SILVER_BULLET = "ny_am_silver_bullet"
    NY_PM_SILVER_BULLET = "ny_pm_silver_bullet"


@dataclass(frozen=True)
class _Window:
    tz: str    # IANA zone this window's start/end are LOCAL wall-clock time in
    start: str  # "HH:MM", inclusive
    end: str    # "HH:MM", exclusive


# Local wall-clock windows, each in its own market's home timezone -- see
# module docstring for the STAR-EA cross-check and the tz-assignment
# rationale. None of these windows wrap midnight in local time (the
# Asian session's underlying UTC window does wrap, but 08:00-17:00 JST
# does not, since Tokyo has no DST to shift it across the UTC day
# boundary) -- killzone_mask() below still handles a wrapping window
# correctly in case a future addition needs one.
_WINDOWS: dict[Killzone, _Window] = {
    Killzone.ASIAN: _Window("Asia/Tokyo", "08:00", "17:00"),
    Killzone.LONDON_OPEN: _Window("Europe/London", "07:00", "10:00"),
    Killzone.LONDON_CLOSE: _Window("Europe/London", "15:00", "17:00"),
    Killzone.NY_OPEN: _Window("America/New_York", "07:00", "10:00"),
    Killzone.NY_LUNCH: _Window("America/New_York", "11:00", "13:00"),
    Killzone.NY_CLOSE: _Window("America/New_York", "14:00", "16:00"),
    Killzone.LONDON_SILVER_BULLET: _Window("Europe/London", "10:00", "11:00"),
    Killzone.NY_AM_SILVER_BULLET: _Window("America/New_York", "10:00", "11:00"),
    Killzone.NY_PM_SILVER_BULLET: _Window("America/New_York", "14:00", "15:00"),
}


def killzone_mask(df: pd.DataFrame, zone: Killzone) -> pd.Series:
    """Boolean mask, True for bars whose real UTC timestamp falls inside
    `zone`'s window when converted to that zone's own local time.
    `df["timestamp"]` must be tz-aware (same requirement as
    e24_strategy_research.strategies.session_mask, which this mirrors)."""
    window = _WINDOWS[zone]
    local = df["timestamp"].dt.tz_convert(ZoneInfo(window.tz))
    start_t = pd.to_datetime(window.start).time()
    end_t = pd.to_datetime(window.end).time()
    local_time = local.dt.time
    if start_t <= end_t:
        in_window = (local_time >= start_t) & (local_time < end_t)
    else:
        in_window = (local_time >= start_t) | (local_time < end_t)
    return pd.Series(in_window, index=df.index)


def active_killzones(df: pd.DataFrame) -> pd.DataFrame:
    """One boolean column per Killzone, same index as `df`. Bars can be
    in zero, one, or more overlapping killzones at once (e.g. NY AM
    Silver Bullet sits fully inside NY Open) -- overlaps are real and
    left visible rather than collapsed, so a caller can tell a plain NY
    Open bar from one that's ALSO inside the tighter Silver Bullet
    window."""
    return pd.DataFrame({zone.value: killzone_mask(df, zone) for zone in Killzone}, index=df.index)


def is_high_probability_window(df: pd.DataFrame) -> pd.Series:
    """True for any bar inside at least one killzone -- the simplest
    'is this even a session worth looking for an ICT setup in' filter.
    Callers wanting a tighter filter (e.g. Silver Bullet only) should use
    killzone_mask()/active_killzones() directly instead."""
    return active_killzones(df).any(axis=1)


def active_killzones_at(timestamp) -> list[Killzone]:
    """Single-timestamp convenience wrapper around active_killzones() --
    added 2026-08-21 for the self-improvement trade journal (checking
    whether one signal/trade's entry_time fell inside a killzone) and for
    signal persistence at generation time, neither of which have a whole
    OHLCV DataFrame handy. `timestamp` must be tz-aware (same requirement
    as killzone_mask/df["timestamp"] everywhere else in this module).
    Wraps the single timestamp in a 1-row DataFrame rather than
    duplicating the window-matching logic -- one real implementation to
    keep correct, not two that could drift."""
    df = pd.DataFrame({"timestamp": [pd.Timestamp(timestamp)]})
    row = active_killzones(df).iloc[0]
    return [zone for zone in Killzone if row[zone.value]]
