"""
Module: test_killzones.py
Description: Unit tests for engines/e07_technical/killzones.py -- see that
    module's docstring for provenance (concept cross-checked against
    NadirAliOfficial/STAR-EA-v11.20, no code copied). Covers: correct
    window membership for each zone, real DST-boundary correctness (the
    exact bug class the module's docstring says this design avoids), and
    overlap/union behavior.
Author: Shantanu Waykar
Version: 1.0.0
"""

import pandas as pd

from project_titan_x.engines.e07_technical.killzones import (
    Killzone,
    active_killzones,
    active_killzones_at,
    is_high_probability_window,
    killzone_mask,
)


def _df(timestamps: list[str]) -> pd.DataFrame:
    return pd.DataFrame({"timestamp": pd.to_datetime(timestamps, utc=True)})


def test_ny_open_window_correct_in_january_est():
    # 07:00-10:00 America/New_York in January is EST (UTC-5) -> 12:00-15:00 UTC.
    df = _df([
        "2026-01-15 11:59:00",  # just before -> False
        "2026-01-15 12:00:00",  # start, inclusive -> True
        "2026-01-15 14:59:00",  # inside -> True
        "2026-01-15 15:00:00",  # end, exclusive -> False
    ])
    mask = killzone_mask(df, Killzone.NY_OPEN)
    assert mask.tolist() == [False, True, True, False]


def test_ny_open_window_correct_in_july_edt_real_dst_shift():
    """The same 07:00-10:00 NY-local window in July (EDT, UTC-4) must
    land ONE HOUR EARLIER in UTC than the January case above (11:00-14:00
    UTC, not 12:00-15:00 UTC) -- this is exactly the real-world
    correctness this module's docstring claims over a hand-maintained
    UTC+manual-offset table: get this wrong and NY Open would silently
    be checked against the wrong UTC hour for half the year."""
    df = _df([
        "2026-07-15 10:59:00",  # just before -> False
        "2026-07-15 11:00:00",  # start, inclusive -> True
        "2026-07-15 13:59:00",  # inside -> True
        "2026-07-15 14:00:00",  # end, exclusive -> False
    ])
    mask = killzone_mask(df, Killzone.NY_OPEN)
    assert mask.tolist() == [False, True, True, False]


def test_london_open_window_shifts_with_bst_too():
    # 07:00-10:00 Europe/London: GMT (UTC+0) in January -> 07:00-10:00 UTC;
    # BST (UTC+1) in July -> 06:00-09:00 UTC.
    winter = _df(["2026-01-15 07:00:00", "2026-01-15 09:59:00", "2026-01-15 10:00:00"])
    summer = _df(["2026-07-15 06:00:00", "2026-07-15 08:59:00", "2026-07-15 09:00:00"])
    assert killzone_mask(winter, Killzone.LONDON_OPEN).tolist() == [True, True, False]
    assert killzone_mask(summer, Killzone.LONDON_OPEN).tolist() == [True, True, False]


def test_asian_session_has_no_dst_and_wraps_the_utc_day_boundary():
    # 08:00-17:00 Asia/Tokyo (UTC+9, no DST) -> 23:00 (prior UTC day)-08:00 UTC.
    df = _df([
        "2026-03-10 22:59:00",  # just before -> False
        "2026-03-10 23:00:00",  # start (wraps) -> True
        "2026-03-11 03:00:00",  # inside, after midnight UTC -> True
        "2026-03-11 07:59:00",  # inside, just before end -> True
        "2026-03-11 08:00:00",  # end, exclusive -> False
    ])
    mask = killzone_mask(df, Killzone.ASIAN)
    assert mask.tolist() == [False, True, True, True, False]


def test_ny_am_silver_bullet_is_distinct_from_ny_open():
    """NY AM Silver Bullet (10:00-11:00 NY time) starts right after NY
    Open (07:00-10:00) ends -- the two windows must not overlap. A bar at
    10:30 NY time should be in the AM Silver Bullet but NOT in NY Open."""
    df = _df(["2026-01-15 15:30:00"])  # 10:30 EST = 15:30 UTC
    assert killzone_mask(df, Killzone.NY_AM_SILVER_BULLET).tolist() == [True]
    assert killzone_mask(df, Killzone.NY_OPEN).tolist() == [False]


def test_active_killzones_returns_one_column_per_zone():
    df = _df(["2026-01-15 12:00:00"])  # inside NY Open (12:00-15:00 UTC in Jan)
    table = active_killzones(df)
    assert set(table.columns) == {z.value for z in Killzone}
    assert bool(table.loc[0, "ny_open"]) is True
    assert bool(table.loc[0, "asian"]) is False


def test_is_high_probability_window_true_inside_any_zone():
    df = _df([
        "2026-01-15 12:00:00",  # inside NY Open (12:00-15:00 UTC in January) -> True
        "2026-01-15 03:00:00",  # inside the Asian session (23:00-08:00 UTC wrap) -> True
    ])
    mask = is_high_probability_window(df)
    assert mask.iloc[0] == True  # noqa: E712
    assert mask.iloc[1] == True  # noqa: E712


def test_active_killzones_at_matches_active_killzones_for_the_same_timestamp():
    ts = pd.Timestamp("2026-01-15 12:00:00", tz="UTC")  # inside NY Open
    result = active_killzones_at(ts)
    assert Killzone.NY_OPEN in result
    assert Killzone.ASIAN not in result


def test_active_killzones_at_empty_in_a_dead_zone():
    ts = pd.Timestamp("2026-01-15 18:30:00", tz="UTC")
    assert active_killzones_at(ts) == []


def test_is_high_probability_window_false_in_a_real_dead_zone():
    # 18:30 UTC in January: NY Lunch ends 13:00 EST=18:00 UTC, NY Close
    # starts 14:00 EST=19:00 UTC, London Close ended 17:00 UTC, Asian
    # starts 23:00 UTC -- a genuine gap between all defined windows.
    df = _df(["2026-01-15 18:30:00"])
    mask = is_high_probability_window(df)
    assert mask.iloc[0] == False  # noqa: E712
