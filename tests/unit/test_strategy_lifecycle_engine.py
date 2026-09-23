"""
Module: test_strategy_lifecycle_engine.py
Description: Unit tests for Engine 25 (Strategy Lifecycle) -- previously
    zero test coverage (confirmed absent before writing this file, not
    assumed). Covers the pre-existing researched/live/validated/decaying
    state derivation and the new "retired" stage
    (docs/UPGRADE_ROADMAP.md P2 item 10).
"""

import json

import pytest

from project_titan_x.engines.e25_strategy_lifecycle.engine import StrategyLifecycleEngine


@pytest.fixture
def engine() -> StrategyLifecycleEngine:
    e = StrategyLifecycleEngine()
    e.initialize()
    return e


@pytest.fixture(autouse=True)
def _isolated_dirs(tmp_path, monkeypatch):
    import project_titan_x.engines.e25_strategy_lifecycle.engine as e25_module

    report_dir = tmp_path / "e24_strategy_research"
    models_dir = tmp_path / "e51_signals"
    report_dir.mkdir()
    models_dir.mkdir()
    monkeypatch.setattr(e25_module, "_E24_REPORT_DIR", report_dir)
    monkeypatch.setattr(e25_module, "_E51_MODELS_DIR", models_dir)
    return report_dir, models_dir


def test_health_check(engine):
    assert engine.health_check().success


def test_not_researched_when_nothing_exists(engine):
    status = engine.status_for("TESTSYM", "TEST=X", "1d")
    assert status.lifecycle_stage == "not_researched"
    assert status.researched is False
    assert status.live_model_kind == "none"


def test_researched_not_promoted(engine, _isolated_dirs):
    report_dir, _ = _isolated_dirs
    (report_dir / "TESTSYM_1d_report.json").write_text(json.dumps({"symbol": "TESTSYM"}))
    status = engine.status_for("TESTSYM", "TEST=X", "1d")
    assert status.lifecycle_stage == "researched_not_promoted"
    assert status.researched is True


def test_live_unverified_provenance_when_required_fields_missing(engine, _isolated_dirs):
    _, models_dir = _isolated_dirs
    (models_dir / "TEST=X_1d_strategy_override.json").write_text(json.dumps({
        "strategy": "donchian_breakout", "params": {},
        # missing validated_at/oos_sharpe/total_trades
    }))
    status = engine.status_for("TESTSYM", "TEST=X", "1d")
    assert status.lifecycle_stage == "live_unverified_provenance"
    assert status.provenance_verified is False
    assert "validated_at" in status.missing_provenance_fields


def test_live_validated_when_all_provenance_fields_present(engine, _isolated_dirs):
    _, models_dir = _isolated_dirs
    (models_dir / "TEST=X_1d_strategy_override.json").write_text(json.dumps({
        "strategy": "donchian_breakout", "params": {},
        "validated_at": "2026-09-01T00:00:00+00:00", "oos_sharpe": 0.8, "total_trades": 60,
    }))
    status = engine.status_for("TESTSYM", "TEST=X", "1d")
    assert status.lifecycle_stage == "live_validated"
    assert status.provenance_verified is True


def test_decaying_when_alpha_decay_monitor_says_so(_isolated_dirs):
    _, models_dir = _isolated_dirs
    (models_dir / "TEST=X_1d_strategy_override.json").write_text(json.dumps({
        "strategy": "donchian_breakout", "params": {},
        "validated_at": "2026-09-01T00:00:00+00:00", "oos_sharpe": 0.8, "total_trades": 60,
    }))

    class _FakeDecayResult:
        success = True
        class data:
            status = "decay_detected"

    class _FakeDecayEngine:
        def assess_decay(self, strategy_name=None):
            return _FakeDecayResult()

    engine = StrategyLifecycleEngine(alpha_decay_monitor_engine=_FakeDecayEngine())
    engine.initialize()
    status = engine.status_for("TESTSYM", "TEST=X", "1d")
    assert status.lifecycle_stage == "decaying"


def test_retired_override_reports_retired_not_live_validated(_isolated_dirs):
    """docs/UPGRADE_ROADMAP.md P2 item 10: a real retired_at tombstone,
    read the same way this engine's own docstring always said it should
    be, rather than invented parallel bookkeeping."""
    _, models_dir = _isolated_dirs
    (models_dir / "TEST=X_1d_strategy_override.json").write_text(json.dumps({
        "strategy": "donchian_breakout", "params": {},
        "validated_at": "2026-09-01T00:00:00+00:00", "oos_sharpe": 0.8, "total_trades": 60,
        "retired_at": "2026-09-13T00:00:00+00:00", "retired_reason": "no longer clears Stage 0",
    }))
    engine = StrategyLifecycleEngine()
    engine.initialize()
    status = engine.status_for("TESTSYM", "TEST=X", "1d")
    assert status.lifecycle_stage == "retired"
    assert status.retired_at == "2026-09-13T00:00:00+00:00"


def test_retired_takes_priority_over_decaying(_isolated_dirs):
    """Retirement is terminal -- even if the alpha decay monitor would
    also flag decay, a retired override reports 'retired', not
    'decaying' (and the decay engine should not even be consulted)."""
    _, models_dir = _isolated_dirs
    (models_dir / "TEST=X_1d_strategy_override.json").write_text(json.dumps({
        "strategy": "donchian_breakout", "params": {},
        "validated_at": "2026-09-01T00:00:00+00:00", "oos_sharpe": 0.8, "total_trades": 60,
        "retired_at": "2026-09-13T00:00:00+00:00",
    }))

    called = {"count": 0}

    class _FakeDecayEngine:
        def assess_decay(self, strategy_name=None):
            called["count"] += 1
            class _R:
                success = True
                class data:
                    status = "decay_detected"
            return _R()

    engine = StrategyLifecycleEngine(alpha_decay_monitor_engine=_FakeDecayEngine())
    engine.initialize()
    status = engine.status_for("TESTSYM", "TEST=X", "1d")
    assert status.lifecycle_stage == "retired"
    assert called["count"] == 0, "decay monitor should not be consulted for an already-retired override"


def test_retired_tuned_params_also_reports_retired(_isolated_dirs):
    _, models_dir = _isolated_dirs
    (models_dir / "TEST=X_1d_tuned_params.json").write_text(json.dumps({
        "trained_at": "2026-09-01T00:00:00+00:00", "oos_sharpe": 0.5, "total_trades": 40,
        "retired_at": "2026-09-13T00:00:00+00:00",
    }))
    engine = StrategyLifecycleEngine()
    engine.initialize()
    status = engine.status_for("TESTSYM", "TEST=X", "1d")
    assert status.lifecycle_stage == "retired"
    assert status.live_model_kind == "tuned_params"


def test_retired_with_unverified_provenance_still_reports_retired(_isolated_dirs):
    """Retirement must veto regardless of provenance status too -- a
    retired-but-never-fully-validated override is still 'retired', not
    'live_unverified_provenance'."""
    _, models_dir = _isolated_dirs
    (models_dir / "TEST=X_1d_strategy_override.json").write_text(json.dumps({
        "strategy": "donchian_breakout", "params": {},
        "retired_at": "2026-09-13T00:00:00+00:00",
        # no validated_at/oos_sharpe/total_trades -- would otherwise be live_unverified_provenance
    }))
    engine = StrategyLifecycleEngine()
    engine.initialize()
    status = engine.status_for("TESTSYM", "TEST=X", "1d")
    assert status.lifecycle_stage == "retired"


def test_to_dict_includes_retired_at(engine):
    status = engine.status_for("TESTSYM", "TEST=X", "1d")
    d = status.to_dict()
    assert "retired_at" in d
    assert d["retired_at"] is None


def test_audit_across_multiple_symbols(engine, _isolated_dirs):
    report_dir, models_dir = _isolated_dirs
    (report_dir / "SYM1_1d_report.json").write_text(json.dumps({"symbol": "SYM1"}))
    result = engine.audit(symbols=[("SYM1", "SYM1"), ("SYM2", "SYM2")], timeframe="1d")
    assert result.success
    assert len(result.data.statuses) == 2
    stages = {s.symbol: s.lifecycle_stage for s in result.data.statuses}
    assert stages["SYM1"] == "researched_not_promoted"
    assert stages["SYM2"] == "not_researched"
