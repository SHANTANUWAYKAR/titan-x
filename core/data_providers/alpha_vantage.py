"""
Module: alpha_vantage.py
Description: Alpha Vantage REST client -- disk-cached, quota-tracked, and
             rate-limited per https://www.alphavantage.co/documentation/.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-07-14
"""

import hashlib
import json
import logging
import threading
import time
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional

import httpx
import pandas as pd

from project_titan_x.core.config import get_settings

logger = logging.getLogger(__name__)

BASE_URL = "https://www.alphavantage.co/query"

# Defensive floor between live calls so a burst of cache misses doesn't also
# trip Alpha Vantage's per-minute throttle (their documented standard rate
# limit). The daily cap itself is enforced separately via a persisted counter.
MIN_SECONDS_BETWEEN_CALLS = 12.0

# How long a cached response stays valid, per Alpha Vantage "function".
# Economic indicators are published monthly/quarterly, so a day-long cache
# costs nothing in freshness; intraday prices move fast so cache is short.
CACHE_TTL_SECONDS = {
    "TIME_SERIES_INTRADAY": 5 * 60,
    "TIME_SERIES_DAILY": 12 * 60 * 60,
    "FX_DAILY": 12 * 60 * 60,
    "DIGITAL_CURRENCY_DAILY": 12 * 60 * 60,
    "GLOBAL_QUOTE": 60,
    "REAL_GDP": 24 * 60 * 60,
    "CPI": 24 * 60 * 60,
    "FEDERAL_FUNDS_RATE": 24 * 60 * 60,
    "TREASURY_YIELD": 24 * 60 * 60,
    "UNEMPLOYMENT": 24 * 60 * 60,
}
DEFAULT_CACHE_TTL_SECONDS = 24 * 60 * 60


class AlphaVantageError(Exception):
    """Raised when Alpha Vantage returns an error/rate-limit payload."""


class AlphaVantageNotConfigured(AlphaVantageError):
    """Raised when no API key is configured."""


class AlphaVantageQuotaExceeded(AlphaVantageError):
    """Raised when the local daily quota tracker is exhausted."""


class AlphaVantageClient:
    """
    Thin REST client for the Alpha Vantage API.

    Every call is disk-cached (repeat lookups within the TTL cost zero quota)
    and counted against a locally persisted daily-request tracker, since
    free-tier keys are capped at a small number of requests/day.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        daily_limit: int = 25,
        cache_dir: Optional[Path] = None,
        timeout: float = 15.0,
    ) -> None:
        self.api_key = api_key
        self.daily_limit = daily_limit
        self.cache_dir = cache_dir or Path("data") / "raw" / "alpha_vantage_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._quota_path = self.cache_dir / "_quota.json"
        self._client = httpx.Client(timeout=timeout)
        self._lock = threading.Lock()
        self._last_call_at = 0.0

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def close(self) -> None:
        self._client.close()

    # -- Public endpoints (https://www.alphavantage.co/documentation/) ------

    def time_series_daily(self, symbol: str, outputsize: str = "compact") -> pd.DataFrame:
        """TIME_SERIES_DAILY -- daily OHLCV for a stock/index/ETF ticker."""
        payload = self._call("TIME_SERIES_DAILY", {"symbol": symbol, "outputsize": outputsize})
        return self._parse_time_series(payload, "Time Series (Daily)")

    def fx_daily(self, from_symbol: str, to_symbol: str, outputsize: str = "compact") -> pd.DataFrame:
        """FX_DAILY -- daily OHLC for a forex pair (no volume)."""
        payload = self._call(
            "FX_DAILY",
            {"from_symbol": from_symbol, "to_symbol": to_symbol, "outputsize": outputsize},
        )
        return self._parse_time_series(payload, "Time Series FX (Daily)")

    def crypto_daily(self, symbol: str, market: str = "USD") -> pd.DataFrame:
        """DIGITAL_CURRENCY_DAILY -- daily OHLCV for a crypto/fiat market."""
        payload = self._call("DIGITAL_CURRENCY_DAILY", {"symbol": symbol, "market": market})
        return self._parse_time_series(payload, "Time Series (Digital Currency Daily)")

    def quote(self, symbol: str) -> dict:
        """GLOBAL_QUOTE -- latest quote snapshot for a symbol."""
        payload = self._call("GLOBAL_QUOTE", {"symbol": symbol})
        data = payload.get("Global Quote") or {}
        return {k.split(". ", 1)[-1]: v for k, v in data.items()}

    def real_gdp(self, interval: str = "quarterly") -> pd.DataFrame:
        """REAL_GDP -- US real GDP, official BEA data."""
        return self._parse_economic_series(self._call("REAL_GDP", {"interval": interval}))

    def cpi(self, interval: str = "monthly") -> pd.DataFrame:
        """CPI -- US consumer price index, official BLS data."""
        return self._parse_economic_series(self._call("CPI", {"interval": interval}))

    def federal_funds_rate(self, interval: str = "monthly") -> pd.DataFrame:
        """FEDERAL_FUNDS_RATE -- effective federal funds rate, official Fed data."""
        return self._parse_economic_series(self._call("FEDERAL_FUNDS_RATE", {"interval": interval}))

    def treasury_yield(self, interval: str = "monthly", maturity: str = "10year") -> pd.DataFrame:
        """TREASURY_YIELD -- US Treasury yield, official daily par yield curve."""
        return self._parse_economic_series(
            self._call("TREASURY_YIELD", {"interval": interval, "maturity": maturity})
        )

    def unemployment(self) -> pd.DataFrame:
        """UNEMPLOYMENT -- US unemployment rate, official BLS data."""
        return self._parse_economic_series(self._call("UNEMPLOYMENT", {}))

    # -- Internals -----------------------------------------------------

    def _call(self, function: str, params: dict) -> dict:
        if not self.is_configured:
            raise AlphaVantageNotConfigured("ALPHA_VANTAGE_API_KEY is not set")

        cache_key = self._cache_key(function, params)
        cached = self._read_cache(cache_key, function)
        if cached is not None:
            return cached

        self._check_and_consume_quota()
        self._throttle()

        query = {"function": function, "apikey": self.api_key, **params}
        response = self._client.get(BASE_URL, params=query)
        response.raise_for_status()
        payload = response.json()

        for error_key in ("Error Message", "Note", "Information"):
            if error_key in payload:
                raise AlphaVantageError(f"Alpha Vantage {function} -- {error_key}: {payload[error_key]}")

        self._write_cache(cache_key, payload)
        return payload

    def _throttle(self) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._last_call_at
            if elapsed < MIN_SECONDS_BETWEEN_CALLS:
                time.sleep(MIN_SECONDS_BETWEEN_CALLS - elapsed)
            self._last_call_at = time.monotonic()

    def _cache_key(self, function: str, params: dict) -> str:
        raw = json.dumps({"function": function, **params}, sort_keys=True)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
        return f"{function}_{digest}"

    def _read_cache(self, cache_key: str, function: str) -> Optional[dict]:
        path = self.cache_dir / f"{cache_key}.json"
        if not path.exists():
            return None
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
            fetched_at = datetime.fromisoformat(envelope["fetched_at"])
        except (OSError, json.JSONDecodeError, KeyError, ValueError):
            return None
        ttl = CACHE_TTL_SECONDS.get(function, DEFAULT_CACHE_TTL_SECONDS)
        age = (datetime.now(timezone.utc) - fetched_at).total_seconds()
        if age > ttl:
            return None
        return envelope["payload"]

    def _write_cache(self, cache_key: str, payload: dict) -> None:
        path = self.cache_dir / f"{cache_key}.json"
        envelope = {"fetched_at": datetime.now(timezone.utc).isoformat(), "payload": payload}
        path.write_text(json.dumps(envelope), encoding="utf-8")

    def _check_and_consume_quota(self) -> None:
        with self._lock:
            today = date.today().isoformat()
            state = {"date": today, "count": 0}
            if self._quota_path.exists():
                try:
                    state = json.loads(self._quota_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    state = {"date": today, "count": 0}
            if state.get("date") != today:
                state = {"date": today, "count": 0}
            if state["count"] >= self.daily_limit:
                raise AlphaVantageQuotaExceeded(
                    f"Local Alpha Vantage daily quota ({self.daily_limit} requests) reached for {today}"
                )
            state["count"] += 1
            self._quota_path.write_text(json.dumps(state), encoding="utf-8")

    @staticmethod
    def _parse_time_series(payload: dict, series_key: str) -> pd.DataFrame:
        series = payload.get(series_key)
        if not series:
            raise AlphaVantageError(f"Unexpected response shape -- missing '{series_key}'")

        rows = []
        for ts, values in series.items():
            row = {"timestamp": ts}
            for raw_key, raw_val in values.items():
                name = raw_key.split(". ", 1)[-1].lower()
                name = name.split(" (")[0]  # strip legacy "(USD)"-style suffixes
                try:
                    row[name] = float(raw_val)
                except (TypeError, ValueError):
                    row[name] = raw_val
            rows.append(row)

        df = pd.DataFrame(rows)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.sort_values("timestamp").reset_index(drop=True)
        return df

    @staticmethod
    def _parse_economic_series(payload: dict) -> pd.DataFrame:
        data = payload.get("data")
        if not data:
            raise AlphaVantageError("Unexpected response shape -- missing 'data'")
        df = pd.DataFrame(data)
        df["date"] = pd.to_datetime(df["date"], utc=True)
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df = df.sort_values("date").reset_index(drop=True)
        return df


@lru_cache
def get_alpha_vantage_client() -> "AlphaVantageClient":
    """Return the process-wide cached Alpha Vantage client singleton, so the
    per-minute throttle and daily quota tracker are shared across every
    engine that uses one rather than reset per-instance."""
    settings = get_settings()
    return AlphaVantageClient(
        api_key=settings.alpha_vantage_api_key,
        daily_limit=settings.alpha_vantage_daily_limit,
    )
