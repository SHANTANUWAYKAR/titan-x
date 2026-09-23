"""
Module: finnhub.py
Description: Finnhub REST client -- disk-cached and rate-limited per
             https://finnhub.io/docs/api (documented free-tier limit:
             60 calls/minute, 30/second burst cap). Same shape as
             core.data_providers.alpha_vantage.AlphaVantageClient
             (Optional[str] api_key, is_configured, disk cache) so the
             engines that use it degrade the same way when unconfigured.

             HONEST GAP: I could not confirm, without an actual registered
             key, whether Finnhub's free tier includes the
             /calendar/economic endpoint specifically (an anonymous
             request correctly returns 401 "Please use an API key" --
             informative about auth requirements, not about which plan
             tier the endpoint sits behind). This client is real,
             working code, but activating it requires a real
             FINNHUB_API_KEY and a live check of whether that key's plan
             actually returns calendar data (some providers gate
             calendar/alternative-data endpoints behind a paid plan even
             when basic quotes are free) -- see Rule 4, never guess a
             specific fact you're not certain of.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-07-19
"""

import hashlib
import json
import logging
import threading
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional

import httpx
import pandas as pd

from project_titan_x.core.config import get_settings

logger = logging.getLogger(__name__)

BASE_URL = "https://finnhub.io/api/v1"

# Finnhub's documented free-tier cap is 60/minute (30/second burst) -- a 1.1s
# floor between calls keeps a burst of cache misses comfortably under that
# without needing a full token-bucket implementation.
MIN_SECONDS_BETWEEN_CALLS = 1.1

# Upcoming economic events genuinely change within a trading day (revisions,
# newly scheduled releases) -- much shorter TTL than Alpha Vantage's
# monthly/quarterly macro series.
CACHE_TTL_SECONDS = 3 * 60 * 60


class FinnhubError(Exception):
    """Raised when Finnhub returns an error payload or an unexpected shape."""


class FinnhubNotConfigured(FinnhubError):
    """Raised when no API key is configured."""


class FinnhubClient:
    """Thin REST client for Finnhub's public REST API. Every call is
    disk-cached; no local daily-quota tracker like Alpha Vantage's since
    Finnhub's documented limit is a per-minute rate, not a daily cap --
    if that turns out to be wrong for the actual plan behind a given key,
    Finnhub's own 429 response surfaces as a FinnhubError, same as any
    other HTTP error here (never silently swallowed)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        cache_dir: Optional[Path] = None,
        timeout: float = 15.0,
    ) -> None:
        self.api_key = api_key
        self.cache_dir = cache_dir or Path("data") / "raw" / "finnhub_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._client = httpx.Client(timeout=timeout)
        self._lock = threading.Lock()
        self._last_call_at = 0.0

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def close(self) -> None:
        self._client.close()

    # -- Public endpoints -------------------------------------------------

    def economic_calendar(self, from_date: str, to_date: str) -> list[dict]:
        """GET /calendar/economic?from=YYYY-MM-DD&to=YYYY-MM-DD -- upcoming
        and recent scheduled macro releases. Returns Finnhub's own event
        dicts as-is (event/country/impact/actual/estimate/prev/unit/time
        fields per their docs) -- normalization into this platform's own
        EconomicEvent shape happens in e05_economic_calendar/engine.py,
        not here, so this client stays a thin, faithful wrapper."""
        payload = self._call("calendar/economic", {"from": from_date, "to": to_date})
        events = payload.get("economicCalendar")
        if events is None:
            raise FinnhubError("Unexpected response shape -- missing 'economicCalendar'")
        return events

    # -- Internals ----------------------------------------------------------

    def _call(self, path: str, params: dict) -> dict:
        if not self.is_configured:
            raise FinnhubNotConfigured("FINNHUB_API_KEY is not set")

        cache_key = self._cache_key(path, params)
        cached = self._read_cache(cache_key)
        if cached is not None:
            return cached

        self._throttle()

        query = {**params, "token": self.api_key}
        response = self._client.get(f"{BASE_URL}/{path}", params=query)
        if response.status_code == 401:
            raise FinnhubError(f"Finnhub {path} -- 401 Unauthorized (bad key or plan doesn't include this endpoint)")
        if response.status_code == 429:
            raise FinnhubError(f"Finnhub {path} -- 429 rate limited")
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and "error" in payload:
            raise FinnhubError(f"Finnhub {path} -- {payload['error']}")

        self._write_cache(cache_key, payload)
        return payload

    def _throttle(self) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._last_call_at
            if elapsed < MIN_SECONDS_BETWEEN_CALLS:
                time.sleep(MIN_SECONDS_BETWEEN_CALLS - elapsed)
            self._last_call_at = time.monotonic()

    def _cache_key(self, path: str, params: dict) -> str:
        raw = json.dumps({"path": path, **params}, sort_keys=True)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
        return f"{path.replace('/', '_')}_{digest}"

    def _read_cache(self, cache_key: str) -> Optional[dict]:
        path = self.cache_dir / f"{cache_key}.json"
        if not path.exists():
            return None
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
            fetched_at = datetime.fromisoformat(envelope["fetched_at"])
        except (OSError, json.JSONDecodeError, KeyError, ValueError):
            return None
        age = (datetime.now(timezone.utc) - fetched_at).total_seconds()
        if age > CACHE_TTL_SECONDS:
            return None
        return envelope["payload"]

    def _write_cache(self, cache_key: str, payload: dict) -> None:
        path = self.cache_dir / f"{cache_key}.json"
        envelope = {"fetched_at": datetime.now(timezone.utc).isoformat(), "payload": payload}
        path.write_text(json.dumps(envelope), encoding="utf-8")


@lru_cache
def get_finnhub_client() -> "FinnhubClient":
    """Process-wide cached Finnhub client singleton, same reasoning as
    get_alpha_vantage_client() -- shares the throttle state across every
    engine that uses one rather than resetting per-instance."""
    settings = get_settings()
    return FinnhubClient(api_key=settings.finnhub_api_key)
