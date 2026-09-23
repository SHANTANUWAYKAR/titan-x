"""
Module: engine.py
Description: Engine 05 -- Economic Calendar Intelligence.

Classifies upcoming high-impact recurring macro releases and estimates
expected volatility around them, without depending on any paid calendar
API. A prior attempt at this engine was skipped (see README.md history)
because TradingEconomics discontinued free/guest access and no other free
calendar feed with adequate coverage existed. This version sidesteps that
entirely: rather than fetching a live calendar feed, it derives event
dates from PUBLISHED, DETERMINISTIC release rules (e.g. US Non-Farm
Payrolls is released the first Friday of every month by BLS policy) and
calibrates each event type's historical volatility impact directly from
real OHLCV price history already available in this project.

Deliberately conservative scope: only event types with a mathematically
certain, publicly documented release rule are included as `date_confirmed
= True`. Events whose exact date varies non-deterministically month to
month (FOMC meeting dates, exact CPI/PPI/Retail Sales release days) are
NOT hardcoded from memory here -- guessing wrong on a date used to size
risk around a real release would be exactly the kind of price/data
inaccuracy this project's owner has explicitly warned costs real money.
Use `register_recurring_event` to add more event types once a real
published schedule (e.g. from the Fed's own site) is available.
Author: Shantanu Waykar
Version: 1.0.0
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Optional
from zoneinfo import ZoneInfo

import pandas as pd

from project_titan_x.core.config import get_asset
from project_titan_x.core.data_providers.finnhub import FinnhubClient, FinnhubError
from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus
from project_titan_x.engines.e01_knowledge.engine import KnowledgeEngine

logger = logging.getLogger(__name__)

# Best-effort keyword match from a real Finnhub event name to one of this
# engine's already-calibrated event keys (see train_e05_event_calibration.py
# -- calibrated from a historical investing.com-style calendar, whose exact
# event-name strings do NOT necessarily match Finnhub's own naming). Each
# calibrated key maps to the keywords that must ALL appear (case-insensitive)
# in a live Finnhub event name for it to count as the same real-world event.
# Unverified against real Finnhub output (see module docstring on
# _fetch_live_events) -- spot-check once a real key confirms calendar access.
_LIVE_EVENT_KEYWORD_MAP: dict[str, tuple[str, ...]] = {
    "US Fed Interest Rate Decision": ("fed", "interest rate"),
    "US Core CPI": ("core", "cpi"),
    "US ISM Manufacturing PMI": ("ism", "manufacturing"),
    "US Crude Oil Inventories": ("crude", "inventories"),
    "ECB Interest Rate Decision": ("ecb", "interest rate"),
    "BoE Interest Rate Decision": ("boe", "interest rate"),
    "BoJ Monetary Policy Statement": ("boj",),
    "India Interest Rate Decision": ("india", "interest rate"),
}


def _match_calibrated_event_key(live_event_name: str) -> Optional[str]:
    """Map a real live event name to one of this engine's calibrated keys,
    or None if nothing matches (an uncalibrated live event is still shown,
    just with a 1.0x/"not yet calibrated" multiplier -- never dropped)."""
    lowered = live_event_name.lower()
    for calibrated_key, keywords in _LIVE_EVENT_KEYWORD_MAP.items():
        if all(kw in lowered for kw in keywords):
            return calibrated_key
    return None

_CALIBRATION_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "models" / "e05_economic_calendar" / "volatility_calibration.json"
)
_ET = ZoneInfo("America/New_York")


class EventImpact(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class EconomicEvent:
    """A single scheduled (or historical) macro release."""

    name: str
    date: datetime
    impact: EventImpact
    date_confirmed: bool  # True only for a deterministic, published release rule
    expected_volatility_multiplier: float = 1.0  # 1.0 = "no calibration yet, assume normal"
    notes: str = ""


@dataclass
class CalendarSnapshot:
    as_of: datetime
    upcoming_events: list[EconomicEvent] = field(default_factory=list)
    high_impact_within_24h: bool = False
    high_impact_within_1h: bool = False
    knowledge_context: Optional[dict] = None


def _first_friday_8_30am_et(year: int, month: int) -> datetime:
    """US Non-Farm Payrolls: released the first Friday of every month at
    8:30am US Eastern time -- a fixed Bureau of Labor Statistics rule, not
    an estimate. DST-aware (zoneinfo handles the EST/EDT switch)."""
    d = datetime(year, month, 1, 8, 30, tzinfo=_ET)
    offset = (4 - d.weekday()) % 7  # Friday == weekday() 4
    return d + timedelta(days=offset)


def _thursday_dates(start: datetime, end: datetime) -> list[datetime]:
    """US Initial Jobless Claims: released every Thursday at 8:30am US
    Eastern time -- a fixed, well-documented weekly Bureau of Labor
    Statistics/Department of Labor release rule, same "safe to hardcode"
    category as NFP's first-Friday rule above (see module docstring on
    why FOMC/CPI/PPI dates, which do NOT follow a simple fixed calendar
    rule, are deliberately NOT hardcoded). DST-aware (zoneinfo handles
    the EST/EDT switch)."""
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    start_et = start.astimezone(_ET)
    first = start_et.replace(hour=8, minute=30, second=0, microsecond=0)
    offset = (3 - first.weekday()) % 7  # Thursday == weekday() 3
    first += timedelta(days=offset)
    dates = []
    current = first
    while current <= end:
        dates.append(current)
        current = current + timedelta(days=7)
    return dates


def _month_iter(start: datetime, end: datetime):
    """Yields (year, month) tuples from start to end inclusive. Compares
    plain (year, month) tuples rather than datetime objects, since start/end
    may carry different tzinfo (or none) than the naive-then-localized
    cursor this would otherwise need to build."""
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        yield year, month
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1


class EconomicCalendarEngine(BaseEngine):
    """
    Economic Calendar Intelligence Engine -- deterministic recurring macro
    release schedule + historically-calibrated volatility expectations.
    """

    engine_id = "e05_economic_calendar"
    engine_name = "Economic Calendar Intelligence Engine"
    version = "1.0.0"

    def __init__(
        self,
        knowledge_engine: Optional[KnowledgeEngine] = None,
        finnhub_client: Optional[FinnhubClient] = None,
    ) -> None:
        super().__init__()
        # name -> (impact, date_confirmed, date_generator(start, end) -> list[datetime])
        self._recurring_events: dict[str, tuple[EventImpact, bool, Callable]] = {}
        # event_name -> {"per_asset": {symbol: multiplier}, "cross_asset_average": float | None}
        self._volatility_calibration: dict[str, dict] = {}
        self.register_recurring_event(
            "US Non-Farm Payrolls",
            EventImpact.HIGH,
            date_confirmed=True,
            date_generator=self._nfp_dates,
        )
        # Added 2026-08-02: US Initial Jobless Claims -- every Thursday,
        # 8:30am ET, the same "fixed, published release rule" category as
        # NFP above (see _thursday_dates' own docstring). Impact is
        # MEDIUM, not HIGH: jobless claims is a real, regularly-watched
        # release but historically produces smaller market reactions than
        # NFP -- reflected honestly once train_e05_economic_calendar.py's
        # real per-asset calibration is run, not asserted here.
        self.register_recurring_event(
            "US Initial Jobless Claims",
            EventImpact.MEDIUM,
            date_confirmed=True,
            date_generator=_thursday_dates,
        )
        # Optional and None by default: without it, analyze() behaves
        # exactly as before (no knowledge_context). Pass a real instance
        # (as registry.py does) to turn it on.
        self._knowledge_engine = knowledge_engine
        # Optional and None by default: without a configured key,
        # upcoming_events() behaves exactly as before (NFP only). With one,
        # real live-scheduled events (Fed/ECB/BoE/BoJ decisions, CPI, PMI,
        # crude inventories -- the event types this engine already has real
        # historical volatility calibration for, see
        # train_e05_event_calibration.py) get merged in too, each correctly
        # marked date_confirmed=True since a live feed genuinely reports a
        # scheduled date, not a guess.
        self._finnhub_client = finnhub_client

    def initialize(self) -> EngineResult:
        self._volatility_calibration = self._load_calibration()
        calibrated_assets = {
            name: sorted(cal["per_asset"].keys()) for name, cal in self._volatility_calibration.items()
        }
        self._set_status(EngineStatus.IDLE)
        return EngineResult(
            success=True,
            message="Economic Calendar Intelligence Engine initialized",
            metadata={"calibrated_events": calibrated_assets},
        )

    def health_check(self) -> EngineResult:
        return EngineResult(success=True, message="Healthy")

    def register_recurring_event(
        self,
        name: str,
        impact: EventImpact,
        date_confirmed: bool,
        date_generator: Callable[[datetime, datetime], list[datetime]],
    ) -> None:
        """Add a recurring event type. `date_generator(start, end)` must
        return every occurrence of this event between start and end.
        Extension point for FOMC/CPI/PPI/Retail Sales once a real published
        schedule is wired in -- deliberately NOT pre-populated with guessed
        dates (see module docstring)."""
        self._recurring_events[name] = (impact, date_confirmed, date_generator)

    @staticmethod
    def _nfp_dates(start: datetime, end: datetime) -> list[datetime]:
        return [_first_friday_8_30am_et(y, m) for y, m in _month_iter(start, end)]

    def _fetch_live_events(self, start: datetime, end: datetime, symbol_key: Optional[str]) -> list[EconomicEvent]:
        """Real upcoming events from Finnhub's live calendar -- returns []
        (never raises) if no client is configured, the key doesn't have
        calendar access, or the request fails for any reason: an
        unavailable live feed must degrade to exactly the NFP-only
        behavior that existed before, never break analyze()/upcoming_events().

        Field-name assumptions (event/time/impact/country) follow Finnhub's
        documented schema but are UNVERIFIED against real output -- this
        client has never been exercised against a real key (see
        core.data_providers.finnhub's module docstring). If real events
        come back with a different shape, malformed rows are skipped
        individually (logged, not raised) rather than losing the whole
        batch."""
        if self._finnhub_client is None or not self._finnhub_client.is_configured:
            return []
        try:
            raw_events = self._finnhub_client.economic_calendar(
                start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
            )
        except FinnhubError as e:
            logger.warning("Live economic calendar unavailable: %s", e)
            return []

        events: list[EconomicEvent] = []
        for raw in raw_events:
            try:
                name = raw.get("event") or raw.get("name")
                time_str = raw.get("time") or raw.get("date")
                if not name or not time_str:
                    continue
                dt = pd.to_datetime(time_str, utc=True).to_pydatetime()

                impact_raw = str(raw.get("impact", "")).strip().lower()
                impact = {"3": EventImpact.HIGH, "high": EventImpact.HIGH,
                           "2": EventImpact.MEDIUM, "medium": EventImpact.MEDIUM}.get(impact_raw, EventImpact.LOW)

                calibrated_key = _match_calibrated_event_key(name)
                multiplier, notes = (
                    self._resolve_multiplier(calibrated_key, symbol_key)
                    if calibrated_key else (1.0, "Live event, not yet calibrated -- assume normal volatility")
                )
                events.append(EconomicEvent(
                    name=name, date=dt, impact=impact, date_confirmed=True,
                    expected_volatility_multiplier=multiplier, notes=notes,
                ))
            except Exception as e:
                logger.warning("Skipping malformed live event %r: %s", raw, e)
                continue
        return events

    @staticmethod
    def _load_calibration() -> dict[str, dict]:
        """Per-asset NFP volatility multipliers from
        scripts/training/train_e05_economic_calendar.py, keyed by event
        name -> {"per_asset": {symbol: multiplier}, "cross_asset_average":
        float | None}. Empty (not fabricated) if the training script
        hasn't been run yet -- see Rule 4, never guess."""
        if not _CALIBRATION_PATH.exists():
            return {}
        try:
            data = json.loads(_CALIBRATION_PATH.read_text())
            calibration: dict[str, dict] = {}
            for event_name, report in data.items():
                per_asset = {
                    symbol: float(entry["expected_volatility_multiplier"])
                    for symbol, entry in report.get("assets", {}).items()
                }
                calibration[event_name] = {
                    "per_asset": per_asset,
                    "cross_asset_average": report.get("cross_asset_average_multiplier"),
                }
            return calibration
        except Exception as e:
            logger.warning("Failed to load economic calendar calibration: %s", e)
            return {}

    @staticmethod
    def _resolve_symbol_key(symbol: str) -> str:
        """Normalize an incoming symbol (raw, Yahoo ticker, or already a
        platform symbol) to the SUPPORTED_ASSETS key the calibration is
        keyed by, e.g. "EURUSD=X" or "eurusd" -> "EURUSD"."""
        asset = get_asset(symbol)
        return asset.symbol if asset else symbol.upper()

    def _resolve_multiplier(self, event_name: str, symbol_key: Optional[str]) -> tuple[float, str]:
        """Look up the expected-volatility multiplier for one event,
        preferring an exact per-asset calibration over the cross-asset
        average, and falling back to 1.0 ("assume normal") only when
        neither exists -- never fabricated."""
        calibration = self._volatility_calibration.get(event_name)
        if calibration is None:
            return 1.0, "Not yet calibrated -- assume normal volatility until trained"

        if symbol_key and symbol_key in calibration["per_asset"]:
            multiplier = calibration["per_asset"][symbol_key]
            return multiplier, f"Historically ~{multiplier:.1f}x normal volatility in the hours around this release for {symbol_key}"

        average = calibration.get("cross_asset_average")
        if average is not None:
            suffix = f" (cross-asset average -- no per-asset calibration for {symbol_key})" if symbol_key else " (cross-asset average)"
            return average, f"Historically ~{average:.1f}x normal volatility in the hours around this release{suffix}"

        return 1.0, "Not yet calibrated -- assume normal volatility until trained"

    def upcoming_events(
        self,
        reference: Optional[datetime] = None,
        lookahead_days: int = 14,
        lookback_days: int = 2,
        symbol: Optional[str] = None,
    ) -> list[EconomicEvent]:
        """All registered recurring events (NFP) plus, when a Finnhub key is
        configured, real live-scheduled events (Fed/ECB/BoE/BoJ decisions,
        CPI, PMI, crude inventories) within [reference - lookback_days,
        reference + lookahead_days]. When `symbol` is given,
        expected_volatility_multiplier reflects that specific asset's own
        calibrated reaction to each event (falling back to the cross-asset
        average, then 1.0, if uncalibrated for this symbol)."""
        ref = reference or datetime.now(timezone.utc)
        start = ref - timedelta(days=lookback_days)
        end = ref + timedelta(days=lookahead_days)
        symbol_key = self._resolve_symbol_key(symbol) if symbol else None

        events: list[EconomicEvent] = []
        for name, (impact, confirmed, generator) in self._recurring_events.items():
            multiplier, notes = self._resolve_multiplier(name, symbol_key)
            for dt in generator(start, end):
                if start <= dt <= end:
                    events.append(EconomicEvent(
                        name=name, date=dt, impact=impact, date_confirmed=confirmed,
                        expected_volatility_multiplier=multiplier, notes=notes,
                    ))
        events.extend(self._fetch_live_events(start, end, symbol_key))
        events.sort(key=lambda e: e.date)
        return events

    def analyze(
        self, reference: Optional[datetime] = None, lookahead_days: int = 14, symbol: Optional[str] = None
    ) -> EngineResult:
        """Snapshot of upcoming high-impact events for signal-generation
        context (e.g. e51_signals attaches this the same way it already
        attaches macro/fundamental/microstructure context -- informational,
        not wired to change confidence/direction). Pass `symbol` to get
        that asset's own calibrated volatility multiplier rather than the
        cross-asset average."""
        try:
            self._set_status(EngineStatus.RUNNING)
            ref = reference or datetime.now(timezone.utc)
            events = self.upcoming_events(ref, lookahead_days=lookahead_days, lookback_days=0, symbol=symbol)

            high_impact_within_24h = any(
                e.impact == EventImpact.HIGH and ref <= e.date <= ref + timedelta(hours=24) for e in events
            )
            high_impact_within_1h = any(
                e.impact == EventImpact.HIGH and ref <= e.date <= ref + timedelta(hours=1) for e in events
            )

            snapshot = CalendarSnapshot(
                as_of=ref,
                upcoming_events=events,
                high_impact_within_24h=high_impact_within_24h,
                high_impact_within_1h=high_impact_within_1h,
                knowledge_context=self._build_knowledge_context(events, high_impact_within_24h),
            )
            self._set_status(EngineStatus.IDLE)
            return EngineResult(
                success=True,
                data=snapshot,
                message=f"{len(events)} upcoming event(s) in next {lookahead_days}d",
                metadata={
                    "high_impact_within_24h": high_impact_within_24h,
                    "high_impact_within_1h": high_impact_within_1h,
                },
            )
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("Economic calendar analysis failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def _build_knowledge_context(self, events: list[EconomicEvent], high_impact_within_24h: bool) -> Optional[dict]:
        """Relevant book content on trading around macro-event volatility,
        attached for transparency -- informational only, never changes
        high_impact_within_24h or any event's date/impact/multiplier.
        Best-effort: only runs if a real KnowledgeEngine instance was
        injected (see __init__ / registry.py)."""
        if self._knowledge_engine is None:
            return None
        if not events:
            return None
        try:
            names = ", ".join(sorted({e.name for e in events}))
            urgency = "imminent high-impact" if high_impact_within_24h else "upcoming"
            query = f"trading around {urgency} economic release events: {names}"
            results = self._knowledge_engine.document_store.hybrid_search(query, limit=3)
        except Exception as e:
            logger.warning("Knowledge context unavailable: %s", e)
            return None
        if not results:
            return None
        return {"query": query, "results": [r.to_dict() for r in results]}
