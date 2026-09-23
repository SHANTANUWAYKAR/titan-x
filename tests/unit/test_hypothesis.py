"""
Module: test_hypothesis.py
Description: Tests for engines/e24_strategy_research/hypothesis.py — P1.2 in
    docs/INSTITUTIONAL_AUDIT.md (`reports/upgrade statergy.txt` PHASES 7, 36, 37).

    The load-bearing test is `test_a_hypothesis_without_a_failure_condition_is_refused`.
    A strategy with no stated failure condition cannot be retired for cause, so
    the only available trigger is a drawdown — which fires long after the reason
    did. Everything else here is bookkeeping around that one requirement.

    The second theme is that a hypothesis must never be mistaken for evidence:
    nothing in this module may promote a strategy or touch a Stage 0 tag.
Author: Shantanu Waykar
Version: 1.0.0
"""

import pytest

from project_titan_x.engines.e24_strategy_research import hypothesis as hyp
from project_titan_x.engines.e24_strategy_research.hypothesis import (
    HypothesisError,
    StrategyHypothesis,
)


@pytest.fixture
def path(tmp_path):
    return tmp_path / "hypotheses.json"


def _h(**over):
    kw = dict(
        strategy="demo", family="breakout",
        works_because="range breaks follow compression",
        works_when="expansion regimes on cost-viable timeframes",
        fails_when="choppy ranges that cross the threshold without follow-through",
        expected_edge="asymmetric payoff, not hit rate",
    )
    kw.update(over)
    return StrategyHypothesis(**kw)


# --------------------------------------------------------------------------
# The required fields
# --------------------------------------------------------------------------

def test_a_hypothesis_without_a_failure_condition_is_refused(path):
    """PHASE 36 cannot retire a strategy for a broken hypothesis if the
    hypothesis never said what breaking would look like."""
    with pytest.raises(HypothesisError, match="retired for cause"):
        hyp.record(_h(fails_when=""), path)


@pytest.mark.parametrize("missing", ["works_because", "works_when", "expected_edge", "family"])
def test_every_phase7_field_is_required(path, missing):
    with pytest.raises(HypothesisError):
        hyp.record(_h(**{missing: ""}), path)


def test_whitespace_is_not_a_failure_condition(path):
    with pytest.raises(HypothesisError, match="fails_when"):
        hyp.record(_h(fails_when="   "), path)


def test_an_unknown_family_is_refused(path):
    """Free-form families would make the registry unqueryable, which is the
    complaint being fixed."""
    with pytest.raises(HypothesisError, match="unknown family"):
        hyp.record(_h(family="vibes"), path)


def test_a_complete_hypothesis_round_trips(path):
    hyp.record(_h(strategy="dual_thrust"), path)
    got = hyp.get("dual_thrust", path)
    assert got.family == "breakout"
    assert "follow-through" in got.fails_when
    assert got.recorded_at            # stamped on write


# --------------------------------------------------------------------------
# Revision is allowed here, unlike the experiment log
# --------------------------------------------------------------------------

def test_a_hypothesis_may_be_revised(path):
    """A hypothesis is a current claim about the world. Revising it when the
    world turns out differently is correct; the EVIDENCE is what must be
    immutable, and that lives in the append-only experiment log."""
    hyp.record(_h(strategy="s", works_because="first theory"), path)
    hyp.record(_h(strategy="s", works_because="revised theory"), path)
    assert hyp.get("s", path).works_because == "revised theory"
    assert len(hyp.load(path)) == 1


def test_recording_one_strategy_does_not_disturb_another(path):
    hyp.record(_h(strategy="a"), path)
    hyp.record(_h(strategy="b"), path)
    assert set(hyp.load(path)) == {"a", "b"}


def test_a_corrupt_registry_reads_as_empty_rather_than_crashing(path):
    path.write_text("{not json", encoding="utf-8")
    assert hyp.load(path) == {}


# --------------------------------------------------------------------------
# Coverage -- the live number is the one that matters
# --------------------------------------------------------------------------

def test_coverage_separates_live_strategies_from_the_search_grid(path):
    """A strategy driving real money with no stated failure condition is a
    different problem from one sitting unused in a 228-entry grid."""
    hyp.record(_h(strategy="live_one"), path)
    rep = hyp.coverage_report(
        known_strategies=["live_one", "grid_a", "grid_b", "grid_c"],
        live_strategies=["live_one"], path=path)
    assert rep["known"] == 4 and rep["with_hypothesis"] == 1
    assert rep["coverage_pct"] == 25.0
    assert rep["live"] == 1 and rep["live_with_hypothesis"] == 1
    assert rep["live_missing"] == []
    assert "every live strategy" in rep["verdict"]


def test_an_uncovered_live_strategy_is_called_out(path):
    rep = hyp.coverage_report(["a", "b"], live_strategies=["a"], path=path)
    assert rep["live_missing"] == ["a"]
    assert "LIVE strategy" in rep["verdict"]


def test_coverage_with_no_live_strategies_says_so(path):
    rep = hyp.coverage_report(["a"], live_strategies=[], path=path)
    assert rep["verdict"] == "no live strategies to check"


def test_missing_list_is_the_gap_not_a_hidden_number(path):
    hyp.record(_h(strategy="a"), path)
    rep = hyp.coverage_report(["a", "b", "c"], path=path)
    assert rep["missing"] == ["b", "c"]


# --------------------------------------------------------------------------
# The seeds are transcriptions, not inventions
# --------------------------------------------------------------------------

def test_seeds_cover_exactly_the_two_live_strategies(path):
    written = hyp.seed(path)
    assert {h.strategy for h in written} == {"dual_thrust", "mss_trend_hold"}


def test_every_seed_cites_where_its_claim_came_from(path):
    """A hypothesis justified by its own backtest is circular. Each seed must
    point at the code or docstring it was transcribed from."""
    for h in hyp.SEED_HYPOTHESES:
        assert h.source and (".py" in h.source)
        assert h.missing_fields() == []


def test_seeds_are_writable_and_readable_back(path):
    hyp.seed(path)
    dt = hyp.get("dual_thrust", path)
    assert dt.family == "breakout"
    assert "33.3%" in dt.expected_edge        # breakeven, not the 50% baseline
    mss = hyp.get("mss_trend_hold", path)
    assert mss.family == "trend_following"
    assert "Ranging markets" in mss.fails_when
