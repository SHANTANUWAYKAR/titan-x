"""
Module: engine.py
Description: Engine 35 -- Performance Analytics. Master prompt scope: KPIs
    computed from a real, logged trade history -- win rate, profit factor,
    expectancy, max drawdown, average/largest win-loss.

    This platform has no execution engine (CLAUDE.md Rule 5: "No engine may
    execute a live trade"), so every row here is a manually-logged,
    retrospective journal entry -- a human recording a trade they actually
    took, optionally linking it back to the specific E51 signal that
    prompted it (core.database.models.Trade.signal_id, nullable -- a trade
    doesn't have to have come from an E51 signal at all).

    Ported from a sibling project's Command Center trade-journal service
    (real, working code, reviewed for correctness) and adapted to this
    platform's own R-multiple convention: the source computed win_rate/
    profit_factor/expectancy from absolute dollar P&L, but this platform's
    Trade model stores pnl_r (R-multiples) instead, consistent with how E51
    already reports expected_value in R and E45 sizes risk as a percentage,
    never a dollar amount. pnl_percent (fractional return on capital
    allocated to that trade) still drives max_drawdown, which needs a
    percentage basis to mean anything independent of account size -- same
    reasoning the source code used, just applied to R-multiples instead of
    dollars for everything else.

    No calibration/training step applies (Rule 3): every formula here is
    exact, deterministic arithmetic on logged numbers, not a fitted
    parameter -- same honest-gap category as E40 Data Quality's mechanical
    validation.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-07-17
"""

import logging
from collections import defaultdict
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from project_titan_x.core.database.models import MistakeRuleDefinition, Signal, Trade, TradeTag
from project_titan_x.core.database.session import get_db_session
from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus
from project_titan_x.engines.e02_market_data.engine import MarketDataEngine
from project_titan_x.engines.e31_portfolio_construction.engine import historical_cvar
from project_titan_x.engines.e35_performance_analytics.mistake_tagging import (
    DEFAULT_RULES,
    TradeRecord,
    evaluate_all_rules,
)

logger = logging.getLogger(__name__)


@dataclass
class PerformanceSummary:
    """KPIs computed from a set of logged trades."""

    n_trades: int
    total_pnl_r: float
    win_rate: float
    profit_factor: Optional[float]  # None == infinite (wins, zero losses) -- not JSON-safe
    expectancy_r: float
    max_drawdown_pct: float
    avg_win_r: float
    avg_loss_r: float
    largest_win_r: float
    largest_loss_r: float
    # Mean/std (Sharpe) and mean/downside-std (Sortino) of per-trade
    # pnl_percent -- deliberately NOT annualized, unlike E26's bar-indexed
    # backtest Sharpe. Trades in a manually-logged journal aren't evenly
    # time-spaced like backtest bars, so picking a periods_per_year here
    # would be a fabricated assumption this file's own Rule 3 philosophy
    # (exact, deterministic arithmetic on logged numbers, no fitted/
    # assumed parameters) avoids everywhere else. None when fewer than 2
    # trades or zero variance in the relevant denominator -- not a
    # fabricated 0.0.
    sharpe_per_trade: Optional[float]
    sortino_per_trade: Optional[float]
    # Added 2026-08-03: cross-referencing this engine against the YouTube
    # knowledge pipeline's extraction (Mind Math Money, 97 videos) found
    # "break-even win rate" taught repeatedly with real worked examples
    # (e.g. "even at 35% win rate, we still have a positive expected
    # value" for a given risk-reward) -- the minimum win rate at which
    # expectancy is zero. Derived from THIS journal's own real avg_win_r/
    # avg_loss_r (not an assumed fixed R:R ratio), so it answers "is my
    # actual realized win rate above or below the line my actual realized
    # win/loss sizes require" -- purely descriptive arithmetic on already-
    # logged numbers, same Rule-3 exemption as every other metric in this
    # file. None (not a fabricated 0.0) when there's no realized loss (or
    # no realized win) to divide by yet.
    break_even_win_rate: Optional[float]
    # Added 2026-09-13, Phase 9. recovery_factor and calmar_ratio reuse
    # E26's OWN formulas (_compute_metrics: total_return/max_dd,
    # cagr/max_dd) rather than reimplementing them -- see summarize's own
    # docstring for why calmar_ratio specifically needs real entry/exit
    # timestamps (a real elapsed-time CAGR, not an assumed periods_per_
    # year) and is None without them. cvar_pct reuses E31's real
    # historical_cvar (historical simulation on this journal's own
    # pnl_pcts, not a parametric/Gaussian estimate) -- None below
    # CVAR_MIN_TRADES, since a 95th-percentile tail estimate from a
    # handful of trades is not a meaningful number.
    recovery_factor: Optional[float]
    calmar_ratio: Optional[float]
    cvar_pct: Optional[float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_trades": self.n_trades,
            "total_pnl_r": round(self.total_pnl_r, 4),
            "win_rate": round(self.win_rate, 4),
            "profit_factor": round(self.profit_factor, 4) if self.profit_factor is not None else None,
            "expectancy_r": round(self.expectancy_r, 4),
            "max_drawdown_pct": round(self.max_drawdown_pct, 4),
            "avg_win_r": round(self.avg_win_r, 4),
            "avg_loss_r": round(self.avg_loss_r, 4),
            "largest_win_r": round(self.largest_win_r, 4),
            "largest_loss_r": round(self.largest_loss_r, 4),
            "sharpe_per_trade": round(self.sharpe_per_trade, 4) if self.sharpe_per_trade is not None else None,
            "sortino_per_trade": round(self.sortino_per_trade, 4) if self.sortino_per_trade is not None else None,
            "break_even_win_rate": round(self.break_even_win_rate, 4) if self.break_even_win_rate is not None else None,
            "recovery_factor": round(self.recovery_factor, 4) if self.recovery_factor is not None else None,
            "calmar_ratio": round(self.calmar_ratio, 4) if self.calmar_ratio is not None else None,
            "cvar_pct": round(self.cvar_pct, 4) if self.cvar_pct is not None else None,
        }


def compute_mae_mfe_r(
    market_data_engine: MarketDataEngine,
    symbol: Optional[str],
    timeframe: str,
    direction: Optional[str],
    entry_price: Optional[float],
    entry_time,
    exit_time,
    stop_loss_price: float,
) -> tuple[Optional[float], Optional[float]]:
    """Maximum Adverse/Favorable Excursion, in R-multiples, from REAL OHLCV
    between entry_time and exit_time -- never estimated or self-reported.
    docs/UPGRADE_BRIEF.md Phase 9 lists these under a manually-filled
    journal field, but a human recalling "how far did it move against me"
    days after the fact is exactly the hindsight-bias problem this
    platform's OWN 2026-08-21 TradeIntent design note already identified
    for entry snapshots -- MAE/MFE are objectively measurable from price
    history, so they're computed here, not asked of the user.

    stop_loss_price is required to convert a raw price excursion into an
    R-multiple (risk_amount = abs(entry_price - stop_loss_price)) -- with
    no stop price, "how many R" has no denominator, so the caller gets
    (None, None) rather than a fabricated number.

    Returns (None, None) on any missing input, an unsupported direction,
    or if fetch_ohlcv can't produce real bars covering that exact window
    (e.g. a very old or illiquid instrument/timeframe combination) --
    an honest gap, matching this codebase's standing convention, never a
    zero or an estimate standing in for real data.
    """
    if not symbol or not direction or entry_price is None or entry_time is None or exit_time is None:
        return None, None
    risk_amount = abs(float(entry_price) - float(stop_loss_price))
    if risk_amount <= 0:
        return None, None
    direction_norm = str(direction).lower()
    if direction_norm not in ("long", "short"):
        return None, None

    try:
        fetch = market_data_engine.fetch_ohlcv(symbol, timeframe, allow_cache=True)
        if not fetch.success or fetch.data is None or len(fetch.data) == 0:
            return None, None
        df = fetch.data
        ts = df["timestamp"]
        if ts.dt.tz is None:
            ts = ts.dt.tz_localize("UTC")
        window = df[(ts >= entry_time) & (ts <= exit_time)]
        if len(window) == 0:
            return None, None
        worst_low = float(window["low"].min())
        best_high = float(window["high"].max())
    except Exception:
        return None, None

    if direction_norm == "long":
        adverse = float(entry_price) - worst_low
        favorable = best_high - float(entry_price)
    else:
        adverse = best_high - float(entry_price)
        favorable = float(entry_price) - worst_low

    mae_r = round(max(0.0, adverse) / risk_amount, 4)
    mfe_r = round(max(0.0, favorable) / risk_amount, 4)
    return mae_r, mfe_r


def equity_curve_from_pnl_pct(pnl_pcts) -> np.ndarray:
    """Starting capital normalized to 1.0 (100%); additive (not compounded)
    cumulative sum of fractional per-trade P&L. Additive rather than
    compounded because pnl_percent represents return on capital ALLOCATED to
    that trade, not the whole account -- summing approximates account-level
    drawdown reasonably when position sizing is a roughly constant fraction
    of capital, which a trade journal (as opposed to a full portfolio
    simulation) can assume."""
    arr = np.asarray(pnl_pcts, dtype=float)
    return 1.0 + np.concatenate([[0.0], np.cumsum(arr)])


def max_drawdown_pct(pnl_pcts) -> float:
    """Max drawdown as a fraction of starting capital, from per-trade
    fractional P&L -- dollar/R drawdown alone has no account-size-
    independent interpretation."""
    if len(pnl_pcts) == 0:
        return 0.0
    equity = equity_curve_from_pnl_pct(pnl_pcts)
    running_max = np.maximum.accumulate(equity)
    dd = (equity - running_max) / running_max
    return max(0.0, -float(dd.min()))


def win_rate(pnl_rs) -> float:
    arr = np.asarray(pnl_rs, dtype=float)
    if len(arr) == 0:
        return 0.0
    return float((arr > 0).sum() / len(arr))


def profit_factor(pnl_rs) -> Optional[float]:
    arr = np.asarray(pnl_rs, dtype=float)
    gains = arr[arr > 0].sum()
    losses = -arr[arr < 0].sum()
    if losses == 0:
        return None if gains > 0 else 0.0
    return float(gains / losses)


def expectancy_r(pnl_rs) -> float:
    arr = np.asarray(pnl_rs, dtype=float)
    if len(arr) == 0:
        return 0.0
    return float(arr.mean())


def average_win_loss_r(pnl_rs) -> dict[str, float]:
    arr = np.asarray(pnl_rs, dtype=float)
    wins = arr[arr > 0]
    losses = arr[arr < 0]
    return {
        "avg_win_r": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss_r": float(losses.mean()) if len(losses) else 0.0,
        "largest_win_r": float(wins.max()) if len(wins) else 0.0,
        "largest_loss_r": float(losses.min()) if len(losses) else 0.0,
    }


def break_even_win_rate(pnl_rs) -> Optional[float]:
    """Minimum win rate at which expectancy = 0, given THIS journal's own
    realized average win/loss R-multiples (not an assumed fixed R:R):
    solving win_rate * avg_win = (1 - win_rate) * avg_loss_abs for
    win_rate gives avg_loss_abs / (avg_win + avg_loss_abs). None (not a
    fabricated 0.0) when there's no realized win or no realized loss yet
    to divide by -- the ratio is undefined, not zero."""
    arr = np.asarray(pnl_rs, dtype=float)
    wins = arr[arr > 0]
    losses = arr[arr < 0]
    if len(wins) == 0 or len(losses) == 0:
        return None
    avg_win = float(wins.mean())
    avg_loss_abs = -float(losses.mean())
    denom = avg_win + avg_loss_abs
    if denom == 0:
        return None
    return avg_loss_abs / denom


def sharpe_per_trade(pnl_pcts) -> Optional[float]:
    """Mean/std of per-trade fractional P&L -- see PerformanceSummary's
    own field docstring for why this is deliberately unannualized."""
    arr = np.asarray(pnl_pcts, dtype=float)
    if len(arr) < 2 or arr.std() == 0:
        return None
    return float(arr.mean() / arr.std())


def sortino_per_trade(pnl_pcts) -> Optional[float]:
    """Same as sharpe_per_trade but only downside (losing-trade) deviation
    in the denominator -- doesn't penalize upside variance."""
    arr = np.asarray(pnl_pcts, dtype=float)
    downside = arr[arr < 0]
    if len(arr) < 2 or len(downside) == 0 or downside.std() == 0:
        return None
    return float(arr.mean() / downside.std())


def recovery_factor_from_pnl_pct(pnl_pcts) -> Optional[float]:
    """Same formula E26's own _compute_metrics uses (total_return / max_dd)
    -- how many times over the max drawdown the total return recovered it.
    None (not a fabricated 0.0) when there's no drawdown to divide by yet
    (a journal with only winning trades)."""
    dd = max_drawdown_pct(pnl_pcts)
    if dd <= 0:
        return None
    total_return = float(equity_curve_from_pnl_pct(pnl_pcts)[-1] - 1.0) if len(pnl_pcts) else 0.0
    return total_return / dd


CVAR_MIN_TRADES = 10


def cvar_pct_from_pnl_pct(pnl_pcts, alpha: float = 0.95) -> Optional[float]:
    """Reuses E31's real historical_cvar (historical simulation, not a
    parametric/Gaussian estimate) on this journal's own realized
    pnl_pcts, treated as a single-asset return series (weights=[1.0]).
    None below CVAR_MIN_TRADES -- a 95th-percentile tail estimate from a
    handful of trades is noise, not a real estimate."""
    if len(pnl_pcts) < CVAR_MIN_TRADES:
        return None
    returns_matrix = np.asarray(pnl_pcts, dtype=float).reshape(-1, 1)
    return float(historical_cvar([1.0], returns_matrix, alpha=alpha) * 100)


def calmar_ratio_from_journal(pnl_pcts, entry_times, exit_times) -> Optional[float]:
    """Same formula E26's own _compute_metrics uses (cagr / max_dd), but
    CAGR here comes from the REAL elapsed wall-clock time this journal's
    own trades actually span (first entry_time to last exit_time) -- never
    an assumed periods_per_year, matching this file's own sharpe_per_trade
    non-annualization philosophy: a manually-logged journal has no fixed
    bar frequency to assume. None when fewer than 2 trades, any timestamp
    is missing, the span is under a day (too short for an annualized rate
    to mean anything), or there's no drawdown to divide by."""
    if len(pnl_pcts) < 2 or any(t is None for t in entry_times) or any(t is None for t in exit_times):
        return None
    dd = max_drawdown_pct(pnl_pcts)
    if dd <= 0:
        return None
    span_days = (max(exit_times) - min(entry_times)).total_seconds() / 86400.0
    if span_days < 1:
        return None
    years = span_days / 365.25
    total_return = float(equity_curve_from_pnl_pct(pnl_pcts)[-1])
    if total_return <= 0:
        return None
    cagr = total_return ** (1 / years) - 1
    return cagr / dd


def summarize(pnl_rs, pnl_pcts, entry_times=None, exit_times=None) -> PerformanceSummary:
    """pnl_rs: R-multiple per trade -- drives total_pnl_r, win_rate,
    profit_factor, expectancy_r, avg/largest win-loss. pnl_pcts: fractional
    P&L per trade -- drives max_drawdown_pct, sharpe_per_trade,
    sortino_per_trade, recovery_factor, cvar_pct. entry_times/exit_times
    (optional, same length as pnl_rs/pnl_pcts): real per-trade timestamps,
    needed only for calmar_ratio's real elapsed-time CAGR -- omitted
    (the default) leaves calmar_ratio as an honest None rather than
    assuming a bar frequency this journal doesn't have."""
    if len(pnl_rs) != len(pnl_pcts):
        raise ValueError("pnl_rs and pnl_pcts must be the same length")
    stats = average_win_loss_r(pnl_rs)
    calmar = (
        calmar_ratio_from_journal(pnl_pcts, entry_times, exit_times)
        if entry_times is not None and exit_times is not None else None
    )
    return PerformanceSummary(
        n_trades=len(pnl_rs),
        total_pnl_r=float(np.sum(pnl_rs)) if len(pnl_rs) else 0.0,
        win_rate=win_rate(pnl_rs),
        profit_factor=profit_factor(pnl_rs),
        expectancy_r=expectancy_r(pnl_rs),
        max_drawdown_pct=max_drawdown_pct(pnl_pcts),
        sharpe_per_trade=sharpe_per_trade(pnl_pcts),
        sortino_per_trade=sortino_per_trade(pnl_pcts),
        break_even_win_rate=break_even_win_rate(pnl_rs),
        recovery_factor=recovery_factor_from_pnl_pct(pnl_pcts),
        calmar_ratio=calmar,
        cvar_pct=cvar_pct_from_pnl_pct(pnl_pcts),
        **stats,
    )


class PerformanceAnalyticsEngine(BaseEngine):
    """
    Performance Analytics Engine (#35) -- trade journal CRUD + performance
    KPIs computed from it. No execution: every trade is logged manually
    after the fact (see module docstring / Rule 5).
    """

    engine_id = "e35_performance_analytics"
    engine_name = "Performance Analytics Engine"
    version = "1.0.0"

    def __init__(
        self,
        session_factory: Optional[Callable[[], AbstractContextManager[Session]]] = None,
        market_data_engine: Optional[MarketDataEngine] = None,
        quant_engine: Optional[Any] = None,
    ) -> None:
        super().__init__()
        # Optional so tests can inject an isolated (e.g. in-memory SQLite)
        # session factory without needing a real Postgres instance running.
        self._session_factory = session_factory or get_db_session
        # Optional, same convention as every other cross-engine collaborator
        # in this codebase -- used only for MAE/MFE computation (added
        # 2026-09-13, Phase 9), which needs real OHLCV between entry_time/
        # exit_time. None (the default) means MAE/MFE stay an honest gap
        # (mae_r/mfe_r=None) rather than fabricated.
        self._market_data_engine = market_data_engine
        # Optional (Any, not QuantResearchEngine directly, to avoid this
        # module importing e12 -- only kelly_criterion is ever called).
        # Used only for the kelly_sizing_exceeded mistake check (Phase 9);
        # None means that check stays skipped, never a fabricated verdict.
        self._quant_engine = quant_engine

    def initialize(self) -> EngineResult:
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Performance Analytics Engine initialized")

    def health_check(self) -> EngineResult:
        try:
            with self._session_factory() as session:
                session.execute(select(Trade).limit(1))
            return EngineResult(success=True, message="Healthy")
        except Exception as e:
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def log_trade(
        self, risk_percent_used: Optional[float] = None, stop_loss_price: Optional[float] = None, **fields: Any
    ) -> EngineResult:
        """Log one closed, already-completed trade. fields match Trade's
        columns (symbol, direction, entry_price, exit_price, entry_time,
        exit_time, pnl_r, pnl_percent, strategy_name, setup, timeframe,
        regime_at_entry, session_tag, notes, signal_id, slippage_r,
        screenshot_url -- all but the identity fields are optional).
        risk_percent_used and stop_loss_price are NOT Trade columns (this
        platform captures no real position-size/order data today) -- both
        are accepted only to feed transient computations (mistake checks;
        MAE/MFE below) and never persisted as trade fields themselves,
        same convention as each other.

        MAE/MFE (added 2026-09-13, Phase 9) are SERVER-COMPUTED from real
        OHLCV between entry_time/exit_time, never client-supplied --
        see compute_mae_mfe_r's own docstring. Requires stop_loss_price
        (to convert a raw price excursion into an R-multiple) AND a real
        market_data_engine; either being absent leaves mae_r/mfe_r as an
        honest None rather than fabricated.

        Mistake-tag computation (added 2026-08-21) runs automatically
        after every trade is logged -- best-effort, exactly the same
        never-raise/never-block convention api/main.py's own
        _persist_signal already uses, so a tagging failure can never
        prevent a real trade from being recorded."""
        try:
            if "symbol" in fields and fields["symbol"]:
                fields["symbol"] = str(fields["symbol"]).upper()
            if stop_loss_price is not None and self._market_data_engine is not None:
                try:
                    mae_r, mfe_r = compute_mae_mfe_r(
                        self._market_data_engine,
                        symbol=fields.get("symbol"),
                        timeframe=fields.get("timeframe") or "1h",
                        direction=fields.get("direction"),
                        entry_price=fields.get("entry_price"),
                        entry_time=fields.get("entry_time"),
                        exit_time=fields.get("exit_time"),
                        stop_loss_price=stop_loss_price,
                    )
                    if mae_r is not None:
                        fields["mae_r"] = mae_r
                    if mfe_r is not None:
                        fields["mfe_r"] = mfe_r
                except Exception as e:
                    logger.warning("MAE/MFE computation failed for %s (trade still logged): %s", fields.get("symbol"), e)
            with self._session_factory() as session:
                trade = Trade(**fields)
                session.add(trade)
                session.flush()
                trade_id = trade.id
            mistake_tags: list[dict[str, Any]] = []
            try:
                tag_result = self.compute_and_persist_mistake_tags(trade_id, risk_percent_used=risk_percent_used)
                if tag_result.success:
                    tags_list = self.list_trade_tags(trade_id)
                    if tags_list.success:
                        mistake_tags = tags_list.data
            except Exception as e:
                logger.warning("Mistake-tag computation failed for trade %s (trade itself was still logged): %s", trade_id, e)
            return EngineResult(success=True, data={"trade_id": trade_id, "mistake_tags": mistake_tags}, message="Trade logged")
        except Exception as e:
            logger.error("Failed to log trade: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def ensure_default_mistake_rules(self) -> EngineResult:
        """Idempotent seed of MistakeRuleDefinition from mistake_tagging.
        DEFAULT_RULES -- only inserts rule_keys that don't already exist,
        same "seed data, never overwrite a user's own edits" convention
        e01_knowledge's trader-profile seeding already uses. Safe to call
        on every startup."""
        try:
            with self._session_factory() as session:
                # select(Model.column).scalars() already yields the plain
                # column values (strings here), not ORM instances -- the
                # earlier `{r.rule_key for r in ...}` tried to access
                # .rule_key on each STRING and raised a real
                # AttributeError the first time this ran against live
                # Postgres (caught during live verification, not by any
                # prior test).
                existing_keys = set(session.execute(select(MistakeRuleDefinition.rule_key)).scalars().all())
                inserted = 0
                for rule in DEFAULT_RULES:
                    if rule["rule_key"] in existing_keys:
                        continue
                    session.add(MistakeRuleDefinition(
                        rule_key=rule["rule_key"], label=rule["label"],
                        category=rule["category"], params=rule["params"], enabled=True,
                    ))
                    inserted += 1
            return EngineResult(success=True, data={"inserted": inserted}, message=f"Seeded {inserted} default mistake rule(s)")
        except Exception as e:
            logger.error("Failed to seed default mistake rules: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def get_mistake_rules(self) -> EngineResult:
        try:
            with self._session_factory() as session:
                rows = session.execute(select(MistakeRuleDefinition).order_by(MistakeRuleDefinition.category, MistakeRuleDefinition.rule_key)).scalars().all()
                data = [{
                    "rule_key": r.rule_key, "label": r.label, "category": r.category,
                    "enabled": r.enabled, "params": r.params,
                } for r in rows]
            return EngineResult(success=True, data=data, message=f"{len(data)} mistake rule(s)")
        except Exception as e:
            logger.error("Failed to list mistake rules: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def update_mistake_rule(self, rule_key: str, enabled: Optional[bool] = None, params: Optional[dict] = None) -> EngineResult:
        """User-editable: toggle a rule on/off, or retune its params
        (e.g. {"min_confidence": 70}) -- never changes what the rule
        DETECTS (that logic lives in mistake_tagging.py), only whether it
        runs and at what threshold."""
        try:
            with self._session_factory() as session:
                rule = session.execute(select(MistakeRuleDefinition).where(MistakeRuleDefinition.rule_key == rule_key)).scalar_one_or_none()
                if rule is None:
                    return EngineResult(success=False, message=f"No mistake rule with rule_key={rule_key!r}")
                if enabled is not None:
                    rule.enabled = enabled
                if params is not None:
                    rule.params = params
            return EngineResult(success=True, message=f"Updated rule {rule_key}")
        except Exception as e:
            logger.error("Failed to update mistake rule %s: %s", rule_key, e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def compute_and_persist_mistake_tags(self, trade_id: int, risk_percent_used: Optional[float] = None) -> EngineResult:
        """Fetches `trade_id` plus every other logged trade (for revenge/
        overtrading/daily-loss/consecutive-loss history checks),
        evaluates every enabled MistakeRuleDefinition against it via
        mistake_tagging.evaluate_all_rules, and persists the results as
        TradeTag rows. Clears any previously-computed rule_adherence/
        behavioral tags for this trade first (idempotent -- calling this
        twice on the same trade doesn't duplicate tags), but leaves
        psychology tags (added manually, not by this method) untouched."""
        try:
            with self._session_factory() as session:
                trade = session.get(Trade, trade_id)
                if trade is None:
                    return EngineResult(success=False, message=f"No trade with id={trade_id}")

                other_trades = session.execute(select(Trade).where(Trade.id != trade_id)).scalars().all()
                history = [self._trade_to_record(t) for t in other_trades]

                kelly_pct = self._kelly_recommended_risk_pct(trade, other_trades)
                disagreeing = self._signal_had_disagreeing_layer(session, trade)
                this_record = self._trade_to_record(
                    trade, risk_percent_used=risk_percent_used,
                    kelly_recommended_risk_pct=kelly_pct, signal_had_disagreeing_layer=disagreeing,
                )

                rules_rows = session.execute(select(MistakeRuleDefinition)).scalars().all()
                rules = {r.rule_key: {"enabled": r.enabled, "params": r.params} for r in rules_rows}

                results = evaluate_all_rules(this_record, history, rules)

                session.query(TradeTag).filter(
                    TradeTag.trade_id == trade_id, TradeTag.category.in_(["rule_adherence", "behavioral"]),
                ).delete(synchronize_session=False)
                for r in results:
                    session.add(TradeTag(trade_id=trade_id, category=r.category, tag_key=r.tag_key, negative=r.negative, detail=r.detail))

            return EngineResult(success=True, data={"tags": [r.tag_key for r in results]}, message=f"{len(results)} mistake tag(s) computed")
        except Exception as e:
            logger.error("Failed to compute mistake tags for trade %s: %s", trade_id, e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def add_trade_tag(self, trade_id: int, category: str, tag_key: str, negative: bool, detail: Optional[dict] = None) -> EngineResult:
        """Manually attach a tag to a trade -- the path for psychology
        tags (category="psychology"), since those require human
        judgment, unlike rule_adherence/behavioral tags which are always
        computed automatically (see compute_and_persist_mistake_tags)."""
        try:
            with self._session_factory() as session:
                if session.get(Trade, trade_id) is None:
                    return EngineResult(success=False, message=f"No trade with id={trade_id}")
                tag = TradeTag(trade_id=trade_id, category=category, tag_key=tag_key, negative=negative, detail=detail or {})
                session.add(tag)
                session.flush()
                tag_id = tag.id
            return EngineResult(success=True, data={"tag_id": tag_id}, message="Tag added")
        except Exception as e:
            logger.error("Failed to add tag to trade %s: %s", trade_id, e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def list_trade_tags(self, trade_id: int) -> EngineResult:
        try:
            with self._session_factory() as session:
                rows = session.execute(select(TradeTag).where(TradeTag.trade_id == trade_id)).scalars().all()
                data = [{
                    "id": t.id, "category": t.category, "tag_key": t.tag_key,
                    "negative": t.negative, "detail": t.detail, "created_at": t.created_at,
                } for t in rows]
            return EngineResult(success=True, data=data, message=f"{len(data)} tag(s)")
        except Exception as e:
            logger.error("Failed to list tags for trade %s: %s", trade_id, e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def aggregate_mistake_costs(self, since: Optional[datetime] = None) -> EngineResult:
        """Phase 4 self-improvement feedback loop: for every mistake tag
        that has fired on a trade closed on/after `since` (default: 30
        days ago), sums the REAL logged pnl_r of every trade carrying
        that tag and counts how many trades it appeared on. Sorted by
        cumulative pnl_r ascending (worst/most costly first) -- answers
        "which mistake tag cost the most cumulative money" directly from
        real journal data. This is a SUGGESTION only: nothing here
        adjusts any live trading parameter, matching the platform's own
        no-execution-engine posture (Rule 5) and the user's own explicit
        instruction that this stays advisory."""
        since = since or (datetime.now(timezone.utc) - timedelta(days=30))
        try:
            by_tag: dict[str, dict[str, Any]] = defaultdict(lambda: {"trade_count": 0, "total_pnl_r": 0.0, "trade_ids": []})
            # Real bug found and fixed 2026-08-21 (caught during live
            # verification, not in a unit test -- the sqlite-backed unit
            # tests never exercise a real session lifecycle the way a
            # live Postgres call does): every ORM attribute this loop
            # reads (tag.tag_key, trade.pnl_r, trade.id) must be accessed
            # WHILE the session is still open. Doing it after the `with`
            # block closed raised a real DetachedInstanceError the moment
            # this endpoint was hit live -- SQLAlchemy tries to refresh
            # the now-stale instance from a session that no longer exists.
            with self._session_factory() as session:
                stmt = (
                    select(TradeTag, Trade)
                    .join(Trade, TradeTag.trade_id == Trade.id)
                    .where(TradeTag.category.in_(["rule_adherence", "behavioral"]))
                    .where(Trade.exit_time.isnot(None))
                    .where(Trade.exit_time >= since)
                )
                for tag, trade in session.execute(stmt).all():
                    bucket = by_tag[tag.tag_key]
                    bucket["trade_count"] += 1
                    bucket["total_pnl_r"] += float(trade.pnl_r or 0.0)
                    bucket["trade_ids"].append(trade.id)

            summary = [
                {"tag_key": key, "trade_count": v["trade_count"], "total_pnl_r": round(v["total_pnl_r"], 4), "trade_ids": v["trade_ids"]}
                for key, v in by_tag.items()
            ]
            summary.sort(key=lambda x: x["total_pnl_r"])
            return EngineResult(
                success=True, data={"since": since.isoformat(), "by_tag": summary},
                message=f"{len(summary)} mistake tag(s) with activity since {since.date()}",
            )
        except Exception as e:
            logger.error("Failed to aggregate mistake costs: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    @staticmethod
    def _trade_to_record(
        trade: Trade, risk_percent_used: Optional[float] = None,
        kelly_recommended_risk_pct: Optional[float] = None,
        signal_had_disagreeing_layer: Optional[bool] = None,
    ) -> TradeRecord:
        return TradeRecord(
            id=trade.id, entry_time=trade.entry_time, exit_time=trade.exit_time,
            pnl_r=float(trade.pnl_r) if trade.pnl_r is not None else None,
            pnl_percent=float(trade.pnl_percent) if trade.pnl_percent is not None else None,
            confidence_at_entry=trade.confidence_at_entry, risk_percent_used=risk_percent_used,
            kelly_recommended_risk_pct=kelly_recommended_risk_pct,
            signal_had_disagreeing_layer=signal_had_disagreeing_layer,
        )

    def _kelly_recommended_risk_pct(self, trade: Trade, other_trades: list) -> Optional[float]:
        """This strategy's own real historical Kelly-optimal risk fraction
        (E12's actual kelly_criterion, never reimplemented here) --
        computed from every OTHER closed trade under the SAME
        strategy_name with a real pnl_r. Requires at least 10 such trades
        (an arbitrary but documented floor -- a 2-3 trade sample makes
        Kelly's win_rate/payoff inputs too noisy to be a meaningful size
        reference) and a real quant_engine; returns None otherwise,
        matching every other honest-skip convention in this module."""
        if self._quant_engine is None or not trade.strategy_name:
            return None
        same_strategy_r = [
            float(t.pnl_r) for t in other_trades
            if t.strategy_name == trade.strategy_name and t.pnl_r is not None
        ]
        if len(same_strategy_r) < 10:
            return None
        wr = win_rate(same_strategy_r)
        if wr <= 0 or wr >= 1:
            return None
        avg = average_win_loss_r(same_strategy_r)
        avg_win = avg.get("avg_win_r")
        # average_win_loss_r's own convention returns avg_loss_r NEGATIVE
        # (it's the mean of the actual, signed losing pnl_rs) --
        # kelly_criterion's own docstring requires avg_loss as a POSITIVE
        # magnitude ("Average loss size... positive number"). Bug found
        # live (2026-09-13): passing the raw negative value straight
        # through made kelly_criterion's own `avg_loss <= 0` guard reject
        # every real, valid history, so this check silently never fired.
        avg_loss = -avg.get("avg_loss_r") if avg.get("avg_loss_r") else None
        if not avg_win or not avg_loss or avg_win <= 0 or avg_loss <= 0:
            return None
        try:
            result = self._quant_engine.kelly_criterion(wr, avg_win, avg_loss)
            if result.success and result.data is not None:
                # kelly_criterion returns a FRACTION of capital (e.g. 0.08
                # for 8%) -- this module's risk_percent_used convention is
                # a PERCENT (e.g. 1.0 for 1%), so convert once here rather
                # than push that unit conversion into the pure check
                # function or the caller of this method.
                half_kelly = getattr(result.data, "half_kelly_fraction", None)
                fraction = half_kelly if half_kelly is not None else getattr(result.data, "kelly_fraction", None)
                return float(fraction) * 100 if fraction is not None else None
        except Exception as e:
            logger.warning("Kelly computation failed for strategy %s (check skipped): %s", trade.strategy_name, e)
        return None

    @staticmethod
    def _signal_had_disagreeing_layer(session: Session, trade: Trade) -> Optional[bool]:
        """Scans this trade's linked Signal.evidence for the exact,
        consistently-generated marker phrase e51_signals' own confluence
        checks already use ("disagrees with direction" -- confirmed via
        grep to appear identically across all 11 confluence methods, a
        controlled internally-generated string, not fuzzy free text).
        None (not False) when there's no linked signal at all -- a
        discretionary trade has nothing to have "overridden"."""
        if trade.signal_id is None:
            return None
        signal = session.get(Signal, trade.signal_id)
        if signal is None or not signal.evidence:
            return None
        return any("disagrees with direction" in str(item) for item in signal.evidence)

    def list_trades(
        self,
        symbol: Optional[str] = None,
        strategy_name: Optional[str] = None,
        regime_at_entry: Optional[str] = None,
        limit: int = 500,
    ) -> EngineResult:
        try:
            with self._session_factory() as session:
                stmt = select(Trade)
                if symbol:
                    stmt = stmt.where(Trade.symbol == symbol.upper())
                if strategy_name:
                    stmt = stmt.where(Trade.strategy_name == strategy_name)
                if regime_at_entry:
                    stmt = stmt.where(Trade.regime_at_entry == regime_at_entry)
                stmt = stmt.order_by(Trade.entry_time.desc()).limit(limit)
                trades = list(session.execute(stmt).scalars().all())
                data = [self._trade_to_dict(t) for t in trades]
            return EngineResult(success=True, data=data, message=f"Found {len(data)} trade(s)")
        except Exception as e:
            logger.error("Failed to list trades: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def list_trades_with_evidence(self, limit: int = 5000) -> EngineResult:
        """Added 2026-08-21 for E34's confluence-accuracy scoreboard
        (attribute_by_confluence_tag) -- same as list_trades() but joins
        each trade's linked Signal (via Trade.signal_id) and includes its
        real `evidence` list (the same reasoning bullets already shown on
        the dashboard's signal cards, e.g. "Confluence: tracked
        cross-asset relationship(s) (E10) intact"). Trades with no linked
        signal (signal_id is nullable -- a discretionary trade never has
        to have come from an E51 signal) get evidence=[] rather than
        being excluded, so the scoreboard's denominator honestly reflects
        every trade, not just signal-originated ones."""
        try:
            with self._session_factory() as session:
                stmt = (
                    select(Trade, Signal.evidence)
                    .outerjoin(Signal, Trade.signal_id == Signal.id)
                    .order_by(Trade.entry_time.desc())
                    .limit(limit)
                )
                data = []
                for trade, evidence in session.execute(stmt).all():
                    row = self._trade_to_dict(trade)
                    row["evidence"] = evidence or []
                    data.append(row)
            return EngineResult(success=True, data=data, message=f"Found {len(data)} trade(s) with evidence")
        except Exception as e:
            logger.error("Failed to list trades with evidence: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def signal_conversion_rate(self, symbol: Optional[str] = None, limit: int = 20000) -> EngineResult:
        """docs/UPGRADE_BRIEF.md Phase 9: "also log signals that were NOT
        taken -- skipped-signal data is where discipline is measured."
        Every E51 signal is already persisted via api/main.py's own
        _persist_signal, and Trade.signal_id marks which ones were acted
        on -- so "signals not taken" was already reconstructable data, just
        never surfaced as an actual metric. This is a READ-ONLY query over
        both existing tables, not a new capture mechanism: an outer join
        from Signal to Trade, counting how many signals have zero linked
        trades.

        Returns generated/taken counts and a take_rate (None, not a
        fabricated 0.0, when zero signals exist for the filter)."""
        try:
            with self._session_factory() as session:
                stmt = select(Signal.id, Signal.asset, func.count(Trade.id)).outerjoin(
                    Trade, Trade.signal_id == Signal.id
                )
                if symbol:
                    stmt = stmt.where(Signal.asset == symbol.upper())
                stmt = stmt.group_by(Signal.id, Signal.asset).limit(limit)
                rows = session.execute(stmt).all()

            n_generated = len(rows)
            n_taken = sum(1 for _, _, trade_count in rows if trade_count > 0)
            take_rate = (n_taken / n_generated) if n_generated > 0 else None

            by_symbol: dict[str, dict[str, int]] = defaultdict(lambda: {"generated": 0, "taken": 0})
            for _, asset, trade_count in rows:
                by_symbol[asset]["generated"] += 1
                if trade_count > 0:
                    by_symbol[asset]["taken"] += 1

            return EngineResult(
                success=True,
                data={
                    "n_generated": n_generated,
                    "n_taken": n_taken,
                    "take_rate": round(take_rate, 4) if take_rate is not None else None,
                    "by_symbol": dict(by_symbol),
                },
                message=f"{n_taken}/{n_generated} generated signals were taken" if n_generated else "No signals recorded yet",
            )
        except Exception as e:
            logger.error("Failed to compute signal conversion rate: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def summarize(
        self,
        symbol: Optional[str] = None,
        strategy_name: Optional[str] = None,
        regime_at_entry: Optional[str] = None,
        limit: int = 5000,
    ) -> EngineResult:
        trades_result = self.list_trades(symbol, strategy_name, regime_at_entry, limit)
        if not trades_result.success:
            return trades_result
        trades = trades_result.data
        if not trades:
            return EngineResult(success=False, message="No trades match the given filters")
        pnl_rs = [t["pnl_r"] or 0.0 for t in trades]
        pnl_pcts = [t["pnl_percent"] or 0.0 for t in trades]
        entry_times = [t["entry_time"] for t in trades]
        exit_times = [t["exit_time"] for t in trades]
        return EngineResult(
            success=True,
            data=summarize(pnl_rs, pnl_pcts, entry_times=entry_times, exit_times=exit_times),
            message="Performance summary computed",
        )

    @staticmethod
    def _trade_to_dict(trade: Trade) -> dict[str, Any]:
        return {
            "id": trade.id,
            "signal_id": trade.signal_id,
            "symbol": trade.symbol,
            "direction": trade.direction,
            "strategy_name": trade.strategy_name,
            "setup": trade.setup,
            "timeframe": trade.timeframe,
            "confidence_at_entry": trade.confidence_at_entry,
            "entry_price": trade.entry_price,
            "exit_price": trade.exit_price,
            "entry_time": trade.entry_time,
            "exit_time": trade.exit_time,
            "pnl_r": trade.pnl_r,
            "pnl_percent": trade.pnl_percent,
            "mae_r": trade.mae_r,
            "mfe_r": trade.mfe_r,
            "slippage_r": trade.slippage_r,
            "screenshot_url": trade.screenshot_url,
            "regime_at_entry": trade.regime_at_entry,
            "session_tag": trade.session_tag,
            "execution_cost": trade.execution_cost,
            "notes": trade.notes,
            "created_at": trade.created_at,
        }
