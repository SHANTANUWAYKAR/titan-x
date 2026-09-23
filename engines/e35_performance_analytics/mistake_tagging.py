"""
Module: mistake_tagging.py
Description: Automatic mistake/rule-adherence tag detection for the
    self-improvement trade journal -- added 2026-08-21 after auditing 5
    real open-source trading journals (TradeNote, tradicted-journal,
    riccorohl/trading-journal, janzofx/Trading_Journal, gbFinch/
    free-trading-journal) for how they model rule-adherence and
    behavioral tracking.

    Deliberate design choice, and why: tradicted-journal is the
    strongest real reference for a rule-adherence checklist, but its OWN
    pre-trade checklist UI never actually persists what got checked
    (`rules_followed: null` hardcoded at trade-creation time in its
    NewTrade.tsx/Calculator.tsx -- only the after-the-fact edit flow
    saves it). A manual checkbox is fragile by construction: a human has
    to remember to fill it in, honestly, in the moment. Every rule below
    is instead evaluated AUTOMATICALLY from data this platform already
    captures (confidence_score, killzone timing, logged trade history) --
    the rule DEFINITIONS (thresholds) are user-editable via
    MistakeRuleDefinition, but the CHECKING itself is never optional or
    forgettable. Also directly validated by auditing gbFinch/
    free-trading-journal: its README claims "behavior analysis" but the
    real code contains zero pattern-detection logic anywhere -- a
    concrete example of exactly the gap this module exists to actually
    close, not just label.

    Every function here is pure (no DB session, no engine dependency
    beyond the already-pure killzones module) -- the engine layer
    (engine.py) is responsible for fetching real Trade rows, converting
    them to TradeRecord, and persisting the results as TradeTag rows.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from project_titan_x.engines.e07_technical.killzones import active_killzones_at


@dataclass
class TradeRecord:
    """Minimal, ORM-decoupled view of a logged trade -- only the fields
    the rule checks below actually need. risk_percent_used is optional
    and NOT part of the existing Trade table (see position_size_exceeded's
    own docstring for why) -- when absent, any rule that needs it is
    skipped, never guessed."""

    id: Optional[int]
    entry_time: Optional[datetime]
    exit_time: Optional[datetime]
    pnl_r: Optional[float]
    pnl_percent: Optional[float]
    confidence_at_entry: Optional[int]
    risk_percent_used: Optional[float] = None
    # Added 2026-09-13, Phase 9. Both are the CALLER's own pre-computed
    # context (PerformanceAnalyticsEngine.compute_and_persist_mistake_tags)
    # -- this module stays pure/dependency-free, so neither E12's real
    # kelly_criterion nor a Signal.evidence scan happens in here.
    kelly_recommended_risk_pct: Optional[float] = None
    signal_had_disagreeing_layer: Optional[bool] = None


@dataclass
class MistakeTagResult:
    tag_key: str
    category: str  # "rule_adherence" | "behavioral"
    negative: bool
    detail: dict[str, Any] = field(default_factory=dict)


# Seeded into mistake_rule_definitions on first use (see
# PerformanceAnalyticsEngine.ensure_default_mistake_rules) -- not
# hardcoded into the check functions themselves, so a user can retune or
# disable any of these without a code change.
DEFAULT_RULES: list[dict[str, Any]] = [
    {"rule_key": "below_confluence_threshold", "label": "Entered below your confluence threshold",
     "category": "rule_adherence", "params": {"min_confidence": 65}},
    {"rule_key": "outside_killzone", "label": "Entered outside any ICT killzone",
     "category": "rule_adherence", "params": {}},
    {"rule_key": "position_size_exceeded", "label": "Risked more than your max per-trade limit",
     "category": "rule_adherence", "params": {"max_risk_percent": 1.0}},
    {"rule_key": "revenge_trade", "label": "Re-entered too soon after a loss (possible revenge trade)",
     "category": "behavioral", "params": {"cooldown_minutes": 30}},
    {"rule_key": "overtrading_session", "label": "Too many trades opened the same day",
     "category": "behavioral", "params": {"max_trades_per_day": 5}},
    {"rule_key": "traded_in_daily_loss_red_zone", "label": "Entered while daily loss budget was already thin",
     "category": "behavioral", "params": {"max_daily_loss_pct": 5.0, "red_zone_threshold_pct": 25.0}},
    {"rule_key": "consecutive_loss_violation", "label": "Entered after your consecutive-loss limit was already hit",
     "category": "behavioral", "params": {"max_consecutive_losses": 5}},
    # Added 2026-09-13, closing two real docs/UPGRADE_BRIEF.md Phase 9
    # gaps confirmed absent by direct inspection before adding:
    {"rule_key": "kelly_sizing_exceeded", "label": "Risked more than your real Kelly-recommended size",
     "category": "rule_adherence", "params": {"margin_multiplier": 1.5}},
    {"rule_key": "overrode_disagreeing_layer", "label": "Took the trade despite a confluence layer disagreeing",
     "category": "rule_adherence", "params": {}},
]


def check_below_confluence_threshold(trade: TradeRecord, params: dict) -> Optional[MistakeTagResult]:
    """Mirrors settings.min_signal_confidence's role in e51_signals, but
    against the USER's own configured minimum (which may differ), and
    against what actually happened, not what the engine would allow."""
    if trade.confidence_at_entry is None:
        return None
    min_confidence = params.get("min_confidence", 65)
    if trade.confidence_at_entry < min_confidence:
        return MistakeTagResult(
            "below_confluence_threshold", "rule_adherence", True,
            {"required": min_confidence, "actual": trade.confidence_at_entry},
        )
    return None


def check_outside_killzone(trade: TradeRecord, params: dict) -> Optional[MistakeTagResult]:
    """Reuses engines/e07_technical/killzones.py directly -- zero new
    detection logic, same real ICT windows the SMC layer already uses."""
    if trade.entry_time is None:
        return None
    active = active_killzones_at(trade.entry_time)
    if not active:
        return MistakeTagResult("outside_killzone", "rule_adherence", True, {"entry_time": trade.entry_time.isoformat()})
    return None


def check_position_size_exceeded(trade: TradeRecord, params: dict) -> Optional[MistakeTagResult]:
    """This platform has no execution engine and TradeCreate doesn't
    capture position size today -- risk_percent_used is an OPTIONAL field
    a caller may supply at journal time specifically to enable this one
    check. Skipped (not fabricated as 'not exceeded') when absent."""
    if trade.risk_percent_used is None:
        return None
    max_risk = params.get("max_risk_percent", 1.0)
    if trade.risk_percent_used > max_risk:
        return MistakeTagResult(
            "position_size_exceeded", "rule_adherence", True,
            {"max_allowed": max_risk, "actual": trade.risk_percent_used},
        )
    return None


def check_kelly_sizing_exceeded(trade: TradeRecord, params: dict) -> Optional[MistakeTagResult]:
    """Distinct from position_size_exceeded above: that one checks against
    a FIXED, user-set percent; this checks against this strategy's own
    REAL historical Kelly-optimal fraction (E12's real kelly_criterion,
    computed by the caller from this strategy's actual win_rate/avg_win_r/
    avg_loss_r -- see TradeRecord.kelly_recommended_risk_pct's own
    docstring; never recomputed here, this module stays dependency-free).

    margin_multiplier (default 1.5) allows sizing somewhat above the raw
    Kelly figure before flagging -- Kelly itself already assumes EXACT
    win-rate/payoff stats, which a finite trade sample never gives
    exactly, so a small margin above it isn't automatically reckless the
    way 3-4x Kelly would be. Skipped (not fabricated) when either
    risk_percent_used or kelly_recommended_risk_pct is absent."""
    if trade.risk_percent_used is None or trade.kelly_recommended_risk_pct is None:
        return None
    margin = params.get("margin_multiplier", 1.5)
    max_allowed = trade.kelly_recommended_risk_pct * margin
    if trade.risk_percent_used > max_allowed:
        return MistakeTagResult(
            "kelly_sizing_exceeded", "rule_adherence", True,
            {
                "kelly_recommended_pct": round(trade.kelly_recommended_risk_pct, 4),
                "margin_multiplier": margin,
                "max_allowed_pct": round(max_allowed, 4),
                "actual_pct": trade.risk_percent_used,
            },
        )
    return None


def check_overrode_disagreeing_layer(trade: TradeRecord, params: dict) -> Optional[MistakeTagResult]:
    """Fires when this trade's linked E51 signal had at least one
    confluence layer (E10/E13/E17/etc.) that disagreed with the direction
    actually taken -- signal_had_disagreeing_layer is the caller's own
    scan of that signal's real evidence text (see
    PerformanceAnalyticsEngine's own helper); None (a discretionary trade
    with no linked signal, or a signal whose evidence couldn't be
    checked) is left unflagged, never assumed True or False."""
    if trade.signal_had_disagreeing_layer is not True:
        return None
    return MistakeTagResult("overrode_disagreeing_layer", "rule_adherence", True, {})


def check_revenge_trade(trade: TradeRecord, closed_before_entry: list[TradeRecord], params: dict) -> Optional[MistakeTagResult]:
    """closed_before_entry: this trader's other trades that had already
    CLOSED by the time `trade` was entered, sorted most-recent-exit
    first. Fires when the immediately preceding trade was a loss and
    this one was entered inside the cooldown window -- optionally also
    flags whether size increased, when risk_percent_used is available
    for both trades (best-effort, not required for the base check)."""
    if trade.entry_time is None or not closed_before_entry:
        return None
    previous = closed_before_entry[0]
    if previous.exit_time is None or previous.pnl_r is None or previous.pnl_r >= 0:
        return None
    cooldown = params.get("cooldown_minutes", 30)
    gap_minutes = (trade.entry_time - previous.exit_time).total_seconds() / 60.0
    if 0 <= gap_minutes < cooldown:
        detail: dict[str, Any] = {
            "cooldown_minutes": cooldown, "actual_gap_minutes": round(gap_minutes, 1),
            "previous_trade_pnl_r": previous.pnl_r,
        }
        if trade.risk_percent_used is not None and previous.risk_percent_used is not None:
            detail["size_increased"] = trade.risk_percent_used > previous.risk_percent_used
        return MistakeTagResult("revenge_trade", "behavioral", True, detail)
    return None


def check_overtrading_session(trade: TradeRecord, same_day_other_trade_count: int, params: dict) -> Optional[MistakeTagResult]:
    """same_day_other_trade_count: how many OTHER trades this trader
    entered on the same calendar day as `trade` (not counting `trade`
    itself)."""
    if trade.entry_time is None:
        return None
    max_trades = params.get("max_trades_per_day", 5)
    total_that_day = same_day_other_trade_count + 1
    if total_that_day > max_trades:
        return MistakeTagResult(
            "overtrading_session", "behavioral", True,
            {"max_allowed": max_trades, "actual": total_that_day},
        )
    return None


def check_daily_loss_red_zone(trade: TradeRecord, same_day_realized_pnl_pct_before_entry: float, params: dict) -> Optional[MistakeTagResult]:
    """same_day_realized_pnl_pct_before_entry: sum of pnl_percent across
    this trader's OTHER trades that both entered and closed earlier the
    same calendar day as `trade` -- a real, retrospective reconstruction
    of what the daily loss budget looked like at the moment of entry,
    computed from logged history (this journal has no live equity feed
    to read instead, per Rule 5)."""
    if trade.entry_time is None:
        return None
    max_daily_loss = params.get("max_daily_loss_pct", 5.0)
    red_zone_threshold = params.get("red_zone_threshold_pct", 25.0)
    if same_day_realized_pnl_pct_before_entry >= 0 or max_daily_loss <= 0:
        return None
    used_pct = min(100.0, (-same_day_realized_pnl_pct_before_entry / max_daily_loss) * 100.0)
    remaining_pct = 100.0 - used_pct
    if remaining_pct <= red_zone_threshold:
        return MistakeTagResult(
            "traded_in_daily_loss_red_zone", "behavioral", True,
            {"daily_budget_remaining_pct": round(remaining_pct, 1), "threshold_pct": red_zone_threshold},
        )
    return None


def check_consecutive_loss_violation(trade: TradeRecord, consecutive_losses_before_this: int, params: dict) -> Optional[MistakeTagResult]:
    """Mirrors e45_risk's real max_consecutive_losses circuit breaker
    (settings.max_consecutive_losses), computed retrospectively from
    journal history rather than the live engine's in-memory counter --
    that counter wouldn't apply here anyway, since journal entries are
    often logged well after the live session that produced them ended."""
    max_losses = params.get("max_consecutive_losses", 5)
    if consecutive_losses_before_this >= max_losses:
        return MistakeTagResult(
            "consecutive_loss_violation", "behavioral", True,
            {"limit": max_losses, "actual_streak": consecutive_losses_before_this},
        )
    return None


def evaluate_all_rules(trade: TradeRecord, history: list[TradeRecord], rules: dict[str, dict]) -> list[MistakeTagResult]:
    """Runs every enabled rule in `rules` (rule_key -> {"enabled": bool,
    "params": dict}) against `trade`, given `history` (every OTHER
    logged trade for this trader -- order doesn't matter, this function
    does its own filtering/sorting per check). Returns only the rules
    that actually fired; a clean trade returns []."""
    results: list[MistakeTagResult] = []

    def _enabled(key: str) -> bool:
        return rules.get(key, {}).get("enabled", True)

    def _params(key: str, default: dict) -> dict:
        rule = rules.get(key)
        return rule["params"] if rule and rule.get("params") else default

    if _enabled("below_confluence_threshold"):
        r = check_below_confluence_threshold(trade, _params("below_confluence_threshold", {}))
        if r:
            results.append(r)

    if _enabled("outside_killzone"):
        r = check_outside_killzone(trade, _params("outside_killzone", {}))
        if r:
            results.append(r)

    if _enabled("position_size_exceeded"):
        r = check_position_size_exceeded(trade, _params("position_size_exceeded", {}))
        if r:
            results.append(r)

    if _enabled("kelly_sizing_exceeded"):
        r = check_kelly_sizing_exceeded(trade, _params("kelly_sizing_exceeded", {}))
        if r:
            results.append(r)

    if _enabled("overrode_disagreeing_layer"):
        r = check_overrode_disagreeing_layer(trade, _params("overrode_disagreeing_layer", {}))
        if r:
            results.append(r)

    if trade.entry_time is not None:
        closed_before_entry = sorted(
            (t for t in history if t.exit_time is not None and t.exit_time <= trade.entry_time),
            key=lambda t: t.exit_time, reverse=True,
        )

        if _enabled("revenge_trade"):
            r = check_revenge_trade(trade, closed_before_entry, _params("revenge_trade", {}))
            if r:
                results.append(r)

        if _enabled("overtrading_session"):
            same_day_other = sum(
                1 for t in history
                if t.id != trade.id and t.entry_time is not None and t.entry_time.date() == trade.entry_time.date()
            )
            r = check_overtrading_session(trade, same_day_other, _params("overtrading_session", {}))
            if r:
                results.append(r)

        if _enabled("traded_in_daily_loss_red_zone"):
            same_day_closed_before = [t for t in closed_before_entry if t.exit_time.date() == trade.entry_time.date()]
            realized_pct = sum(t.pnl_percent or 0.0 for t in same_day_closed_before)
            r = check_daily_loss_red_zone(trade, realized_pct, _params("traded_in_daily_loss_red_zone", {}))
            if r:
                results.append(r)

        if _enabled("consecutive_loss_violation"):
            streak = 0
            for t in closed_before_entry:
                if t.pnl_r is not None and t.pnl_r < 0:
                    streak += 1
                else:
                    break
            r = check_consecutive_loss_violation(trade, streak, _params("consecutive_loss_violation", {}))
            if r:
                results.append(r)

    return results
