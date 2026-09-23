"""
Module: test_experiment.py
Description: Tests for core/experiment.py — P1.1 in docs/INSTITUTIONAL_AUDIT.md
    (`reports/upgrade statergy.txt` PHASES 8, 24, 29).

    Two things carry the weight here, and both are about not lying in a record
    that will outlive the session that wrote it:

    1. A dirty working tree must make `reproducible` False. A git SHA alone
       implies a reproducibility it does not deliver — this repo has 270 files
       modified against `992f8f6`, so "run at 992f8f6" would be actively
       misleading for anything run today.
    2. Nothing may be overwritten. Non-negotiables 8, 9 and 15 forbid hiding
       failed research, deleting negative results, and silently changing
       historical ones, so a duplicate id raises rather than replacing.
Author: Shantanu Waykar
Version: 1.0.0
"""

from datetime import datetime, timezone

import pytest

from project_titan_x.core import experiment as ex
from project_titan_x.core.experiment import ExperimentIntegrityError

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def log(tmp_path):
    return tmp_path / "experiments.jsonl"


def _rec(log, **over):
    kw = dict(
        kind="sweep", title="demo", conclusion="rejected: OOS Sharpe below bar",
        log_path=log, now=NOW, capture_versions=False,
    )
    kw.update(over)
    return ex.record(**kw)


# --------------------------------------------------------------------------
# Reproducibility honesty
# --------------------------------------------------------------------------

def test_a_dirty_tree_means_not_reproducible(log, monkeypatch):
    monkeypatch.setattr(ex, "code_version",
                        lambda *a, **k: {"git_sha": "992f8f6", "dirty": True, "dirty_file_count": 270})
    monkeypatch.setattr(ex, "data_version", lambda *a, **k: {"checksum": "abc"})
    rec = _rec(log, symbol="ETHUSD", timeframe="1d", capture_versions=True)
    assert rec.reproducible is False
    assert any("working tree was dirty" in r for r in rec.why_not_reproducible())
    assert any("NOT REPRODUCIBLE" in n for n in rec.notes)


def test_a_clean_tree_with_known_data_is_reproducible(log, monkeypatch):
    monkeypatch.setattr(ex, "code_version",
                        lambda *a, **k: {"git_sha": "abc1234", "dirty": False, "dirty_file_count": 0})
    monkeypatch.setattr(ex, "data_version", lambda *a, **k: {"checksum": "deadbeef"})
    rec = _rec(log, symbol="ETHUSD", timeframe="1d", capture_versions=True)
    assert rec.reproducible is True
    assert rec.why_not_reproducible() == []
    assert not any("NOT REPRODUCIBLE" in n for n in rec.notes)


def test_a_clean_tree_with_unknown_data_is_still_not_reproducible(log, monkeypatch):
    """Known code against unidentified input does not let anyone re-run it."""
    monkeypatch.setattr(ex, "code_version",
                        lambda *a, **k: {"git_sha": "abc1234", "dirty": False, "dirty_file_count": 0})
    monkeypatch.setattr(ex, "data_version", lambda *a, **k: {})
    rec = _rec(log, symbol="X", timeframe="1d", capture_versions=True)
    assert rec.reproducible is False
    assert any("no dataset checksum" in r for r in rec.why_not_reproducible())


def test_missing_git_is_recorded_as_absent_not_invented(log, monkeypatch):
    monkeypatch.setattr(ex, "code_version", lambda *a, **k: {})
    rec = _rec(log, capture_versions=True)
    assert rec.code_version == {}
    assert any("no git revision" in r for r in rec.why_not_reproducible())


# --------------------------------------------------------------------------
# Append-only lineage
# --------------------------------------------------------------------------

def test_a_duplicate_id_is_refused_not_overwritten(log):
    first = _rec(log, experiment_id="fixed-id", conclusion="original finding")
    with pytest.raises(ExperimentIntegrityError, match="append-only"):
        _rec(log, experiment_id="fixed-id", conclusion="revised finding")
    assert ex.get("fixed-id", log).conclusion == "original finding"
    assert len(ex.load(log)) == 1
    assert first.experiment_id == "fixed-id"


def test_recording_appends_rather_than_replacing(log):
    _rec(log, title="first")
    before = log.read_text(encoding="utf-8")
    _rec(log, title="second")
    assert log.read_text(encoding="utf-8").startswith(before)
    assert [r.title for r in ex.load(log)] == ["first", "second"]


def test_a_malformed_line_does_not_cost_the_whole_history(log):
    _rec(log, title="real")
    with log.open("a", encoding="utf-8") as fh:
        fh.write("{not json\n")
        fh.write('{"experiment_id": "x"}\n')       # missing required fields
    recs = ex.load(log)
    assert [r.title for r in recs] == ["real"]


# --------------------------------------------------------------------------
# A conclusion is mandatory
# --------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["", "   ", None])
def test_an_experiment_without_a_conclusion_is_refused(log, bad):
    """Without it, this log is only a second copy of the sweep reports."""
    with pytest.raises(ExperimentIntegrityError, match="needs a conclusion"):
        _rec(log, conclusion=bad)


def test_a_failed_experiment_is_recordable_as_a_failure(log):
    """Non-negotiables 8 and 9: failed research is kept, not hidden."""
    rec = _rec(log, conclusion="REJECTED -- cleared the bar in-sample, failed OOS")
    assert "REJECTED" in ex.get(rec.experiment_id, log).conclusion


# --------------------------------------------------------------------------
# Ids and retrieval
# --------------------------------------------------------------------------

def test_ids_are_sortable_and_carry_their_kind():
    a = ex.new_experiment_id("sweep", NOW)
    assert a.startswith("sweep-20260915T120000-")
    assert a != ex.new_experiment_id("sweep", NOW)     # collision-resistant


def test_get_returns_none_for_an_unknown_id(log):
    _rec(log)
    assert ex.get("no-such-experiment", log) is None


def test_an_unknown_kind_is_recorded_rather_than_refused(log, caplog):
    """Losing a real experiment to a vocabulary mismatch is worse than an
    untidy `kind` field."""
    rec = _rec(log, kind="something_new")
    assert ex.get(rec.experiment_id, log).kind == "something_new"


# --------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------

def test_summarise_counts_by_kind_and_reproducibility(log, monkeypatch):
    monkeypatch.setattr(ex, "code_version",
                        lambda *a, **k: {"git_sha": "abc", "dirty": False, "dirty_file_count": 0})
    monkeypatch.setattr(ex, "data_version", lambda *a, **k: {"checksum": "x"})
    _rec(log, kind="sweep", symbol="A", timeframe="1d", capture_versions=True)
    _rec(log, kind="sweep", symbol="B", timeframe="1d", capture_versions=True)
    _rec(log, kind="null_campaign")                       # no versions captured
    s = ex.summarise(log)
    assert s["total"] == 3
    assert s["by_kind"] == {"sweep": 2, "null_campaign": 1}
    assert s["reproducible"] == 2
    assert s["not_reproducible"] == 1


def test_summarise_on_an_absent_log_is_empty(tmp_path):
    s = ex.summarise(tmp_path / "nope.jsonl")
    assert s["total"] == 0 and s["by_kind"] == {}


# --------------------------------------------------------------------------
# Data provenance delegates to the catalog, and resolves both spellings
# --------------------------------------------------------------------------

def test_data_version_resolves_registry_and_yahoo_spellings(monkeypatch):
    """Real trap: the catalog is keyed by yahoo symbol ("ETH-USD") while sweep
    reports and overrides use the registry symbol ("ETHUSD"). Measured before
    the fix: data_version("ETHUSD", "1d") returned {} while data_version
    ("ETH-USD", "1d") returned a full record."""
    entry = {"dataset_id": "ETH-USD_1d", "source": "yahoo_finance", "rows": 731,
             "date_range": ["a", "b"], "checksum": "daac44", "version": 5,
             "fetched_at": "2026-09-14T09:23:58+00:00"}

    class _Cat:
        def get_dataset(self, sym, tf):
            return entry if sym == "ETH-USD" else None

    monkeypatch.setattr("project_titan_x.core.catalog.get_catalog", lambda: _Cat())
    assert ex.data_version("ETH-USD", "1d")["checksum"] == "daac44"
    assert ex.data_version("ETHUSD", "1d")["checksum"] == "daac44"


def test_data_version_for_an_uncatalogued_dataset_is_empty(monkeypatch):
    class _Cat:
        def get_dataset(self, sym, tf):
            return None

    monkeypatch.setattr("project_titan_x.core.catalog.get_catalog", lambda: _Cat())
    assert ex.data_version("NOSUCH", "1d") == {}


# --------------------------------------------------------------------------
# Deployment auditing — PHASE 26's "audit logging" where it matters
#
# A stage0 tag is the single thing standing between a search result and real
# money. Flipping one used to leave no record at all, so "when did this go
# live, and on what evidence" — the question worth asking after a loss — had
# no answer anywhere.
# --------------------------------------------------------------------------

def test_going_live_is_recorded_with_its_evidence(log):
    rec = ex.record_deployment_change(
        symbol="BTC-USD", timeframe="1d", strategy="dual_thrust",
        previous_status="UNVALIDATED", new_status="VALIDATED",
        reason="null percentile 98.0 vs bar 95.0",
        evidence={"null_percentile": 98.0, "trades": 80}, log_path=log)
    assert rec is not None
    assert rec.kind == "deployment"
    assert "PROMOTED TO LIVE" in rec.conclusion
    assert rec.metrics["null_percentile"] == 98.0
    assert any("drives real signals" in n for n in rec.notes)


def test_withdrawal_from_live_is_recorded_too(log):
    """Non-negotiable 9: a strategy being pulled is a negative result, and
    negative results are kept."""
    rec = ex.record_deployment_change(
        symbol="BTC-USD", timeframe="1d", strategy="dual_thrust",
        previous_status="VALIDATED", new_status="UNVALIDATED",
        reason="re-calibrated null moved the percentile below the bar", log_path=log)
    assert "WITHDRAWN FROM LIVE" in rec.conclusion
    assert any("no longer drives signals" in n for n in rec.notes)


def test_an_unchanged_status_is_not_logged(log):
    """The tagger is idempotent and re-run often; padding the log with no-ops
    would bury the changes that matter."""
    assert ex.record_deployment_change(
        symbol="X", timeframe="1d", strategy="s",
        previous_status="VALIDATED", new_status="VALIDATED",
        reason="re-ran tagger", log_path=log) is None
    assert ex.load(log) == []


def test_first_ever_tagging_is_recorded_as_a_change(log):
    rec = ex.record_deployment_change(
        symbol="X", timeframe="1d", strategy="s",
        previous_status=None, new_status="UNVALIDATED",
        reason="first tagging run", log_path=log)
    assert rec is not None
    assert "untagged -> UNVALIDATED" in rec.title


def test_deployment_history_is_filterable_and_ordered(log):
    for prev, new in (("UNVALIDATED", "VALIDATED"), ("VALIDATED", "UNVALIDATED")):
        ex.record_deployment_change(
            symbol="BTC-USD", timeframe="1d", strategy="dual_thrust",
            previous_status=prev, new_status=new, reason="r", log_path=log)
    ex.record_deployment_change(
        symbol="ETH-USD", timeframe="1d", strategy="mss_trend_hold",
        previous_status=None, new_status="VALIDATED", reason="r", log_path=log)

    assert len(ex.deployment_history(log_path=log)) == 3
    btc = ex.deployment_history("BTC-USD", log_path=log)
    assert len(btc) == 2
    assert "PROMOTED" in btc[0].conclusion and "WITHDRAWN" in btc[1].conclusion


def test_an_audit_failure_never_blocks_the_deployment_change(tmp_path, monkeypatch):
    """A missing audit line is bad; a tagging run dying halfway, leaving some
    overrides tagged and others not, is worse."""
    def _boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(ex, "record", _boom)
    assert ex.record_deployment_change(
        symbol="X", timeframe="1d", strategy="s", previous_status=None,
        new_status="VALIDATED", reason="r", log_path=tmp_path / "x.jsonl") is None
