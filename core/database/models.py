"""
Module: models.py
Description: SQLAlchemy ORM models for PROJECT TITAN-X.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-06-28
"""

from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base declarative class for all ORM models."""


class OHLCV(Base):
    """OHLCV candlestick market data."""

    __tablename__ = "ohlcv"
    __table_args__ = (UniqueConstraint("symbol", "timeframe", "timestamp"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    high: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    low: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    close: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TraderProfile(Base):
    """Trader knowledge profile from the intelligence library."""

    __tablename__ = "trader_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    biography: Mapped[Optional[str]] = mapped_column(Text)
    philosophy: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    frameworks: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    success_patterns: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    failure_patterns: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    regime_suitability: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    embedding_id: Mapped[Optional[str]] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Strategy(Base):
    """Registered trading strategy with version history."""

    __tablename__ = "strategies"
    __table_args__ = (UniqueConstraint("name", "version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0.0")
    description: Mapped[Optional[str]] = mapped_column(Text)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    best_regime: Mapped[Optional[str]] = mapped_column(String(50))
    worst_regime: Mapped[Optional[str]] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="research")
    sharpe_backtest: Mapped[Optional[float]] = mapped_column(Numeric(6, 3))
    sharpe_live: Mapped[Optional[float]] = mapped_column(Numeric(6, 3))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    signals: Mapped[list["Signal"]] = relationship("Signal", back_populates="strategy")


class Signal(Base):
    """Trading signal with full metadata and evidence."""

    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    strategy_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("strategies.id"))
    asset: Mapped[str] = mapped_column(String(20), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    entry_price: Mapped[Optional[float]] = mapped_column(Numeric(18, 6))
    stop_loss: Mapped[Optional[float]] = mapped_column(Numeric(18, 6))
    take_profit_1: Mapped[Optional[float]] = mapped_column(Numeric(18, 6))
    take_profit_2: Mapped[Optional[float]] = mapped_column(Numeric(18, 6))
    risk_percent: Mapped[Optional[float]] = mapped_column(Numeric(5, 2))
    confidence_score: Mapped[Optional[int]] = mapped_column(Integer)
    expected_value: Mapped[Optional[float]] = mapped_column(Numeric(6, 3))
    regime: Mapped[Optional[str]] = mapped_column(String(50))
    evidence: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    invalidation: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    strategy: Mapped[Optional["Strategy"]] = relationship("Strategy", back_populates="signals")
    trades: Mapped[list["Trade"]] = relationship("Trade", back_populates="signal")


class Trade(Base):
    """
    Closed trade with attribution and lessons -- always a manually-logged,
    retrospective journal entry (this platform has no execution engine, see
    CLAUDE.md Rule 5). signal_id optionally links back to the specific E51
    signal that prompted it (for richer attribution against that signal's
    own recorded confidence/regime/evidence); symbol/direction/strategy_name
    are also stored directly (not only derivable via signal) because a
    trade the user logs did not necessarily originate from an E51 signal at
    all -- a purely discretionary or externally-sourced trade still needs a
    home here.
    """

    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    signal_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("signals.id"))
    symbol: Mapped[Optional[str]] = mapped_column(String(20), index=True)
    direction: Mapped[Optional[str]] = mapped_column(String(10))
    strategy_name: Mapped[Optional[str]] = mapped_column(String(64), index=True, default="unspecified")
    # The signal's confidence_score at the moment this trade was taken --
    # denormalized (not only derivable via signal_id) for the same reason
    # symbol/direction are: a purely discretionary trade with no linked E51
    # signal still needs a confidence value to feed e42_confidence_calibration.
    confidence_at_entry: Mapped[Optional[int]] = mapped_column(Integer)
    # 32, not 16 -- session_tag_from_hour's own "london_or_new_york"/
    # "london_ny_overlap" labels are 17-18 chars, wider than a plausible-
    # looking-but-too-narrow first guess.
    session_tag: Mapped[Optional[str]] = mapped_column(String(32))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    entry_price: Mapped[Optional[float]] = mapped_column(Numeric(18, 6))
    exit_price: Mapped[Optional[float]] = mapped_column(Numeric(18, 6))
    entry_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    exit_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    pnl_r: Mapped[Optional[float]] = mapped_column(Numeric(8, 4))
    pnl_percent: Mapped[Optional[float]] = mapped_column(Numeric(8, 4))
    regime_at_entry: Mapped[Optional[str]] = mapped_column(String(50))
    execution_cost: Mapped[Optional[float]] = mapped_column(Numeric(8, 4))
    attribution: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    lessons: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    # Added 2026-09-13, closing real docs/UPGRADE_BRIEF.md Phase 9 gaps
    # (verified absent by direct inspection before adding, not assumed):
    setup: Mapped[Optional[str]] = mapped_column(String(64))
    timeframe: Mapped[Optional[str]] = mapped_column(String(10))
    # MAE/MFE (Maximum Adverse/Favorable Excursion), in R-multiples,
    # SERVER-COMPUTED from real OHLCV between entry_time/exit_time at log
    # time (see PerformanceAnalyticsEngine.log_trade) -- never a client-
    # supplied number, so these are absent from TradeCreate. None (not
    # 0.0) when the real bars for that exact window aren't available,
    # same "honest gap, never fabricated" convention as everywhere else
    # in this codebase.
    mae_r: Mapped[Optional[float]] = mapped_column(Numeric(8, 4))
    mfe_r: Mapped[Optional[float]] = mapped_column(Numeric(8, 4))
    # Self-reported, same honesty convention as risk_percent_used (this
    # platform has no execution engine and captures no real fill data) --
    # realized exit price vs. the price the user intended, in R-multiples.
    slippage_r: Mapped[Optional[float]] = mapped_column(Numeric(8, 4))
    # A plain external link, not file storage this platform doesn't have
    # -- "screenshot refs," not "screenshot hosting" (see this field's own
    # design note in the Phase 9 plan: E36's docstring already documented
    # "screenshots: no real implementation" as an honest, permanent gap;
    # this closes the referenceable-link half of that honestly, without
    # fabricating an upload backend).
    screenshot_url: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    signal: Mapped[Optional["Signal"]] = relationship("Signal", back_populates="trades")
    # ORM-side only -- ForeignKey lives on TradeTag, so this adds no
    # column/migration to the `trades` table itself (see TradeTag below,
    # added 2026-08-21 for the self-improvement journal).
    tags: Mapped[list["TradeTag"]] = relationship("TradeTag", back_populates="trade")


class SignalContextSnapshot(Base):
    """
    Added 2026-08-21 for the self-improvement trade journal. One row per
    signal, written automatically at signal-generation time (see
    api/main.py's _persist_signal) -- NOT written by the user, so this is
    always real, captured-before-any-outcome-bias context, never a
    reconstructed-after-the-fact guess.

    Deliberately minimal: confidence_score/regime/evidence already live on
    the `signals` table this row's signal_id points to (Signal.
    confidence_score, .regime, .evidence) -- duplicating them here would
    restructure nothing but would drift the moment either table changed,
    so this table only stores the ONE piece of context that genuinely
    doesn't exist anywhere else yet: whether the signal fired inside a
    real ICT killzone (engines/e07_technical/killzones.py). A trade's full
    context is the join trades.signal_id -> signals -> this table, not a
    copy of the same facts in two places.
    """

    __tablename__ = "signal_context_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # ondelete="CASCADE" -- same reasoning as TradeTag.trade_id below: this
    # row has no meaning independent of the signal it was captured for.
    signal_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("signals.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    killzone_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Names of every ICT killzone active at generation time (a bar can be
    # inside more than one, e.g. NY Open AND the NY AM Silver Bullet) --
    # see Killzone enum in engines/e07_technical/killzones.py for the
    # real, fixed set of possible values. Empty list, not null, when none
    # were active.
    active_killzones: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MistakeRuleDefinition(Base):
    """
    Added 2026-08-21. The user's own small, editable set of rules a logged
    trade gets automatically checked against (see engines/
    e35_performance_analytics/mistake_tagging.py) -- deliberately NOT a
    manual pre-trade checklist a human has to remember to fill in (a real
    bug found while auditing tradicted/tradicted-journal for this exact
    feature: its own pre-trade checklist UI never actually persisted what
    got checked). rule_key is a fixed, code-known identifier (the
    detection logic for each key lives in mistake_tagging.py); params
    lets the user tune the threshold (e.g. {"min_confidence": 65}) without
    a code change. Seeded with sensible defaults on first use, not
    hardcoded -- see MistakeTaggingEngine.ensure_default_rules.
    """

    __tablename__ = "mistake_rule_definitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)  # "rule_adherence" | "behavioral"
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TradeIntent(Base):
    """
    Added 2026-08-21. A manual "I took this trade" acknowledgment,
    written the moment a human clicks the mark-as-taken button on a
    signal card -- captures the intended entry snapshot BEFORE outcome
    bias can creep into memory, closing this journal's own hindsight-bias
    gap (the trade record logged later, possibly days after close, is
    reconstructed from memory otherwise). This is still purely
    retrospective journaling metadata, not an order -- it records that a
    human says they acted, it does not act. No execution engine, no
    broker call, no live order of any kind (Rule 5, non-negotiable). A
    trade later logged via /performance/trades for the same signal_id is
    a separate, independent record; this table is never read by any
    pricing/execution/risk-sizing code path, only by the journal UI to
    prefill the eventual close-out form.
    """

    __tablename__ = "trade_intents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    signal_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("signals.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    intended_entry_price: Mapped[Optional[float]] = mapped_column(Numeric(18, 6))
    marked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TradeTag(Base):
    """
    Added 2026-08-21. One row per (trade, tag) -- unifies rule-violation,
    behavioral, and psychology tags in a single table (borrowing
    TradeNote's generic-tag pattern, crossed with tradicted-journal's
    `negative: boolean` on psychology tags) rather than three separate
    tables, since "group all my trades by tag, across categories" is
    exactly the kind of always-on pattern-surfacing TradeNote's own
    11-axis grouping engine does well. `detail` carries the specific
    numbers that made the tag fire (e.g. {"required": 65, "actual": 52}
    for below_confluence_threshold) so a trade's tag is never just an
    unexplained label.
    """

    __tablename__ = "trade_tags"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # ondelete="CASCADE" -- a tag has no meaning independent of its trade.
    # Real bug found and fixed 2026-08-21 during live verification:
    # without this, deleting a Trade that had any tags (which is now
    # EVERY logged trade, since log_trade auto-computes tags) raised a
    # real psycopg2 ForeignKeyViolation -- caught by this feature's own
    # new tests failing, but it also broke a pre-existing, unrelated
    # test's cleanup helper the same way, since that helper deletes
    # trades directly and had no reason to expect a new dependent table.
    trade_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("trades.id", ondelete="CASCADE"), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(30), nullable=False)  # "rule_adherence" | "behavioral" | "psychology"
    tag_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # True when this tag represents an undesirable/costly pattern. Always
    # True for rule_adherence/behavioral tags (they only ever fire on a
    # violation) -- present as a real column (not inferred from category)
    # because psychology tags vary: "disciplined" is a psychology tag with
    # negative=False, "revenge" is negative=True, same pattern
    # tradicted-journal's own psych_tag taxonomy uses.
    negative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    trade: Mapped["Trade"] = relationship("Trade", back_populates="tags")


class MacroRegime(Base):
    """Daily macro regime classification."""

    __tablename__ = "macro_regimes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, unique=True)
    regime: Mapped[str] = mapped_column(String(50), nullable=False)
    risk_on_off: Mapped[Optional[float]] = mapped_column(Numeric(3, 2))
    liquidity_score: Mapped[Optional[float]] = mapped_column(Numeric(3, 2))
    currency_strength: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AlphaHypothesis(Base):
    """Alpha research hypothesis with test results."""

    __tablename__ = "alpha_hypotheses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hypothesis: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="idea")
    sharpe_result: Mapped[Optional[float]] = mapped_column(Numeric(6, 3))
    win_rate: Mapped[Optional[float]] = mapped_column(Numeric(5, 4))
    test_results: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    validated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class RiskEvent(Base):
    """CRO risk event audit log."""

    __tablename__ = "risk_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    event_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    veto_applied: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    """Security audit log for all system actions."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource: Mapped[Optional[str]] = mapped_column(String(100))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    ip_address: Mapped[Optional[str]] = mapped_column(INET)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NewsEvent(Base):
    """
    Added 2026-09-13 for docs/UPGRADE_BRIEF.md Phase 11 (News + Sentiment).
    One row per de-duplicated news item that survived the E03->E09
    enrichment pipeline (see engines/e03_news/enrichment.py).

    Two deliberately distinct timestamps -- the brief asks for this, and
    conflating them would misrepresent something RSS feeds don't actually
    give us:
      - source_timestamp: the feed's own claimed publish time (may be
        absent, backdated, or simply wrong -- it's whatever the publisher
        put in the feed, not verified).
      - published_timestamp: when Titan-X itself actually ingested the
        item (server_default=now(), always real and monotonic for this
        platform's own processing).
    Neither one is a "true event occurrence time" -- RSS feeds don't carry
    that, and fabricating one would violate Rule 4. as_of-based lookahead
    filtering (see fetch_headlines(as_of=...)) filters on source_timestamp,
    since that's the publisher's own claimed knowledge-available time.
    """

    __tablename__ = "news_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    link: Mapped[str] = mapped_column(String(1000), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text)
    # sha256 of the normalized (lowercased, whitespace-collapsed) title --
    # the dedup key. Catches both re-fetching the same feed entry and the
    # same wire headline appearing verbatim across two different feeds.
    # Deliberately NOT fuzzy/near-duplicate matching across differently
    # worded coverage of the same story -- that would need a similarity
    # model this platform doesn't have and isn't in Phase 11's stated scope
    # ("duplicate-news prevention", not "same-story clustering").
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    source_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    published_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Symbols from core.config.assets.SUPPORTED_ASSETS matched in the
    # title/summary text (see engines/e03_news/enrichment.py:extract_entities)
    # -- deterministic keyword/alias matching against this platform's own
    # known instrument universe, never a trained NER model.
    entities: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    # One of enrichment.EVENT_TYPES -- deterministic keyword classification,
    # never a trained classifier (see that module's own docstring).
    event_type: Mapped[str] = mapped_column(String(30), nullable=False, default="other")
    sentiment_label: Mapped[Optional[str]] = mapped_column(String(10))
    sentiment_score: Mapped[Optional[float]] = mapped_column(Numeric(6, 4))
    # abs(sentiment_score) * this event_type's weight -- see
    # enrichment.market_impact_score for the exact, documented formula.
    market_impact_score: Mapped[Optional[float]] = mapped_column(Numeric(6, 4))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OptionChainOISnapshot(Base):
    """
    Added 2026-09-13 for docs/UPGRADE_ROADMAP.md P1 item 5, closing the
    "OI change" gap docs/UPGRADE_BRIEF.md Phase 10 itself flagged as
    honestly incomplete: every option-chain read was previously stateless,
    so no "change since last read" could ever be computed.

    One row per (symbol, expiry, strike, option_type) PER READ of
    GET /api/v1/derivatives/india-option-chain -- api/main.py's route
    persists a full batch (all strikes/legs from one read) sharing the
    same `captured_at`, then on the NEXT read looks up the most recent
    prior batch by MAX(captured_at) for the same (symbol, expiry) and
    diffs oi against it. Deliberately named distinctly from
    core.data_providers.kite_option_chain's own (non-persisted)
    OptionChainSnapshot/OptionChainRow dataclasses -- this is the
    persistence-layer sibling, not a duplicate.

    Not deduplicated/merged across reads: every read is its own real,
    timestamped observation, kept permanently (like OHLCV bars), not
    upserted -- the same "compute once, read many, keep the history"
    convention as this table's siblings, and because deleting the
    superseded batch would make "how much did OI change over the last N
    reads" unanswerable later.
    """

    __tablename__ = "option_chain_oi_snapshots"
    __table_args__ = (
        UniqueConstraint("symbol", "expiry", "strike", "option_type", "captured_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    expiry: Mapped[date] = mapped_column(Date, nullable=False)
    strike: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    option_type: Mapped[str] = mapped_column(String(2), nullable=False)  # "CE" or "PE"
    oi: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    # Set explicitly by the route to one shared value per batch (not left
    # to server_default's per-row/per-transaction timing) so "the most
    # recent batch" is an exact, unambiguous MAX(captured_at) match.
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
