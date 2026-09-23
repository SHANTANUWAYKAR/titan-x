"""
Module: test_strategy_score.py
Description: Tests for engines/e24_strategy_research/strategy_score.py
    (reports/statergy.txt PHASES 11 and 19).

    The gate tests matter most. statergy.txt is explicit that "A strategy cannot
    receive A+ merely because it makes large profits", so the majority of these
    pin that a spectacular backtest still fails without validation, sample size,
    and parameter stability behind it.
Author: Shantanu Waykar
Version: 1.0.0
"""

import pytest

from project_titan_x.engines.e24_strategy_research.strategy_score import (
    WEIGHTS,
    parameter_robustness,
    score_candidate,
)


def _cand(**over):
    base = dict(
        strategy="demo", params={"a": 1},
        is_trades=120, is_sharpe=1.5, oos_sharpe=1.4, is_max_dd=-8.0,
        win_rate=0.58, profit_factor=2.1, expectancy=0.9,
    )
    base.update(over)
    return base


def _siblings(scores):
    """Sibling candidates whose min(IS,OOS) equals each given score."""
    return [_cand(is_sharpe=s, oos_sharpe=s) for s in scores]


# --------------------------------------------------------------------------
# Weights
# --------------------------------------------------------------------------

def test_weights_sum_to_one():
    assert sum(WEIGHTS.values()) == pytest.approx(1.0, abs=1e-3)


def test_score_is_not_driven_by_profit_alone():
    """A huge profit factor with a broken OOS must not outscore a modest,
    consistent, validated result -- PHASE 11's central requirement."""
    flashy = score_candidate(
        _cand(profit_factor=99.0, expectancy=50.0, is_sharpe=4.0, oos_sharpe=-0.5, is_max_dd=-24.0),
        "X", "1d", siblings=_siblings([4.0, -1.0, 2.0, -2.0]),
    )
    modest = score_candidate(
        _cand(profit_factor=1.6, expectancy=0.4, is_sharpe=1.1, oos_sharpe=1.05, is_max_dd=-6.0),
        "X", "1d", siblings=_siblings([1.1, 1.05, 1.0, 1.08]),
    )
    assert modest.a_plus_score > flashy.a_plus_score


# --------------------------------------------------------------------------
# Hard gates -- A+ is never earned by score alone
# --------------------------------------------------------------------------

def test_never_scored_against_null_cannot_be_a_plus():
    """The single most important gate: this project measured noise clearing its
    legacy bar 137/150 times at 4h, so an unvalidated backtest is capped."""
    s = score_candidate(_cand(is_sharpe=3.0, oos_sharpe=2.9), "X", "1d",
                        siblings=_siblings([3.0, 2.9, 2.95, 3.05]), null_percentile=None)
    assert s.grade not in ("S", "A+")
    assert any("never scored" in f for f in s.gate_failures)
    assert s.overfitting_risk.startswith("unknown")


def test_null_percentile_below_floor_blocks_a_plus():
    s = score_candidate(_cand(is_sharpe=3.0, oos_sharpe=2.9), "X", "1d",
                        siblings=_siblings([3.0, 2.9, 2.95, 3.05]), null_percentile=64.0)
    assert s.grade not in ("S", "A+")
    assert any("null percentile" in f for f in s.gate_failures)


def test_thin_sample_blocks_a_plus_even_when_validated():
    s = score_candidate(_cand(is_trades=30, is_sharpe=2.0, oos_sharpe=1.9), "X", "1d",
                        siblings=_siblings([2.0, 1.9, 1.95, 2.05]), null_percentile=99.0)
    assert s.grade not in ("S", "A+")
    assert any("trades" in f for f in s.gate_failures)


def test_negative_expectancy_blocks_a_plus():
    """A 65% win rate can carry negative expectancy -- measured on real ETHUSD
    data by this project's own engine. Win rate must never be enough."""
    s = score_candidate(_cand(win_rate=0.65, expectancy=-7.195, is_sharpe=2.0, oos_sharpe=1.9),
                        "X", "1d", siblings=_siblings([2.0, 1.9, 1.95, 2.05]), null_percentile=99.0)
    assert s.grade not in ("S", "A+")
    assert any("expectancy" in f for f in s.gate_failures)


def test_fully_qualified_candidate_reaches_a_plus():
    # dsr is part of "fully qualified" since the deflated-Sharpe gate was
    # added: a backtest that cannot be separated from the best of its own
    # search is not A+ however good its other numbers look.
    s = score_candidate(_cand(is_trades=120, is_sharpe=1.6, oos_sharpe=1.5, is_max_dd=-5.0),
                        "X", "1d", siblings=_siblings([1.6, 1.5, 1.55, 1.58]),
                        null_percentile=99.0, dsr=0.99)
    assert s.grade in ("S", "A+")
    assert s.gate_failures == []
    assert s.status == "A+"


def test_missing_deflated_sharpe_blocks_a_plus():
    """A dsr that could not be computed is an evidence GAP, not a pass.

    Same convention the null-percentile gate already uses: absent evidence
    fails rather than waving the candidate through.
    """
    s = score_candidate(_cand(is_trades=120, is_sharpe=1.6, oos_sharpe=1.5, is_max_dd=-5.0),
                        "X", "1d", siblings=_siblings([1.6, 1.5, 1.55, 1.58]),
                        null_percentile=99.0, dsr=None)
    assert s.grade not in ("S", "A+")
    assert any("deflated Sharpe not computable" in f for f in s.gate_failures)


def test_deflated_sharpe_below_bar_blocks_a_plus():
    """An observed Sharpe indistinguishable from the best of its own search.

    This is BTCUSD 1d dual_thrust's real situation: OOS Sharpe 0.59 against a
    noise floor of ~1.01 at this project's grid size, giving dsr 0.09.
    """
    s = score_candidate(_cand(is_trades=120, is_sharpe=1.6, oos_sharpe=1.5, is_max_dd=-5.0),
                        "X", "1d", siblings=_siblings([1.6, 1.5, 1.55, 1.58]),
                        null_percentile=99.0, dsr=0.09)
    assert s.grade not in ("S", "A+")
    assert any("not separable from the best of its own search" in f for f in s.gate_failures)


# --------------------------------------------------------------------------
# Parameter robustness -- the real PHASE 8 measurement
# --------------------------------------------------------------------------

def test_parameter_plateau_scores_more_robust_than_a_spike():
    plateau = parameter_robustness(_cand(is_sharpe=1.0, oos_sharpe=1.0), _siblings([1.0, 0.98, 1.02, 0.99]))
    spike = parameter_robustness(_cand(is_sharpe=1.0, oos_sharpe=1.0), _siblings([1.0, -0.5, 2.5, -1.0]))
    assert plateau > spike
    assert plateau > 0.8 and spike < 0.5


def test_too_few_siblings_returns_none_not_a_flattering_default():
    assert parameter_robustness(_cand(), _siblings([1.0, 1.1])) is None


def test_unmeasurable_robustness_scores_neutral_and_says_so():
    s = score_candidate(_cand(), "X", "1d", siblings=_siblings([1.0]))
    assert s.param_robustness is None
    assert s.components["robustness"] == pytest.approx(0.5)
    assert any("not measurable" in n for n in s.notes)


# --------------------------------------------------------------------------
# Cost hurdle feeds through from the instrument profile
# --------------------------------------------------------------------------

def test_prohibitive_cost_discounts_execution_realism():
    sibs = _siblings([1.5, 1.4, 1.45, 1.48])
    ok = score_candidate(_cand(), "X", "1d", siblings=sibs, cost_verdict="workable")
    bad = score_candidate(_cand(), "X", "15m", siblings=sibs, cost_verdict="prohibitive")
    assert bad.components["execution_realism"] < ok.components["execution_realism"]
    assert bad.a_plus_score < ok.a_plus_score
    assert any("prohibitive" in n for n in bad.notes)


# --------------------------------------------------------------------------
# Honesty of reporting
# --------------------------------------------------------------------------

def test_regime_omission_is_disclosed_on_every_row():
    """PHASE 11 suggests scoring regime diversification; it is not measurable
    here, and the omission must travel with the row rather than be buried."""
    s = score_candidate(_cand(), "X", "1d", siblings=_siblings([1.0, 1.1, 1.2]))
    assert any("regime" in n for n in s.notes)


def test_unknown_overfitting_risk_is_distinct_from_low():
    unknown = score_candidate(_cand(), "X", "1d", siblings=_siblings([1.0, 1.1, 1.2]))
    known = score_candidate(_cand(), "X", "1d", siblings=_siblings([1.0, 1.1, 1.2]), null_percentile=99.0)
    assert unknown.overfitting_risk.startswith("unknown")
    assert known.overfitting_risk == "low"
