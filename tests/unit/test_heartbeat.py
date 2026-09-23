"""
Module: test_heartbeat.py
Description: Tests for core/heartbeat.py — P0.2 in docs/INSTITUTIONAL_AUDIT.md
    (`reports/upgrade statergy.txt` PHASES 25 and 27).

    The load-bearing test here is `test_a_job_that_never_ran_is_not_healthy`.
    Everything else this module does is bookkeeping; the reason it exists is
    that a job which silently stopped — or never started because a try/except
    in lifespan swallowed its registration error — used to be indistinguishable
    from a healthy system with nothing to do. Defaulting an unknown job to `ok`
    would rebuild exactly that blindness.
Author: Shantanu Waykar
Version: 1.0.0
"""

from datetime import datetime, timedelta, timezone

import pytest

from project_titan_x.core import heartbeat as hb

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
HOURLY = 3600.0


@pytest.fixture
def state(tmp_path):
    return tmp_path / "heartbeats.json"


# --------------------------------------------------------------------------
# The point of the module
# --------------------------------------------------------------------------

def test_a_job_that_never_ran_is_not_healthy(state):
    """A job listed as expected but never seen must report `never_run`. This
    is the failure the module exists to catch: silence looks identical to
    success unless absence is reported explicitly."""
    [s] = hb.check({"forward_test": HOURLY}, state, now=NOW)
    assert s.name == "forward_test"
    assert s.state == "never_run"
    assert s.healthy is False
    assert hb.overall_state([s]) == "degraded"


def test_an_unknown_job_is_not_invented(state):
    """Only jobs that are expected or have recorded a beat are reported."""
    hb.record_success("real_job", HOURLY, state, now=NOW)
    names = {s.name for s in hb.check({}, state, now=NOW)}
    assert names == {"real_job"}


def test_a_job_that_only_ever_failed_is_never_run_not_ok(state):
    hb.record_failure("forward_test", "fetch blew up", HOURLY, state, now=NOW)
    [s] = hb.check({"forward_test": HOURLY}, state, now=NOW)
    assert s.state == "never_run"
    assert "fetch blew up" in s.detail


# --------------------------------------------------------------------------
# States
# --------------------------------------------------------------------------

def test_a_recent_success_is_ok(state):
    hb.record_success("job", HOURLY, state, now=NOW)
    [s] = hb.check({"job": HOURLY}, state, now=NOW + timedelta(minutes=30))
    assert s.state == "ok"
    assert hb.overall_state([s]) == "healthy"


def test_an_ordinary_late_run_is_not_called_stale(state):
    """A monitor that cries stale on every slightly-late run gets ignored,
    which is worse than no monitor. Tolerance is 2x the interval."""
    hb.record_success("job", HOURLY, state, now=NOW)
    [s] = hb.check({"job": HOURLY}, state, now=NOW + timedelta(minutes=90))
    assert s.state == "ok"


def test_a_job_well_past_its_interval_is_stale(state):
    hb.record_success("job", HOURLY, state, now=NOW)
    [s] = hb.check({"job": HOURLY}, state, now=NOW + timedelta(hours=5))
    assert s.state == "stale"
    assert "may have stopped running" in s.detail
    assert s.seconds_since_success == pytest.approx(5 * 3600)


def test_one_bad_run_is_not_failing_but_three_are(state):
    hb.record_success("job", HOURLY, state, now=NOW)
    hb.record_failure("job", "transient", HOURLY, state, now=NOW)
    assert hb.check({"job": HOURLY}, state, now=NOW)[0].state == "ok"
    hb.record_failure("job", "again", HOURLY, state, now=NOW)
    hb.record_failure("job", "and again", HOURLY, state, now=NOW)
    s = hb.check({"job": HOURLY}, state, now=NOW)[0]
    assert s.state == "failing"
    assert s.consecutive_failures == 3
    assert "and again" in s.detail


def test_a_success_clears_the_failure_streak(state):
    # A prior success is required for `failing` to apply at all: with none,
    # the job is `never_run`, which outranks it (see the test above).
    hb.record_success("job", HOURLY, state, now=NOW)
    for i in range(4):
        hb.record_failure("job", f"e{i}", HOURLY, state, now=NOW)
    assert hb.check({"job": HOURLY}, state, now=NOW)[0].state == "failing"

    hb.record_success("job", HOURLY, state, now=NOW)
    s = hb.check({"job": HOURLY}, state, now=NOW)[0]
    assert s.state == "ok"
    assert s.consecutive_failures == 0
    assert hb.load(state)["job"].last_error is None


def test_a_job_with_no_expected_interval_cannot_be_stale(state):
    """Without an interval there is no basis to call a gap abnormal, and
    guessing one would produce alerts that mean nothing."""
    hb.record_success("adhoc", None, state, now=NOW)
    [s] = hb.check({}, state, now=NOW + timedelta(days=30))
    assert s.state == "ok"


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

def test_problems_sort_before_healthy_jobs(state):
    hb.record_success("fine", HOURLY, state, now=NOW)
    hb.record_success("old", HOURLY, state, now=NOW - timedelta(hours=10))
    states = [s.state for s in hb.check({"fine": HOURLY, "old": HOURLY, "missing": HOURLY},
                                        state, now=NOW)]
    assert states == ["never_run", "stale", "ok"]


def test_overall_is_healthy_only_when_nothing_is_wrong(state):
    hb.record_success("a", HOURLY, state, now=NOW)
    hb.record_success("b", HOURLY, state, now=NOW)
    assert hb.overall_state(hb.check({"a": HOURLY, "b": HOURLY}, state, now=NOW)) == "healthy"
    assert hb.overall_state(hb.check({"a": HOURLY, "c": HOURLY}, state, now=NOW)) == "degraded"


# --------------------------------------------------------------------------
# Durability -- recording must never cost the work it observes
# --------------------------------------------------------------------------

def test_recording_survives_an_unwritable_location(tmp_path):
    """Best-effort by contract: a heartbeat write failing must not raise into
    the job it was observing."""
    bad = tmp_path / "nonexistent-file" / "nested" / "x.json"
    (tmp_path / "nonexistent-file").write_text("I am a file, not a directory", encoding="utf-8")
    hb.record_success("job", HOURLY, bad)        # must not raise
    hb.record_failure("job", "err", HOURLY, bad)  # must not raise


def test_a_corrupt_state_file_reads_as_empty_rather_than_crashing(state):
    state.write_text("{not json", encoding="utf-8")
    assert hb.load(state) == {}
    [s] = hb.check({"job": HOURLY}, state, now=NOW)
    assert s.state == "never_run"          # not silently healthy


def test_state_survives_a_reload(state):
    hb.record_success("job", HOURLY, state, now=NOW)
    reloaded = hb.load(state)
    assert reloaded["job"].total_successes == 1
    assert reloaded["job"].expected_interval_seconds == HOURLY


def test_an_unreadable_entry_does_not_sink_the_others(state):
    import json
    hb.record_success("good", HOURLY, state, now=NOW)
    doc = json.loads(state.read_text(encoding="utf-8"))
    doc["heartbeats"]["bad"] = {"unexpected_field": 1}
    state.write_text(json.dumps(doc), encoding="utf-8")
    assert "good" in hb.load(state)


# --------------------------------------------------------------------------
# guard()
# --------------------------------------------------------------------------

def test_guard_records_success_on_a_clean_block(state):
    with hb.guard("job", HOURLY, state):
        pass
    assert hb.load(state)["job"].total_successes == 1


def test_guard_records_failure_and_re_raises(state):
    """This observes; it never swallows."""
    with pytest.raises(ValueError, match="boom"):
        with hb.guard("job", HOURLY, state):
            raise ValueError("boom")
    b = hb.load(state)["job"]
    assert b.total_failures == 1
    assert "boom" in b.last_error


# --------------------------------------------------------------------------
# Data staleness — asset-class aware
#
# The regression this pins: a blanket bar-count rule flags every equity,
# forex, index and commodity instrument as stale EVERY weekend. A staleness
# alarm that fires 104 days a year is one nobody reads by the time it matters.
# --------------------------------------------------------------------------

TUESDAY = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
PRIOR_FRIDAY = datetime(2026, 9, 11, 0, 0, tzinfo=timezone.utc)


def test_a_weekend_gap_is_not_stale_for_a_market_that_was_closed():
    v = hb.data_staleness_verdict("EURUSD=X", "1d", PRIOR_FRIDAY, TUESDAY)
    assert v["continuous_market"] is False
    assert v["state"] == "ok"
    assert "session-based" in v["detail"]


def test_the_same_gap_is_stale_for_a_market_that_never_closes():
    v = hb.data_staleness_verdict("BTC-USD", "1d", PRIOR_FRIDAY, TUESDAY)
    assert v["continuous_market"] is True
    assert v["state"] == "stale"
    assert "24/7" in v["detail"]


def test_fresh_data_is_ok_for_both_kinds_of_market():
    fresh = TUESDAY - timedelta(hours=6)
    for sym in ("BTC-USD", "AAPL"):
        assert hb.data_staleness_verdict(sym, "1d", fresh, TUESDAY)["state"] == "ok"


def test_a_genuinely_abandoned_feed_is_stale_for_every_asset_class():
    ancient = TUESDAY - timedelta(days=30)
    for sym in ("BTC-USD", "EURUSD=X", "AAPL"):
        assert hb.data_staleness_verdict(sym, "1d", ancient, TUESDAY)["state"] == "stale"


def test_an_unknown_asset_gets_the_stricter_tolerance():
    """A staleness check must not become more permissive because it failed to
    identify the instrument."""
    v = hb.data_staleness_verdict("NOT-A-REAL-SYMBOL", "1d", PRIOR_FRIDAY, TUESDAY)
    assert v["continuous_market"] is True
    assert v["tolerance_bars"] == 3.0


def test_an_unknown_timeframe_reports_unknown_rather_than_guessing():
    v = hb.data_staleness_verdict("BTC-USD", "3h", PRIOR_FRIDAY, TUESDAY)
    assert v["state"] == "unknown"
    assert v["age_bars"] is None


def test_a_naive_timestamp_is_treated_as_utc_not_rejected():
    naive = PRIOR_FRIDAY.replace(tzinfo=None)
    assert hb.data_staleness_verdict("BTC-USD", "1d", naive, TUESDAY)["state"] == "stale"
