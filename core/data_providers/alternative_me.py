"""
Module: alternative_me.py
Description: alternative.me public API client -- free, no-auth Crypto
             Fear & Greed Index (https://alternative.me/crypto/fear-and-greed-index/).
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-07-16
"""

import logging
from typing import Optional

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

BASE_URL = "https://api.alternative.me/fng/"


class AlternativeMeError(Exception):
    """Raised when the alternative.me endpoint returns an error or unusable payload."""


class AlternativeMeClient:
    """Thin, unauthenticated REST client for alternative.me's Fear & Greed Index."""

    def __init__(self, timeout: float = 15.0) -> None:
        self._client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def get_fear_greed_index(self, limit: int = 30) -> pd.DataFrame:
        """Most recent `limit` days of the Fear & Greed Index (0-100,
        "Extreme Fear" to "Extreme Greed"). Market-wide crypto sentiment,
        not asset-specific -- same reading regardless of which supported
        crypto asset is being analyzed."""
        response = self._client.get(BASE_URL, params={"limit": limit})
        response.raise_for_status()
        payload = response.json()
        if payload.get("metadata", {}).get("error"):
            raise AlternativeMeError(f"alternative.me error: {payload['metadata']['error']}")
        data = payload.get("data") or []
        if not data:
            return pd.DataFrame()

        df = pd.DataFrame(data)
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df["timestamp"] = pd.to_datetime(df["timestamp"].astype(int), unit="s", utc=True)
        df = df.rename(columns={"value_classification": "classification"})
        df = df[["timestamp", "value", "classification"]].sort_values("timestamp").reset_index(drop=True)
        return df


_client: Optional[AlternativeMeClient] = None


def get_alternative_me_client() -> AlternativeMeClient:
    """Process-wide cached alternative.me client singleton."""
    global _client
    if _client is None:
        _client = AlternativeMeClient()
    return _client
