"""
Module: test_instrument_profile.py
Description: Tests for engines/e24_strategy_research/instrument_profile.py
    (reports/statergy.txt PHASE 3).

    The two most important tests here pin real defects found on this module's
    own first full 116-profile run, because both produced output that LOOKED
    like a finding and was not:

    1. E12's `mean_reverting` flag is True for any positive theta, and came
       back True on 101 of 116 profiles with half-lives up to 33,138 bars. It
       was scoring mean_reversion above trend_following on 61 profiles whose
       Hurst simultaneously read "trending".
    2. When no family cleared its test every family tied at the 0.2 baseline,
       so sort order silently promoted an arbitrary one to "top family".

    Both are the same failure mode -- presenting an artefact as a
    recommendation -- which statergy.txt forbids explicitly ("Never present an
    assumption as a proven edge").
Author: Shantanu Waykar
Version: 1.0.0
"""

import numpy as np
import pandas as pd
import pytest

from project_titan_x.engines.e24_strategy_research.instrument_profile import (
    COST_HURDLE_PROHIBITIVE,
    MAX_TRADEABLE_HALF_LIFE_BARS,
    InstrumentProfile,
    _rank_families,
    build_profile,
)


def _frame(n=600, seed=0, drift=0.0, vol=0.01, price=100.0):
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, vol, n)
    close = price * np.exp(np.cumsum(rets))
    high = close * (1 + np.abs(rng.normal(0, vol / 2, n)))
    low = close * (1 - np.abs(rng.normal(0, vol / 2, n)))
    return pd.DataFrame({
        "open": np.r_[close[0], close[:-1]], "high": high, "low": low,
        "close": close, "volume": rng.integers(1000, 5000, n),
    })


# --------------------------------------------------------------------------
# Cost hurdle -- the headline number
# --------------------------------------------------------------------------

def test_cost_ratio_is_round_trip_over_median_bar_range():
    """0.1% commission + 0.05% slippage, charged both sides = 0.30% round trip."""
    df = _frame(vol=0.01)
    p = build_profile(df, "TEST", "1d")
    assert p.cost_per_round_trip_pct == pytest.approx(0.30, abs=1e-6)
    # cost_atr_ratio is stored rounded to 3 decimals, so compare at that
    # precision rather than against the unrounded quotient.
    assert p.cost_atr_ratio == pytest.approx(0.30 / p.median_bar_range_pct, abs=5e-4)


def test_tiny_bar_range_is_flagged_prohibitive():
    """An instrument whose typical bar is smaller than a round trip cannot pay
    for a trade -- this must be stated, not left for a strategy to discover."""
    df = _frame(vol=0.0002)          # ~0.02% bars vs 0.30% costs
    p = build_profile(df, "TEST", "15m")
    assert p.cost_atr_ratio > COST_HURDLE_PROHIBITIVE
    assert p.cost_verdict == "prohibitive"
    assert any("cannot pay" in n for n in p.notes)


def test_wide_bar_range_is_workable():
    df = _frame(vol=0.03)
    p = build_profile(df, "TEST", "1d")
    assert p.cost_verdict == "workable"


def test_prohibitive_cost_discounts_every_family_prior():
    """Cost overrides character: a good Hurst reading must not outrank the
    arithmetic that the bar cannot cover the spread."""
    cheap = InstrumentProfile(symbol="X", timeframe="1d", bars=500, generated_at="",
                              hurst=0.70, cost_verdict="workable")
    dear = InstrumentProfile(symbol="X", timeframe="15m", bars=500, generated_at="",
                             hurst=0.70, cost_verdict="prohibitive")
    best_cheap = _rank_families(cheap)[0]["prior_score"]
    best_dear = _rank_families(dear)[0]["prior_score"]
    assert best_dear < best_cheap


# --------------------------------------------------------------------------
# Real defect #1 -- slow OU reversion must not count as tradeable
# --------------------------------------------------------------------------

def test_slow_mean_reversion_does_not_score_as_reverting():
    """101 of 116 real profiles carried mean_reverting=True with half-lives up
    to 33,138 bars. A 900-bar half-life is not a harvestable edge and must not
    outrank measured trend persistence."""
    p = InstrumentProfile(symbol="X", timeframe="4h", bars=2000, generated_at="",
                          hurst=0.58, mean_reverting=True, half_life_periods=900.0,
                          cost_verdict="workable")
    ranked = {e["family"]: e for e in _rank_families(p)}
    assert ranked["mean_reversion"]["prior_score"] == pytest.approx(0.2)
    assert "too slow to harvest" in ranked["mean_reversion"]["rationale"]
    # trend persistence was measured, so it must win
    assert ranked["trend_following"]["prior_score"] > ranked["mean_reversion"]["prior_score"]


def test_fast_mean_reversion_does_score_as_reverting():
    p = InstrumentProfile(symbol="X", timeframe="1h", bars=2000, generated_at="",
                          hurst=0.50, mean_reverting=True,
                          half_life_periods=MAX_TRADEABLE_HALF_LIFE_BARS / 2,
                          cost_verdict="workable")
    ranked = {e["family"]: e for e in _rank_families(p)}
    assert ranked["mean_reversion"]["prior_score"] > 0.5


def test_half_life_exactly_at_ceiling_is_still_tradeable():
    p = InstrumentProfile(symbol="X", timeframe="1h", bars=2000, generated_at="",
                          hurst=0.50, mean_reverting=True,
                          half_life_periods=MAX_TRADEABLE_HALF_LIFE_BARS,
                          cost_verdict="workable")
    ranked = {e["family"]: e for e in _rank_families(p)}
    assert ranked["mean_reversion"]["prior_score"] > 0.5


# --------------------------------------------------------------------------
# Real defect #2 -- a tie must not be reported as a recommendation
# --------------------------------------------------------------------------

def test_no_character_yields_none_indicated_not_an_arbitrary_family():
    """With Hurst at a random walk and no fast reversion, every family ties at
    the baseline and sort order was silently picking a 'winner'."""
    p = InstrumentProfile(symbol="X", timeframe="1h", bars=2000, generated_at="",
                          hurst=0.50, mean_reverting=False, cost_verdict="workable")
    ranked = _rank_families(p)
    assert ranked[0]["family"] == "none_indicated"
    assert ranked[0]["prior_score"] == 0.0
    assert "random walk" in ranked[0]["rationale"]


def test_clear_trend_is_not_reported_as_none_indicated():
    p = InstrumentProfile(symbol="X", timeframe="1d", bars=2000, generated_at="",
                          hurst=0.72, mean_reverting=False, cost_verdict="workable")
    assert _rank_families(p)[0]["family"] != "none_indicated"


# --------------------------------------------------------------------------
# Honesty / degradation
# --------------------------------------------------------------------------

def test_too_few_bars_reports_a_note_rather_than_a_confident_profile():
    p = build_profile(_frame(n=40), "TEST", "1d")
    assert p.hurst is None
    assert any("too few" in n for n in p.notes)


def test_priors_are_labelled_as_hypotheses_with_rationale():
    """Every prior must carry the measurement behind it -- a bare score reads
    as a verdict."""
    p = build_profile(_frame(vol=0.02), "TEST", "1d")
    for entry in p.suitable_families:
        assert "family" in entry and "prior_score" in entry and entry["rationale"]


def test_uses_enriched_atr_when_present():
    """Must prefer E07's own atr column over re-deriving from high/low, so the
    profile agrees with the rest of the platform."""
    df = _frame(vol=0.02)
    df["atr"] = df["close"] * 0.05           # deliberately unlike high-low
    p = build_profile(df, "TEST", "1d")
    assert p.median_bar_range_pct == pytest.approx(5.0, abs=0.3)
