"""
Module: event_bus.py
Description: In-process publish/subscribe event bus for Titan Brain.

    Scope note: this is an in-process bus, not a distributed message queue
    -- redis is listed in requirements.txt but isn't actually wired up
    anywhere in this codebase (confirmed by grep before writing this), and
    this platform runs as a single process, so a real broker would be
    infrastructure with no current consumer. Revisit if the platform ever
    splits into multiple processes/services.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

logger = logging.getLogger(__name__)

EventHandler = Callable[["Event"], None]


@dataclass
class Event:
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "payload": self.payload,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
        }


class EventBus:
    """Synchronous pub/sub: publish() calls every subscribed handler for
    that event_type immediately, in registration order. A handler that
    raises is logged and skipped -- one bad subscriber must never prevent
    the others from receiving the event or prevent publish() from
    returning to its caller."""

    def __init__(self, history_size: int = 500) -> None:
        self._subscribers: dict[str, list[EventHandler]] = {}
        self._history: deque[Event] = deque(maxlen=history_size)

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        self._subscribers.setdefault(event_type, []).append(handler)

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        handlers = self._subscribers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)

    def publish(self, event_type: str, payload: dict[str, Any] | None = None, source: str = "") -> Event:
        event = Event(event_type=event_type, payload=payload or {}, source=source)
        self._history.append(event)
        for handler in self._subscribers.get(event_type, []):
            try:
                handler(event)
            except Exception as e:
                logger.error("Event handler for %s raised: %s", event_type, e)
        return event

    def history(self, event_type: str | None = None, limit: int = 50) -> list[Event]:
        events = list(self._history)
        if event_type is not None:
            events = [e for e in events if e.event_type == event_type]
        return events[-limit:]

    def subscriber_count(self, event_type: str) -> int:
        return len(self._subscribers.get(event_type, []))
