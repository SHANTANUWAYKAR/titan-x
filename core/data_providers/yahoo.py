"""
Module: yahoo.py
Description: One resilient wrapper around the raw `yfinance` calls that six
    engines were each making directly.

    THE PROBLEM THIS FIXES (docs/PROJECT_AUDIT.md, weakness W1). E02 Market
    Data owns a real fallback chain -- yfinance, then ccxt, then nselib,
    then Alpha Vantage. Six other engines (E04, E06, E10, E13, E14, E15)
    reached past it and called `yf.Ticker(...).history(...)` themselves, so
    they inherited NONE of that resilience. A Yahoo outage degraded each of
    them silently, and differently, depending on what each one's own
    try/except happened to do with the exception.

    That failure mode is not hypothetical on this platform: two strategy
    matrix runs were previously corrupted because a Yahoo outage surfaced
    as "insufficient history" rather than as an error, which is
    indistinguishable from a real finding.

    WHAT THIS DOES, AND DELIBERATELY DOES NOT DO. It adds bounded retry
    with backoff and ONE consistent, logged failure path, so an outage
    looks the same everywhere and is visible in the logs. It does NOT route
    these engines through E02.fetch_ohlcv, which would be a much larger
    change: E02 speaks (symbol, timeframe, years) against its own asset
    registry and records a catalog entry plus an audit-log row on every
    fetch, while these call sites want an ad-hoc ticker ("^GSPC", "IEF",
    "^TNX") over a relative period ("5d", "3mo"). Forcing them through that
    API would either pollute the catalog with non-registry tickers or need
    a second, parallel code path inside E02. Routing them properly is a
    real design decision; making their failure mode consistent is not, and
    is what was actually broken.

    NEVER RAISES. Every function returns an empty DataFrame or an empty
    dict on total failure, matching what each caller's existing try/except
    already degraded to -- so this is a resilience upgrade, not a change in
    contract.

Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# Bounded and short on purpose. These calls sit on interactive paths (a
# signal scan fans across assets), so a long retry ladder would turn one
# slow provider into a stalled scan -- the same "always return SOMETHING,
# never let one slow collaborator sink the whole call" discipline
# e51_signals.scan_all_assets already established.
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (0.5, 1.5)


def ticker_history(
    symbol: str,
    period: str = "5d",
    interval: Optional[str] = None,
    *,
    start: Optional[Any] = None,
    end: Optional[Any] = None,
    context: str = "",
) -> pd.DataFrame:
    """OHLCV history for `symbol`, or an EMPTY DataFrame.

    An empty frame is the honest answer when the provider is unreachable --
    every existing caller already checks `.empty` or lets the subsequent
    `.iloc[-1]` raise inside its own try/except, so the degraded path is
    unchanged. What changes is that the failure is retried first and then
    logged once, in the same shape, from every call site.

    start/end (added 2026-09-14, for research/cross_asset_ic_analysis.py's
    point-in-time backtest): yfinance's own `Ticker.history(start=, end=)`
    absolute-date window, an alternative to the relative `period` this
    function already took. Mutually exclusive with `period` at the
    yfinance API level -- passing `start` switches this call to the
    absolute-window mode instead of period; every existing caller passes
    neither, so this is purely additive. No new caller assumes anything
    about which mode a given call used internally."""
    last_err: Optional[Exception] = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            t = yf.Ticker(symbol)
            if start is not None:
                hist = t.history(start=start, end=end, interval=interval) if interval else t.history(start=start, end=end)
            else:
                hist = t.history(period=period, interval=interval) if interval else t.history(period=period)
            if hist is not None and not hist.empty:
                return hist
            # An empty frame is not necessarily an outage -- a delisted or
            # wrong ticker returns empty too. Retrying once distinguishes a
            # transient blip from a genuinely empty series without turning
            # a bad ticker into three slow calls every time.
            if attempt == MAX_ATTEMPTS:
                logger.warning(
                    "Yahoo returned no rows for %s (period=%s)%s -- treating as unavailable",
                    symbol, period, f" [{context}]" if context else "",
                )
                return pd.DataFrame()
        except Exception as e:  # noqa: BLE001 - provider errors are not enumerable
            last_err = e
        if attempt < MAX_ATTEMPTS:
            time.sleep(BACKOFF_SECONDS[min(attempt - 1, len(BACKOFF_SECONDS) - 1)])

    logger.warning(
        "Yahoo fetch FAILED for %s (period=%s) after %d attempts%s: %s",
        symbol, period, MAX_ATTEMPTS, f" [{context}]" if context else "", last_err,
    )
    return pd.DataFrame()


def ticker_info(symbol: str, *, context: str = "") -> dict[str, Any]:
    """`.info` for `symbol`, or an EMPTY dict.

    Separate from ticker_history because `.info` is a different Yahoo
    endpoint with its own failure behaviour -- it can return a dict of
    mostly-None values rather than raising, which callers already handle
    with `.get(...)`.
    """
    last_err: Optional[Exception] = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            info = yf.Ticker(symbol).info
            if info:
                return dict(info)
            if attempt == MAX_ATTEMPTS:
                logger.warning("Yahoo returned empty info for %s%s", symbol,
                               f" [{context}]" if context else "")
                return {}
        except Exception as e:  # noqa: BLE001
            last_err = e
        if attempt < MAX_ATTEMPTS:
            time.sleep(BACKOFF_SECONDS[min(attempt - 1, len(BACKOFF_SECONDS) - 1)])

    logger.warning("Yahoo info FAILED for %s after %d attempts%s: %s",
                   symbol, MAX_ATTEMPTS, f" [{context}]" if context else "", last_err)
    return {}
