"""
Module: engine.py
Description: Engine 12 — Risk Management (CRO absolute authority).
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-06-28
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from project_titan_x.core.config import get_asset, get_settings
from project_titan_x.core.database import RiskEvent, get_db_session
from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus
from project_titan_x.engines.e01_knowledge.engine import KnowledgeEngine

logger = logging.getLogger(__name__)
settings = get_settings()

_STRATEGY_OVERRIDE_DIR = Path(__file__).resolve().parents[2] / "data" / "models" / "e51_signals"


def _load_min_confidence_override(asset: str, timeframe: str) -> Optional[int]:
    """Independent, self-contained lookup of a per-asset confidence floor
    from the SAME on-disk validated strategy-override artifact
    e51_signals._load_strategy_override reads -- deliberately re-read here
    rather than trusted from the proposer, so this engine's veto authority
    is never influenced by what any other engine computed at runtime (see
    Rule 5 / this class's docstring: absolute CRO authority). A threshold
    only exists on disk here after scripts/training/research_signal_
    strategies*.py has actually validated a replacement strategy for this
    EXACT asset+timeframe against E26's full walk-forward bar (>=30 trades,
    in-sample Sharpe>0.5, max drawdown<25%, positive out-of-sample Sharpe)
    -- see data/models/e51_signals/strategy_research_report*.json. Every
    other asset keeps the blanket settings.min_signal_confidence floor
    completely unchanged.

    STAGE 0 AWARE (added 2026-09-13, docs/UPGRADE_ROADMAP.md P0 item 1).
    Real bug found while implementing that item: this function honored
    `min_confidence` from ANY override file that existed on disk,
    regardless of Stage 0 status -- `_promote()` always writes
    `min_confidence`, and Stage 0 tagging is a separate, later pass that
    only ADDS a `stage0` block, never removes `min_confidence`. So this
    engine was relaxing its risk floor for the same 43-of-45 overrides
    e51_signals._load_strategy_override already refuses to drive a live
    signal from -- a real inconsistency between the two engines, not just
    a hypothetical one, now closed by requiring the identical explicit
    `"stage0": {"status": "VALIDATED"}` tag here too.

    RETIRED AWARE (added 2026-09-13, docs/UPGRADE_ROADMAP.md P2 item 10):
    same `retired_at` tombstone e51_signals._load_strategy_override
    checks, for the identical reason -- an explicitly retired override
    must never relax this engine's risk floor, regardless of a stale
    VALIDATED stage0 tag."""
    asset_def = get_asset(asset)
    lookup_symbol = asset_def.yahoo_symbol if asset_def else asset
    path = _STRATEGY_OVERRIDE_DIR / f"{lookup_symbol}_{timeframe}_strategy_override.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        if isinstance(data, dict) and data.get("retired_at"):
            return None
        stage0 = data.get("stage0") if isinstance(data, dict) else None
        if not (isinstance(stage0, dict) and stage0.get("status") == "VALIDATED"):
            return None
        return int(data["min_confidence"]) if "min_confidence" in data else None
    except Exception as e:
        logger.warning("Failed to load min-confidence override from %s: %s", path, e)
        return None


@dataclass
class FundedAccountProfile:
    """A funded/prop-firm evaluation account's real risk rules -- when
    active, these are AUTHORITATIVE for daily-loss/drawdown (replace,
    don't blend with, settings.max_daily_loss_pct/max_drawdown_pct),
    since those generic defaults are calibrated for this platform's own
    small-capital mode, not any specific prop firm's actual binding
    constraint. Every OTHER rule in evaluate_trade (confidence floor,
    R:R, max risk per trade, portfolio heat, risk of ruin, mandatory
    stop-loss) stays fully in effect regardless -- a funded profile only
    ever ADDS a stricter check, never loosens anything."""

    name: str
    profit_target_pct: float
    max_daily_loss_pct: float
    max_overall_drawdown_pct: float
    # "static": the drawdown floor is fixed at account-start balance minus
    # max_overall_drawdown_pct and never rises, even as equity grows above
    # the start balance. "trailing": the floor rises with new equity highs.
    # FundingPips' own 2-Step models use static -- verified directly
    # against fundingpips.com/trading-objectives (blocked by bot
    # protection when fetched directly) cross-referenced with
    # proptradingvibes.com/blog/fundingpips-rules, 2026-07-20.
    drawdown_type: str
    min_trading_days: int
    source_note: str = ""
    # Added 2026-08-21: many prop firms fail an evaluation if any single
    # day's profit exceeds this % of the total profit_target_pct, even
    # when every daily-loss/drawdown rule is otherwise respected (e.g. a
    # 20% consistency cap on an 8% target means no single day may
    # contribute more than 1.6 percentage points of that 8%). 0.0 (the
    # default, matching the 3 real profiles below -- none of their
    # source_notes confirm a specific consistency-rule percentage, so
    # this is left off rather than guessed) means the check is skipped
    # entirely, never a fabricated 0% cap.
    consistency_rule_pct: float = 0.0


# Funded-account daily-loss ZONE thresholds (added 2026-09-13, closes a real
# Phase 8 gap: docs/UPGRADE_BRIEF.md explicitly asks for "a green/yellow/red
# zone system that reduces size as daily losses accumulate, with a hard stop
# at 80% of the daily limit (buffer for slippage)" -- before this, the daily-
# loss check in _check_funded_account_limits was BINARY: full requested size
# right up until the exact 100%-of-budget floor, then an outright veto. That
# is the opposite of what a slippage buffer is for -- the whole point is to
# stop BEFORE the true floor, not exactly at it.
#
# GREEN (< 50% of today's loss budget used): full requested size.
# YELLOW (50-80%): size scales down LINEARLY from 1.0x at 50% to
# FUNDED_ZONE_YELLOW_FLOOR_MULT at just under 80% -- the same "warn and
# shrink, don't block" shape Rule 8 (portfolio heat) already uses below.
# RED (>= 80%): hard stop. The remaining 20% of budget is the slippage/
# execution-gap buffer the brief asks for, never spent.
#
# 50% is this engine's own documented convention (not sourced from any
# specific prop firm, same "static, documented, not fabricated precision"
# honesty as e13_derivatives' skew thresholds) -- the brief specifies the
# 80% hard stop exactly; where the yellow zone should START is a reasonable
# choice, not a measured one.
FUNDED_ZONE_YELLOW_START_PCT = 50.0
FUNDED_ZONE_RED_PCT = 80.0
FUNDED_ZONE_YELLOW_FLOOR_MULT = 0.2


# Generic (non-funded) OVERALL EQUITY drawdown zone thresholds, added
# 2026-09-14. A real, distinct gap from the funded-account zones above --
# those close docs/UPGRADE_BRIEF.md's daily-loss zone request specifically;
# this closes the SEPARATE "trailing equity drawdown... a trailing
# high-water-mark model and the green/yellow/red size-reduction zones"
# item the brief also names (Phase 8), which was still genuinely open:
# confirmed by grep across the whole codebase that nothing ever actually
# CALLS update_portfolio_state() with a real current_drawdown_pct in
# production -- the field existed, but nothing tracked a peak or computed
# drawdown FROM one, so Rule 6's hard veto below trusted a number no real
# caller ever correctly supplied. See update_portfolio_state's own
# docstring for the fix: E45 now tracks peak equity itself and computes
# current_drawdown_pct authoritatively, rather than trusting the caller.
#
# Same "warn and shrink, don't block" shape as the funded zones and
# Rule 8 (portfolio heat): GREEN (< 50% of settings.max_drawdown_pct)
# full size; YELLOW (50-100%) linear scale-down to
# GENERIC_ZONE_YELLOW_FLOOR_MULT; RED (>= 100%, i.e. settings.
# max_drawdown_pct itself) is Rule 6's existing hard veto, unchanged --
# no new red threshold needed since that veto already IS the red line.
# 50%/floor-mult reuse the funded zones' own documented-convention
# values (same honesty: a reasonable choice, not a measured one).
GENERIC_ZONE_YELLOW_START_PCT = 50.0
GENERIC_ZONE_YELLOW_FLOOR_MULT = 0.2


# Real, verified FundingPips 2-Step rules (not guessed -- see each
# profile's source_note for exactly what was confirmed vs. inferred).
FUNDINGPIPS_PROFILES: dict[str, FundedAccountProfile] = {
    "fundingpips_2step_standard_phase1": FundedAccountProfile(
        name="FundingPips 2-Step Standard -- Phase 1 (Student)",
        profit_target_pct=8.0, max_daily_loss_pct=5.0, max_overall_drawdown_pct=10.0,
        drawdown_type="static", min_trading_days=3,
        source_note=(
            "Verified 2026-07-20 via WebSearch + WebFetch(proptradingvibes.com/blog/fundingpips-rules) "
            "-- fundingpips.com's own trading-objectives page returned HTTP 403 (bot protection) when "
            "fetched directly, so this is cross-referenced from a secondary source, not the first-party "
            "page itself. Re-verify against fundingpips.com/trading-objectives before relying on this for "
            "a real account if their rules may have changed."
        ),
    ),
    "fundingpips_2step_standard_phase2": FundedAccountProfile(
        name="FundingPips 2-Step Standard -- Phase 2 (Practitioner)",
        profit_target_pct=5.0, max_daily_loss_pct=5.0, max_overall_drawdown_pct=10.0,
        drawdown_type="static", min_trading_days=3,
        source_note=(
            "Verified 2026-07-20, same sourcing caveat as Phase 1. One unconfirmed nuance: one source "
            "described Phase 2's daily-loss basis as '5% of the higher of daily starting balance or "
            "current equity' (vs. a flat balance-based 5% elsewhere) -- this engine uses the MORE "
            "CONSERVATIVE interpretation (whichever basis is higher, since that produces the tighter/"
            "earlier-triggering floor) rather than assume which is exactly correct."
        ),
    ),
    "fundingpips_2step_pro": FundedAccountProfile(
        name="FundingPips 2-Step Pro",
        profit_target_pct=6.0, max_daily_loss_pct=3.0, max_overall_drawdown_pct=6.0,
        drawdown_type="static", min_trading_days=1,
        source_note=(
            "Verified 2026-07-20, same sourcing caveat as Standard. The source only gave COMBINED "
            "numbers for the Pro model (not broken out per-phase like Standard) -- applied to both "
            "phases identically here; re-verify per-phase if FundingPips' Pro model actually differs "
            "between Phase 1 and Phase 2."
        ),
    ),
}


class RiskVerdict(str, Enum):
    """Risk check verdict."""

    APPROVED = "approved"
    REJECTED = "rejected"
    VETO = "veto"
    WARNING = "warning"


@dataclass
class PortfolioRiskState:
    """Current portfolio risk snapshot.

    current_drawdown_pct: a caller MAY set this, but RiskManagementEngine.
    update_portfolio_state() OVERWRITES it with its own trailing
    high-water-mark computation before storing the state (see that
    method's own docstring) -- total_capital is the only input that
    actually needs to be honest; the engine derives drawdown-from-peak
    itself rather than trusting a value a caller might compute
    inconsistently or not at all. Kept as a settable field (not removed)
    so an already-correct caller's value is harmless, and so
    dataclass-construction call sites elsewhere aren't broken."""

    total_capital: float = 10_000.0
    daily_pnl_pct: float = 0.0
    weekly_pnl_pct: float = 0.0
    monthly_pnl_pct: float = 0.0
    current_drawdown_pct: float = 0.0
    portfolio_heat_pct: float = 0.0
    open_positions: int = 0
    risk_of_ruin_pct: float = 0.0
    correlation_max: float = 0.0


@dataclass
class TradeRiskProposal:
    """Proposed trade for risk evaluation."""

    asset: str
    direction: str
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_percent: float
    confidence_score: int
    regime: str = ""
    strategy_id: Optional[int] = None
    timeframe: str = "1d"


@dataclass
class RiskCheckResult:
    """Result of a risk check."""

    verdict: RiskVerdict
    approved: bool
    messages: list[str] = field(default_factory=list)
    veto_reason: Optional[str] = None
    adjusted_risk_pct: Optional[float] = None
    knowledge_context: Optional[dict] = None


class RiskManagementEngine(BaseEngine):
    """
    Risk Management Engine — highest authority after human trader.

    Enforces: daily/weekly/monthly loss limits, drawdown limits,
    portfolio heat, risk of ruin, correlation limits, min R:R.
 
    The CRO has absolute VETO authority. No trade executes against its rules.
    """

    engine_id = "e45_risk"
    engine_name = "Risk Management Engine (CRO)"
    version = "1.0.0"

    def __init__(self, knowledge_engine: Optional[KnowledgeEngine] = None) -> None:
        super().__init__()
        self._portfolio_state = PortfolioRiskState(total_capital=settings.starting_capital)
        self._trading_halted = False
        # Optional and None by default: without it, evaluate_trade()
        # behaves exactly as before (no knowledge_context). Purely
        # informational when present -- NEVER read by any risk rule below,
        # so it cannot influence approved/verdict/adjusted_risk_pct. This
        # engine's entire purpose is being a deterministic, auditable veto
        # gate; retrieved text is attached for a human's benefit only.
        self._knowledge_engine = knowledge_engine
        # Funded-account state -- None until activate_funded_account() is
        # called with real account details (never guessed/defaulted to a
        # specific account size). See FundedAccountProfile's docstring for
        # why this is authoritative over settings.max_daily_loss_pct/
        # max_drawdown_pct rather than blended with them.
        self._funded_profile: Optional[FundedAccountProfile] = None
        self._funded_account_start_balance: Optional[float] = None
        self._funded_daily_start_balance: Optional[float] = None
        self._funded_current_equity: Optional[float] = None
        self._funded_last_reset_date = None
        # Added 2026-08-21 for real consistency-rule enforcement (see
        # FundedAccountProfile.consistency_rule_pct). Unlike
        # _funded_daily_start_balance (overwritten every new day, only
        # ever knows TODAY), this keeps one (date, realized_pnl_pct)
        # entry per COMPLETED day, appended in update_funded_account_equity
        # right before that overwrite happens -- otherwise a prior day's
        # result is unrecoverably lost the moment the next day starts,
        # and the consistency check could only ever see the single day
        # currently in progress.
        self._funded_daily_pnl_history: list[tuple] = []
        # Added 2026-08-02: consecutive-loss circuit breaker state. A
        # standard discretionary-risk practice (halt after N losses in a
        # row, independent of cumulative %-loss limits) that this engine
        # had no way to track before, since evaluate_trade only ever saw
        # PROPOSALS, never outcomes -- see record_trade_result().
        self._consecutive_losses = 0
        # Added 2026-09-14: trailing high-water-mark for the generic
        # (non-funded) overall-drawdown zone system -- see
        # GENERIC_ZONE_YELLOW_START_PCT's own docstring for why this
        # closes a real, previously-open gap. None until the first real
        # total_capital comes through update_portfolio_state (never
        # guessed/defaulted to a number that might not match the
        # caller's actual starting equity).
        self._peak_equity: Optional[float] = None

    def initialize(self) -> EngineResult:
        """Initialize risk engine with configured limits."""
        self._set_status(EngineStatus.IDLE)
        return EngineResult(
            success=True,
            message="Risk Management Engine initialized",
            metadata={
                "max_daily_loss": settings.max_daily_loss_pct,
                "max_drawdown": settings.max_drawdown_pct,
                "max_portfolio_heat": settings.max_portfolio_heat_pct,
            },
        )

    def health_check(self) -> EngineResult:
        """Health check."""
        return EngineResult(
            success=not self._trading_halted,
            message="Trading halted" if self._trading_halted else "Healthy",
        )

    def update_portfolio_state(self, state: PortfolioRiskState) -> None:
        """Update current portfolio risk state.

        Real gap found and fixed 2026-09-14 (see GENERIC_ZONE_YELLOW_
        START_PCT's own docstring): grep across the whole codebase found
        no production caller that ever set state.current_drawdown_pct to
        a real, trailing-peak-based number -- Rule 6's hard veto in
        evaluate_trade was trusting a field nothing correctly populated.
        This method now tracks its OWN peak equity (a monotonic running
        max of every total_capital it's ever seen) and computes
        current_drawdown_pct authoritatively from that peak, overwriting
        whatever the caller passed -- total_capital is the only number a
        caller needs to report honestly. A fresh equity high resets
        drawdown to exactly 0%, same "peak resets on every new high"
        definition every real drawdown metric uses (e.g. E35's own
        max_drawdown_pct, engines/e35_performance_analytics/engine.py)."""
        self._peak_equity = max(self._peak_equity or state.total_capital, state.total_capital)
        state.current_drawdown_pct = (
            max(0.0, (self._peak_equity - state.total_capital) / self._peak_equity * 100.0)
            if self._peak_equity > 0 else 0.0
        )
        self._portfolio_state = state
        self._check_portfolio_limits()

    def get_portfolio_state(self) -> PortfolioRiskState:
        """Read-only access to the current portfolio risk snapshot -- for
        e46_chief_risk_officer's own higher-altitude oversight read.
        Deliberately a plain getter, not a copy/deepcopy: nothing outside
        this class should ever WRITE through it (only update_portfolio_state
        above does that), and Python dataclass fields are all plain
        floats/ints here, so there's no mutable-shared-state risk."""
        return self._portfolio_state

    def activate_funded_account(
        self, profile: FundedAccountProfile, account_size: float, current_equity: Optional[float] = None
    ) -> EngineResult:
        """Switch this CRO instance into funded-account mode: from this
        call on, evaluate_trade's daily-loss/drawdown checks use `profile`
        and REAL account numbers instead of settings.max_daily_loss_pct/
        max_drawdown_pct. `account_size` must be the real, current account
        balance -- never inferred or defaulted."""
        if account_size <= 0:
            return EngineResult(success=False, message="account_size must be a real, positive balance")
        self._funded_profile = profile
        self._funded_account_start_balance = account_size
        equity = current_equity if current_equity is not None else account_size
        self._funded_current_equity = equity
        self._funded_daily_start_balance = equity
        self._funded_last_reset_date = datetime.now(timezone.utc).date()
        self._log_risk_event(
            "funded_account_activated", "info",
            f"Funded account activated: {profile.name}, size={account_size}",
            {"profile": profile.name, "account_size": account_size},
        )
        return EngineResult(
            success=True,
            message=f"Funded account active: {profile.name} (size={account_size:.2f}, daily loss floor / max DD now enforced from real account rules)",
            metadata={"profile": profile.name, "source_note": profile.source_note},
        )

    def deactivate_funded_account(self) -> EngineResult:
        """Return to the platform's generic settings-based risk limits."""
        self._funded_profile = None
        self._funded_account_start_balance = None
        self._funded_daily_start_balance = None
        self._funded_current_equity = None
        self._funded_last_reset_date = None
        self._funded_daily_pnl_history = []
        return EngineResult(success=True, message="Funded account mode deactivated -- generic settings-based limits apply again")

    def update_funded_account_equity(self, current_equity: float) -> EngineResult:
        """Mark-to-market update -- call this whenever the real account's
        equity changes (a trade closes, a new day's balance is confirmed).
        Automatically rolls the daily-loss reference balance over at the
        first update of a new UTC calendar day (same "new day" convention
        prop firms use for their own daily reset). Also archives the
        just-completed day's realized P&L into _funded_daily_pnl_history
        (see that field's own docstring) -- must happen BEFORE the
        daily_start_balance overwrite below, or the completed day's
        result is lost."""
        if self._funded_profile is None:
            return EngineResult(success=False, message="No funded account is active")
        today = datetime.now(timezone.utc).date()
        if self._funded_last_reset_date != today:
            if self._funded_last_reset_date is not None and self._funded_account_start_balance:
                completed_day_pnl_pct = (
                    (self._funded_current_equity - self._funded_daily_start_balance)
                    / self._funded_account_start_balance * 100
                )
                self._funded_daily_pnl_history.append((self._funded_last_reset_date, completed_day_pnl_pct))
            self._funded_daily_start_balance = current_equity
            self._funded_last_reset_date = today
        self._funded_current_equity = current_equity
        return EngineResult(success=True, message=f"Funded account equity updated: {current_equity:.2f}")

    def _check_funded_account_limits(self, proposal: TradeRiskProposal) -> Optional[EngineResult]:
        """Real-money-account-aware checks, run in ADDITION to (before)
        every other rule in evaluate_trade when a funded profile is
        active. All checks are against REAL tracked equity, never
        estimated: (1) has today's loss already breached the RED-ZONE
        floor (80% of the daily budget, not 100% -- see
        FUNDED_ZONE_RED_PCT's own docstring for why the buffer exists),
        (2) has overall equity already breached the drawdown floor, (3)
        -- the proactive one the generic percentage-based rules don't do
        -- would even a FULL loss on THIS proposed trade alone push equity
        into the red zone. Returns a veto EngineResult, or None if the
        funded-account checks all pass (caller continues to the rest of
        evaluate_trade, including the zone-based size reduction in
        _funded_zone_risk_multiplier below)."""
        profile = self._funded_profile
        equity = self._funded_current_equity if self._funded_current_equity is not None else self._funded_account_start_balance
        daily_basis = max(self._funded_daily_start_balance, equity)
        daily_loss_budget = daily_basis * (profile.max_daily_loss_pct / 100)
        red_zone_floor = daily_basis - daily_loss_budget * (FUNDED_ZONE_RED_PCT / 100)
        if equity <= red_zone_floor:
            return self._veto(
                f"[{profile.name}] Daily loss red zone already reached ({FUNDED_ZONE_RED_PCT:g}% of budget): "
                f"equity {equity:.2f} <= floor {red_zone_floor:.2f}"
            )

        if profile.drawdown_type == "static":
            overall_floor = self._funded_account_start_balance * (1 - profile.max_overall_drawdown_pct / 100)
        else:
            overall_floor = max(self._funded_account_start_balance, equity) * (1 - profile.max_overall_drawdown_pct / 100)
        if equity <= overall_floor:
            return self._veto(
                f"[{profile.name}] Max drawdown already breached: equity {equity:.2f} <= floor {overall_floor:.2f}"
            )

        proposed_loss_amount = equity * (proposal.risk_percent / 100)
        remaining_red_zone_buffer = equity - red_zone_floor
        if proposed_loss_amount >= remaining_red_zone_buffer:
            return self._veto(
                f"[{profile.name}] This trade's own risk ({proposal.risk_percent}% = {proposed_loss_amount:.2f}) "
                f"could alone push equity into the red zone -- only {remaining_red_zone_buffer:.2f} of buffer "
                f"remains before the {FUNDED_ZONE_RED_PCT:g}% floor"
            )
        return None

    def _funded_zone_risk_multiplier(self) -> tuple[str, float]:
        """Green/yellow/red daily-loss zone (see FUNDED_ZONE_* constants'
        own docstring). Called AFTER _check_funded_account_limits has
        already vetoed a red-zone breach outright -- this only ever
        handles green (full size) and yellow (linearly shrinking size),
        the same "warn and shrink, don't block" shape Rule 8 (portfolio
        heat) below already uses. Returns (zone_name, multiplier) --
        multiplier is always 1.0 outside a funded profile's control (the
        caller only invokes this when a funded profile IS active)."""
        profile = self._funded_profile
        equity = self._funded_current_equity if self._funded_current_equity is not None else self._funded_account_start_balance
        daily_basis = max(self._funded_daily_start_balance, equity)
        daily_loss_budget = daily_basis * (profile.max_daily_loss_pct / 100)
        if daily_loss_budget <= 0:
            return "green", 1.0
        loss_so_far = max(0.0, daily_basis - equity)
        pct_of_budget_used = loss_so_far / daily_loss_budget * 100

        if pct_of_budget_used < FUNDED_ZONE_YELLOW_START_PCT:
            return "green", 1.0
        if pct_of_budget_used >= FUNDED_ZONE_RED_PCT:
            # Already vetoed by _check_funded_account_limits before this is
            # ever called -- defensive floor only, never expected live.
            return "red", FUNDED_ZONE_YELLOW_FLOOR_MULT
        span = FUNDED_ZONE_RED_PCT - FUNDED_ZONE_YELLOW_START_PCT
        progress = (pct_of_budget_used - FUNDED_ZONE_YELLOW_START_PCT) / span
        multiplier = 1.0 - progress * (1.0 - FUNDED_ZONE_YELLOW_FLOOR_MULT)
        return "yellow", multiplier

    def _generic_zone_risk_multiplier(self) -> tuple[str, float]:
        """Green/yellow/red OVERALL EQUITY drawdown zone for the generic
        (non-funded) path -- see GENERIC_ZONE_YELLOW_START_PCT's own
        docstring. Mirrors _funded_zone_risk_multiplier's shape exactly,
        just against settings.max_drawdown_pct (the red/veto line, via
        Rule 6's existing hard stop) instead of a funded profile's daily
        budget. current_drawdown_pct here is always the engine's own
        peak-equity-derived figure (see update_portfolio_state), never a
        caller-supplied one. Called only when NOT in funded-account mode
        -- the funded path has its own, separate zone system above."""
        red_pct = settings.max_drawdown_pct
        if red_pct <= 0:
            return "green", 1.0
        current = self._portfolio_state.current_drawdown_pct
        if current < GENERIC_ZONE_YELLOW_START_PCT / 100 * red_pct:
            return "green", 1.0
        if current >= red_pct:
            # Rule 6's hard veto already fires before this is ever reached
            # live -- defensive floor only, same convention as the funded
            # zone's own "red" branch above.
            return "red", GENERIC_ZONE_YELLOW_FLOOR_MULT
        yellow_start = GENERIC_ZONE_YELLOW_START_PCT / 100 * red_pct
        span = red_pct - yellow_start
        progress = (current - yellow_start) / span
        multiplier = 1.0 - progress * (1.0 - GENERIC_ZONE_YELLOW_FLOOR_MULT)
        return "yellow", multiplier

    def _check_consistency_rule(self) -> Optional[str]:
        """Real (not the dashboard planner's informational-only version)
        consistency-rule check, added 2026-08-21. Deliberately a WARNING
        (returns a message appended to evaluate_trade's `messages`, never
        a veto) rather than blocking the trade -- unlike the daily-loss/
        drawdown floors above, this isn't a capital-preservation risk (a
        big winning day doesn't threaten the account), it's an
        evaluation-compliance risk, and the profit could still move
        before the day closes. Checks BOTH today's running profit
        so-far AND every already-completed day in
        _funded_daily_pnl_history -- a past violation is just as worth
        surfacing as today's in-progress one, and the caller currently
        proposing a new trade may not know about either."""
        profile = self._funded_profile
        if not profile.consistency_rule_pct or profile.profit_target_pct <= 0:
            return None
        max_single_day_pct = profile.profit_target_pct * (profile.consistency_rule_pct / 100)

        violations: list[str] = []
        for day, pnl_pct in self._funded_daily_pnl_history:
            if pnl_pct > max_single_day_pct:
                violations.append(f"{day.isoformat()} banked {pnl_pct:.2f}%")

        if self._funded_current_equity is not None and self._funded_daily_start_balance is not None and self._funded_account_start_balance:
            today_pnl_pct = (self._funded_current_equity - self._funded_daily_start_balance) / self._funded_account_start_balance * 100
            if today_pnl_pct > max_single_day_pct:
                violations.append(f"today (so far) is at {today_pnl_pct:.2f}%")

        if not violations:
            return None
        return (
            f"[{profile.name}] Consistency rule: no single day should exceed {max_single_day_pct:.2f}% "
            f"({profile.consistency_rule_pct:.0f}% of the {profile.profit_target_pct:.1f}% profit target) -- "
            f"{'; '.join(violations)}. This can fail an otherwise-passing evaluation even with every other "
            f"rule respected."
        )

    def evaluate_trade(self, proposal: TradeRiskProposal) -> EngineResult:
        """
        Evaluate a trade proposal against all risk rules.

        Args:
            proposal: Trade risk proposal.

        Returns:
            EngineResult with RiskCheckResult in data field.
        """
        try:
            self._set_status(EngineStatus.RUNNING)
            messages: list[str] = []
            verdict = RiskVerdict.APPROVED
            veto_reason: Optional[str] = None
            adjusted_risk = proposal.risk_percent

            if self._trading_halted:
                return self._veto("Trading is halted by CRO")

            # Rule 0: Funded-account real-money checks (see
            # FundedAccountProfile's docstring) -- authoritative over the
            # generic percentage-based daily-loss/drawdown rules below
            # when active, so those two are skipped in favor of this,
            # never blended with it.
            if self._funded_profile is not None:
                funded_veto = self._check_funded_account_limits(proposal)
                if funded_veto is not None:
                    return funded_veto
                zone, zone_mult = self._funded_zone_risk_multiplier()
                if zone_mult < 1.0:
                    pre_zone_risk = adjusted_risk
                    adjusted_risk = max(0.1, adjusted_risk * zone_mult)
                    verdict = RiskVerdict.WARNING
                    messages.append(
                        f"[{self._funded_profile.name}] {zone.upper()} zone (daily loss budget "
                        f"partially used): size reduced {pre_zone_risk:.2f}% -> {adjusted_risk:.2f}%"
                    )
                consistency_warning = self._check_consistency_rule()
                if consistency_warning is not None:
                    messages.append(consistency_warning)

            # Rule 1: Confidence threshold -- an asset with its own
            # validated structural strategy override gets its own,
            # independently-looked-up floor here (see
            # _load_min_confidence_override); every other asset keeps the
            # blanket floor below unchanged.
            min_confidence = _load_min_confidence_override(proposal.asset, proposal.timeframe)
            if min_confidence is None:
                min_confidence = settings.min_signal_confidence
            if proposal.confidence_score < min_confidence:
                return self._veto(
                    f"Confidence {proposal.confidence_score}% below minimum "
                    f"{min_confidence}%"
                )

            # Rule 1b (added 2026-09-11): stop-loss/take-profit must sit on
            # the geometrically correct side of entry for the stated
            # direction. Found via hypothesis property-based testing
            # (REPO_REFERENCE.md Tier 4) against the invariant "a stop
            # always sits on the correct side of entry" -- Rule 2 below
            # computes risk/reward via abs(), which is direction-blind by
            # construction, and Rule 10's stop-loss check only rejects
            # stop_loss<=0 or stop_loss==entry_price, never checking which
            # SIDE it's on. Before this fix, a LONG proposal with
            # stop_loss ABOVE entry and take_profit BELOW entry (a fully
            # inverted, backwards trade) was silently APPROVED with a
            # "clean" 2.00 R:R message -- verified live, not hypothetical.
            # `proposal.direction` was already being read (for logging and
            # the knowledge-context query only, see line ~582/979) but
            # never actually checked against these two prices anywhere.
            if proposal.direction == "LONG":
                if proposal.stop_loss >= proposal.entry_price:
                    return self._veto(
                        f"LONG stop_loss {proposal.stop_loss} must be below entry "
                        f"{proposal.entry_price} -- stop is on the wrong side"
                    )
                if proposal.take_profit <= proposal.entry_price:
                    return self._veto(
                        f"LONG take_profit {proposal.take_profit} must be above entry "
                        f"{proposal.entry_price} -- target is on the wrong side"
                    )
            elif proposal.direction == "SHORT":
                if proposal.stop_loss <= proposal.entry_price:
                    return self._veto(
                        f"SHORT stop_loss {proposal.stop_loss} must be above entry "
                        f"{proposal.entry_price} -- stop is on the wrong side"
                    )
                if proposal.take_profit >= proposal.entry_price:
                    return self._veto(
                        f"SHORT take_profit {proposal.take_profit} must be below entry "
                        f"{proposal.entry_price} -- target is on the wrong side"
                    )

            # Rule 2: Risk:Reward ratio
            risk_amount = abs(proposal.entry_price - proposal.stop_loss)
            reward_amount = abs(proposal.take_profit - proposal.entry_price)
            if risk_amount > 0:
                rr_ratio = reward_amount / risk_amount
                # e51_signals constructs take_profit_1 as EXACTLY
                # stop_distance*2.0 from entry (a clean 2:1 by design), but
                # risk_amount/reward_amount here are RECOMPUTED via
                # subtraction from entry_price/stop_loss/take_profit --
                # floating-point subtraction of two large near-equal
                # doubles (e.g. entry_price=4296.5123..., take_profit=
                # entry+2*stop_distance) doesn't always perfectly recover
                # the original multiple. Verified live: ~25% of realistic
                # price/ATR combinations land the recomputed ratio at
                # 1.9999999999998-ish instead of exactly 2.0, incorrectly
                # tripping a strict `<` comparison against a threshold
                # that's ALSO exactly 2.0 -- a real bug (not a hypothetical
                # one) that was silently vetoing roughly a quarter of
                # otherwise-valid signals system-wide. A tolerance far
                # larger than the observed error (~1e-13) but far smaller
                # than any real R:R difference an trader would care about
                # absorbs the float noise without weakening the actual
                # risk rule.
                if rr_ratio < settings.min_risk_reward_ratio - 1e-9:
                    return self._veto(
                        f"R:R ratio {rr_ratio:.2f} below minimum "
                        f"{settings.min_risk_reward_ratio}"
                    )
                messages.append(f"R:R ratio {rr_ratio:.2f} — acceptable")

            # Rule 3: Daily loss limit -- skipped when a funded profile is
            # active (Rule 0 above already checked the real-account
            # equivalent); this generic percentage-based state isn't fed
            # real funded-account numbers, so checking both would be
            # meaningless, not extra-safe.
            if self._funded_profile is None and self._portfolio_state.daily_pnl_pct <= -settings.max_daily_loss_pct:
                return self._veto(
                    f"Daily loss limit breached: {self._portfolio_state.daily_pnl_pct:.2f}%"
                )

            # Rule 4: Weekly loss limit
            if self._portfolio_state.weekly_pnl_pct <= -settings.max_weekly_loss_pct:
                return self._veto(
                    f"Weekly loss limit breached: {self._portfolio_state.weekly_pnl_pct:.2f}%"
                )

            # Rule 5: Monthly loss limit
            if self._portfolio_state.monthly_pnl_pct <= -settings.max_monthly_loss_pct:
                return self._veto(
                    f"Monthly loss limit breached: {self._portfolio_state.monthly_pnl_pct:.2f}%"
                )

            # Rule 6: Maximum drawdown -- skipped when a funded profile is
            # active, same reasoning as Rule 3 above (the funded path has
            # its own equivalent hard stop in _check_funded_account_limits).
            if self._funded_profile is None:
                if self._portfolio_state.current_drawdown_pct >= settings.max_drawdown_pct:
                    return self._veto(
                        f"Max drawdown breached: {self._portfolio_state.current_drawdown_pct:.2f}%"
                    )
                # Rule 6b (added 2026-09-14): green/yellow zone size
                # reduction BEFORE the hard veto above -- see
                # GENERIC_ZONE_YELLOW_START_PCT's own docstring for why
                # this closes a real, previously-open gap (the brief's
                # trailing-drawdown zone request, distinct from the
                # funded-account daily-loss zones above). Same "warn and
                # shrink, don't block" application as the funded zone's
                # own use above.
                zone, zone_mult = self._generic_zone_risk_multiplier()
                if zone_mult < 1.0:
                    pre_zone_risk = adjusted_risk
                    adjusted_risk = max(0.1, adjusted_risk * zone_mult)
                    verdict = RiskVerdict.WARNING
                    messages.append(
                        f"{zone.upper()} zone (overall drawdown {self._portfolio_state.current_drawdown_pct:.2f}% "
                        f"of {settings.max_drawdown_pct:g}% limit): size reduced {pre_zone_risk:.2f}% -> {adjusted_risk:.2f}%"
                    )

            # Rule 7: Max risk per trade (small capital protection)
            if proposal.risk_percent > settings.max_risk_per_trade_pct:
                return self._veto(
                    f"Risk {proposal.risk_percent}% exceeds max "
                    f"{settings.max_risk_per_trade_pct}% per trade"
                )

            # Rule 8: Portfolio heat
            new_heat = self._portfolio_state.portfolio_heat_pct + proposal.risk_percent
            if new_heat > settings.max_portfolio_heat_pct:
                excess = new_heat - settings.max_portfolio_heat_pct
                adjusted_risk = max(0.1, proposal.risk_percent - excess)
                verdict = RiskVerdict.WARNING
                messages.append(
                    f"Portfolio heat adjusted: {proposal.risk_percent}% → {adjusted_risk:.2f}%"
                )

            # Rule 8b (added 2026-09-13, same insertion convention as Rule
            # 1b): max open positions. docs/UPGRADE_BRIEF.md Phase 8 asks
            # for this as its own limit -- PortfolioRiskState.open_positions
            # already existed and was read by E46's own narrative text, but
            # nothing in evaluate_trade ever checked it against a limit
            # (confirmed via grep before adding settings.max_open_positions
            # above). Independent of portfolio_heat_pct: heat measures
            # cumulative RISK PERCENT across positions, which a few
            # tightly-risked positions can keep low even at a large position
            # COUNT -- operational/attention risk (more open trades than a
            # single trader can realistically monitor) is a different axis.
            if self._portfolio_state.open_positions >= settings.max_open_positions:
                return self._veto(
                    f"Max open positions reached: {self._portfolio_state.open_positions} "
                    f">= limit {settings.max_open_positions}"
                )

            # Rule 9: Risk of ruin
            if self._portfolio_state.risk_of_ruin_pct > settings.max_risk_of_ruin_pct:
                return self._veto(
                    f"Risk of ruin {self._portfolio_state.risk_of_ruin_pct:.2f}% "
                    f"exceeds limit {settings.max_risk_of_ruin_pct}%"
                )

            # Rule 10: Stop loss must exist
            if proposal.stop_loss <= 0 or proposal.stop_loss == proposal.entry_price:
                return self._veto("Stop loss is mandatory — no trade without invalidation level")

            # Rule 11 (added 2026-08-02): portfolio correlation exposure.
            # PortfolioRiskState.correlation_max existed as a field long
            # before this rule did -- confirmed via a full-codebase grep
            # that nothing ever read it. High correlation across open
            # positions means portfolio_heat_pct's implicit diversification
            # assumption is false (several "different" positions moving as
            # one is effectively a single oversized position).
            if self._portfolio_state.correlation_max > settings.max_correlation_exposure:
                return self._veto(
                    f"Portfolio correlation {self._portfolio_state.correlation_max:.2f} exceeds "
                    f"max {settings.max_correlation_exposure:.2f} — open positions are too "
                    "correlated to treat as diversified risk"
                )

            # Rule 12 (added 2026-08-02): consecutive-loss circuit breaker.
            # A standard discretionary-risk practice independent of the
            # cumulative %-loss rules above -- N losses in a row can still
            # be well within daily/weekly loss limits while being a real
            # signal that current conditions or the active strategy aren't
            # working, worth a forced pause regardless of cumulative P&L.
            if self._consecutive_losses >= settings.max_consecutive_losses:
                return self._veto(
                    f"{self._consecutive_losses} consecutive losses reached the circuit-breaker "
                    f"limit of {settings.max_consecutive_losses} — pausing for human review "
                    "regardless of cumulative P&L"
                )

            result = RiskCheckResult(
                verdict=verdict,
                approved=verdict in (RiskVerdict.APPROVED, RiskVerdict.WARNING),
                messages=messages,
                veto_reason=veto_reason,
                adjusted_risk_pct=adjusted_risk,
                knowledge_context=self._build_knowledge_context(proposal, verdict.value, None),
            )

            self._log_risk_event(
                "trade_evaluation",
                "info" if result.approved else "critical",
                f"Trade {proposal.asset} {proposal.direction}: {verdict.value}",
                {"proposal": proposal.__dict__, "result": result.__dict__},
                veto_applied=not result.approved,
            )

            self._set_status(EngineStatus.IDLE)
            return EngineResult(
                success=True,
                data=result,
                message=f"Risk check: {verdict.value}",
            )
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("Risk evaluation failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def halt_trading(self, reason: str) -> EngineResult:
        """
        CRO emergency halt — stops all trading.

        Args:
            reason: Reason for halt.

        Returns:
            EngineResult confirming halt.
        """
        self._trading_halted = True
        self._log_risk_event("trading_halt", "critical", reason, {}, veto_applied=True)
        logger.critical("CRO TRADING HALT: %s", reason)
        return EngineResult(success=True, message=f"Trading halted: {reason}")

    def resume_trading(self) -> EngineResult:
        """Resume trading after manual human approval."""
        self._trading_halted = False
        self._log_risk_event("trading_resume", "info", "Trading resumed by human approval")
        return EngineResult(success=True, message="Trading resumed")

    def _veto(self, reason: str) -> EngineResult:
        """Apply CRO veto."""
        result = RiskCheckResult(
            verdict=RiskVerdict.VETO,
            approved=False,
            veto_reason=reason,
            messages=[reason],
            knowledge_context=self._build_knowledge_context(None, "veto", reason),
        )
        self._log_risk_event("veto", "critical", reason, {}, veto_applied=True)
        logger.warning("CRO VETO: %s", reason)
        return EngineResult(success=True, data=result, message=f"VETO: {reason}")

    def record_trade_result(self, won: bool) -> EngineResult:
        """Call this once a trade closes, with whether it won or lost --
        feeds the consecutive-loss circuit breaker (Rule 12 in
        evaluate_trade). A win resets the streak to 0; a loss increments
        it. Separate from update_portfolio_state() since a single closed
        trade's win/loss is a different signal than the aggregate P&L
        percentages that method tracks -- N small losses in a row can
        still leave daily_pnl_pct comfortably inside its limit while still
        being exactly the pattern this circuit breaker exists to catch."""
        if won:
            self._consecutive_losses = 0
        else:
            self._consecutive_losses += 1
            if self._consecutive_losses >= settings.max_consecutive_losses:
                self._log_risk_event(
                    "consecutive_loss_limit",
                    "critical",
                    f"{self._consecutive_losses} consecutive losses reached the circuit-breaker limit",
                    {"consecutive_losses": self._consecutive_losses},
                )
        return EngineResult(
            success=True,
            message=f"Trade result recorded: {'win' if won else 'loss'} (consecutive losses: {self._consecutive_losses})",
            data={"consecutive_losses": self._consecutive_losses},
        )

    def _check_portfolio_limits(self) -> None:
        """Auto-halt if portfolio limits breached."""
        if self._portfolio_state.current_drawdown_pct >= settings.max_drawdown_pct:
            self.halt_trading(
                f"Auto-halt: drawdown {self._portfolio_state.current_drawdown_pct:.2f}%"
            )

    def _log_risk_event(
        self,
        event_type: str,
        severity: str,
        message: str,
        metadata: dict[str, Any],
        veto_applied: bool = False,
    ) -> None:
        """Log risk event to database."""
        try:
            with get_db_session() as session:
                event = RiskEvent(
                    event_type=event_type,
                    severity=severity,
                    message=message,
                    event_metadata=metadata,
                    veto_applied=veto_applied,
                )
                session.add(event)
        except Exception as e:
            logger.error("Failed to log risk event: %s", e)

    def calculate_position_size(
        self,
        capital: float,
        entry_price: float,
        stop_loss: float,
        risk_percent: float,
    ) -> EngineResult:
        """
        Calculate position size based on fixed fractional risk.

        Args:
            capital: Account trading capital.
            entry_price: Planned entry price.
            stop_loss: Stop loss price.
            risk_percent: Risk as percentage of capital.

        Returns:
            EngineResult with position size.
        """
        # Reject nonsensical inputs rather than propagating them (added
        # 2026-08-23). Previously a negative capital or a negative
        # risk_percent produced a NEGATIVE position size and returned
        # success=True: e.g. capital=-5000 -> size -50. Nothing downstream
        # treats size as signed, so a negative size reads as an inverted
        # position -- a short where a long was intended -- from an input
        # that is simply invalid. Failing loudly is the only safe response.
        if capital <= 0:
            return EngineResult(success=False, message=f"Capital must be positive (got {capital})")
        if risk_percent <= 0:
            return EngineResult(success=False, message=f"Risk percent must be positive (got {risk_percent})")
        if risk_percent > 100:
            return EngineResult(
                success=False,
                message=f"Risk percent {risk_percent} exceeds 100% of capital -- refusing to size this",
            )
        if entry_price <= 0:
            return EngineResult(success=False, message=f"Entry price must be positive (got {entry_price})")

        risk_amount = capital * (risk_percent / 100)
        stop_distance = abs(entry_price - stop_loss)
        if stop_distance == 0:
            return EngineResult(success=False, message="Stop distance cannot be zero")

        position_size = risk_amount / stop_distance

        # Leverage cap (added 2026-08-22). Fixed-fractional sizing answers
        # "how many units put exactly risk_amount at risk if the stop is
        # hit" -- it says nothing about whether that many units are
        # AFFORDABLE, and nothing here previously checked. Because size is
        # inversely proportional to stop distance, a tighter stop silently
        # inflates notional without changing the risk the user set:
        # measured on $10,000 at 1% risk, a 0.5% stop implies 2x notional,
        # 0.25% implies 4x, 0.1% implies 10x. That is ordinary for an
        # intraday stop, so the old behaviour could hand a cash account a
        # position it cannot hold, from a setting reading "risk 1%".
        #
        # Capping SIZE (not the risk percent) is the honest correction:
        # the trade stays takeable at a smaller size, and the caller is
        # told plainly that its real risk is now BELOW the requested
        # percent -- never silently above it.
        capped = False
        max_notional = capital * settings.max_position_leverage
        if entry_price > 0 and position_size * entry_price > max_notional:
            position_size = max_notional / entry_price
            risk_amount = position_size * stop_distance
            capped = True

        message = f"Position size: {position_size:.4f} units"
        if capped:
            message += (
                f" (capped at {settings.max_position_leverage:g}x capital; "
                f"real risk reduced to {risk_amount / capital * 100:.2f}% "
                f"of capital, below the {risk_percent:g}% requested)"
            )
        return EngineResult(
            success=True,
            data={
                "position_size": position_size,
                "risk_amount": risk_amount,
                "stop_distance": stop_distance,
                "risk_percent": risk_amount / capital * 100 if capital > 0 else risk_percent,
                "requested_risk_percent": risk_percent,
                "leverage_capped": capped,
                "notional": position_size * entry_price,
            },
            message=message,
        )

    def calculate_kelly_position_size(
        self,
        capital: float,
        win_rate: float,
        avg_win_r: float,
        avg_loss_r: float,
        kelly_fraction: float = 0.25,
    ) -> EngineResult:
        """
        Kelly Criterion position sizing -- added 2026-08-02, a genuinely
        different method from the fixed-fractional calculate_position_size
        above (which risks a flat % regardless of edge). Kelly computes
        the mathematically edge-optimal risk fraction from the strategy's
        own actual win rate and win/loss size ratio:

            f* = p - (1-p)/b       where b = avg_win_r / avg_loss_r

        Full Kelly is famously aggressive (correct on average, but with
        drawdowns most traders can't tolerate) -- kelly_fraction=0.25
        ("quarter Kelly") is a conventional, much cited compromise in
        practical risk-management literature: roughly half the growth
        rate of full Kelly for a large reduction in variance/drawdown
        depth. Returns a hard failure (not a silently clamped value) if
        the edge is non-positive (b*p <= 1-p) -- Kelly says don't bet at
        all in that case, and silently returning 0 without saying why
        would hide a real "this setup has no edge" finding.

        Args:
            capital: Account trading capital.
            win_rate: Historical win rate (0-1).
            avg_win_r: Average win, in R-multiples (e.g. 2.0 = wins average 2R).
            avg_loss_r: Average loss, in R-multiples, positive number (e.g. 1.0 = losses average 1R).
            kelly_fraction: Fraction of full Kelly to actually risk (default 0.25 = quarter Kelly).

        Returns:
            EngineResult with the recommended risk percent and position-sizing capital amount.
        """
        if not (0.0 < win_rate < 1.0):
            return EngineResult(success=False, message="win_rate must be strictly between 0 and 1")
        if avg_win_r <= 0 or avg_loss_r <= 0:
            return EngineResult(success=False, message="avg_win_r and avg_loss_r must both be positive")

        b = avg_win_r / avg_loss_r
        full_kelly = win_rate - (1 - win_rate) / b
        if full_kelly <= 0:
            return EngineResult(
                success=False,
                message=(
                    f"No positive edge at these inputs (full Kelly = {full_kelly:.3f}) -- "
                    "Kelly Criterion says this setup should not be sized at all, not "
                    "sized to zero silently"
                ),
            )

        recommended_fraction = full_kelly * kelly_fraction
        risk_amount = capital * recommended_fraction
        return EngineResult(
            success=True,
            data={
                "full_kelly_fraction": round(full_kelly, 4),
                "kelly_fraction_used": kelly_fraction,
                "recommended_risk_pct": round(recommended_fraction * 100, 3),
                "recommended_risk_amount": round(risk_amount, 2),
            },
            message=f"Kelly-recommended risk: {recommended_fraction * 100:.2f}% of capital ({kelly_fraction:.0%} of full Kelly)",
        )

    def compute_risk_of_ruin(
        self,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
        risk_per_trade: float,
        n_trades: int = 1000,
    ) -> float:
        """
        Estimate risk of ruin via Monte Carlo approximation.

        Args:
            win_rate: Historical win rate (0-1).
            avg_win: Average win in R-multiples.
            avg_loss: Average loss in R-multiples (positive number).
            risk_per_trade: Risk per trade as fraction.
            n_trades: Simulation length.

        Returns:
            Risk of ruin as percentage.
        """
        ruin_count = 0
        simulations = 500
        ruin_threshold = 0.5

        for _ in range(simulations):
            equity = 1.0
            for _ in range(n_trades):
                if np_random() < win_rate:
                    equity += avg_win * risk_per_trade
                else:
                    equity -= avg_loss * risk_per_trade
                if equity <= ruin_threshold:
                    ruin_count += 1
                    break

        return ruin_count / simulations * 100

    def compute_value_at_risk(
        self, returns: list[float], confidence: float = 0.95, capital: Optional[float] = None
    ) -> EngineResult:
        """
        Value at Risk (VaR) and Conditional VaR / Expected Shortfall (CVaR)
        -- added 2026-08-02. The single most fundamental risk metric in
        risk-management literature, previously entirely absent from this
        engine despite it being the CRO's core domain.

        Computes BOTH:
          - Historical VaR/CVaR: from the empirical distribution of
            `returns` directly, no distributional assumption. VaR is the
            loss at the (1-confidence) percentile; CVaR is the average of
            everything AT OR BEYOND that percentile -- a strictly more
            conservative number than VaR alone, since VaR only says how
            bad the cutoff is, not how bad things get past it.
          - Parametric VaR/CVaR: assumes returns are normally distributed
            (mean/std of the same `returns`) and uses the closed-form
            normal-distribution formulas. Only as good as the normality
            assumption -- real return distributions are typically
            fat-tailed, so parametric VaR usually UNDERSTATES true tail
            risk relative to the historical figure. Both are reported
            side by side rather than picking one, specifically so a large
            gap between them is visible (a sign the return series is
            meaningfully non-normal / fat-tailed).

        Args:
            returns: Historical returns as fractions (e.g. -0.02 for -2%), NOT R-multiples.
            confidence: Confidence level (e.g. 0.95 = 95% VaR).
            capital: If given, also reports VaR/CVaR in currency terms, not just as a fraction.

        Returns:
            EngineResult with historical and parametric VaR/CVaR.
        """
        if len(returns) < 20:
            return EngineResult(
                success=False,
                message=f"Need at least 20 return observations for a meaningful VaR estimate, got {len(returns)}",
            )
        if not (0.0 < confidence < 1.0):
            return EngineResult(success=False, message="confidence must be strictly between 0 and 1")

        import numpy as np
        from scipy import stats

        arr = np.asarray(returns, dtype=float)
        alpha = 1.0 - confidence

        hist_var = float(np.percentile(arr, alpha * 100))
        tail = arr[arr <= hist_var]
        hist_cvar = float(tail.mean()) if len(tail) > 0 else hist_var

        mean, std = float(arr.mean()), float(arr.std(ddof=1))
        z = float(stats.norm.ppf(alpha))
        param_var = mean + z * std
        # Closed-form normal-distribution Expected Shortfall: the mean of
        # the tail beyond the z-cutoff, using the standard normal PDF at z
        # divided by alpha (the tail probability mass).
        param_cvar = mean - std * (stats.norm.pdf(z) / alpha)

        data = {
            "confidence": confidence,
            "n_observations": len(returns),
            "historical_var_pct": round(hist_var * 100, 3),
            "historical_cvar_pct": round(hist_cvar * 100, 3),
            "parametric_var_pct": round(param_var * 100, 3),
            "parametric_cvar_pct": round(param_cvar * 100, 3),
        }
        if capital is not None:
            data["historical_var_amount"] = round(hist_var * capital, 2)
            data["historical_cvar_amount"] = round(hist_cvar * capital, 2)

        return EngineResult(
            success=True,
            data=data,
            message=(
                f"{confidence:.0%} VaR: {hist_var * 100:.2f}% (historical) / {param_var * 100:.2f}% "
                f"(parametric); CVaR: {hist_cvar * 100:.2f}% / {param_cvar * 100:.2f}%"
            ),
        )

    def _build_knowledge_context(
        self, proposal: Optional[TradeRiskProposal], verdict: str, reason: Optional[str]
    ) -> Optional[dict]:
        """Relevant risk-management book content for this evaluation,
        attached for transparency ONLY -- read by nothing else in this
        class. This engine's entire purpose is being a deterministic,
        auditable veto gate (loss limits, drawdown, portfolio heat, risk
        of ruin, mandatory stop-loss); no rule above ever reads this
        field, so it is architecturally incapable of influencing
        approved/verdict/adjusted_risk_pct. Best-effort: only runs if a
        real KnowledgeEngine instance was injected (see __init__ /
        registry.py)."""
        if self._knowledge_engine is None:
            return None
        try:
            if reason:
                query = f"risk management {verdict}: {reason}"
            elif proposal:
                query = f"risk management {verdict} for {proposal.direction} trade in {proposal.regime} regime"
            else:
                query = f"risk management {verdict}"
            results = self._knowledge_engine.document_store.hybrid_search(query, limit=3)
        except Exception as e:
            logger.warning("Knowledge context unavailable: %s", e)
            return None
        if not results:
            return None
        return {"query": query, "results": [r.to_dict() for r in results]}


def np_random() -> float:
    """Simple random for risk of ruin (avoids numpy import at module level)."""
    import random
    return random.random()
