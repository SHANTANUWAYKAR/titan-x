"""
Module: cftc.py
Description: CFTC public Socrata Open Data client -- free, no-auth weekly
             Commitment of Traders (COT) futures positioning reports
             (https://publicreporting.cftc.gov, "Futures Only" legacy
             report, dataset 6dca-aqww). Real, published-by-regulator
             hedger/speculator positioning data -- no API key, no quota.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-07-16
"""

import logging
from typing import Optional

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

BASE_URL = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"

# Platform asset symbol -> exact CFTC "market_and_exchange_names" value on
# the legacy Futures-Only COT report. Verified live against the real API,
# not guessed -- CFTC's commodity_name field alone is ambiguous (e.g.
# "CRUDE OIL" covers several distinct contracts), so this maps to the
# precise market/exchange string instead.
SYMBOL_TO_CFTC_MARKET = {
    "EURUSD": "EURO FX - CHICAGO MERCANTILE EXCHANGE",
    "GBPUSD": "BRITISH POUND - CHICAGO MERCANTILE EXCHANGE",
    "USDJPY": "JAPANESE YEN - CHICAGO MERCANTILE EXCHANGE",
    "GOLD": "GOLD - COMMODITY EXCHANGE INC.",
    "SILVER": "SILVER - COMMODITY EXCHANGE INC.",
    "CRUDE": "WTI-PHYSICAL - NEW YORK MERCANTILE EXCHANGE",
    "BTCUSD": "BITCOIN - CHICAGO MERCANTILE EXCHANGE",
    "ETHUSD": "ETHER CASH SETTLED - CHICAGO MERCANTILE EXCHANGE",
    "US10Y": "UST 10Y NOTE - CHICAGO BOARD OF TRADE",
    "SP500": "E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE",
    # USDINR, NIFTY50, BANKNIFTY: not US-listed futures contracts -- CFTC
    # has no COT data for these, and none is fabricated here.
}


class CFTCError(Exception):
    """Raised when the CFTC Socrata endpoint returns an error or unusable payload."""


class CFTCClient:
    """Thin, unauthenticated REST client for CFTC's public COT dataset."""

    def __init__(self, timeout: float = 20.0) -> None:
        self._client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def get_cot_report(self, market_and_exchange_names: str, limit: int = 52) -> pd.DataFrame:
        """Most recent `limit` weekly COT reports for one exact market.
        Returns an empty DataFrame (not an error) if CFTC has no data for
        this market name -- a wrong/unmapped name should fail loudly at
        the caller, not silently look like zero rows are "normal"."""
        params = {
            "$limit": limit,
            "$order": "report_date_as_yyyy_mm_dd DESC",
            "market_and_exchange_names": market_and_exchange_names,
        }
        response = self._client.get(BASE_URL, params=params)
        response.raise_for_status()
        rows = response.json()
        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        df["report_date"] = pd.to_datetime(df["report_date_as_yyyy_mm_dd"], utc=True)
        numeric_cols = [
            "open_interest_all", "noncomm_positions_long_all", "noncomm_positions_short_all",
            "comm_positions_long_all", "comm_positions_short_all",
            "nonrept_positions_long_all", "nonrept_positions_short_all",
        ]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.sort_values("report_date").reset_index(drop=True)
        return df


_client: Optional[CFTCClient] = None


def get_cftc_client() -> CFTCClient:
    """Process-wide cached CFTC client singleton."""
    global _client
    if _client is None:
        _client = CFTCClient()
    return _client
