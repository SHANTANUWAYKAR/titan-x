"""
Module: test_forward_test.py
Description: Tests for engines/e24_strategy_research/forward_test.py
    (reports/statergy.txt NON-NEGOTIABLE #14).

    The integrity tests carry the weight here. A forward-test log that can be
    backfilled is a backtest with a misleading name, and it would be worse than
    no log at all because it would carry the authority of the word "forward"
    while inheriting the selection bias of the search that produced the
    strategy. So most of this file pins that bad records are REFUSED, not
    merely warned about -- and that the refusal raises rather than returning a
    status a caller could overlook.

    The other emphasis is on not flattering a thin sample: 4 forward trades
    must produce "not decidable", never a win rate presented as a result.
Author: Shantanu Waykar
Version: 1.0.0
"""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from project_titan_x.engines.e24_strategy_research import forward_test as ft
from project_titan_x.engines.e24_strategy_research.forward_test import (
    ForwardTestIntegrityError,
    ForwardTestRecord,
    compare_to_backtest,
    load_log,
    observations_needed_to_detect,
    record_signal,
    resolve_record,
    summarise,
)


@pytest.fixture
def log(tmp_path):
    return tmp_path / "forward_test_log.jsonl"


NOW = datetime(2026, 9, 15, 14, 0, tzinfo=timezone.utc)


def _record(log, **over):
    kw = dict(
        symbol="ETH-USD", timeframe="1d", strategy="mss_trend_hold",
        direction="LONG", bar_time=NOW.replace(hour=0), entry=100.0,
        stop_loss=95.0, take_profit=110.0, horizon_bars=5,
        log_path=log, now=NOW,
    )
    kw.update(over)
    return record_signal(**kw)


def _bars(rows, start=None):
    """rows: list of (high, low, close), one per day after the signal bar."""
    start = start or NOW.replace(hour=0) + timedelta(days=1)
    idx = pd.DatetimeIndex([start + timedelta(days=i) for i in range(len(rows))])
    return pd.DataFrame(
        {"high": [r[0] for r in rows], "low": [r[1] for r in rows],
         "close": [r[2] for r in rows]}, index=idx)


# --------------------------------------------------------------------------
# Integrity -- these are the point of the module
# --------------------------------------------------------------------------

def test_backfilled_bar_is_refused(log):
    """The single most important test. Replaying history into the forward log
    would produce a backtest labelled as forward evidence."""
    _record(log)                                   # establishes inception
    with pytest.raises(ForwardTestIntegrityError, match="predates this log"):
        _record(log, bar_time=NOW - timedelta(days=90))


def test_future_bar_is_refused(log):
    _record(log)
    with pytest.raises(ForwardTestIntegrityError, match="in the future"):
        _record(log, bar_time=NOW + timedelta(days=10))


def test_stale_bar_is_refused(log):
    """A prediction written a week after its bar closed had the outcome
    available to it; it is not forward evidence regardless of intent.

    Note this bar is comfortably AFTER inception -- the point is that being
    forward-dated is not sufficient on its own. A runner that wakes up late
    must not quietly log the bars it slept through.
    """
    _record(log)                                   # inception at NOW
    with pytest.raises(ForwardTestIntegrityError, match="bars old at record time"):
        _record(log, bar_time=NOW + timedelta(days=3), now=NOW + timedelta(days=10))


def test_statistics_failure_is_not_reported_as_an_absent_claim(log, monkeypatch):
    """Regression: a broken E12 import used to surface as 'no_claim_to_test',
    which reads as a property of the strategy rather than a broken dependency."""
    monkeypatch.setattr(ft, "_posterior", lambda *a, **k: None)
    out = compare_to_backtest(_resolved(19, 11), 0.625, 64)
    assert out["verdict"] == "statistics_unavailable"
    assert any("broken dependency" in n for n in out["notes"])


def test_first_bar_of_a_fresh_log_is_accepted(log):
    """Regression: a log created at 14:00 must still accept today's 1d bar,
    which is stamped 00:00 and so predates inception by fourteen hours."""
    rec = _record(log, bar_time=NOW.replace(hour=0))
    assert rec is not None
    assert load_log(log)[0].bar_time.startswith("2026-09-15T00:00")


def test_stop_on_the_wrong_side_of_entry_is_refused(log):
    """Without a positive risk distance no R-multiple can ever be computed,
    so the record could never become evidence of anything."""
    with pytest.raises(ForwardTestIntegrityError, match="no risk denominator"):
        _record(log, entry=100.0, stop_loss=105.0)


def test_unknown_timeframe_is_refused_rather_than_defaulted(log):
    with pytest.raises(ForwardTestIntegrityError, match="Unknown timeframe"):
        _record(log, timeframe="3h")


def test_log_without_an_inception_line_is_refused(log):
    """A hand-edited or pre-format log must not have 'now' adopted as its
    inception -- that would make every historical row look forward-dated."""
    log.write_text('{"kind": "prediction", "record_id": "x"}\n', encoding="utf-8")
    with pytest.raises(ForwardTestIntegrityError, match="no inception line"):
        _record(log)


def test_a_truncated_row_does_not_take_the_whole_log_down(log):
    """A partial write must cost one prediction, not every prediction."""
    _record(log)
    with log.open("a", encoding="utf-8") as fh:
        fh.write('{"kind": "prediction", "record_id": "broken"}\n')   # missing fields
        fh.write("{not json at all\n")
    records = load_log(log)
    assert len(records) == 1
    assert records[0].strategy == "mss_trend_hold"


def test_duplicate_within_the_same_bar_is_a_no_op_not_an_error(log):
    """Re-running the scanner inside one bar is normal operation."""
    assert _record(log) is not None
    assert _record(log) is None
    assert len(load_log(log)) == 1


# --------------------------------------------------------------------------
# Append-only: a prediction is never rewritten
# --------------------------------------------------------------------------

def test_resolution_is_a_separate_line_and_prediction_is_untouched(log):
    rec = _record(log)
    before = log.read_text(encoding="utf-8")
    res = resolve_record(rec, _bars([(112, 99, 111)]))
    with log.open("a", encoding="utf-8") as fh:
        import json
        fh.write(json.dumps(res) + "\n")
    after = log.read_text(encoding="utf-8")
    assert after.startswith(before)               # nothing rewritten, only appended
    folded = load_log(log)[0]
    assert folded.outcome == "target"
    assert folded.resolved is True


# --------------------------------------------------------------------------
# Resolution arithmetic -- hand-computed, not "did it return a float"
# --------------------------------------------------------------------------

def test_target_hit_gives_the_hand_computed_r(log):
    # entry 100, stop 95 -> risk 5. Target 110 -> (110-100)/5 = +2.0R
    rec = _record(log)
    res = resolve_record(rec, _bars([(111, 99, 110)]))
    assert res["outcome"] == "target"
    assert res["r_multiple"] == pytest.approx(2.0)
    assert res["bars_held"] == 1


def test_stop_hit_gives_exactly_minus_one_r(log):
    rec = _record(log)
    res = resolve_record(rec, _bars([(101, 94, 96)]))
    assert res["outcome"] == "stop"
    assert res["r_multiple"] == pytest.approx(-1.0)


def test_horizon_exit_uses_the_closing_price(log):
    # never touches 95 or 110; closes at 103 on bar 5 -> (103-100)/5 = +0.6R
    rec = _record(log, horizon_bars=5)
    res = resolve_record(rec, _bars([(105, 98, 101)] * 4 + [(106, 99, 103)]),
                         now=NOW + timedelta(days=7))
    assert res["outcome"] == "horizon"
    assert res["r_multiple"] == pytest.approx(0.6)
    assert res["bars_held"] == 5


def test_horizon_exit_waits_for_the_bar_to_actually_close(log):
    """A horizon exit settles at a CLOSE, and resolutions are first-wins and
    never revisited -- so taking a still-forming bar's provisional close would
    bake a price that was never final into the R-multiple permanently."""
    rec = _record(log, horizon_bars=5)
    bars = _bars([(105, 98, 101)] * 4 + [(106, 99, 103)])
    # wall clock sits INSIDE the final bar: it has opened but not closed
    mid_final_bar = NOW.replace(hour=0) + timedelta(days=5, hours=6)
    assert resolve_record(rec, bars, now=mid_final_bar) is None
    # one second after it closes, it settles
    just_closed = NOW.replace(hour=0) + timedelta(days=6, seconds=1)
    assert resolve_record(rec, bars, now=just_closed)["outcome"] == "horizon"


def test_an_intrabar_touch_still_counts_on_a_forming_bar(log):
    """Unlike a close, a high is a high whether or not the bar has finished --
    if price traded through the target, it traded through the target."""
    rec = _record(log)
    mid_bar = NOW.replace(hour=0) + timedelta(days=1, hours=6)
    res = resolve_record(rec, _bars([(111, 99, 104)]), now=mid_bar)
    assert res["outcome"] == "target"


def test_short_direction_r_is_sign_correct(log):
    # SHORT entry 100, stop 105 -> risk 5. Target 90 -> (100-90)/5 = +2.0R
    rec = _record(log, direction="SHORT", entry=100.0, stop_loss=105.0, take_profit=90.0)
    res = resolve_record(rec, _bars([(101, 89, 91)]))
    assert res["outcome"] == "target"
    assert res["r_multiple"] == pytest.approx(2.0)


def test_ambiguous_bar_resolves_as_a_stop_and_says_so(log):
    """A bar spanning both levels cannot be ordered from OHLC. Resolving it
    the flattering way would silently inflate every forward result."""
    rec = _record(log)
    res = resolve_record(rec, _bars([(115, 90, 108)]))     # spans 95 AND 110
    assert res["outcome"] == "stop"
    assert res["ambiguous_bar"] is True
    assert res["r_multiple"] == pytest.approx(-1.0)


def test_signal_bar_itself_cannot_resolve_the_prediction(log):
    """Classic lookahead: the bar that generated the signal must not also
    decide its outcome."""
    rec = _record(log)
    signal_bar = _bars([(999, 1, 500)], start=NOW.replace(hour=0))
    assert resolve_record(rec, signal_bar) is None


def test_immature_prediction_stays_unresolved(log):
    rec = _record(log, horizon_bars=5)
    assert resolve_record(rec, _bars([(105, 98, 101)] * 2)) is None


def test_resolve_pending_writes_only_matured_records(log):
    _record(log)
    written = ft.resolve_pending(lambda s, tf: _bars([(111, 99, 110)]), log_path=log)
    assert len(written) == 1
    assert load_log(log)[0].outcome == "target"
    # A second pass must not re-resolve what is already settled.
    assert ft.resolve_pending(lambda s, tf: _bars([(111, 99, 110)]), log_path=log) == []


# --------------------------------------------------------------------------
# Frame shape -- both of these are regressions from the first live run
# --------------------------------------------------------------------------

def _native_frame(rows, start=None):
    """This platform's real OHLCV shape: a RangeIndex with the bar time in a
    `timestamp` column, and a `date` column that is entirely null (confirmed on
    ETH-USD_1d: 3674 nulls of 3674 rows)."""
    start = start or NOW.replace(hour=0) + timedelta(days=1)
    return pd.DataFrame({
        "date": [None] * len(rows),
        "timestamp": pd.to_datetime([start + timedelta(days=i) for i in range(len(rows))], utc=True),
        "high": [r[0] for r in rows], "low": [r[1] for r in rows],
        "close": [r[2] for r in rows],
    })


def test_resolution_accepts_the_platforms_native_frame_shape(log):
    """Regression: requiring a DatetimeIndex rejected every frame
    e02_market_data returns, so no prediction could ever have resolved."""
    rec = _record(log)
    res = resolve_record(rec, _native_frame([(111, 99, 110)]))
    assert res is not None
    assert res["outcome"] == "target"
    assert res["r_multiple"] == pytest.approx(2.0)


def test_all_null_date_column_does_not_shadow_the_timestamp_column(log):
    """`date` is present and entirely null in the real parquets; preferring it
    would turn every bar time into NaT and silently drop all bars."""
    df = ft.as_time_indexed(_native_frame([(111, 99, 110), (112, 100, 111)]))
    assert len(df) == 2
    assert df.index.notna().all()


def test_a_row_number_passed_as_a_bar_time_is_named_as_such(log):
    """The first live run passed df.index[-1] (the integer 729). A bare
    ValueError from a date parser gave no hint what had gone wrong."""
    with pytest.raises(ForwardTestIntegrityError, match="row number"):
        _record(log, bar_time=729)


def test_bar_timestamp_reads_the_last_bar_from_either_shape():
    rows = [(111, 99, 110), (112, 100, 111)]
    expected = NOW.replace(hour=0) + timedelta(days=2)
    assert ft.bar_timestamp(_native_frame(rows)) == expected
    assert ft.bar_timestamp(_bars(rows)) == expected


def test_frame_with_no_usable_time_is_refused_not_silently_empty():
    df = pd.DataFrame({"high": [1.0], "low": [0.5], "close": [0.8]})
    with pytest.raises(ForwardTestIntegrityError, match="no usable time column"):
        ft.as_time_indexed(df)


# --------------------------------------------------------------------------
# Comparison -- must not flatter a thin sample
# --------------------------------------------------------------------------

def _resolved(n_wins, n_losses):
    out = []
    for i in range(n_wins + n_losses):
        win = i < n_wins
        out.append(ForwardTestRecord(
            record_id=f"r{i}", symbol="X", timeframe="1d", strategy="s",
            direction="LONG", bar_time=f"2026-09-{(i % 28) + 1:02d}T00:00:00+00:00",
            recorded_at="2026-09-15T00:00:00+00:00", entry=100.0, stop_loss=95.0,
            take_profit=110.0, horizon_bars=5, outcome="target" if win else "stop",
            r_multiple=2.0 if win else -1.0,
        ))
    return out


def test_no_forward_evidence_is_stated_not_scored():
    out = compare_to_backtest([], 0.625, 64)
    assert out["verdict"] == "no_forward_evidence"
    assert out["forward_win_rate"] is None


def test_thin_sample_refuses_a_verdict():
    """4 trades at 75% must not read as confirmation of a 62.5% claim."""
    out = compare_to_backtest(_resolved(3, 1), 0.625, 64)
    assert out["verdict"] == "insufficient_evidence"
    assert out["forward_win_rate"] == pytest.approx(0.75)
    assert any("not yet decidable" in n for n in out["notes"])


def test_degradation_is_detected_from_forward_evidence_alone():
    """The decisive test: forward evidence says degraded, while the backtest
    prior (200 pseudo-observations) would blend it away to 'consistent'.
    The verdict must follow the forward evidence."""
    out = compare_to_backtest(_resolved(10, 20), 0.625, 200)
    assert out["verdict"] == "degraded"
    # the blended posterior is reported, but did not decide
    blended = out["posterior_with_backtest_prior"]["mean"]
    fwd = out["posterior_forward_only"]["mean"]
    assert blended > fwd
    assert blended > 0.5 > fwd
    assert any("context only" in n for n in out["notes"])


def test_consistent_result_is_reported_as_consistent():
    out = compare_to_backtest(_resolved(19, 11), 0.625, 64)
    assert out["verdict"] == "consistent"


def test_outperformance_is_not_treated_as_licence_to_size_up():
    out = compare_to_backtest(_resolved(28, 2), 0.50, 64)
    assert out["verdict"] == "better_than_claim"
    assert any("unmodelled" in n for n in out["notes"])


def test_ambiguous_fraction_is_surfaced_in_the_comparison():
    recs = _resolved(10, 10)
    for r in recs[:6]:
        r.ambiguous_bar = True
    out = compare_to_backtest(recs, 0.625, 64)
    assert out["ambiguous_resolutions"] == 6
    assert any("counted as a stop" in n for n in out["notes"])


def test_missing_backtest_claim_says_so_rather_than_inventing_one():
    out = compare_to_backtest(_resolved(15, 10), None, None)
    assert out["verdict"] == "no_claim_to_test"


# --------------------------------------------------------------------------
# Power -- the number the user actually needs
# --------------------------------------------------------------------------

def test_detecting_a_smaller_degradation_needs_more_trades():
    big = observations_needed_to_detect(0.625, 0.45)
    small = observations_needed_to_detect(0.625, 0.58)
    assert big < small


def test_breakeven_win_rate_matches_the_reward_risk():
    assert ft.breakeven_win_rate(1.0) == pytest.approx(0.5)
    assert ft.breakeven_win_rate(2.0) == pytest.approx(1 / 3)
    assert ft.breakeven_win_rate(3.0) == pytest.approx(0.25)
    assert ft.breakeven_win_rate(0) is None


def test_planned_reward_risk_uses_the_median_not_the_mean():
    """One signal with a distant target must not drag the breakeven estimate
    and, with it, every count derived from it."""
    recs = _resolved(3, 0)
    for r, tp in zip(recs, (110.0, 112.0, 400.0)):   # 2:1, 2.4:1, 60:1
        r.take_profit = tp
    assert ft.planned_reward_risk(recs) == pytest.approx(2.4)


def test_power_is_measured_against_breakeven_not_a_coin_flip(log):
    """Regression on a real defect. BTC-USD's live dual_thrust signal plans
    2:1, where breakeven is 33.3%. Testing its 52.5% claim against 50% asked
    when it would fall far BELOW breakeven, and answered 1080 trades where the
    decision-relevant question answers 19."""
    _record(log, entry=100.0, stop_loss=95.0, take_profit=110.0,   # 2:1
            backtest_claim={"win_rate": 0.525, "total_trades": 80})
    s = summarise(log)["series"][0]
    assert s["planned_reward_risk"] == pytest.approx(2.0)
    assert s["breakeven_win_rate"] == pytest.approx(1 / 3, abs=1e-3)
    assert s["trades_to_detect_degradation"] < 100
    assert s["trades_to_detect_degradation"] < observations_needed_to_detect(0.525, 0.5)


def test_claim_at_or_below_its_own_breakeven_is_called_out(log):
    """A 40% claim on a 1:1 structure loses money at its own stated hit rate.
    That must be stated, not buried in a power calculation."""
    _record(log, entry=100.0, stop_loss=95.0, take_profit=105.0,   # 1:1 -> 50% breakeven
            backtest_claim={"win_rate": 0.40, "total_trades": 80})
    s = summarise(log)["series"][0]
    assert any("does not profit at its own claimed hit rate" in n for n in s["notes"])


def test_claim_significance_reports_both_baselines():
    """Neither number is quotable alone: dual_thrust's real 52.5% over 80
    trades reads as noise against 50% and as strong against its own 33.3%."""
    sig = ft.claim_significance(0.525, 80, 1 / 3)
    assert sig["p_vs_coin_flip"] == pytest.approx(0.369, abs=0.01)
    assert sig["p_vs_breakeven"] < 0.001
    assert sig["wins"] == 42


def test_claim_significance_needs_all_three_inputs():
    assert ft.claim_significance(None, 80, 0.5) is None
    assert ft.claim_significance(0.6, None, 0.5) is None
    assert ft.claim_significance(0.6, 80, None) is None


def test_summary_states_the_baseline_alongside_the_p_value(log):
    _record(log, entry=100.0, stop_loss=95.0, take_profit=110.0,
            backtest_claim={"win_rate": 0.525, "total_trades": 80})
    s = summarise(log)["series"][0]
    assert s["claim_significance"]["p_vs_breakeven"] < 0.001
    assert any("without its baseline" in n for n in s["notes"])


def test_undetectable_degradation_returns_none_rather_than_a_number():
    assert observations_needed_to_detect(0.625, 0.624, max_n=200) is None


def test_nonsense_inputs_return_none():
    assert observations_needed_to_detect(0.5, 0.7) is None       # "degraded" is higher
    assert observations_needed_to_detect(0.625, 0.0) is None


# --------------------------------------------------------------------------
# Orchestration -- deny-by-default, and never fabricate on failure
# --------------------------------------------------------------------------

def _write_override(d, symbol, timeframe, status, strategy="mss_trend_hold"):
    import json
    doc = {
        "strategy": strategy, "params": {"hold_bars": 5},
        "win_rate": 0.625, "total_trades": 64, "is_sharpe": 1.12, "oos_sharpe": 1.08,
    }
    if status is not None:
        doc["stage0"] = {"status": status, "measured": {"null_percentile": 100.0}}
    (d / f"{symbol}_{timeframe}_strategy_override.json").write_text(
        json.dumps(doc), encoding="utf-8")


def test_only_explicitly_validated_overrides_are_forward_tested(tmp_path):
    """Same deny-by-default rule the live signal gate applies: a missing or
    malformed stage0 block is not an implicit pass."""
    _write_override(tmp_path, "ETH-USD", "1d", "VALIDATED")
    _write_override(tmp_path, "BTC-USD", "1d", "UNVALIDATED")
    _write_override(tmp_path, "GC=F", "4h", None)             # no stage0 block
    (tmp_path / "BAD_1d_strategy_override.json").write_text("{not json", encoding="utf-8")

    found = ft.validated_overrides(tmp_path)
    assert [o["yahoo_symbol"] for o in found] == ["ETH-USD"]
    assert found[0]["claim"]["win_rate"] == 0.625
    assert found[0]["claim"]["null_percentile"] == 100.0


class _FakeResult:
    def __init__(self, data=None, success=True, message=""):
        self.data, self.success, self.message = data, success, message


class _FakeRegistry:
    """Minimal stand-in for the engine registry: enough to drive the chain,
    with `fail_at` to prove a mid-chain failure skips rather than fabricates."""

    def __init__(self, signal=None, fail_at=None, bars=None):
        self.signal, self.fail_at, self.bars = signal, fail_at, bars

    def get(self, name):
        reg = self

        class _E:
            def fetch_ohlcv(self, sym, tf, years=2):
                if reg.fail_at == "e02_market_data":
                    return _FakeResult(success=False, message="rate limited")
                return _FakeResult(data=reg.bars)

            def repair(self, df):
                return _FakeResult(data=df)

            def analyze(self, df=None, symbol=None, timeframe=None):
                if reg.fail_at == name:
                    return _FakeResult(success=False, message="boom")
                return _FakeResult(data={"snapshot": object(), "df": df})

            def classify(self, df, snap, macro):
                if reg.fail_at == name:
                    return _FakeResult(success=False, message="boom")
                return _FakeResult(data=object())

            def generate_signal(self, *a, **k):
                if reg.signal is None:
                    return _FakeResult(data=None, message="no signal")
                return _FakeResult(data=reg.signal)

        if name == "e04_macro":
            class _Macro(_E):
                def analyze(self, *a, **k):
                    return _FakeResult(data=None)
            return _Macro()
        return _E()


class _FakeSignal:
    asset, direction = "ETHUSD", "LONG"
    entry, stop_loss, take_profit_1 = 100.0, 95.0, 110.0
    confidence_score = 71


def test_scan_and_record_logs_a_real_signal(tmp_path, log):
    _write_override(tmp_path, "ETH-USD", "1d", "VALIDATED")
    bars = _native_frame([(101, 99, 100)], start=NOW.replace(hour=0))
    reg = _FakeRegistry(signal=_FakeSignal(), bars=bars)

    out = ft.scan_and_record(reg, ft.validated_overrides(tmp_path), log_path=log, now=NOW)
    assert len(out["recorded"]) == 1
    rec = load_log(log)[0]
    assert rec.direction == "LONG"
    assert rec.horizon_bars == 5                    # from the override's params
    assert rec.backtest_claim["win_rate"] == 0.625  # claim frozen at record time


def test_a_bar_with_no_signal_is_not_logged_as_a_trade(tmp_path, log):
    _write_override(tmp_path, "ETH-USD", "1d", "VALIDATED")
    reg = _FakeRegistry(signal=None, bars=_native_frame([(101, 99, 100)], start=NOW.replace(hour=0)))
    out = ft.scan_and_record(reg, ft.validated_overrides(tmp_path), log_path=log, now=NOW)
    assert out["recorded"] == []
    assert out["silent"] and load_log(log) == []


@pytest.mark.parametrize("stage", ["e02_market_data", "e07_technical", "e08_regime"])
def test_engine_failure_skips_rather_than_fabricating(tmp_path, log, stage):
    """A gap in the log is recoverable; a fabricated prediction in it is not."""
    _write_override(tmp_path, "ETH-USD", "1d", "VALIDATED")
    reg = _FakeRegistry(signal=_FakeSignal(), fail_at=stage,
                        bars=_native_frame([(101, 99, 100)], start=NOW.replace(hour=0)))
    out = ft.scan_and_record(reg, ft.validated_overrides(tmp_path), log_path=log, now=NOW)
    assert out["recorded"] == []
    assert len(out["skipped"]) == 1
    assert load_log(log) == []


def test_scan_twice_in_one_bar_records_once(tmp_path, log):
    _write_override(tmp_path, "ETH-USD", "1d", "VALIDATED")
    reg = _FakeRegistry(signal=_FakeSignal(),
                        bars=_native_frame([(101, 99, 100)], start=NOW.replace(hour=0)))
    ovs = ft.validated_overrides(tmp_path)
    ft.scan_and_record(reg, ovs, log_path=log, now=NOW)
    second = ft.scan_and_record(reg, ovs, log_path=log, now=NOW)
    assert second["recorded"] == []
    assert len(load_log(log)) == 1


# --------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------

def test_summarise_groups_by_series_and_carries_inception(log):
    _record(log, backtest_claim={"win_rate": 0.625, "total_trades": 64})
    _record(log, symbol="BTC-USD", backtest_claim={"win_rate": 0.60, "total_trades": 71})
    out = summarise(log)
    assert out["total_predictions"] == 2
    assert out["inception"] is not None
    assert {s["symbol"] for s in out["series"]} == {"ETH-USD", "BTC-USD"}
    for s in out["series"]:
        assert s["trades_to_detect_degradation"] > 0


def test_summarise_on_an_absent_log_is_empty_not_an_error(tmp_path):
    out = summarise(tmp_path / "nope.jsonl")
    assert out["total_predictions"] == 0
    assert out["series"] == []


# --------------------------------------------------------------------------
# Decay detection reuses E38 rather than defining "decay" a second time
# --------------------------------------------------------------------------

def test_as_trade_dicts_is_most_recent_first():
    """E35.list_trades' ordering, which E38 assumes when it splits the list
    into a recent window and a baseline window. Reversed input would make E38
    compare the oldest trades against the newest and report the decay
    backwards."""
    recs = _resolved(2, 2)
    for i, r in enumerate(recs):
        r.exit_time = f"2026-09-{i + 1:02d}T00:00:00+00:00"
    out = ft.as_trade_dicts(recs)
    assert [t["exit_time"] for t in out] == [
        "2026-09-04T00:00:00+00:00", "2026-09-03T00:00:00+00:00",
        "2026-09-02T00:00:00+00:00", "2026-09-01T00:00:00+00:00",
    ]


def test_as_trade_dicts_skips_unresolved_predictions():
    recs = _resolved(2, 1)
    recs.append(ForwardTestRecord(
        record_id="pending", symbol="X", timeframe="1d", strategy="s", direction="LONG",
        bar_time="2026-09-20T00:00:00+00:00", recorded_at="2026-09-20T00:00:00+00:00",
        entry=100.0, stop_loss=95.0, take_profit=110.0, horizon_bars=5))
    assert len(ft.as_trade_dicts(recs)) == 3


def test_as_trade_dicts_does_not_invent_an_account_percentage():
    """A forward record stores R, not account percentage. Fabricating one
    would feed a made-up number into a decay test."""
    assert all(t["pnl_percent"] is None for t in ft.as_trade_dicts(_resolved(1, 1)))


def test_a_thin_forward_sample_yields_insufficient_data_not_a_verdict(log):
    out = ft.decay_assessment(_resolved(2, 1), strategy_name="s")
    assert out is None or out.get("status") == "insufficient_data"


def test_decay_assessment_without_any_resolved_records_is_none():
    assert ft.decay_assessment([], strategy_name="s") is None
