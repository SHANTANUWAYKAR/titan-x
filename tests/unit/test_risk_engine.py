"""
Module: test_risk_engine.py
Description: Unit tests for Risk Management Engine (CRO).
Author: Shantanu Waykar
Version: 1.0.0
"""

import pytest

from project_titan_x.engines.e45_risk import (
    FUNDINGPIPS_PROFILES,
    FundedAccountProfile,
    PortfolioRiskState,
    RiskManagementEngine,
    RiskVerdict,
    TradeRiskProposal,
)


@pytest.fixture
def risk_engine() -> RiskManagementEngine:
    """Create risk engine instance."""
    engine = RiskManagementEngine()
    engine.initialize()
    return engine


def test_approve_valid_trade(risk_engine: RiskManagementEngine):
  """Test approval of valid trade proposal."""
  proposal = TradeRiskProposal(
    asset="NIFTY50",
    direction="LONG",
    entry_price=24500,
    stop_loss=24300,
    take_profit=24900,
    risk_percent=0.5,
    confidence_score=85,
  )
  result = risk_engine.evaluate_trade(proposal)
  assert result.success
  assert result.data.approved
  assert result.data.verdict in (RiskVerdict.APPROVED, RiskVerdict.WARNING)


def test_veto_low_confidence(risk_engine: RiskManagementEngine):
  """Test veto on low confidence -- below the global floor (20, see
  settings.min_signal_confidence), not the retired 80% bar."""
  proposal = TradeRiskProposal(
    asset="NIFTY50",
    direction="LONG",
    entry_price=24500,
    stop_loss=24300,
    take_profit=24900,
    risk_percent=1.0,
    confidence_score=10,
  )
  result = risk_engine.evaluate_trade(proposal)
  assert result.data.verdict == RiskVerdict.VETO
  assert not result.data.approved


def test_veto_poor_risk_reward(risk_engine: RiskManagementEngine):
  """Test veto on poor risk:reward."""
  proposal = TradeRiskProposal(
    asset="NIFTY50",
    direction="LONG",
    entry_price=24500,
    stop_loss=24300,
    take_profit=24550,
    risk_percent=1.0,
    confidence_score=90,
  )
  result = risk_engine.evaluate_trade(proposal)
  assert result.data.verdict == RiskVerdict.VETO


def test_halt_trading(risk_engine: RiskManagementEngine):
  """Test CRO trading halt."""
  risk_engine.halt_trading("Test halt")
  proposal = TradeRiskProposal(
    asset="TEST",
    direction="LONG",
    entry_price=100,
    stop_loss=95,
    take_profit=110,
    risk_percent=1.0,
    confidence_score=90,
  )
  result = risk_engine.evaluate_trade(proposal)
  assert result.data.verdict == RiskVerdict.VETO


def test_position_size_calculation(risk_engine: RiskManagementEngine):
  """Test position size calculation."""
  result = risk_engine.calculate_position_size(
    capital=10_000,
    entry_price=100,
    stop_loss=95,
    risk_percent=0.5,
  )
  assert result.success
  assert result.data["position_size"] == 10.0
  assert result.data["risk_amount"] == 50.0


def test_veto_excessive_risk_per_trade(risk_engine: RiskManagementEngine):
  """Test veto when risk per trade exceeds max for small capital."""
  proposal = TradeRiskProposal(
    asset="EURUSD",
    direction="LONG",
    entry_price=1.10,
    stop_loss=1.09,
    take_profit=1.12,
    risk_percent=2.0,
    confidence_score=90,
  )
  result = risk_engine.evaluate_trade(proposal)
  assert result.data.verdict.value == "veto"


def test_drawdown_auto_halt(risk_engine: RiskManagementEngine):
  """Test auto-halt on max drawdown.

  Real bug found and fixed 2026-09-14: this used to construct
  PortfolioRiskState(current_drawdown_pct=25.0) directly -- exactly the
  pattern that turned out to be the real, live gap (no production caller
  ever actually computed current_drawdown_pct from a real peak; the
  engine trusted whatever number showed up). update_portfolio_state now
  computes current_drawdown_pct itself from a tracked peak equity, so
  triggering the halt for real means reporting an actual capital loss
  from a real peak, not setting the field directly."""
  risk_engine.update_portfolio_state(PortfolioRiskState(total_capital=10_000.0))  # establishes the peak
  risk_engine.update_portfolio_state(PortfolioRiskState(total_capital=7_500.0))  # 25% drawdown from that peak
  health = risk_engine.health_check()
  assert not health.success


# ---- trailing high-water-mark drawdown + generic zone system (2026-09-14) ----

def test_peak_equity_tracked_and_drawdown_computed_from_it(risk_engine: RiskManagementEngine):
  """current_drawdown_pct is derived from a tracked peak, not a caller-
  supplied number -- the real gap this whole section closes."""
  risk_engine.update_portfolio_state(PortfolioRiskState(total_capital=10_000.0))
  risk_engine.update_portfolio_state(PortfolioRiskState(total_capital=9_000.0))
  assert risk_engine.get_portfolio_state().current_drawdown_pct == pytest.approx(10.0)


def test_caller_supplied_current_drawdown_pct_is_overwritten(risk_engine: RiskManagementEngine):
  """A caller passing a fabricated/stale current_drawdown_pct must not
  survive -- this is the exact pattern that made the old veto trust a
  number nothing in production ever correctly computed."""
  risk_engine.update_portfolio_state(
    PortfolioRiskState(total_capital=10_000.0, current_drawdown_pct=99.0)
  )
  assert risk_engine.get_portfolio_state().current_drawdown_pct == pytest.approx(0.0)


def test_new_equity_high_resets_drawdown_to_zero(risk_engine: RiskManagementEngine):
  """A fresh peak must reset drawdown to exactly 0%, and become the new
  high-water mark for future drawdown math."""
  risk_engine.update_portfolio_state(PortfolioRiskState(total_capital=10_000.0))
  risk_engine.update_portfolio_state(PortfolioRiskState(total_capital=9_500.0))  # small dip
  risk_engine.update_portfolio_state(PortfolioRiskState(total_capital=11_000.0))  # new high
  assert risk_engine.get_portfolio_state().current_drawdown_pct == pytest.approx(0.0)
  risk_engine.update_portfolio_state(PortfolioRiskState(total_capital=10_450.0))  # 5% off the NEW peak
  assert risk_engine.get_portfolio_state().current_drawdown_pct == pytest.approx(5.0)


def test_green_zone_full_size_when_drawdown_small(risk_engine: RiskManagementEngine):
  """Well below the yellow zone (settings.max_drawdown_pct defaults to
  20%, yellow starts at 50% of that = 10%) -- full requested size."""
  risk_engine.update_portfolio_state(PortfolioRiskState(total_capital=10_000.0))
  risk_engine.update_portfolio_state(PortfolioRiskState(total_capital=9_800.0))  # 2% drawdown
  proposal = TradeRiskProposal(
    asset="NIFTY50", direction="LONG", entry_price=24500, stop_loss=24300,
    take_profit=24900, risk_percent=0.5, confidence_score=85,
  )
  result = risk_engine.evaluate_trade(proposal)
  assert result.data.verdict == RiskVerdict.APPROVED
  assert result.data.adjusted_risk_pct == pytest.approx(0.5)


def test_yellow_zone_shrinks_risk_size_without_blocking(risk_engine: RiskManagementEngine):
  """Between 50% and 100% of max_drawdown_pct (10%-20% with the default
  20% limit): warn and shrink, same "don't block" shape the funded-
  account zones and portfolio-heat rule already use."""
  risk_engine.update_portfolio_state(PortfolioRiskState(total_capital=10_000.0))
  risk_engine.update_portfolio_state(PortfolioRiskState(total_capital=8_500.0))  # 15% drawdown -- mid-yellow
  proposal = TradeRiskProposal(
    asset="NIFTY50", direction="LONG", entry_price=24500, stop_loss=24300,
    take_profit=24900, risk_percent=1.0, confidence_score=85,
  )
  result = risk_engine.evaluate_trade(proposal)
  assert result.data.approved is True  # shrunk, not blocked
  assert result.data.verdict == RiskVerdict.WARNING
  assert result.data.adjusted_risk_pct is not None
  assert 0.0 < result.data.adjusted_risk_pct < 1.0
  assert any("zone" in m.lower() for m in result.data.messages)


def test_generic_zone_skipped_entirely_in_funded_mode(risk_engine: RiskManagementEngine):
  """The generic overall-drawdown zone must never fire once a funded
  profile is active -- that path has its own, separate zone system
  (_funded_zone_risk_multiplier), never blended with this one."""
  risk_engine.update_portfolio_state(PortfolioRiskState(total_capital=10_000.0))
  risk_engine.update_portfolio_state(PortfolioRiskState(total_capital=8_500.0))  # would be yellow generically
  risk_engine.activate_funded_account(
    FUNDINGPIPS_PROFILES["fundingpips_2step_standard_phase1"], account_size=10_000.0
  )
  proposal = TradeRiskProposal(
    asset="NIFTY50", direction="LONG", entry_price=24500, stop_loss=24300,
    take_profit=24900, risk_percent=0.5, confidence_score=85,
  )
  result = risk_engine.evaluate_trade(proposal)
  # Approved/shrunk only by the FUNDED zone (fresh funded equity, no
  # daily loss yet) -- never mentions the generic "zone" wording, which
  # only the code path this test guards against would produce.
  assert not any("overall drawdown" in m.lower() for m in result.data.messages)


# ---- knowledge_context (E01 integration) ----


def _real_knowledge_engine(tmp_path, note_text: str):
    from project_titan_x.engines.e01_knowledge.document_store import DocumentStore
    from project_titan_x.engines.e01_knowledge.engine import KnowledgeEngine

    store = DocumentStore(persist_dir=tmp_path / "chroma")
    knowledge_engine = KnowledgeEngine(knowledge_dir=tmp_path / "kd", data_root=tmp_path / "data", document_store=store)
    notes = tmp_path / "data" / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    (notes / "doc.txt").write_text(note_text, encoding="utf-8")
    knowledge_engine.ingestion.ingest_all()
    return knowledge_engine


def _approved_proposal() -> TradeRiskProposal:
    return TradeRiskProposal(
        asset="EURUSD", direction="LONG", entry_price=1.10, stop_loss=1.09,
        take_profit=1.12, risk_percent=0.5, confidence_score=90,
    )


def test_evaluate_trade_attaches_knowledge_context_when_injected(tmp_path):
    knowledge_engine = _real_knowledge_engine(
        tmp_path,
        "Chapter 1: Position Sizing\n\nRisking a small, fixed percentage of capital per trade protects against ruin over a long series of trades.",
    )
    engine = RiskManagementEngine(knowledge_engine=knowledge_engine)
    engine.initialize()
    result = engine.evaluate_trade(_approved_proposal())
    assert result.success
    assert result.data.knowledge_context is not None
    assert result.data.knowledge_context["results"]


def test_evaluate_trade_knowledge_context_none_without_engine(risk_engine):
    result = risk_engine.evaluate_trade(_approved_proposal())
    assert result.success
    assert result.data.knowledge_context is None


def test_veto_attaches_knowledge_context_but_never_changes_verdict(tmp_path):
    """knowledge_context on a veto path must be purely informational --
    confirms the veto fires for the SAME reason regardless of whether a
    knowledge engine is injected."""
    knowledge_engine = _real_knowledge_engine(
        tmp_path,
        "Chapter 1: Stop Losses\n\nEvery position must have a predefined invalidation level before entry.",
    )
    engine = RiskManagementEngine(knowledge_engine=knowledge_engine)
    engine.initialize()
    bad_proposal = TradeRiskProposal(
        asset="EURUSD", direction="LONG", entry_price=1.10, stop_loss=0,
        take_profit=1.12, risk_percent=0.5, confidence_score=90,
    )
    result = engine.evaluate_trade(bad_proposal)
    assert result.data.verdict == RiskVerdict.VETO
    assert result.data.approved is False
    assert result.data.knowledge_context is not None


# ---- per-asset confidence floor from a validated strategy override ----
#
# e51_signals can wire in a validated, structurally-different strategy for
# a specific asset (e.g. SP500's Donchian breakout) whose honest backtested
# win rate is nowhere near the blanket 80% floor. E45 must independently
# re-read the SAME on-disk validated calibration file for its own veto
# decision -- never trust a threshold handed to it at runtime by the
# proposer -- so these tests write the override file directly rather than
# going through e51_signals at all.

def test_veto_uses_blanket_floor_when_no_override_exists(risk_engine, tmp_path, monkeypatch):
    import project_titan_x.engines.e45_risk.engine as e45_module

    monkeypatch.setattr(e45_module, "_STRATEGY_OVERRIDE_DIR", tmp_path)
    proposal = TradeRiskProposal(
        asset="EURUSD", direction="LONG", entry_price=1.10, stop_loss=1.09,
        take_profit=1.12, risk_percent=0.5, confidence_score=10, timeframe="1d",
    )
    result = risk_engine.evaluate_trade(proposal)
    assert result.data.verdict == RiskVerdict.VETO
    assert "20%" in result.data.veto_reason


def test_approves_below_blanket_floor_when_asset_has_validated_override(risk_engine, tmp_path, monkeypatch):
    import json
    import project_titan_x.engines.e45_risk.engine as e45_module

    monkeypatch.setattr(e45_module, "_STRATEGY_OVERRIDE_DIR", tmp_path)
    (tmp_path / "MES=F_1d_strategy_override.json").write_text(json.dumps({
        "strategy": "donchian_breakout", "params": {"entry_n": 15, "exit_n": 7},
        "win_rate": 0.567, "min_confidence": 50,
        "stage0": {"status": "VALIDATED"},
    }))
    proposal = TradeRiskProposal(
        asset="SP500", direction="LONG", entry_price=5900, stop_loss=5850,
        take_profit=6000, risk_percent=0.5, confidence_score=57, timeframe="1d",
    )
    result = risk_engine.evaluate_trade(proposal)
    assert result.data.approved is True
    assert result.data.verdict in (RiskVerdict.APPROVED, RiskVerdict.WARNING)


def test_override_floor_still_vetoes_below_its_own_threshold(risk_engine, tmp_path, monkeypatch):
    """The per-asset floor is a real gate, not a rubber stamp -- a
    confidence below even the override's own (lower) threshold still gets
    vetoed."""
    import json
    import project_titan_x.engines.e45_risk.engine as e45_module

    monkeypatch.setattr(e45_module, "_STRATEGY_OVERRIDE_DIR", tmp_path)
    (tmp_path / "MES=F_1d_strategy_override.json").write_text(json.dumps({
        "strategy": "donchian_breakout", "params": {"entry_n": 15, "exit_n": 7},
        "win_rate": 0.567, "min_confidence": 50,
        "stage0": {"status": "VALIDATED"},
    }))
    proposal = TradeRiskProposal(
        asset="SP500", direction="LONG", entry_price=5900, stop_loss=5850,
        take_profit=6000, risk_percent=0.5, confidence_score=30, timeframe="1d",
    )
    result = risk_engine.evaluate_trade(proposal)
    assert result.data.verdict == RiskVerdict.VETO
    assert "50%" in result.data.veto_reason


def test_override_lookup_is_asset_specific_not_global(risk_engine, tmp_path, monkeypatch):
    """A validated override for SP500 must not relax the floor for a
    different asset that has no override of its own."""
    import json
    import project_titan_x.engines.e45_risk.engine as e45_module

    monkeypatch.setattr(e45_module, "_STRATEGY_OVERRIDE_DIR", tmp_path)
    (tmp_path / "MES=F_1d_strategy_override.json").write_text(json.dumps({
        "strategy": "donchian_breakout", "params": {"entry_n": 15, "exit_n": 7},
        "win_rate": 0.567, "min_confidence": 50,
        "stage0": {"status": "VALIDATED"},
    }))
    proposal = TradeRiskProposal(
        asset="EURUSD", direction="LONG", entry_price=1.10, stop_loss=1.09,
        take_profit=1.12, risk_percent=0.5, confidence_score=10, timeframe="1d",
    )
    result = risk_engine.evaluate_trade(proposal)
    assert result.data.verdict == RiskVerdict.VETO
    assert "20%" in result.data.veto_reason


def test_override_with_no_stage0_tag_does_not_relax_the_floor(risk_engine, tmp_path, monkeypatch):
    """docs/UPGRADE_ROADMAP.md P0 item 1: a real bug found while fixing
    e51_signals' own Stage 0 default -- _promote() always writes
    min_confidence, and Stage 0 tagging only ADDS a stage0 block later, so
    a freshly-promoted (not-yet-tagged) override must NOT relax this
    engine's floor, the same as e51_signals must not drive a live signal
    from it."""
    import json
    import project_titan_x.engines.e45_risk.engine as e45_module

    monkeypatch.setattr(e45_module, "_STRATEGY_OVERRIDE_DIR", tmp_path)
    (tmp_path / "MES=F_1d_strategy_override.json").write_text(json.dumps({
        "strategy": "donchian_breakout", "params": {"entry_n": 15, "exit_n": 7},
        "win_rate": 0.567, "min_confidence": 50,
    }))
    proposal = TradeRiskProposal(
        asset="SP500", direction="LONG", entry_price=5900, stop_loss=5850,
        take_profit=6000, risk_percent=0.5, confidence_score=10, timeframe="1d",
    )
    result = risk_engine.evaluate_trade(proposal)
    assert result.data.verdict == RiskVerdict.VETO
    assert "20%" in result.data.veto_reason


def test_override_with_explicit_unvalidated_tag_does_not_relax_the_floor(risk_engine, tmp_path, monkeypatch):
    import json
    import project_titan_x.engines.e45_risk.engine as e45_module

    monkeypatch.setattr(e45_module, "_STRATEGY_OVERRIDE_DIR", tmp_path)
    (tmp_path / "MES=F_1d_strategy_override.json").write_text(json.dumps({
        "strategy": "donchian_breakout", "params": {"entry_n": 15, "exit_n": 7},
        "win_rate": 0.567, "min_confidence": 50,
        "stage0": {"status": "UNVALIDATED"},
    }))
    proposal = TradeRiskProposal(
        asset="SP500", direction="LONG", entry_price=5900, stop_loss=5850,
        take_profit=6000, risk_percent=0.5, confidence_score=10, timeframe="1d",
    )
    result = risk_engine.evaluate_trade(proposal)
    assert result.data.verdict == RiskVerdict.VETO
    assert "20%" in result.data.veto_reason


def test_retired_override_does_not_relax_the_floor_even_with_validated_tag(risk_engine, tmp_path, monkeypatch):
    """docs/UPGRADE_ROADMAP.md P2 item 10: same retired_at tombstone
    e51_signals checks, for the identical reason -- terminal, vetoes
    regardless of a stale VALIDATED stage0 tag."""
    import json
    import project_titan_x.engines.e45_risk.engine as e45_module

    monkeypatch.setattr(e45_module, "_STRATEGY_OVERRIDE_DIR", tmp_path)
    (tmp_path / "MES=F_1d_strategy_override.json").write_text(json.dumps({
        "strategy": "donchian_breakout", "params": {"entry_n": 15, "exit_n": 7},
        "win_rate": 0.567, "min_confidence": 50,
        "stage0": {"status": "VALIDATED"}, "retired_at": "2026-09-13T00:00:00+00:00",
    }))
    proposal = TradeRiskProposal(
        asset="SP500", direction="LONG", entry_price=5900, stop_loss=5850,
        take_profit=6000, risk_percent=0.5, confidence_score=10, timeframe="1d",
    )
    result = risk_engine.evaluate_trade(proposal)
    assert result.data.verdict == RiskVerdict.VETO
    assert "20%" in result.data.veto_reason


# ---- Funded account profiles (FundingPips) ----


def _safe_proposal(risk_percent=0.5, confidence=85) -> TradeRiskProposal:
    return TradeRiskProposal(
        asset="EURUSD", direction="LONG", entry_price=1.10, stop_loss=1.09,
        take_profit=1.12, risk_percent=risk_percent, confidence_score=confidence, timeframe="1d",
    )


def test_fundingpips_profiles_have_expected_real_numbers():
    """Locks in the real, web-verified numbers so a future refactor can't
    silently drift them -- see each profile's source_note for what was
    actually confirmed."""
    p1 = FUNDINGPIPS_PROFILES["fundingpips_2step_standard_phase1"]
    assert (p1.profit_target_pct, p1.max_daily_loss_pct, p1.max_overall_drawdown_pct, p1.drawdown_type) == (8.0, 5.0, 10.0, "static")
    p2 = FUNDINGPIPS_PROFILES["fundingpips_2step_standard_phase2"]
    assert (p2.profit_target_pct, p2.max_daily_loss_pct, p2.max_overall_drawdown_pct) == (5.0, 5.0, 10.0)
    pro = FUNDINGPIPS_PROFILES["fundingpips_2step_pro"]
    assert (pro.profit_target_pct, pro.max_daily_loss_pct, pro.max_overall_drawdown_pct) == (6.0, 3.0, 6.0)


def test_activate_funded_account_rejects_nonpositive_balance(risk_engine):
    result = risk_engine.activate_funded_account(FUNDINGPIPS_PROFILES["fundingpips_2step_standard_phase1"], account_size=0)
    assert not result.success


def test_activate_funded_account_success(risk_engine):
    result = risk_engine.activate_funded_account(FUNDINGPIPS_PROFILES["fundingpips_2step_standard_phase1"], account_size=100_000)
    assert result.success
    assert risk_engine._funded_profile is not None
    assert risk_engine._funded_account_start_balance == 100_000
    assert risk_engine._funded_daily_start_balance == 100_000


def test_funded_account_approves_safe_trade(risk_engine):
    risk_engine.activate_funded_account(FUNDINGPIPS_PROFILES["fundingpips_2step_standard_phase1"], account_size=100_000)
    result = risk_engine.evaluate_trade(_safe_proposal(risk_percent=0.5))
    assert result.data.approved


def test_funded_account_vetoes_when_daily_loss_floor_already_breached(risk_engine):
    profile = FUNDINGPIPS_PROFILES["fundingpips_2step_standard_phase1"]  # 5% daily loss
    risk_engine.activate_funded_account(profile, account_size=100_000)
    risk_engine.update_funded_account_equity(94_000)  # already down 6% today -- past the 5% floor
    result = risk_engine.evaluate_trade(_safe_proposal())
    assert result.data.verdict == RiskVerdict.VETO
    assert "Daily loss red zone" in result.data.veto_reason


def test_funded_account_vetoes_when_overall_drawdown_already_breached(risk_engine):
    profile = FUNDINGPIPS_PROFILES["fundingpips_2step_standard_phase1"]  # 10% static max DD
    risk_engine.activate_funded_account(profile, account_size=100_000)
    # Simulate the SAME day so the daily floor (95k) isn't what trips this --
    # equity below the static overall floor (90k) specifically.
    risk_engine._funded_daily_start_balance = 89_000
    risk_engine._funded_current_equity = 89_000
    result = risk_engine.evaluate_trade(_safe_proposal())
    assert result.data.verdict == RiskVerdict.VETO
    assert "Max drawdown" in result.data.veto_reason


def test_funded_account_static_drawdown_does_not_trail_upward(risk_engine):
    """The defining feature of FundingPips' static drawdown: after equity
    grows well above the start balance, the floor stays at start-balance
    minus max_overall_drawdown_pct -- it must NOT rise to track the new
    high, unlike a trailing-drawdown model."""
    profile = FUNDINGPIPS_PROFILES["fundingpips_2step_standard_phase1"]
    risk_engine.activate_funded_account(profile, account_size=100_000)
    # Equity grew to 150k, then dropped back to 92k -- a TRAILING model
    # would have already blown through its floor (150k*0.9=135k); the
    # real static-model floor is still just 90k (100k*0.9), so 92k is
    # still safe.
    risk_engine._funded_daily_start_balance = 92_000
    risk_engine._funded_current_equity = 92_000
    result = risk_engine.evaluate_trade(_safe_proposal())
    assert result.data.approved


def test_funded_account_vetoes_trade_whose_own_risk_could_breach_daily_floor(risk_engine):
    """The proactive check: even if today's REALIZED loss hasn't hit the
    floor yet, a proposed trade whose own worst case would breach it must
    still be blocked before it's taken -- not approved and only caught
    after the fact."""
    profile = FUNDINGPIPS_PROFILES["fundingpips_2step_standard_phase1"]  # 5% daily loss on 100k = 5k buffer
    risk_engine.activate_funded_account(profile, account_size=100_000)
    risk_engine._funded_daily_start_balance = 100_000
    risk_engine._funded_current_equity = 96_500  # only 1.5k of the 5k daily buffer left
    proposal = _safe_proposal(risk_percent=3.0)  # risks 3% of 96.5k = ~2.9k -- exceeds remaining buffer
    result = risk_engine.evaluate_trade(proposal)
    assert result.data.verdict == RiskVerdict.VETO
    assert "could alone push equity into the red zone" in result.data.veto_reason


def test_funded_account_green_zone_below_half_budget_used_keeps_full_size(risk_engine):
    """< 50% of the daily loss budget used -> no size reduction at all."""
    profile = FUNDINGPIPS_PROFILES["fundingpips_2step_standard_phase1"]  # 5% daily loss on 100k = 5k budget
    risk_engine.activate_funded_account(profile, account_size=100_000)
    risk_engine._funded_daily_start_balance = 100_000
    risk_engine._funded_current_equity = 99_000  # 1k of 5k budget used = 20% -- green
    result = risk_engine.evaluate_trade(_safe_proposal(risk_percent=0.5))
    assert result.data.verdict == RiskVerdict.APPROVED
    assert result.data.adjusted_risk_pct == 0.5


def test_funded_account_yellow_zone_shrinks_size_without_vetoing(risk_engine):
    """60% of the daily loss budget used (between the 50% yellow start and
    the 80% red-zone hard stop) must reduce size, not block the trade."""
    profile = FUNDINGPIPS_PROFILES["fundingpips_2step_standard_phase1"]  # 5% daily loss on 100k = 5k budget
    risk_engine.activate_funded_account(profile, account_size=100_000)
    risk_engine._funded_daily_start_balance = 100_000
    risk_engine._funded_current_equity = 97_000  # 3k of 5k budget used = 60% -- yellow
    result = risk_engine.evaluate_trade(_safe_proposal(risk_percent=0.5))
    assert result.data.verdict == RiskVerdict.WARNING
    assert result.data.approved
    assert 0.0 < result.data.adjusted_risk_pct < 0.5
    assert any("YELLOW zone" in m for m in result.data.messages)


def test_funded_account_red_zone_hard_stop_is_at_80pct_not_100pct(risk_engine):
    """The whole point of the buffer: a hard stop at 80% of budget used,
    not 100% -- equity at exactly 80% used (96k on this 5k budget) must
    already veto, well before the old 100%-used floor (95k) would have."""
    profile = FUNDINGPIPS_PROFILES["fundingpips_2step_standard_phase1"]  # 5% daily loss on 100k = 5k budget
    risk_engine.activate_funded_account(profile, account_size=100_000)
    risk_engine._funded_daily_start_balance = 100_000
    risk_engine._funded_current_equity = 95_500  # 4.5k of 5k used = 90% -- past the 80% red zone, but NOT past the old 100% floor
    result = risk_engine.evaluate_trade(_safe_proposal(risk_percent=0.5))
    assert result.data.verdict == RiskVerdict.VETO
    assert "red zone" in result.data.veto_reason.lower()


def test_max_open_positions_vetoes_at_the_limit(risk_engine):
    state = PortfolioRiskState(open_positions=risk_engine.get_portfolio_state().open_positions)
    from project_titan_x.core.config import get_settings
    settings = get_settings()
    state.open_positions = settings.max_open_positions
    risk_engine.update_portfolio_state(state)
    result = risk_engine.evaluate_trade(_safe_proposal())
    assert result.data.verdict == RiskVerdict.VETO
    assert "Max open positions" in result.data.veto_reason


def test_max_open_positions_approves_one_below_the_limit(risk_engine):
    from project_titan_x.core.config import get_settings
    settings = get_settings()
    state = PortfolioRiskState(open_positions=settings.max_open_positions - 1)
    risk_engine.update_portfolio_state(state)
    result = risk_engine.evaluate_trade(_safe_proposal())
    assert result.data.approved


def test_funded_account_daily_floor_resets_on_new_day(risk_engine, monkeypatch):
    import project_titan_x.engines.e45_risk.engine as e45_module
    from datetime import date, datetime, timezone

    profile = FUNDINGPIPS_PROFILES["fundingpips_2step_standard_phase1"]
    risk_engine.activate_funded_account(profile, account_size=100_000)
    risk_engine._funded_last_reset_date = date(2026, 7, 19)

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 7, 20, 5, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(e45_module, "datetime", _FrozenDatetime)
    risk_engine.update_funded_account_equity(97_000)  # a new day -- 97k becomes the new daily reference
    assert risk_engine._funded_daily_start_balance == 97_000
    assert risk_engine._funded_last_reset_date == date(2026, 7, 20)


def _profile_with_consistency_rule(consistency_rule_pct: float) -> FundedAccountProfile:
    base = FUNDINGPIPS_PROFILES["fundingpips_2step_standard_phase1"]  # 8% profit target
    return FundedAccountProfile(
        name=base.name, profit_target_pct=base.profit_target_pct,
        max_daily_loss_pct=base.max_daily_loss_pct, max_overall_drawdown_pct=base.max_overall_drawdown_pct,
        drawdown_type=base.drawdown_type, min_trading_days=base.min_trading_days,
        consistency_rule_pct=consistency_rule_pct,
    )


def test_consistency_rule_off_by_default_no_warning(risk_engine):
    """The 3 real FUNDINGPIPS_PROFILES all default consistency_rule_pct
    to 0.0 (no source confirmed a specific %) -- must produce zero
    consistency-related messages even on a huge single-day profit."""
    profile = FUNDINGPIPS_PROFILES["fundingpips_2step_standard_phase1"]
    risk_engine.activate_funded_account(profile, account_size=100_000)
    risk_engine._funded_daily_start_balance = 100_000
    risk_engine._funded_current_equity = 106_000  # +6% today, huge relative to the 8% target
    result = risk_engine.evaluate_trade(_safe_proposal())
    assert result.data.approved
    assert not any("Consistency rule" in m for m in result.data.messages)


def test_consistency_rule_warns_on_todays_running_profit_without_vetoing(risk_engine):
    """20% consistency cap on an 8% target = 1.6 percentage points max
    per day. +3% today should warn (real, not fabricated: banked profit
    genuinely exceeds the real threshold) but must NOT block the trade
    -- this is a compliance risk, not a capital-preservation one."""
    profile = _profile_with_consistency_rule(20.0)
    risk_engine.activate_funded_account(profile, account_size=100_000)
    risk_engine._funded_daily_start_balance = 100_000
    risk_engine._funded_current_equity = 103_000  # +3% today, past the 1.6% cap
    result = risk_engine.evaluate_trade(_safe_proposal())
    assert result.data.verdict == RiskVerdict.APPROVED
    assert result.data.approved
    warning = next((m for m in result.data.messages if "Consistency rule" in m), None)
    assert warning is not None
    assert "1.60%" in warning
    assert "today" in warning


def test_consistency_rule_no_warning_when_today_under_threshold(risk_engine):
    profile = _profile_with_consistency_rule(20.0)
    risk_engine.activate_funded_account(profile, account_size=100_000)
    risk_engine._funded_daily_start_balance = 100_000
    risk_engine._funded_current_equity = 100_500  # +0.5% today, well under the 1.6% cap
    result = risk_engine.evaluate_trade(_safe_proposal())
    assert not any("Consistency rule" in m for m in result.data.messages)


def test_consistency_rule_surfaces_a_past_completed_day_violation(risk_engine, monkeypatch):
    """A day that already closed with a rule-violating profit must still
    be surfaced on a LATER day's trade evaluation -- the trader may not
    have been watching when it happened, and the history must survive
    the daily rollover (see update_funded_account_equity's own
    docstring: it archives the completed day BEFORE overwriting)."""
    import project_titan_x.engines.e45_risk.engine as e45_module
    from datetime import date, datetime, timezone

    profile = _profile_with_consistency_rule(20.0)
    risk_engine.activate_funded_account(profile, account_size=100_000)
    risk_engine._funded_last_reset_date = date(2026, 7, 19)
    risk_engine._funded_daily_start_balance = 100_000
    risk_engine._funded_current_equity = 104_000  # day 1 banked +4%, well past the 1.6% cap

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 7, 20, 5, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(e45_module, "datetime", _FrozenDatetime)
    risk_engine.update_funded_account_equity(104_000)  # rolls to day 2, archives day 1's +4%

    assert risk_engine._funded_daily_pnl_history == [(date(2026, 7, 19), pytest.approx(4.0))]

    result = risk_engine.evaluate_trade(_safe_proposal())
    warning = next((m for m in result.data.messages if "Consistency rule" in m), None)
    assert warning is not None
    assert "2026-07-19" in warning
    assert "4.00%" in warning


def test_deactivate_funded_account_clears_daily_pnl_history(risk_engine):
    risk_engine.activate_funded_account(_profile_with_consistency_rule(20.0), account_size=100_000)
    risk_engine._funded_daily_pnl_history = [("2026-07-19", 4.0)]
    risk_engine.deactivate_funded_account()
    assert risk_engine._funded_daily_pnl_history == []


def test_deactivate_funded_account_restores_generic_limits(risk_engine):
    profile = FUNDINGPIPS_PROFILES["fundingpips_2step_standard_phase1"]
    risk_engine.activate_funded_account(profile, account_size=100_000)
    risk_engine._funded_daily_start_balance = 89_000
    risk_engine._funded_current_equity = 89_000  # would veto if still active
    result = risk_engine.deactivate_funded_account()
    assert result.success
    assert risk_engine._funded_profile is None
    # Generic portfolio state (fixture default) is healthy -- should approve now.
    result2 = risk_engine.evaluate_trade(_safe_proposal())
    assert result2.data.approved


def test_funded_account_does_not_weaken_confidence_or_rr_or_stoploss_rules(risk_engine):
    """A funded profile only ADDS checks -- it must never bypass the
    existing confidence/R:R/mandatory-stop-loss rules."""
    risk_engine.activate_funded_account(FUNDINGPIPS_PROFILES["fundingpips_2step_standard_phase1"], account_size=100_000)
    low_confidence = _safe_proposal(confidence=1)
    result = risk_engine.evaluate_trade(low_confidence)
    assert result.data.verdict == RiskVerdict.VETO
    assert "Confidence" in result.data.veto_reason


def test_position_size_never_exceeds_leverage_cap(risk_engine):
    """Regression for the 2026-08-22 leverage gap. Fixed-fractional sizing
    is risk_amount/stop_distance, which is inversely proportional to stop
    distance -- so a tight stop silently inflated NOTIONAL far past the
    account's capital while the user's risk setting still read '1%'.
    Measured before the fix on $10,000 at 1% risk: a 0.5% stop implied 2x
    notional, 0.25% implied 4x, 0.1% implied 10x."""
    capital, entry = 10_000.0, 4679.0
    for stop_pct in (1.0, 0.5, 0.25, 0.1):
        stop = entry * (1 - stop_pct / 100)
        data = risk_engine.calculate_position_size(capital, entry, stop, 1.0).data
        notional = data["position_size"] * entry
        assert notional <= capital * 1.0001, f"{stop_pct}% stop leveraged to ${notional:,.0f}"


def test_leverage_cap_reduces_risk_and_reports_it_honestly(risk_engine):
    """When the cap binds, real risk must come out BELOW the requested
    percent and be reported as such -- never silently above it."""
    capital, entry = 10_000.0, 4679.0
    stop = entry * (1 - 0.1 / 100)          # 0.1% stop: cap definitely binds
    result = risk_engine.calculate_position_size(capital, entry, stop, 1.0)
    data = result.data
    assert data["leverage_capped"] is True
    assert data["requested_risk_percent"] == 1.0
    assert data["risk_percent"] < 1.0
    assert "capped" in result.message


def test_wide_stop_is_untouched_by_the_cap(risk_engine):
    """A normal, wide stop must size exactly as before -- the cap is a
    ceiling, not a change to ordinary fixed-fractional behaviour."""
    capital, entry = 10_000.0, 4679.0
    stop = entry * (1 - 5.0 / 100)
    data = risk_engine.calculate_position_size(capital, entry, stop, 1.0).data
    assert data["leverage_capped"] is False
    assert data["risk_percent"] == pytest.approx(1.0, abs=0.01)
    assert data["position_size"] == pytest.approx(100.0 / (entry * 0.05), rel=1e-6)


@pytest.mark.parametrize("capital,entry,stop,risk,why", [
    (-5000.0, 100.0, 95.0, 1.0, "negative capital"),
    (0.0, 100.0, 95.0, 1.0, "zero capital"),
    (10_000.0, 100.0, 95.0, -1.0, "negative risk"),
    (10_000.0, 100.0, 95.0, 0.0, "zero risk"),
    (10_000.0, 100.0, 95.0, 500.0, "risk above 100%"),
    (10_000.0, 0.0, -5.0, 1.0, "zero entry price"),
])
def test_position_size_rejects_nonsensical_inputs(risk_engine, capital, entry, stop, risk, why):
    """Regression for the 2026-08-23 signed-size gap.

    Negative capital or negative risk previously returned success=True with
    a NEGATIVE position size (capital=-5000 -> size -50). Nothing
    downstream treats size as signed, so that reads as an inverted
    position -- a short where a long was intended -- from input that is
    simply invalid. These must fail loudly instead."""
    result = risk_engine.calculate_position_size(capital, entry, stop, risk)
    assert not result.success, f"{why} should be rejected, not sized"


def test_position_size_is_never_negative_for_any_accepted_input(risk_engine):
    """The invariant behind the above: whatever is accepted must be a real,
    takeable long size."""
    for stop in (95.0, 99.0, 99.9, 105.0):        # includes stop above entry
        result = risk_engine.calculate_position_size(10_000.0, 100.0, stop, 1.0)
        if result.success:
            assert result.data["position_size"] > 0
