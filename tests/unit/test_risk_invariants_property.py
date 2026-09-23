"""
Property-based tests (Hypothesis) closing docs/UPGRADE_BRIEF.md Phase
17's "confidence always 0-100" requirement.

The other two named invariants ("stop always on the correct side of
entry for both directions" and "no feature at bar t uses data from
t+k") already have real, existing coverage found by reading the suite
directly before adding anything -- not assumed:
  - Stop/target geometry: tests/unit/test_risk_engine_properties.py's
    own test_inverted_direction_trades_are_always_vetoed and
    test_direction_correct_trades_are_never_vetoed_for_geometry already
    property-test this exact invariant across hundreds of generated
    price/gap combinations. Duplicating it here was the first draft of
    this file; removed once that existing coverage was found, per the
    same "don't duplicate functionality" discipline this whole session
    has followed elsewhere.
  - No lookahead: test_market_structure_shift.py, test_crt.py, and
    test_cisd.py each assert bar-by-bar consistency under multi-
    truncation (0.35/0.5/0.65/0.8/0.93) directly against real detector
    output -- more precise than a generic property test could add.

This file's own test is genuinely new: it targets E51's override-path
CONFIDENCE COMPUTATION specifically (`round(win_rate * 100)`), not E45's
robustness to an already-valid confidence input (which
test_risk_engine_properties.py's test_confidence_score_never_crashes_
the_engine already covers). Writing it found a real, previously-
unclamped gap, fixed in engine.py and kept here as the permanent
regression test.
"""

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st


@given(win_rate=st.floats(min_value=-5.0, max_value=5.0, allow_nan=False, allow_infinity=False))
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
def test_override_confidence_always_clamped_to_0_100(win_rate, monkeypatch):
    """Real gap found while writing this test (docs/UPGRADE_ROADMAP.md
    Phase 17): `confidence = round(win_rate * 100)` had no clamp.
    win_rate is read from an on-disk override file this function doesn't
    otherwise validate -- a malformed value (e.g. a future write bug
    expressing it as a 0-100 percentage instead of a 0-1 fraction, or a
    stray negative) would have flowed straight into confidence_score
    unclamped. Fixed in engine.py; this is the permanent regression test.
    Deliberately sweeps FAR outside the real [0, 1] domain win_rate is
    supposed to have -- the clamp must hold even for garbage input, not
    just plausible-but-wrong input.

    Uses "donchian_breakout" as the fake strategy name specifically
    because it's one of the two archetypes _determine_direction_from_
    override's own `needs_enriched` check skips technical-engine
    enrichment for (raw OHLCV is enough) -- keeps this test fast and
    isolated from a real indicator computation neither this test nor the
    invariant it checks has anything to do with."""
    import project_titan_x.engines.e51_signals.engine as e51_module
    import pandas as pd

    df = pd.DataFrame({"close": [100.0] * 5, "open": [100.0] * 5, "high": [100.5] * 5, "low": [99.5] * 5})

    def _always_long(frame, **params):
        return pd.Series([1] * len(frame))

    monkeypatch.setitem(e51_module.STRATEGIES, "donchian_breakout", _always_long)

    override = {"strategy": "donchian_breakout", "params": {}, "win_rate": win_rate}
    engine = e51_module.SignalIntelligenceEngine()
    engine.initialize()
    direction, confidence, evidence = engine._determine_direction_from_override(df, override)
    assert direction == "LONG"
    assert 0 <= confidence <= 100
