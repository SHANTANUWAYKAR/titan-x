"""
Module: test_model_risk_engine.py
Description: Unit tests for Engine 39 (Model Risk Management) -- one of the
    engines the Phase 1 audit found had zero test reference at all, and a
    genuinely load-bearing one: e47_governance's own "model_provenance"
    check delegates entirely to this engine's audit() (never a duplicate
    check, per Rule 4), so a defect here silently weakens the platform's
    governance audit too.

    Same "operate on this platform's own real files, real assets" scope
    the engine's own docstring describes -- tests use tmp_path directories
    (monkeypatched over the module's _DATA_MODELS_DIR/_SIGNALS_MODELS_DIR
    constants) for deterministic, isolated coverage of the file-inventory
    and provenance logic, plus one real-environment smoke test (same
    "the actual guarantee, not a stand-in" pattern test_rule5_enforcement.
    py's own real-registry test already established) that runs audit()
    against the platform's real data/models/ directory and real asset
    list.
Author: Shantanu Waykar
Version: 1.0.0
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import project_titan_x.engines.e39_model_risk.engine as mod
from project_titan_x.core.config.assets import AssetClass, AssetDefinition
from project_titan_x.engines.e39_model_risk.engine import (
    STALE_AFTER_DAYS,
    ModelRiskManagementEngine,
)


@pytest.fixture
def engine() -> ModelRiskManagementEngine:
    e = ModelRiskManagementEngine(timeframe="1d")
    e.initialize()
    return e


@pytest.fixture
def isolated_models_dir(tmp_path, monkeypatch):
    """Points the module's own directory constants at a fresh tmp_path
    tree instead of the real data/models/ -- same monkeypatch-the-module
    convention test_rule5_enforcement.py already uses for `settings`."""
    models_dir = tmp_path / "data" / "models"
    signals_dir = models_dir / "e51_signals"
    signals_dir.mkdir(parents=True)
    monkeypatch.setattr(mod, "_DATA_MODELS_DIR", models_dir)
    monkeypatch.setattr(mod, "_SIGNALS_MODELS_DIR", signals_dir)
    return models_dir, signals_dir


def _write_override(signals_dir: Path, yahoo_symbol: str, timeframe: str, **fields) -> Path:
    p = signals_dir / f"{yahoo_symbol}_{timeframe}_strategy_override.json"
    p.write_text(json.dumps(fields), encoding="utf-8")
    return p


def _write_tuned_params(signals_dir: Path, yahoo_symbol: str, timeframe: str, **fields) -> Path:
    p = signals_dir / f"{yahoo_symbol}_{timeframe}_tuned_params.json"
    p.write_text(json.dumps(fields), encoding="utf-8")
    return p


_VALID_OVERRIDE_FIELDS = dict(
    strategy="trend_following", params={"lookback": 20}, validated_at="2026-08-01",
    oos_sharpe=1.2, total_trades=145,
)
_VALID_TUNED_FIELDS = dict(trained_at="2026-08-01", oos_sharpe=0.9, total_trades=80)


# --------------------------------------------------------------------------
# Single-symbol provenance check (the hot-path method, check_symbol/
# _check_live_provenance)
# --------------------------------------------------------------------------

def test_no_file_at_all_is_baseline_composite_rule(isolated_models_dir):
    result = mod.ModelRiskManagementEngine._check_live_provenance("BTCUSD", "BTC-USD", "1d")
    assert result.model_kind == "baseline_composite_rule"
    assert result.provenance == "not_applicable"
    assert result.file_path is None


def test_valid_override_is_verified(isolated_models_dir):
    _, signals_dir = isolated_models_dir
    _write_override(signals_dir, "BTC-USD", "1d", **_VALID_OVERRIDE_FIELDS)
    result = mod.ModelRiskManagementEngine._check_live_provenance("BTCUSD", "BTC-USD", "1d")
    assert result.model_kind == "strategy_override"
    assert result.provenance == "verified"
    assert result.missing_fields == []


def test_override_missing_a_required_field_is_flagged(isolated_models_dir):
    """An unknown/hand-dropped file (missing the governance fields the
    real training script always writes) must never silently pass as
    verified -- exactly the master-prompt scope this engine exists for."""
    _, signals_dir = isolated_models_dir
    fields = dict(_VALID_OVERRIDE_FIELDS)
    del fields["oos_sharpe"]
    _write_override(signals_dir, "BTC-USD", "1d", **fields)
    result = mod.ModelRiskManagementEngine._check_live_provenance("BTCUSD", "BTC-USD", "1d")
    assert result.provenance == "missing_required_fields"
    assert "oos_sharpe" in result.missing_fields


@pytest.mark.parametrize("field_name", ["strategy", "params", "validated_at", "oos_sharpe", "total_trades"])
def test_every_required_override_field_is_checked(isolated_models_dir, field_name):
    """Parametrised deliberately, same reasoning test_rule5_enforcement.py's
    own per-method-name parametrisation uses: a refactor that dropped one
    field from the required tuple should be caught by exactly one of
    these, not silently pass because some OTHER field happened to be
    checked instead."""
    _, signals_dir = isolated_models_dir
    fields = dict(_VALID_OVERRIDE_FIELDS)
    del fields[field_name]
    _write_override(signals_dir, "BTC-USD", "1d", **fields)
    result = mod.ModelRiskManagementEngine._check_live_provenance("BTCUSD", "BTC-USD", "1d")
    assert result.provenance == "missing_required_fields"
    assert field_name in result.missing_fields


def test_unreadable_override_file_is_unverified_not_crash(isolated_models_dir):
    _, signals_dir = isolated_models_dir
    p = signals_dir / "BTC-USD_1d_strategy_override.json"
    p.write_text("{not valid json", encoding="utf-8")
    result = mod.ModelRiskManagementEngine._check_live_provenance("BTCUSD", "BTC-USD", "1d")
    assert result.provenance == "unverified"
    assert any("unreadable" in m for m in result.missing_fields)


def test_tuned_params_used_when_no_override_present(isolated_models_dir):
    _, signals_dir = isolated_models_dir
    _write_tuned_params(signals_dir, "BTC-USD", "1d", **_VALID_TUNED_FIELDS)
    result = mod.ModelRiskManagementEngine._check_live_provenance("BTCUSD", "BTC-USD", "1d")
    assert result.model_kind == "tuned_params"
    assert result.provenance == "verified"


def test_override_takes_precedence_over_tuned_params(isolated_models_dir):
    """Same structural > tuning > baseline precedence e51_signals itself
    uses -- both files present, override must win."""
    _, signals_dir = isolated_models_dir
    _write_override(signals_dir, "BTC-USD", "1d", **_VALID_OVERRIDE_FIELDS)
    _write_tuned_params(signals_dir, "BTC-USD", "1d", **_VALID_TUNED_FIELDS)
    result = mod.ModelRiskManagementEngine._check_live_provenance("BTCUSD", "BTC-USD", "1d")
    assert result.model_kind == "strategy_override"


def test_check_symbol_matches_check_live_provenance(isolated_models_dir, engine):
    """check_symbol is documented as reusing the SAME underlying check
    audit() itself uses, never a second implementation -- pin that the
    public convenience method and the internal one actually agree."""
    _, signals_dir = isolated_models_dir
    _write_override(signals_dir, "BTC-USD", "1d", **_VALID_OVERRIDE_FIELDS)
    via_public = engine.check_symbol("BTCUSD", "BTC-USD", "1d")
    via_internal = mod.ModelRiskManagementEngine._check_live_provenance("BTCUSD", "BTC-USD", "1d")
    assert via_public == via_internal


# --------------------------------------------------------------------------
# Full audit() -- file inventory + live provenance across every real asset
# --------------------------------------------------------------------------

def test_audit_inventories_files_with_real_hashes(isolated_models_dir, engine):
    models_dir, _ = isolated_models_dir
    sub = models_dir / "e24_strategy_research"
    sub.mkdir()
    content = b'{"a": 1}'
    (sub / "report.json").write_bytes(content)

    result = engine.audit()
    assert result.success is True
    tracked = {f.relative_path: f for f in result.data.tracked_files}
    entry = tracked["e24_strategy_research/report.json"]
    assert entry.engine_dir == "e24_strategy_research"
    assert entry.status == "ok"
    assert entry.size_bytes == len(content)
    import hashlib
    assert entry.sha256 == hashlib.sha256(content).hexdigest()


def test_audit_flags_corrupt_json_and_sets_overall_verdict(isolated_models_dir, engine):
    models_dir, _ = isolated_models_dir
    sub = models_dir / "e24_strategy_research"
    sub.mkdir()
    (sub / "broken.json").write_text("{not valid", encoding="utf-8")

    result = engine.audit()
    assert "e24_strategy_research/broken.json" in result.data.corrupt_files
    assert result.data.overall_verdict == "corrupt_files_present"


def test_audit_flags_stale_files(isolated_models_dir, engine):
    models_dir, _ = isolated_models_dir
    sub = models_dir / "e24_strategy_research"
    sub.mkdir()
    p = sub / "old_report.json"
    p.write_text("{}", encoding="utf-8")
    import os
    old_time = (datetime.now(timezone.utc) - timedelta(days=STALE_AFTER_DAYS + 10)).timestamp()
    os.utime(p, (old_time, old_time))

    result = engine.audit()
    assert "e24_strategy_research/old_report.json" in result.data.stale_files


def test_audit_overall_verdict_clean_when_nothing_wrong(isolated_models_dir, engine, monkeypatch):
    _, signals_dir = isolated_models_dir
    _write_override(signals_dir, "BTC-USD", "1d", **_VALID_OVERRIDE_FIELDS)
    assets = [AssetDefinition("BTCUSD", "Bitcoin", AssetClass.CRYPTO, "BTC-USD", "note", 0.0)]
    monkeypatch.setattr(mod, "list_assets", lambda: assets)

    result = engine.audit()
    assert result.data.overall_verdict == "clean"
    assert result.data.unverified_live_models == []


def test_audit_overall_verdict_unverified_when_any_asset_has_no_verified_model(isolated_models_dir, engine, monkeypatch):
    """A real, live danger case: an asset whose override file is missing a
    required field must flip the WHOLE audit's overall_verdict, not just
    that one asset's own entry -- an unverified model live anywhere on the
    platform is exactly what this engine exists to surface."""
    _, signals_dir = isolated_models_dir
    fields = dict(_VALID_OVERRIDE_FIELDS)
    del fields["total_trades"]
    _write_override(signals_dir, "BTC-USD", "1d", **fields)
    assets = [AssetDefinition("BTCUSD", "Bitcoin", AssetClass.CRYPTO, "BTC-USD", "note", 0.0)]
    monkeypatch.setattr(mod, "list_assets", lambda: assets)

    result = engine.audit()
    assert result.data.overall_verdict == "unverified_models_live"
    assert "BTCUSD" in result.data.unverified_live_models


def test_audit_corrupt_files_takes_precedence_over_unverified(isolated_models_dir, engine, monkeypatch):
    """Both a corrupt file AND an unverified live model present at once --
    overall_verdict must report SOMETHING is wrong either way; pin the
    documented precedence (corrupt_files_present wins) rather than leave
    it to accidental if/elif ordering that could silently flip."""
    models_dir, signals_dir = isolated_models_dir
    sub = models_dir / "e24_strategy_research"
    sub.mkdir()
    (sub / "broken.json").write_text("{not valid", encoding="utf-8")
    fields = dict(_VALID_OVERRIDE_FIELDS)
    del fields["oos_sharpe"]
    _write_override(signals_dir, "BTC-USD", "1d", **fields)
    assets = [AssetDefinition("BTCUSD", "Bitcoin", AssetClass.CRYPTO, "BTC-USD", "note", 0.0)]
    monkeypatch.setattr(mod, "list_assets", lambda: assets)

    result = engine.audit()
    assert result.data.overall_verdict == "corrupt_files_present"


def test_audit_handles_missing_models_directory_gracefully(tmp_path, monkeypatch, engine):
    """A brand-new environment with no data/models/ directory yet at all
    must not crash the audit -- honest empty inventory, not an error."""
    monkeypatch.setattr(mod, "_DATA_MODELS_DIR", tmp_path / "does_not_exist")
    monkeypatch.setattr(mod, "_SIGNALS_MODELS_DIR", tmp_path / "does_not_exist" / "e51_signals")
    monkeypatch.setattr(mod, "list_assets", lambda: [])
    result = engine.audit()
    assert result.success is True
    assert result.data.tracked_files == []
    assert result.data.overall_verdict == "clean"


# --------------------------------------------------------------------------
# THE ACTUAL GUARANTEE -- the real platform, not a stand-in
# --------------------------------------------------------------------------

def test_real_audit_runs_clean_against_the_live_platform(engine):
    """Runs audit() against the platform's REAL data/models/ directory and
    REAL asset list (no monkeypatching) -- proves the engine actually
    works end-to-end against real files, not just constructed fixtures.
    Deliberately does not assert overall_verdict == "clean": a real
    unverified/stale/corrupt file legitimately existing on this platform
    right now is a fact about the platform, not a bug in this test, so
    asserting a specific verdict here would make the test fragile against
    real environment drift rather than testing the engine itself."""
    result = engine.audit()
    assert result.success is True
    assert result.data is not None
    assert result.data.overall_verdict in ("clean", "unverified_models_live", "corrupt_files_present")
    assert isinstance(result.data.tracked_files, list)
    assert isinstance(result.data.live_provenance, list)
    assert len(result.data.live_provenance) > 0  # real assets exist
