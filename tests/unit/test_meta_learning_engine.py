"""
Module: test_meta_learning_engine.py
Description: First real test coverage for engines/e37_meta_learning --
    verified directly (grep across tests/) that this engine, despite
    being wired live into e51_signals' confluence scoring since
    2026-08-05, had zero test coverage before this file. Scoped to what
    this session's own change touches plus the highest-value existing
    untested logic it depends on: `_determine_verdict` (the
    regime_dependent/regime_consistent/insufficient_data classification)
    and `evaluate_live_confluence`/`_wrong_regime_multiplier` (the
    confidence adjustment e51_signals actually consumes).

    `_wrong_regime_multiplier` is the new logic (2026-09-13): closes a
    real gap found while cross-checking both PDFs in data/PDF/'s
    "IC-weighted confluence" recommendation against
    data/models/e37_meta_learning/regime_fit_database.json's own real
    numbers -- the old flat 0.90 wrong-regime penalty treated
    BHARTIARTL's -0.0084R (basically noise) the same as SILVER's
    -1.3928R (a real, well-evidenced loser). These tests assert the
    scaling is monotonic, bounded, and falls back safely on thin data,
    using the platform's own real recorded numbers as fixtures where
    convenient rather than inventing arbitrary ones.
Author: Shantanu Waykar
Version: 1.0.0
"""

from project_titan_x.engines.e37_meta_learning.engine import (
    RegimePerformance,
    MetaLearningEngine,
)


def _regime_fit_entry(current_regime_expectancy: float, current_regime_trades: int, current_regime: str = "trending") -> dict:
    other_regime = "ranging" if current_regime == "trending" else "trending"
    return {
        "verdict": "regime_dependent",
        "best_regime": other_regime,
        "regime_performance": [
            {"regime": current_regime, "n_trades": current_regime_trades, "expectancy_r": current_regime_expectancy, "status": "ok"},
            {"regime": other_regime, "n_trades": 90, "expectancy_r": 0.5, "status": "ok"},
        ],
    }


class TestWrongRegimeMultiplier:
    def test_near_breakeven_expectancy_gives_near_full_multiplier(self):
        """BHARTIARTL's real recorded worst-regime expectancy (-0.0084R,
        n=97) should produce a multiplier very close to 1.0 -- the old
        flat 0.90 was overpenalizing an effect this small."""
        entry = _regime_fit_entry(current_regime_expectancy=-0.0084, current_regime_trades=97)
        multiplier = MetaLearningEngine._wrong_regime_multiplier(entry, "trending")
        assert multiplier > 0.99

    def test_severe_real_expectancy_gives_a_much_larger_penalty_than_flat(self):
        """SILVER's real recorded worst-regime expectancy (-1.3928R,
        n=33) should produce a materially larger haircut than the old
        flat 0.90 -- confirms the scaling actually responds to a real,
        severe measured effect rather than clamping everything to the
        same number."""
        entry = _regime_fit_entry(current_regime_expectancy=-1.3928, current_regime_trades=33)
        multiplier = MetaLearningEngine._wrong_regime_multiplier(entry, "trending")
        assert multiplier < MetaLearningEngine._FLAT_FALLBACK_MULTIPLIER
        assert MetaLearningEngine._SCALED_PENALTY_FLOOR < multiplier < 0.75

    def test_expectancy_at_or_beyond_negative_two_r_hits_the_floor(self):
        entry = _regime_fit_entry(current_regime_expectancy=-2.0, current_regime_trades=50)
        multiplier = MetaLearningEngine._wrong_regime_multiplier(entry, "trending")
        assert multiplier == MetaLearningEngine._SCALED_PENALTY_FLOOR

    def test_extreme_outlier_expectancy_still_respects_the_floor(self):
        """A hypothetical -10R average (never seen live, but the formula
        must not extrapolate past the floor for an out-of-range input)."""
        entry = _regime_fit_entry(current_regime_expectancy=-10.0, current_regime_trades=500)
        multiplier = MetaLearningEngine._wrong_regime_multiplier(entry, "trending")
        assert multiplier == MetaLearningEngine._SCALED_PENALTY_FLOOR

    def test_scaling_is_monotonic_in_measured_expectancy(self):
        mild = MetaLearningEngine._wrong_regime_multiplier(
            _regime_fit_entry(current_regime_expectancy=-0.1, current_regime_trades=50), "trending"
        )
        moderate = MetaLearningEngine._wrong_regime_multiplier(
            _regime_fit_entry(current_regime_expectancy=-0.5, current_regime_trades=50), "trending"
        )
        severe = MetaLearningEngine._wrong_regime_multiplier(
            _regime_fit_entry(current_regime_expectancy=-1.0, current_regime_trades=50), "trending"
        )
        assert 1.0 > mild > moderate > severe >= MetaLearningEngine._SCALED_PENALTY_FLOOR

    def test_thin_sample_falls_back_to_flat_penalty(self):
        """Below MIN_TRADES_FOR_SCALED_PENALTY, a severe-looking
        expectancy must NOT be trusted to scale the penalty -- falls back
        to the original flat 0.90 regardless of how dramatic the number
        looks on too few trades."""
        entry = _regime_fit_entry(current_regime_expectancy=-3.0, current_regime_trades=6)
        multiplier = MetaLearningEngine._wrong_regime_multiplier(entry, "trending")
        assert multiplier == MetaLearningEngine._FLAT_FALLBACK_MULTIPLIER

    def test_missing_expectancy_falls_back_to_flat_penalty(self):
        entry = {
            "regime_performance": [
                {"regime": "trending", "n_trades": 40, "expectancy_r": None, "status": "insufficient_data"},
            ]
        }
        multiplier = MetaLearningEngine._wrong_regime_multiplier(entry, "trending")
        assert multiplier == MetaLearningEngine._FLAT_FALLBACK_MULTIPLIER

    def test_no_matching_regime_row_falls_back_to_flat_penalty(self):
        entry = _regime_fit_entry(current_regime_expectancy=-1.0, current_regime_trades=50, current_regime="trending")
        multiplier = MetaLearningEngine._wrong_regime_multiplier(entry, "ranging_typo_never_matches")
        assert multiplier == MetaLearningEngine._FLAT_FALLBACK_MULTIPLIER


class TestEvaluateLiveConfluence:
    def test_none_for_regime_consistent_verdict(self, monkeypatch):
        engine = MetaLearningEngine()
        monkeypatch.setattr(engine, "lookup_regime_fit", lambda symbol: {"verdict": "regime_consistent", "best_regime": "trending"})
        assert engine.evaluate_live_confluence("EURUSD", "LONG") is None

    def test_none_for_insufficient_data_verdict(self, monkeypatch):
        engine = MetaLearningEngine()
        monkeypatch.setattr(engine, "lookup_regime_fit", lambda symbol: {"verdict": "insufficient_data", "best_regime": None})
        assert engine.evaluate_live_confluence("EURUSD", "LONG") is None

    def test_none_when_no_database_entry(self, monkeypatch):
        engine = MetaLearningEngine()
        monkeypatch.setattr(engine, "lookup_regime_fit", lambda symbol: None)
        assert engine.evaluate_live_confluence("UNKNOWN", "LONG") is None

    def test_flat_boost_when_currently_in_best_regime(self, monkeypatch):
        engine = MetaLearningEngine()
        entry = _regime_fit_entry(current_regime_expectancy=-1.0, current_regime_trades=50, current_regime="ranging")
        monkeypatch.setattr(engine, "lookup_regime_fit", lambda symbol: entry)
        monkeypatch.setattr(engine, "_current_trending_state", lambda symbol: True)  # best_regime is "trending" here
        multiplier, evidence = engine.evaluate_live_confluence("SILVER", "LONG")
        assert multiplier == 1.05
        assert "IN its best regime" in evidence

    def test_scaled_penalty_when_outside_best_regime(self, monkeypatch):
        engine = MetaLearningEngine()
        entry = _regime_fit_entry(current_regime_expectancy=-1.3928, current_regime_trades=33, current_regime="trending")
        monkeypatch.setattr(engine, "lookup_regime_fit", lambda symbol: entry)
        monkeypatch.setattr(engine, "_current_trending_state", lambda symbol: True)  # best_regime is "ranging" here
        multiplier, evidence = engine.evaluate_live_confluence("SILVER", "LONG")
        assert multiplier < MetaLearningEngine._FLAT_FALLBACK_MULTIPLIER
        assert "OUTSIDE its best regime" in evidence

    def test_none_when_live_regime_check_fails(self, monkeypatch):
        engine = MetaLearningEngine()
        entry = _regime_fit_entry(current_regime_expectancy=-1.0, current_regime_trades=50)
        monkeypatch.setattr(engine, "lookup_regime_fit", lambda symbol: entry)
        monkeypatch.setattr(engine, "_current_trending_state", lambda symbol: None)
        assert engine.evaluate_live_confluence("SILVER", "LONG") is None


class TestDetermineVerdict:
    def test_regime_dependent_when_one_side_profitable_one_not(self):
        perf = [
            RegimePerformance("trending", 40, 30.0, -0.2, "ok"),
            RegimePerformance("ranging", 90, 55.0, 0.3, "ok"),
        ]
        verdict, best = MetaLearningEngine._determine_verdict(perf)
        assert verdict == "regime_dependent"
        assert best == "ranging"

    def test_regime_consistent_when_both_sides_positive(self):
        perf = [
            RegimePerformance("trending", 40, 50.0, 0.1, "ok"),
            RegimePerformance("ranging", 90, 55.0, 0.3, "ok"),
        ]
        verdict, best = MetaLearningEngine._determine_verdict(perf)
        assert verdict == "regime_consistent"
        assert best == "ranging"

    def test_insufficient_data_when_fewer_than_two_valid_regimes(self):
        perf = [
            RegimePerformance("trending", 3, None, None, "insufficient_data"),
            RegimePerformance("ranging", 90, 55.0, 0.3, "ok"),
        ]
        verdict, best = MetaLearningEngine._determine_verdict(perf)
        assert verdict == "insufficient_data"
        assert best == "ranging"

    def test_insufficient_data_when_zero_valid_regimes(self):
        perf = [
            RegimePerformance("trending", 3, None, None, "insufficient_data"),
            RegimePerformance("ranging", 4, None, None, "insufficient_data"),
        ]
        verdict, best = MetaLearningEngine._determine_verdict(perf)
        assert verdict == "insufficient_data"
        assert best is None
