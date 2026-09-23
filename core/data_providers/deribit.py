"""
Module: deribit.py
Description: Deribit public REST client -- free, no-auth crypto options
             market data (https://docs.deribit.com/#public-get_book_summary_by_currency,
             #public-get_ticker). Used by e13_derivatives since Deribit is the
             only genuinely free options data source for this platform's
             asset universe (BTC/ETH); no free options chain exists for
             forex/commodities/indices.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-07-16
"""

import logging
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://www.deribit.com/api/v2/public"
SUPPORTED_CURRENCIES = {"BTC", "ETH"}  # the only crypto options Deribit lists


class DeribitError(Exception):
    """Raised when Deribit returns an error payload or an unsupported currency is requested."""


class DeribitClient:
    """Thin, unauthenticated REST client for Deribit's public market-data
    endpoints. No API key, no daily quota -- this is public options-chain
    data, same as anyone can see on Deribit's own website."""

    def __init__(self, timeout: float = 15.0) -> None:
        self._client = httpx.Client(timeout=timeout, base_url=BASE_URL)
        self._last_call_at = 0.0
        self._min_seconds_between_calls = 0.2  # light self-throttle, courteous to a free public API

    def close(self) -> None:
        self._client.close()

    def get_book_summary_by_currency(self, currency: str, kind: str = "option") -> list[dict]:
        """All live instruments of `kind` for `currency`, each with
        mark_iv, open_interest, volume, strike/expiry embedded in
        instrument_name. One call covers the entire options chain."""
        return self._call("get_book_summary_by_currency", {"currency": currency, "kind": kind})

    def get_ticker(self, instrument_name: str) -> dict:
        """Real-time greeks (delta/gamma/theta/vega/rho), mark_iv, and
        open_interest for one specific instrument."""
        result = self._call("ticker", {"instrument_name": instrument_name})
        return result if isinstance(result, dict) else {}

    def _call(self, endpoint: str, params: dict):
        if params.get("currency") and params["currency"] not in SUPPORTED_CURRENCIES:
            raise DeribitError(f"Deribit lists options only for {sorted(SUPPORTED_CURRENCIES)}, got {params['currency']!r}")
        self._throttle()
        response = self._client.get(f"/{endpoint}", params=params)
        response.raise_for_status()
        payload = response.json()
        if "error" in payload:
            raise DeribitError(f"Deribit {endpoint} error: {payload['error']}")
        return payload.get("result")

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_call_at
        if elapsed < self._min_seconds_between_calls:
            time.sleep(self._min_seconds_between_calls - elapsed)
        self._last_call_at = time.monotonic()


_client: Optional[DeribitClient] = None


def get_deribit_client() -> DeribitClient:
    """Process-wide cached Deribit client singleton."""
    global _client
    if _client is None:
        _client = DeribitClient()
    return _client
