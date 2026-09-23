"""
Module: test_improvement_loop.py
Description: Tests for engines/e24_strategy_research/improvement_loop.py —
    PHASE 23 of `reports/upgrade statergy.txt`.

    Three properties carry the weight, and all three are about the loop not
    fooling itself:

    1. An in-sample gain bought with an out-of-sample loss must be REJECTED.
       The spec says so explicitly, and it is the single most common way a
       self-tuning trading agent talks itself into overfitting.
    2. Exactly one variable changes per variant. A two-parameter jump cannot
       attribute its result to anything.
    3. The trial count is part of the result, not a log line. Best-of-N climbs
       on noise alone; a winner after 30 trials is a far weaker claim than one
       after 3, and this project has already measured noise clearing its own
       bar 137 times in 150.

    Plus the safety property: nothing in this module may deploy anything.
Author: Shantanu Waykar
Version: 1.0.0
"""

import pytest

from project_titan_x.engines.e24_strategy_research import improvement_loop as il


BASE = {"lookback": 10, "k1": 0.5, "k2": 0.5}


def _grid(*param_dicts):
    return {"dual_thrust": list(param_dicts)}


def _metrics(is_s, oos_s, trades=88):
    return {"is_sharpe": is_s, "oos_sharpe": oos_s, "is_trades": trades}


# --------------------------------------------------------------------------
# Diagnose before optimizing
# --------------------------------------------------------------------------

def test_a_strategy_below_the_bar_is_diagnosed_as_such():
    d = il.diagnose("dual_thrust", "BTC-USD", "1d", _metrics(0.894, 0.589), bar=0.59)
    assert d.selection_score == pytest.approx(0.589)
    assert d.margin == pytest.approx(-0.001, abs=1e-3)
    assert "below the Stage 0 bar" in d.primary_failure


def test_sitting_on_the_bar_is_reported_as_indistinguishable_not_as_a_pass():
    """A margin inside the split noise is not a pass."""
    d = il.diagnose("s", "X", "1d", _metrics(1.0, 0.60), bar=0.59)
    assert d.selection_score > d.bar
    assert "indistinguishable from the Stage 0 bar" in d.primary_failure


def test_severe_oos_decay_is_named():
    d = il.diagnose("s", "X", "1d", _metrics(2.0, 0.4), bar=0.59)
    assert any("decay" in f for f in d.failures)


def test_a_thin_sample_outranks_every_other_complaint():
    """With 12 trades nothing else computed from them means anything."""
    d = il.diagnose("s", "X", "1d", _metrics(3.0, 2.9, trades=12), bar=0.59)
    assert "sample too thin" in d.primary_failure


def test_a_healthy_strategy_has_no_failure():
    d = il.diagnose("s", "X", "1d", _metrics(1.44, 1.05, trades=71), bar=0.59)
    assert d.failures == []
    assert d.primary_failure == "no failure identified"


# --------------------------------------------------------------------------
# One variable at a time
# --------------------------------------------------------------------------

def test_only_single_parameter_neighbours_are_proposed():
    grid = _grid(
        {"lookback": 10, "k1": 0.5, "k2": 0.5},   # the incumbent itself
        {"lookback": 8, "k1": 0.5, "k2": 0.5},    # one change  -> proposed
        {"lookback": 8, "k1": 0.7, "k2": 0.5},    # two changes -> refused
        {"lookback": 10, "k1": 0.7, "k2": 0.5},   # one change  -> proposed
    )
    d = il.diagnose("dual_thrust", "X", "1d", _metrics(0.9, 0.6), bar=0.59)
    out = il.propose_variants(BASE, grid, d)
    assert {v.changed_key for v in out} == {"lookback", "k1"}
    assert len(out) == 2
    for v in out:
        differing = [k for k in set(BASE) | set(v.params) if BASE.get(k) != v.params.get(k)]
        assert len(differing) == 1


def test_every_variant_states_what_it_is_trying_to_fix():
    """'Never optimize blindly' — a proposal with no target is a random walk."""
    grid = _grid({"lookback": 8, "k1": 0.5, "k2": 0.5})
    d = il.diagnose("dual_thrust", "X", "1d", _metrics(0.9, 0.6), bar=0.59)
    v = il.propose_variants(BASE, grid, d)[0]
    assert "lookback" in v.hypothesis
    assert d.primary_failure in v.hypothesis


def test_duplicate_parameter_values_are_not_proposed_twice():
    grid = _grid({"lookback": 8, "k1": 0.5, "k2": 0.5},
                 {"lookback": 8, "k1": 0.5, "k2": 0.5})
    d = il.diagnose("dual_thrust", "X", "1d", _metrics(0.9, 0.6), bar=0.59)
    assert len(il.propose_variants(BASE, grid, d)) == 1


def test_an_unknown_strategy_yields_no_variants_rather_than_inventing_any():
    """Inventing parameter values would widen the search beyond what the null
    campaigns were calibrated against."""
    d = il.diagnose("not_in_grid", "X", "1d", _metrics(0.9, 0.6), bar=0.59)
    assert il.propose_variants(BASE, _grid({"lookback": 8}), d) == []


# --------------------------------------------------------------------------
# Acceptance is out-of-sample first
# --------------------------------------------------------------------------

def _variant(key="lookback", to=8):
    return il.Variant(params={**BASE, key: to}, changed_key=key,
                      from_value=BASE.get(key), to_value=to, hypothesis="h")


def test_an_in_sample_gain_costing_out_of_sample_is_rejected():
    """The spec's explicit rule, and the main way self-tuning agents overfit."""
    results, _ = il.evaluate(
        [_variant()],
        run_candidate=lambda p: _metrics(5.0, 0.30),   # IS soars, OOS falls
        incumbent_selection=0.589, incumbent_oos=0.589)
    assert results[0].accepted is False
    assert "out-of-sample Sharpe fell" in results[0].reason


def test_an_improvement_inside_the_noise_is_rejected():
    results, _ = il.evaluate(
        [_variant()],
        run_candidate=lambda p: _metrics(0.90, 0.60),   # +0.011 selection
        incumbent_selection=0.589, incumbent_oos=0.589, min_improvement=0.05)
    assert results[0].accepted is False
    assert "Inside the noise" in results[0].reason


def test_a_genuine_out_of_sample_improvement_is_accepted():
    results, _ = il.evaluate(
        [_variant()],
        run_candidate=lambda p: _metrics(1.40, 0.95),
        incumbent_selection=0.589, incumbent_oos=0.589)
    assert results[0].accepted is True
    assert results[0].selection_score == pytest.approx(0.95)


def test_a_candidate_that_does_not_run_is_recorded_not_skipped():
    results, trials = il.evaluate([_variant()], run_candidate=lambda p: None,
                                  incumbent_selection=0.5, incumbent_oos=0.5)
    assert trials == 1
    assert results[0].accepted is False
    assert "did not run" in results[0].reason


# --------------------------------------------------------------------------
# The trial count is part of the result
# --------------------------------------------------------------------------

def test_the_trial_ceiling_is_enforced():
    variants = [_variant(to=i) for i in range(50)]
    _, trials = il.evaluate(variants, run_candidate=lambda p: _metrics(0.5, 0.4),
                            incumbent_selection=0.589, incumbent_oos=0.589,
                            max_trials=7)
    assert trials == 7


def test_a_truncated_search_says_so():
    d = il.diagnose("s", "X", "1d", _metrics(0.9, 0.6), bar=0.59)
    s = il.summarise_run(d, [], trials=40, max_trials=40)
    assert any("ceiling was reached" in c for c in s["caveats"])


def test_a_winner_after_many_trials_carries_the_multiple_comparison_warning():
    """The Stage 0 percentile is not valid for a variant found by searching."""
    d = il.diagnose("s", "X", "1d", _metrics(0.9, 0.6), bar=0.59)
    good = il.TrialResult(_variant(), 1.2, 1.5, 1.2, 80, True, "better")
    s = il.summarise_run(d, [good], trials=30)
    assert any("NOT valid" in c for c in s["caveats"])


def test_the_trial_count_is_always_in_the_summary():
    d = il.diagnose("s", "X", "1d", _metrics(0.9, 0.6), bar=0.59)
    s = il.summarise_run(d, [], trials=5)
    assert s["trials_consumed"] == 5
    assert any("5 variant(s) were tried" in c for c in s["caveats"])


# --------------------------------------------------------------------------
# Failed attempts are kept, and nothing deploys
# --------------------------------------------------------------------------

def test_rejections_are_retained_in_the_summary():
    """Non-negotiables 8 and 9: they are the evidence the winner was not just
    the luckiest draw."""
    d = il.diagnose("s", "X", "1d", _metrics(0.9, 0.6), bar=0.59)
    bad = il.TrialResult(_variant(), 0.3, 0.9, 0.3, 80, False, "REJECTED: worse")
    s = il.summarise_run(d, [bad], trials=1)
    assert s["n_rejected"] == 1
    assert s["rejections"][0]["reason"].startswith("REJECTED")


def test_no_proposal_is_a_real_result_not_an_error():
    d = il.diagnose("s", "X", "1d", _metrics(0.9, 0.6), bar=0.59)
    s = il.summarise_run(d, [], trials=3)
    assert s["proposal"] is None
    assert s["n_accepted"] == 0


def test_the_loop_never_marks_anything_deployed():
    d = il.diagnose("s", "X", "1d", _metrics(0.9, 0.6), bar=0.59)
    good = il.TrialResult(_variant(), 1.2, 1.5, 1.2, 80, True, "better")
    s = il.summarise_run(d, [good], trials=2)
    assert s["deployed"] is False
    assert any("cannot write one" in c for c in s["caveats"])


def test_a_run_is_recorded_with_its_rejections(tmp_path):
    from project_titan_x.core import experiment as ex
    log = tmp_path / "experiments.jsonl"
    d = il.diagnose("s", "X", "1d", _metrics(0.9, 0.6), bar=0.59)
    bad = il.TrialResult(_variant(), 0.3, 0.9, 0.3, 80, False, "REJECTED: worse")
    s = il.summarise_run(d, [bad], trials=4)
    eid = il.record_run(s, log_path=log)
    assert eid
    rec = ex.get(eid, log)
    assert rec.metrics["n_rejected"] == 1
    assert "4 single-variable trials" in rec.conclusion
