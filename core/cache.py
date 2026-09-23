"""
Module: cache.py
Description: Thin, best-effort Redis cache client -- added 2026-08-21.
    `redis` has been an installed dependency (requirements.txt) and a
    running, healthy container (docker-compose.yml) since early in this
    project, but had ZERO actual usage anywhere in the codebase until
    this module -- confirmed via a full-repo grep before writing this.
    Its first real use is engines/e02_market_data's OHLCV fetch cache,
    the single largest real, measured contributor to slow multi-asset
    scans (a live-profiled ~0.78s of network I/O per asset, unavoidable
    on a cache miss but fully skippable on a hit within the same short
    window a trader is actively re-scanning in).

    Every function here is best-effort and NEVER raises: a Redis outage
    must degrade to "no caching" (same correctness, just the original
    per-call cost), not break a real data fetch or signal. Same
    never-block convention this codebase already uses for every other
    optional dependency (knowledge_engine, microstructure_engine, etc.).
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import redis
from redis.backoff import NoBackoff
from redis.retry import Retry

from project_titan_x.core.config import get_settings

logger = logging.getLogger(__name__)

_client: Optional[redis.Redis] = None


def get_cache_client() -> redis.Redis:
    """Process-wide cached Redis client -- same singleton convention as
    every core.data_providers get_*_client(). redis-py connects lazily
    (no real socket opened until the first command), so constructing
    this never itself fails even if Redis is currently unreachable --
    failures surface (and are caught) at the actual GET/SET call."""
    global _client
    if _client is None:
        settings = get_settings()
        # retry_on_timeout=False and an explicit Retry(0) matter as much as
        # the timeouts themselves: with redis-py's defaults a single "cache
        # miss" against a down Redis was measured at ~25 SECONDS, not the
        # 1.0s the socket timeout implies, because the client retried
        # underneath. Timeouts are also cut to 0.25s -- a local Redis that
        # cannot answer in 250ms is not helping a latency-sensitive path.
        _client = redis.Redis(
            host=settings.redis_host, port=settings.redis_port, db=settings.redis_db,
            socket_connect_timeout=0.25, socket_timeout=0.25,
            retry_on_timeout=False, retry=Retry(NoBackoff(), 0),
        )
    return _client


# Circuit breaker (added 2026-08-22). With Redis simply not running, this
# cache turned from an optimization into the single largest source of scan
# latency -- the exact opposite of why it exists.
#
# Measured, not estimated: one failed call took ~25 SECONDS (redis-py
# retried beneath the socket timeout, see get_cache_client above), and a
# scan issues a GET and a SET per asset. Combined with the retry fix, 30
# consecutive failed lookups went from minutes to 0.55s total.
#
# The FIRST failure opens the breaker (threshold 1): with Redis down the
# very next call would fail identically, so paying a second timeout to
# confirm it is pure waste on a user-facing path.
#
# After _FAIL_THRESHOLD consecutive failures the cache short-circuits for
# _COOLDOWN_SECONDS, returning instantly instead of timing out. One probe
# is allowed through after the cooldown, so a Redis that comes back up is
# picked up automatically rather than staying off until restart. Any
# success resets the breaker.
_FAIL_THRESHOLD = 1
_COOLDOWN_SECONDS = 60.0
_consecutive_failures = 0
_circuit_open_until = 0.0


def _circuit_open() -> bool:
    return _consecutive_failures >= _FAIL_THRESHOLD and time.monotonic() < _circuit_open_until


def _record_failure() -> None:
    global _consecutive_failures, _circuit_open_until
    _consecutive_failures += 1
    if _consecutive_failures == _FAIL_THRESHOLD:
        logger.warning(
            "Redis unreachable %d times consecutively -- bypassing cache for %.0fs "
            "so calls fail instantly instead of each paying the socket timeout.",
            _consecutive_failures, _COOLDOWN_SECONDS,
        )
    _circuit_open_until = time.monotonic() + _COOLDOWN_SECONDS


def _record_success() -> None:
    global _consecutive_failures, _circuit_open_until
    if _consecutive_failures:
        logger.info("Redis reachable again -- cache re-enabled.")
    _consecutive_failures = 0
    _circuit_open_until = 0.0


def cache_get_bytes(key: str) -> Optional[bytes]:
    """Returns the cached value, or None on a genuine cache miss OR any
    Redis failure (connection refused, timeout, etc.) -- callers cannot
    (and must not try to) distinguish the two; either way, the correct
    response is to fetch the real data fresh."""
    if _circuit_open():
        return None
    try:
        value = get_cache_client().get(key)
        _record_success()
        return value
    except Exception as e:
        _record_failure()
        logger.warning("Redis GET failed for key=%s (continuing without cache): %s", key, e)
        return None


def cache_set_bytes(key: str, value: bytes, ttl_seconds: int) -> None:
    """Best-effort write-through -- a failure here is silently swallowed
    (logged, not raised), since caching is strictly an optimization: the
    caller's real data was already fetched successfully before this is
    ever called, and that result must reach the caller regardless of
    whether the cache write succeeds."""
    if _circuit_open():
        return
    try:
        get_cache_client().setex(key, ttl_seconds, value)
        _record_success()
    except Exception as e:
        _record_failure()
        logger.warning("Redis SET failed for key=%s (continuing without cache): %s", key, e)
