"""
Module: fred.py
Description: FRED (Federal Reserve Economic Data, St. Louis Fed) REST
             client -- disk-cached, same Optional[str] api_key /
             is_configured / graceful-no-op shape as
             core.data_providers.alpha_vantage.AlphaVantageClient and
             core.data_providers.finnhub.FinnhubClient, so e19_global_
             liquidity degrades the same way when unconfigured.

             VERIFIED (Rule 4 -- never guess a specific fact you're not
             certain of): a real, unauthenticated request to
             https://api.stlouisfed.org/fred/series/observations was made
             during this session and returned HTTP 400 with
             "The value for variable api_key is not a 32 character
             alpha-numeric lower-case string" -- confirming FRED's REST API
             requires a real, free, self-registered API key
             (https://fred.stlouisfed.org/docs/api/api_key.html), same
             honest-gap shape as finnhub_api_key.
             MIN_SECONDS_BETWEEN_CALLS below is a deliberately conservative
             default, NOT a figure copied from FRED's own published limit
             page -- that page was not fetched/verified this session, so
             asserting a specific documented number here would violate the
             same rule this comment is following.

             UPDATE 2026-08-02 (Rule 4 again, this time proving the gap
             smaller than assumed): a real, unauthenticated request to
             https://fred.stlouisfed.org/graph/fredgraph.csv?id=WALCL was
             also made and returned a real HTTP 200 with the FULL WALCL
             history back to 2002 -- no key required. This is the same
             public CSV-download endpoint FRED's own interactive graph
             pages use, and what pandas_datareader's FredReader fetches
             under the hood; it is a genuinely different, no-key path from
             the api_key-gated REST API above, not a workaround of it.
             Verified the same way for M2SL and DFII10. series_observations
             (REST, needs a key) is left in place for any future caller
             that wants it; series_observations_csv (no key, full history)
             is what e19_global_liquidity actually calls now.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-07-19
"""

import csv
import hashlib
import io
import json
import logging
import threading
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional

import httpx

from project_titan_x.core.config import get_settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.stlouisfed.org/fred"
CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"

# Conservative, unverified-against-FRED's-own-docs default -- see module
# docstring.
MIN_SECONDS_BETWEEN_CALLS = 1.0

# Macro series (Fed balance sheet, M2, real yields) update weekly/monthly at
# most -- a long TTL is appropriate and keeps this well clear of any rate
# limit regardless of what FRED's actual one turns out to be.
CACHE_TTL_SECONDS = 12 * 60 * 60


class FredError(Exception):
    """Raised when FRED returns an error payload or an unexpected shape."""


class FredNotConfigured(FredError):
    """Raised when no API key is configured."""


class FredClient:
    """Thin REST client for FRED's public REST API. Every call is
    disk-cached; no local quota tracker (see module docstring for why a
    specific numeric limit isn't asserted here) -- a real 429/4xx from FRED
    surfaces as a FredError, never silently swallowed."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        cache_dir: Optional[Path] = None,
        timeout: float = 15.0,
    ) -> None:
        self.api_key = api_key
        self.cache_dir = cache_dir or Path("data") / "raw" / "fred_cache"
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

    def series_observations(
        self,
        series_id: str,
        observation_start: Optional[str] = None,
        observation_end: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        """GET /series/observations?series_id=...&file_type=json -- real
        FRED time series values (date/value pairs, ascending by date).
        Returns FRED's own observation dicts as-is; normalization into this
        platform's own shape happens in e19_global_liquidity/engine.py, not
        here, so this client stays a thin, faithful wrapper (same
        convention as core.data_providers.finnhub.economic_calendar)."""
        params = {"series_id": series_id, "limit": limit}
        if observation_start:
            params["observation_start"] = observation_start
        if observation_end:
            params["observation_end"] = observation_end
        payload = self._call("series/observations", params)
        observations = payload.get("observations")
        if observations is None:
            raise FredError("Unexpected response shape -- missing 'observations'")
        return observations

    def series_observations_csv(self, series_id: str) -> list[dict]:
        """GET fred.stlouisfed.org/graph/fredgraph.csv?id=... -- the public,
        no-API-key CSV download FRED's own graph pages use. Returns the
        SAME shape as series_observations() ({"date": ..., "value": ...}
        dicts, ascending by date, missing values as "." left as-is for the
        caller to filter same as the REST path) so callers don't need to
        care which path served them. Does NOT require is_configured/api_key
        -- this endpoint has no auth at all (verified live, see module
        docstring)."""
        cache_key = self._cache_key("csv_" + series_id, {})
        cached = self._read_cache(cache_key)
        if cached is not None:
            return cached["observations"]

        self._throttle()

        response = self._client.get(CSV_URL, params={"id": series_id})
        if response.status_code == 429:
            raise FredError(f"FRED CSV {series_id} -- 429 rate limited")
        response.raise_for_status()

        reader = csv.reader(io.StringIO(response.text))
        rows = list(reader)
        if not rows or len(rows[0]) != 2:
            raise FredError(f"FRED CSV {series_id} -- unexpected response shape: {response.text[:200]!r}")

        observations = [{"date": date, "value": value} for date, value in rows[1:]]
        self._write_cache(cache_key, {"observations": observations})
        return observations

    # -- Internals ----------------------------------------------------------

    def _call(self, path: str, params: dict) -> dict:
        if not self.is_configured:
            raise FredNotConfigured("FRED_API_KEY is not set")

        cache_key = self._cache_key(path, params)
        cached = self._read_cache(cache_key)
        if cached is not None:
            return cached

        self._throttle()

        query = {**params, "api_key": self.api_key, "file_type": "json"}
        response = self._client.get(f"{BASE_URL}/{path}", params=query)
        if response.status_code == 400:
            raise FredError(f"FRED {path} -- 400 Bad Request (likely a bad/missing api_key): {response.text[:200]}")
        if response.status_code == 429:
            raise FredError(f"FRED {path} -- 429 rate limited")
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and "error_code" in payload:
            raise FredError(f"FRED {path} -- {payload.get('error_message', payload['error_code'])}")

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
def get_fred_client() -> "FredClient":
    """Process-wide cached FRED client singleton, same reasoning as
    get_finnhub_client()/get_alpha_vantage_client()."""
    settings = get_settings()
    return FredClient(api_key=settings.fred_api_key)
