"""
Module: test_economic_calendar_engine.py
Description: Unit tests for Engine 05 (Economic Calendar Intelligence).
Author: Shantanu Waykar
Version: 1.0.0
"""

from datetime import datetime, timedelta, timezone

import pytest

from project_titan_x.engines.e05_economic_calendar.engine import (
    EconomicCalendarEngine,
    EventImpact,
    _first_friday_8_30am_et,
    _match_calibrated_event_key,
    _month_iter,
)
from tests._artifacts import requires_data


@pytest.fixture
def engine() -> EconomicCalendarEngine:
    e = EconomicCalendarEngine()
    e.initialize()
    return e


def test_first_friday_is_always_a_friday():
    for year in (2024, 2025, 2026):
        for month in range(1, 13):
            d = _first_friday_8_30am_et(year, month)
            assert d.weekday() == 4  # Friday
            assert d.day <= 7  # first Friday must fall within days 1-7


def test_first_friday_is_first_occurrence_not_a_later_one():
    # January 2026: Jan 1 2026 is a Thursday, so first Friday is Jan 2.
    d = _first_friday_8_30am_et(2026, 1)
    assert d.day == 2


def test_month_iter_covers_inclusive_range():
    start = datetime(2024, 11, 15, tzinfo=timezone.utc)
    end = datetime(2025, 2, 3, tzinfo=timezone.utc)
    months = list(_month_iter(start, end))
    assert months == [(2024, 11), (2024, 12), (2025, 1), (2025, 2)]


def test_upcoming_events_within_window_are_returned(engine):
    ref = datetime(2026, 7, 1, tzinfo=timezone.utc)
    events = engine.upcoming_events(reference=ref, lookahead_days=10, lookback_days=0)
    # 1 NFP (Jul 3) + 2 Initial Jobless Claims Thursdays (Jul 2, Jul 9) --
    # the latter added 2026-08-02 as a second real recurring event.
    assert len(events) == 3
    nfp_events = [e for e in events if e.name == "US Non-Farm Payrolls"]
    assert len(nfp_events) == 1
    assert nfp_events[0].impact == EventImpact.HIGH
    assert nfp_events[0].date_confirmed is True
    claims_events = [e for e in events if e.name == "US Initial Jobless Claims"]
    assert len(claims_events) == 2
    assert all(e.impact == EventImpact.MEDIUM and e.date_confirmed for e in claims_events)


def test_upcoming_events_outside_window_are_excluded(engine):
    ref = datetime(2026, 7, 10, tzinfo=timezone.utc)
    events = engine.upcoming_events(reference=ref, lookahead_days=5, lookback_days=0)
    assert events == []


def test_analyze_flags_high_impact_within_24h(engine):
    nfp_date = _first_friday_8_30am_et(2026, 8)
    just_before = nfp_date.astimezone(timezone.utc) - timedelta(hours=2)
    result = engine.analyze(reference=just_before, lookahead_days=1)
    assert result.success
    assert result.data.high_impact_within_24h is True
    assert result.data.high_impact_within_1h is False


def test_analyze_returns_no_events_when_none_upcoming(engine):
    ref = datetime(2026, 7, 4, tzinfo=timezone.utc)  # right after Jul 3 NFP, well before Aug 7 NFP
    result = engine.analyze(reference=ref, lookahead_days=10)
    assert result.success
    # No HIGH-impact NFP in this window, but a MEDIUM-impact Initial Jobless
    # Claims Thursday (Jul 9) still falls in range -- confirms the
    # no-high-impact-upcoming case still degrades correctly with a real
    # MEDIUM event present, not that the calendar is literally empty.
    assert {e.name for e in result.data.upcoming_events} == {"US Initial Jobless Claims"}
    assert result.data.high_impact_within_24h is False


# ---- per-asset volatility calibration ----


def test_resolve_symbol_key_normalizes_various_forms(engine):
    assert engine._resolve_symbol_key("EURUSD=X") == "EURUSD"
    assert engine._resolve_symbol_key("eurusd") == "EURUSD"
    assert engine._resolve_symbol_key("GC=F") == "GOLD"
    assert engine._resolve_symbol_key("NOT_A_REAL_ASSET") == "NOT_A_REAL_ASSET"


def test_resolve_multiplier_uses_per_asset_calibration_when_present(engine):
    engine._volatility_calibration = {
        "US Non-Farm Payrolls": {"per_asset": {"GOLD": 2.5, "EURUSD": 1.8}, "cross_asset_average": 2.0}
    }
    multiplier, notes = engine._resolve_multiplier("US Non-Farm Payrolls", "GOLD")
    assert multiplier == 2.5
    assert "GOLD" in notes
    assert "average" not in notes


def test_resolve_multiplier_falls_back_to_cross_asset_average(engine):
    engine._volatility_calibration = {
        "US Non-Farm Payrolls": {"per_asset": {"GOLD": 2.5}, "cross_asset_average": 2.0}
    }
    multiplier, notes = engine._resolve_multiplier("US Non-Farm Payrolls", "NIFTY50")
    assert multiplier == 2.0
    assert "cross-asset average" in notes
    assert "NIFTY50" in notes


def test_resolve_multiplier_defaults_to_one_when_event_uncalibrated(engine):
    engine._volatility_calibration = {}
    multiplier, notes = engine._resolve_multiplier("US Non-Farm Payrolls", "GOLD")
    assert multiplier == 1.0
    assert "Not yet calibrated" in notes


@requires_data("models/e05_economic_calendar/volatility_calibration.json")
def test_upcoming_events_with_symbol_uses_that_assets_own_multiplier(engine):
    """Real (not injected) calibration file -- GOLD and EURUSD must resolve
    to their OWN distinct, real calibrated multipliers, confirming
    per-asset differentiation actually reaches upcoming_events(), not just
    _resolve_multiplier() in isolation."""
    ref = datetime(2026, 7, 1, tzinfo=timezone.utc)
    gold_events = engine.upcoming_events(reference=ref, lookahead_days=10, lookback_days=0, symbol="GOLD")
    eurusd_events = engine.upcoming_events(reference=ref, lookahead_days=10, lookback_days=0, symbol="EURUSD")
    assert gold_events and eurusd_events
    assert gold_events[0].expected_volatility_multiplier != eurusd_events[0].expected_volatility_multiplier
    assert "GOLD" in gold_events[0].notes
    assert "EURUSD" in eurusd_events[0].notes


@requires_data("models/e05_economic_calendar/volatility_calibration.json")
def test_upcoming_events_uncalibrated_symbol_falls_back_to_average(engine):
    """NIFTY50/BANKNIFTY have no per-asset NFP calibration (NFP releases
    after Indian markets close, so there's no intraday reaction window to
    measure) -- must fall back to the cross-asset average, not error or
    silently return 1.0 when an average is actually available."""
    ref = datetime(2026, 7, 1, tzinfo=timezone.utc)
    events = engine.upcoming_events(reference=ref, lookahead_days=10, lookback_days=0, symbol="NIFTY50")
    assert events
    assert "cross-asset average" in events[0].notes


@requires_data("models/e05_economic_calendar/volatility_calibration.json")
def test_analyze_passes_symbol_through_to_multiplier_resolution(engine):
    ref = datetime(2026, 7, 1, tzinfo=timezone.utc)
    result = engine.analyze(reference=ref, lookahead_days=10, symbol="GOLD")
    assert result.success
    assert result.data.upcoming_events
    assert "GOLD" in result.data.upcoming_events[0].notes


def test_register_recurring_event_extension_point(engine):
    """Confirms new event types (e.g. a real FOMC schedule, once available)
    can be added without modifying the engine itself."""
    calls = []

    def fixed_dates(start, end):
        calls.append((start, end))
        return [datetime(2026, 9, 1, 14, 0, tzinfo=timezone.utc)]

    engine.register_recurring_event("Test Event", EventImpact.MEDIUM, date_confirmed=False, date_generator=fixed_dates)
    ref = datetime(2026, 8, 25, tzinfo=timezone.utc)
    events = engine.upcoming_events(reference=ref, lookahead_days=10, lookback_days=0)
    names = {e.name for e in events}
    assert "Test Event" in names
    assert calls  # date_generator was actually invoked


# ---- extended event calibration (train_e05_event_calibration.py) ----
# Real (not injected) calibration file, loaded via engine.initialize() --
# proves the 8 event types calibrated from the imported 2011-2021
# historical economic calendar are genuinely usable, while confirming
# they do NOT leak into the live upcoming_events()/analyze() surface
# (none of them has a deterministic future-date rule, unlike NFP).


@requires_data("models/e05_economic_calendar/volatility_calibration.json")
def test_extended_calibration_events_are_loaded(engine):
    assert "US Fed Interest Rate Decision" in engine._volatility_calibration
    assert "India Interest Rate Decision" in engine._volatility_calibration
    assert "US Non-Farm Payrolls" in engine._volatility_calibration  # original NFP untouched


@requires_data("models/e05_economic_calendar/volatility_calibration.json")
def test_extended_calibration_resolves_a_real_per_asset_multiplier(engine):
    multiplier, notes = engine._resolve_multiplier("US Fed Interest Rate Decision", "GOLD")
    assert multiplier != 1.0
    assert "GOLD" in notes


def test_extended_calibration_events_never_appear_in_upcoming_events(engine):
    """The whole point of NOT registering these as recurring events: no
    deterministic future-date rule exists for Fed/ECB/BoE/BoJ/India rate
    decisions, so upcoming_events() must keep surfacing ONLY the two real
    recurring events (NFP, Initial Jobless Claims) even though 8 more
    event types are now calibrated in the same file."""
    ref = datetime(2026, 7, 1, tzinfo=timezone.utc)
    events = engine.upcoming_events(reference=ref, lookahead_days=365, lookback_days=0)
    names = {e.name for e in events}
    assert names == {"US Non-Farm Payrolls", "US Initial Jobless Claims"}


# ---- live events (Finnhub integration) ----


def test_match_calibrated_event_key_finds_real_matches():
    assert _match_calibrated_event_key("Fed Interest Rate Decision") == "US Fed Interest Rate Decision"
    assert _match_calibrated_event_key("ECB Interest Rate Decision") == "ECB Interest Rate Decision"
    assert _match_calibrated_event_key("Core CPI m/m") == "US Core CPI"
    assert _match_calibrated_event_key("Crude Oil Inventories") == "US Crude Oil Inventories"


def test_match_calibrated_event_key_no_match_returns_none():
    assert _match_calibrated_event_key("Building Permits") is None
    assert _match_calibrated_event_key("Retail Sales") is None


def test_upcoming_events_without_finnhub_client_unchanged(engine):
    """No finnhub_client injected -- must behave exactly as before (just
    the two registered recurring events, no live-fetched ones), never
    raise just because live events aren't configured."""
    ref = datetime(2026, 7, 1, tzinfo=timezone.utc)
    events = engine.upcoming_events(reference=ref, lookahead_days=10, lookback_days=0)
    assert {e.name for e in events} == {"US Non-Farm Payrolls", "US Initial Jobless Claims"}


class _FakeFinnhubClient:
    def __init__(self, events=None, configured=True, raises=None):
        self._events = events or []
        self.is_configured = configured
        self._raises = raises

    def economic_calendar(self, from_date, to_date):
        if self._raises:
            raise self._raises
        return self._events


def test_upcoming_events_merges_real_live_events():
    fake_client = _FakeFinnhubClient(events=[
        {"event": "Fed Interest Rate Decision", "time": "2026-07-08 18:00:00", "impact": "high"},
    ])
    engine = EconomicCalendarEngine(finnhub_client=fake_client)
    engine.initialize()
    ref = datetime(2026, 7, 1, tzinfo=timezone.utc)
    events = engine.upcoming_events(reference=ref, lookahead_days=10, lookback_days=0)
    names = {e.name for e in events}
    assert "Fed Interest Rate Decision" in names
    live_event = next(e for e in events if e.name == "Fed Interest Rate Decision")
    assert live_event.date_confirmed is True
    assert live_event.impact == EventImpact.HIGH


def test_upcoming_events_live_client_not_configured_returns_nfp_only():
    fake_client = _FakeFinnhubClient(configured=False)
    engine = EconomicCalendarEngine(finnhub_client=fake_client)
    engine.initialize()
    ref = datetime(2026, 7, 1, tzinfo=timezone.utc)
    events = engine.upcoming_events(reference=ref, lookahead_days=10, lookback_days=0)
    assert {e.name for e in events} == {"US Non-Farm Payrolls", "US Initial Jobless Claims"}


def test_upcoming_events_live_fetch_failure_degrades_gracefully():
    from project_titan_x.core.data_providers.finnhub import FinnhubError

    fake_client = _FakeFinnhubClient(raises=FinnhubError("simulated failure"))
    engine = EconomicCalendarEngine(finnhub_client=fake_client)
    engine.initialize()
    ref = datetime(2026, 7, 1, tzinfo=timezone.utc)
    # Must not raise -- a live-feed failure degrades to just the registered
    # recurring events, same as if no client were configured at all.
    events = engine.upcoming_events(reference=ref, lookahead_days=10, lookback_days=0)
    assert {e.name for e in events} == {"US Non-Farm Payrolls", "US Initial Jobless Claims"}


def test_upcoming_events_skips_malformed_live_event_without_losing_others():
    fake_client = _FakeFinnhubClient(events=[
        {"event": "Fed Interest Rate Decision", "time": "2026-07-08 18:00:00", "impact": "high"},
        {"impact": "high"},  # missing event/time -- must be skipped, not crash the batch
    ])
    engine = EconomicCalendarEngine(finnhub_client=fake_client)
    engine.initialize()
    ref = datetime(2026, 7, 1, tzinfo=timezone.utc)
    events = engine.upcoming_events(reference=ref, lookahead_days=10, lookback_days=0)
    names = {e.name for e in events}
    assert "Fed Interest Rate Decision" in names
    assert "US Non-Farm Payrolls" in names


def test_upcoming_events_live_event_uses_real_calibration():
    """A live event that matches a calibrated key must get that asset's
    REAL calibrated multiplier, not a generic 1.0 -- proves _match_calibrated_event_key
    actually reaches _resolve_multiplier, not just returns a key nobody uses."""
    fake_client = _FakeFinnhubClient(events=[
        {"event": "Fed Interest Rate Decision", "time": "2026-07-08 18:00:00", "impact": "high"},
    ])
    engine = EconomicCalendarEngine(finnhub_client=fake_client)
    engine.initialize()
    engine._volatility_calibration = {
        "US Fed Interest Rate Decision": {"per_asset": {"GOLD": 2.5}, "cross_asset_average": 1.5}
    }
    ref = datetime(2026, 7, 1, tzinfo=timezone.utc)
    events = engine.upcoming_events(reference=ref, lookahead_days=10, lookback_days=0, symbol="GOLD")
    live_event = next(e for e in events if e.name == "Fed Interest Rate Decision")
    assert live_event.expected_volatility_multiplier == 2.5


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


def test_analyze_attaches_knowledge_context_when_injected(tmp_path):
    knowledge_engine = _real_knowledge_engine(
        tmp_path,
        "Chapter 1: Trading Around News\n\nVolatility typically spikes around high-impact economic releases like Non-Farm Payrolls.",
    )
    engine = EconomicCalendarEngine(knowledge_engine=knowledge_engine)
    engine.initialize()
    ref = datetime(2026, 7, 1, tzinfo=timezone.utc)
    result = engine.analyze(reference=ref, lookahead_days=10)
    assert result.success
    assert result.data.knowledge_context is not None
    assert result.data.knowledge_context["results"]


def test_analyze_knowledge_context_none_without_engine(engine):
    ref = datetime(2026, 7, 1, tzinfo=timezone.utc)
    result = engine.analyze(reference=ref, lookahead_days=10)
    assert result.success
    assert result.data.knowledge_context is None


def test_analyze_knowledge_context_none_when_no_events_in_window(tmp_path):
    """No upcoming events in the window -> no knowledge lookup either
    (nothing to build a query from)."""
    knowledge_engine = _real_knowledge_engine(tmp_path, "Chapter 1: Test\n\nSome unrelated content.")
    engine = EconomicCalendarEngine(knowledge_engine=knowledge_engine)
    engine.initialize()
    ref = datetime(2026, 7, 4, tzinfo=timezone.utc)  # gap between NFP dates, see test_analyze_returns_no_events_when_none_upcoming
    result = engine.analyze(reference=ref, lookahead_days=10)
    assert result.success
    assert result.data.knowledge_context is None
