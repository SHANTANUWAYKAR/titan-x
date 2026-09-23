"""
Tests for Engine 34 -- Trade Attribution.

attribute_by_field's own grouping/best-worst logic is tested against a
STUB PerformanceAnalyticsEngine (no real database needed -- this engine's
own logic is pure grouping + arithmetic on whatever list_trades returns).
One real-collaborator test (Rule 4) confirms it actually works against the
REAL PerformanceAnalyticsEngine's real return shape, not just the stub's
assumed shape.
"""

import datetime as dt

import pytest

from project_titan_x.engines.e34_trade_attribution.engine import (
    TradeAttributionEngine,
    day_of_week_tag,
    session_tag_from_hour,
)
from project_titan_x.engines.e35_performance_analytics.engine import PerformanceAnalyticsEngine


def test_day_of_week_tag():
    monday = dt.datetime(2026, 7, 13, 10, 0)  # a known Monday
    assert day_of_week_tag(monday) == "Monday"


@pytest.mark.parametrize(
    "hour,expected",
    [(3, "asian"), (9, "london_or_new_york"), (13, "london_ny_overlap"), (22, "asian")],
)
def test_session_tag_from_hour(hour, expected):
    assert session_tag_from_hour(hour) == expected


class _StubResult:
    def __init__(self, success=True, data=None, message=""):
        self.success = success
        self.data = data
        self.message = message


class _StubPerformanceEngine:
    def __init__(self, trades):
        self._trades = trades

    def list_trades(self, symbol=None, strategy_name=None, regime_at_entry=None, limit=5000):
        return _StubResult(True, self._trades)

    def list_trades_with_evidence(self, limit=5000):
        return _StubResult(True, self._trades)

    def health_check(self):
        return _StubResult(True)


_SAMPLE_TRADES = [
    {"pnl_r": 2.0, "pnl_percent": 0.02, "strategy_name": "donchian", "regime_at_entry": "Trending Up", "symbol": "SP500", "direction": "long", "session_tag": "new_york"},
    {"pnl_r": -1.0, "pnl_percent": -0.01, "strategy_name": "donchian", "regime_at_entry": "Ranging", "symbol": "SP500", "direction": "long", "session_tag": "asian"},
    {"pnl_r": -1.5, "pnl_percent": -0.015, "strategy_name": "heuristic", "regime_at_entry": "Ranging", "symbol": "GOLD", "direction": "short", "session_tag": None},
]


def test_attribute_by_field_groups_correctly():
    engine = TradeAttributionEngine(performance_engine=_StubPerformanceEngine(_SAMPLE_TRADES))
    result = engine.attribute_by_field("strategy_name")
    assert result.success
    groups = result.data["groups"]
    assert set(groups.keys()) == {"donchian", "heuristic"}
    assert groups["donchian"].n_trades == 2
    assert groups["heuristic"].n_trades == 1


def test_attribute_by_field_reports_best_and_worst_group():
    engine = TradeAttributionEngine(performance_engine=_StubPerformanceEngine(_SAMPLE_TRADES))
    result = engine.attribute_by_field("strategy_name")
    assert result.data["best_group"] == "donchian"  # expectancy (2.0 + -1.0)/2 = 0.5
    assert result.data["worst_group"] == "heuristic"  # expectancy -1.5


def test_attribute_by_field_null_tag_becomes_unspecified():
    engine = TradeAttributionEngine(performance_engine=_StubPerformanceEngine(_SAMPLE_TRADES))
    result = engine.attribute_by_field("session_tag")
    assert "unspecified" in result.data["groups"]


def test_attribute_by_field_rejects_disallowed_field():
    engine = TradeAttributionEngine(performance_engine=_StubPerformanceEngine(_SAMPLE_TRADES))
    result = engine.attribute_by_field("notes")  # not in ALLOWED_ATTRIBUTION_FIELDS
    assert not result.success


def test_attribute_by_field_no_trades_fails_gracefully():
    engine = TradeAttributionEngine(performance_engine=_StubPerformanceEngine([]))
    result = engine.attribute_by_field("strategy_name")
    assert not result.success


# ---- day_of_week attribution (was dead code -- day_of_week_tag existed
# but attribute_by_field never actually derived a group key from it) ----

_DOW_TRADES = [
    {"pnl_r": 1.0, "pnl_percent": 0.01, "entry_time": dt.datetime(2026, 7, 13, 10, 0)},  # Monday
    {"pnl_r": -1.0, "pnl_percent": -0.01, "entry_time": dt.datetime(2026, 7, 13, 15, 0)},  # Monday
    {"pnl_r": 2.0, "pnl_percent": 0.02, "entry_time": dt.datetime(2026, 7, 17, 9, 0)},  # Friday
    {"pnl_r": 0.5, "pnl_percent": 0.005, "entry_time": None},  # no entry_time on record
]


def test_attribute_by_field_day_of_week_is_derived_from_entry_time():
    engine = TradeAttributionEngine(performance_engine=_StubPerformanceEngine(_DOW_TRADES))
    result = engine.attribute_by_field("day_of_week")
    assert result.success
    groups = result.data["groups"]
    assert set(groups.keys()) == {"Monday", "Friday", "unspecified"}
    assert groups["Monday"].n_trades == 2
    assert groups["Friday"].n_trades == 1
    assert groups["unspecified"].n_trades == 1


# ---- confluence-accuracy scoreboard (added 2026-08-21) ----

_CONFLUENCE_TRADES = [
    {
        "pnl_r": 2.0, "pnl_percent": 0.02,
        "evidence": ["Confluence: tracked cross-asset relationship(s) (E10) intact"],
    },
    {
        "pnl_r": 1.5, "pnl_percent": 0.015,
        "evidence": ["Confluence: tracked cross-asset relationship(s) (E10) intact"],
    },
    {
        "pnl_r": -1.0, "pnl_percent": -0.01,
        "evidence": ["Confluence: a tracked cross-asset relationship (E10) is breaking down"],
    },
    {
        "pnl_r": 0.8, "pnl_percent": 0.008,
        "evidence": ["Confluence: high execution risk (E11) — confidence tempered"],
    },
    {"pnl_r": 0.3, "pnl_percent": 0.003, "evidence": []},  # no confluence evidence at all
    {"pnl_r": -0.4, "pnl_percent": -0.004, "evidence": None},  # discretionary trade, no linked signal
]


def test_attribute_by_confluence_tag_groups_by_engine_and_classification():
    engine = TradeAttributionEngine(performance_engine=_StubPerformanceEngine(_CONFLUENCE_TRADES))
    result = engine.attribute_by_confluence_tag()
    assert result.success
    assert set(result.data.keys()) == {"(E10)", "(E11)"}
    assert result.data["(E10)"]["agree"].n_trades == 2
    assert result.data["(E10)"]["disagree"].n_trades == 1
    assert "agree" not in result.data["(E11)"]  # "confidence tempered" classifies as disagree, never agree
    assert result.data["(E11)"]["disagree"].n_trades == 1


def test_attribute_by_confluence_tag_agree_bucket_has_better_expectancy():
    """The real point of this feature: an "agree" bucket that performs
    worse than "disagree" would be a genuine, useful finding -- this
    fixture is deliberately constructed so agree performs better, and
    the test confirms the arithmetic actually reflects that rather than
    just checking bucket membership."""
    engine = TradeAttributionEngine(performance_engine=_StubPerformanceEngine(_CONFLUENCE_TRADES))
    result = engine.attribute_by_confluence_tag()
    e10 = result.data["(E10)"]
    assert e10["agree"].expectancy_r > e10["disagree"].expectancy_r


def test_attribute_by_confluence_tag_ignores_trades_with_no_confluence_evidence():
    """Trades with evidence=[] or evidence=None (no linked signal) must
    never be silently forced into a fabricated bucket."""
    engine = TradeAttributionEngine(performance_engine=_StubPerformanceEngine(_CONFLUENCE_TRADES))
    result = engine.attribute_by_confluence_tag()
    total_bucketed = sum(c.n_trades for classes in result.data.values() for c in classes.values())
    assert total_bucketed == 4  # only the 4 trades with a real (E##) tag in their evidence


def test_attribute_by_confluence_tag_no_evidence_anywhere_fails_gracefully():
    engine = TradeAttributionEngine(performance_engine=_StubPerformanceEngine([
        {"pnl_r": 1.0, "pnl_percent": 0.01, "evidence": []},
    ]))
    result = engine.attribute_by_confluence_tag()
    assert not result.success


@pytest.mark.network
def test_attribute_by_confluence_tag_uses_real_signal_evidence_join():
    """Real-collaborator test: writes a real Signal row with real
    (E10)-tagged evidence, a real Trade linking to it via signal_id, and
    confirms list_trades_with_evidence's actual JOIN + attribute_by_
    confluence_tag's parsing work against the real Postgres schema, not
    just the stub's assumed shape."""
    from sqlalchemy import delete
    from project_titan_x.core.database.models import Signal, Trade
    from project_titan_x.core.database.session import get_db_session

    performance_engine = PerformanceAnalyticsEngine()
    performance_engine.initialize()
    strategy = "test_e34_confluence_real_collab_unique_tag"
    signal_id = None
    try:
        with get_db_session() as session:
            row = Signal(
                asset="EURUSD", direction="LONG", entry_price=1.10,
                evidence=["Confluence: tracked cross-asset relationship(s) (E10) intact"],
                status="pending",
            )
            session.add(row)
            session.flush()
            signal_id = row.id

        now = dt.datetime.now(dt.timezone.utc)
        performance_engine.log_trade(
            symbol="EURUSD", direction="long", entry_price=1.10, exit_price=1.11,
            entry_time=now, exit_time=now, pnl_r=1.5, pnl_percent=0.01,
            strategy_name=strategy, signal_id=signal_id,
        )

        engine = TradeAttributionEngine(performance_engine=performance_engine)
        result = engine.attribute_by_confluence_tag(limit=20000)
        assert result.success
        assert "(E10)" in result.data
        assert result.data["(E10)"]["agree"].n_trades >= 1
    finally:
        with get_db_session() as session:
            session.execute(delete(Trade).where(Trade.strategy_name == strategy))
            if signal_id is not None:
                session.execute(delete(Signal).where(Signal.id == signal_id))


@pytest.mark.network
def test_attribute_by_field_uses_real_performance_engine():
    """Real-collaborator test (Rule 4): confirms attribute_by_field's field
    access (t["pnl_r"], t["pnl_percent"], t.get(field)) matches
    PerformanceAnalyticsEngine.list_trades' REAL dict shape, not a stub's
    assumed shape. Cleans up its own rows (CLAUDE.md Rule 4: "clean up
    test/exploration residue from real persistent stores") since this
    writes to the real, shared Postgres dev database."""
    from sqlalchemy import delete
    from project_titan_x.core.database.models import Trade
    from project_titan_x.core.database.session import get_db_session

    performance_engine = PerformanceAnalyticsEngine()
    performance_engine.initialize()
    strategy = "test_e34_real_collab_unique_tag"
    try:
        now = dt.datetime.now(dt.timezone.utc)
        for pnl_r, pnl_pct, regime in [(1.0, 0.01, "Trending Up"), (-1.0, -0.01, "Ranging")]:
            performance_engine.log_trade(
                symbol="SILVER", direction="long", entry_price=25.0, exit_price=25.5,
                entry_time=now, exit_time=now, pnl_r=pnl_r, pnl_percent=pnl_pct,
                strategy_name=strategy, regime_at_entry=regime,
            )
        engine = TradeAttributionEngine(performance_engine=performance_engine)
        result = engine.attribute_by_field("strategy_name", limit=20000)
        assert result.success
        assert strategy in result.data["groups"]
        assert result.data["groups"][strategy].n_trades == 2
    finally:
        with get_db_session() as session:
            session.execute(delete(Trade).where(Trade.strategy_name == strategy))
