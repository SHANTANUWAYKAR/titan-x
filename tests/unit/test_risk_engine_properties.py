"""
Module: test_risk_engine_properties.py
Description: Property-based tests (hypothesis) on E45 Risk Management (CRO)
    -- REPO_REFERENCE.md Tier 4, applied to this codebase's own highest-
    stakes veto authority per CLAUDE.md's Rule 5 and financial-safety
    discipline. Research cited in REPO_REFERENCE.md motivates this: property
    tests catch a materially wider range of mutations than example-based
    unit tests, because each run explores hundreds of generated inputs
    instead of a handful of hand-picked ones.

    REAL BUG FOUND BY WRITING THIS FILE, FIXED IN engines/e45_risk/engine.py
    (Rule 1b): `proposal.direction` was read only for logging and the
    knowledge-context query, never checked against stop_loss/take_profit --
    a LONG proposal with stop_loss ABOVE entry and take_profit BELOW entry
    (a fully inverted trade) was silently APPROVED with a "clean" 2.00 R:R
    message, verified live before any fix was written. Rule 2's R:R check
    uses abs(), which is direction-blind by construction, and Rule 10's
    stop-loss check only rejected stop_loss<=0 or stop_loss==entry_price,
    never checking which SIDE of entry it sat on.

    test_direction_correct_trades_are_never_vetoed_for_geometry and
    test_inverted_direction_trades_are_always_vetoed below are the
    permanent regression coverage for that fix -- generated over hundreds
    of realistic price/confidence combinations, not the single hand-picked
    repro used to first confirm the bug.
Author: Shantanu Waykar
Version: 1.0.0
"""

from hypothesis import given, settings
from hypothesis import strategies as st

# deadline=None on every property test below (scoped to this file only, via
# each @settings(...) call, not a global profile): each example constructs a
# fresh RiskManagementEngine (real file I/O via _load_min_confidence_override)
# and none of these tests assert anything about timing. Hypothesis's default
# 200ms per-example deadline flagged test_direction_correct_trades_are_never_
# vetoed_for_geometry as failing twice (2026-09-11/12), both times ONLY
# inside the ~9-10 minute, 1132-test full suite run -- never in 30+ isolated
# reruns (6,000+ examples) or an earlier targeted 5,000-example/6-seed search
# (also zero reproductions). The code path itself (Rule 1b geometry check) is
# pure arithmetic on proposal fields with no shared mutable state (verified:
# _funded_daily_pnl_history is instance-level, TradeRiskProposal has no
# mutable defaults) -- ruling out a real correctness bug. A GC pause or OS
# scheduling hiccup under full-suite load pushing one example past 200ms
# wall-clock, misreported as a test failure, fits every observed fact. The
# deadline exists to catch runaway test logic (e.g. an accidental network
# call), not to fail correct, fast code on scheduling noise.

from project_titan_x.engines.e45_risk import (
    RiskManagementEngine, RiskVerdict, TradeRiskProposal,
)

# Confidence fixed high and risk_percent fixed small so only the property
# under test (stop/target geometry, or the R:R float boundary) can trigger a
# veto -- isolates the invariant from every OTHER real, independent rule
# (confidence floor, portfolio heat, daily loss, etc.) this engine also
# enforces, which is not what these tests are checking.
HIGH_CONFIDENCE = 95
SMALL_RISK_PCT = 0.5

prices = st.floats(min_value=10.0, max_value=100_000.0, allow_nan=False, allow_infinity=False)
gaps = st.floats(min_value=0.01, max_value=5000.0, allow_nan=False, allow_infinity=False)


@given(entry=prices, stop_gap=gaps, target_gap=gaps)
@settings(max_examples=200, deadline=None)
def test_direction_correct_trades_are_never_vetoed_for_geometry(entry, stop_gap, target_gap):
    """A LONG with stop below entry and target above (or the SHORT mirror)
    must never be vetoed FOR GEOMETRY -- regardless of the exact real-valued
    gaps, since the sides are correct by construction here."""
    engine = RiskManagementEngine()
    engine.initialize()

    long_proposal = TradeRiskProposal(
        asset="TEST", direction="LONG", entry_price=entry,
        stop_loss=entry - stop_gap, take_profit=entry + target_gap,
        risk_percent=SMALL_RISK_PCT, confidence_score=HIGH_CONFIDENCE,
    )
    result = engine.evaluate_trade(long_proposal)
    assert "wrong side" not in "".join(result.data.messages)

    short_proposal = TradeRiskProposal(
        asset="TEST", direction="SHORT", entry_price=entry,
        stop_loss=entry + stop_gap, take_profit=entry - target_gap,
        risk_percent=SMALL_RISK_PCT, confidence_score=HIGH_CONFIDENCE,
    )
    result = engine.evaluate_trade(short_proposal)
    assert "wrong side" not in "".join(result.data.messages)


@given(entry=prices, stop_gap=gaps, target_gap=gaps)
@settings(max_examples=200, deadline=None)
def test_inverted_direction_trades_are_always_vetoed(entry, stop_gap, target_gap):
    """A LONG with stop ABOVE entry or target BELOW entry (or the SHORT
    mirror) must always be vetoed -- the exact real bug this file's own
    docstring documents finding and fixing."""
    engine = RiskManagementEngine()
    engine.initialize()

    inverted_long = TradeRiskProposal(
        asset="TEST", direction="LONG", entry_price=entry,
        stop_loss=entry + stop_gap, take_profit=entry - target_gap,
        risk_percent=SMALL_RISK_PCT, confidence_score=HIGH_CONFIDENCE,
    )
    result = engine.evaluate_trade(inverted_long)
    assert result.data.verdict == RiskVerdict.VETO
    assert not result.data.approved

    inverted_short = TradeRiskProposal(
        asset="TEST", direction="SHORT", entry_price=entry,
        stop_loss=entry - stop_gap, take_profit=entry + target_gap,
        risk_percent=SMALL_RISK_PCT, confidence_score=HIGH_CONFIDENCE,
    )
    result = engine.evaluate_trade(inverted_short)
    assert result.data.verdict == RiskVerdict.VETO
    assert not result.data.approved


@given(confidence=st.integers(min_value=0, max_value=100))
@settings(max_examples=50, deadline=None)
def test_confidence_score_never_crashes_the_engine(confidence):
    """The full valid confidence range (0-100) must always produce a real
    verdict, never raise -- a basic robustness property for the field
    e51_signals feeds this engine on every live signal."""
    engine = RiskManagementEngine()
    engine.initialize()
    proposal = TradeRiskProposal(
        asset="TEST", direction="LONG", entry_price=100.0,
        stop_loss=95.0, take_profit=112.0,
        risk_percent=SMALL_RISK_PCT, confidence_score=confidence,
    )
    result = engine.evaluate_trade(proposal)
    assert result.success
    assert result.data.verdict in (RiskVerdict.APPROVED, RiskVerdict.WARNING, RiskVerdict.VETO)


@given(stop_distance=st.floats(min_value=0.5, max_value=500.0, allow_nan=False))
@settings(max_examples=200, deadline=None)
def test_exact_2to1_construction_never_trips_the_float_epsilon_veto(stop_distance):
    """Regression coverage for the CLAUDE.md-documented catastrophic-
    cancellation bug: take_profit built as EXACTLY stop_distance*2.0 from
    entry, then risk/reward RECOMPUTED via subtraction, must never be
    incorrectly vetoed by float noise landing the ratio at
    1.9999999999998-ish instead of exactly 2.0."""
    engine = RiskManagementEngine()
    engine.initialize()
    entry = 4296.5123456789
    proposal = TradeRiskProposal(
        asset="TEST", direction="LONG", entry_price=entry,
        stop_loss=entry - stop_distance, take_profit=entry + stop_distance * 2.0,
        risk_percent=SMALL_RISK_PCT, confidence_score=HIGH_CONFIDENCE,
    )
    result = engine.evaluate_trade(proposal)
    assert "below minimum" not in "".join(result.data.messages)
