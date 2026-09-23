"""
Tests for the API's exposure controls: the X-API-Key gate, the CORS
allowlist, and the loopback bind default.

WHY THESE EXIST. Before 2026-09-08 the API had no authentication on any of
its 78 routes, bound 0.0.0.0, and set allow_origins=["*"]. Nothing in the
suite would have noticed any of that, and nothing would notice it coming
back. These tests fail if it does.

The gate is exercised through the real `require_api_key` dependency with a
real Starlette Request, rather than by booting the whole app: importing
api.main costs ~14s and starting its lifespan initialises all 55 engines,
which would make a security regression test too slow to keep.
"""

import asyncio

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from project_titan_x.api.main import _AUTH_EXEMPT_PATHS, _CORS_ORIGINS, require_api_key
from project_titan_x.core.config import Settings


def _request(path: str, headers: dict[str, str] | None = None) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": "GET", "path": path, "headers": raw})


def _call(path: str, headers: dict[str, str] | None = None):
    return asyncio.run(require_api_key(_request(path, headers)))


@pytest.fixture
def keyed(monkeypatch):
    """Configure a known API key on the module-level settings the gate reads."""
    import project_titan_x.api.main as main

    monkeypatch.setattr(main.settings, "api_key", "test-key-abc123", raising=False)
    return "test-key-abc123"


# --- the gate ------------------------------------------------------------

def test_exempt_paths_need_no_key(keyed):
    """Health and docs stay reachable so a healthcheck needs no secret."""
    for path in _AUTH_EXEMPT_PATHS:
        assert _call(path) is None


def test_protected_route_rejects_missing_key(keyed):
    with pytest.raises(HTTPException) as e:
        _call("/api/v1/engines")
    assert e.value.status_code == 401


def test_protected_route_rejects_wrong_key(keyed):
    with pytest.raises(HTTPException) as e:
        _call("/api/v1/engines", {"X-API-Key": "wrong"})
    assert e.value.status_code == 401


def test_protected_route_accepts_correct_key(keyed):
    assert _call("/api/v1/engines", {"X-API-Key": keyed}) is None


def test_header_name_is_case_insensitive(keyed):
    """HTTP headers are case-insensitive; the gate must not depend on casing."""
    assert _call("/api/v1/engines", {"x-api-key": keyed}) is None


def test_write_route_is_protected(keyed):
    """The fetch/workflow routes are the ones worth protecting, not just reads."""
    for path in ("/api/v1/market-data/fetch", "/api/v1/brain/workflows/x/run"):
        with pytest.raises(HTTPException):
            _call(path)


def test_gate_is_inert_when_no_key_configured(monkeypatch):
    """Unset key = open API. Safe only because the bind is loopback, which
    test_default_bind_is_loopback pins, and which startup warns about."""
    import project_titan_x.api.main as main

    monkeypatch.setattr(main.settings, "api_key", None, raising=False)
    assert _call("/api/v1/engines") is None


# --- configuration defaults ---------------------------------------------

def test_default_bind_is_loopback():
    """The code default must be loopback even if a local .env widens it."""
    assert Settings(_env_file=None).api_host == "127.0.0.1"


def test_no_api_key_by_default():
    assert Settings(_env_file=None).api_key is None


def test_cors_is_not_wildcard():
    assert "*" not in _CORS_ORIGINS
    assert _CORS_ORIGINS, "an empty allowlist would silently disable CORS entirely"
    for origin in _CORS_ORIGINS:
        assert origin.startswith("http://") or origin.startswith("https://")


def test_cors_default_is_localhost_only():
    for origin in Settings(_env_file=None).cors_allow_origins.split(","):
        assert "localhost" in origin or "127.0.0.1" in origin
