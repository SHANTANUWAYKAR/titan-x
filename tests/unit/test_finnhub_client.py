"""Unit tests for the Finnhub client -- HTTP is mocked, no live calls."""

import httpx
import pytest

from project_titan_x.core.data_providers import finnhub as fh_module
from project_titan_x.core.data_providers.finnhub import (
    FinnhubClient,
    FinnhubError,
    FinnhubNotConfigured,
)


@pytest.fixture(autouse=True)
def no_throttle(monkeypatch):
    monkeypatch.setattr(fh_module, "MIN_SECONDS_BETWEEN_CALLS", 0.0)


@pytest.fixture
def client(tmp_path):
    c = FinnhubClient(api_key="demo", cache_dir=tmp_path)
    yield c
    c.close()


def _mock_response(status: int, payload) -> httpx.Response:
    return httpx.Response(status, json=payload, request=httpx.Request("GET", fh_module.BASE_URL))


def test_not_configured_raises(tmp_path):
    c = FinnhubClient(api_key=None, cache_dir=tmp_path)
    with pytest.raises(FinnhubNotConfigured):
        c.economic_calendar("2026-07-01", "2026-07-31")


def test_economic_calendar_parses_and_caches(client, monkeypatch):
    payload = {"economicCalendar": [
        {"event": "Fed Interest Rate Decision", "time": "2026-07-30 18:00:00", "impact": "high", "country": "US"},
        {"event": "Core CPI", "time": "2026-07-15 12:30:00", "impact": "medium", "country": "US"},
    ]}
    calls = {"count": 0}

    def fake_get(self, url, params=None, **kwargs):
        calls["count"] += 1
        return _mock_response(200, payload)

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    events = client.economic_calendar("2026-07-01", "2026-07-31")
    assert len(events) == 2
    assert events[0]["event"] == "Fed Interest Rate Decision"
    assert calls["count"] == 1

    # Second call within TTL must hit the disk cache, not the network.
    events2 = client.economic_calendar("2026-07-01", "2026-07-31")
    assert calls["count"] == 1
    assert len(events2) == 2


def test_missing_key_shape_raises(client, monkeypatch):
    monkeypatch.setattr(httpx.Client, "get", lambda self, url, params=None, **kw: _mock_response(200, {}))
    with pytest.raises(FinnhubError):
        client.economic_calendar("2026-07-01", "2026-07-31")


def test_401_raises_with_clear_message(client, monkeypatch):
    monkeypatch.setattr(
        httpx.Client, "get",
        lambda self, url, params=None, **kw: _mock_response(401, {"error": "Invalid API key"}),
    )
    with pytest.raises(FinnhubError, match="401"):
        client.economic_calendar("2026-07-01", "2026-07-31")


def test_429_raises_rate_limit_error(client, monkeypatch):
    monkeypatch.setattr(
        httpx.Client, "get",
        lambda self, url, params=None, **kw: _mock_response(429, {"error": "limit exceeded"}),
    )
    with pytest.raises(FinnhubError, match="429"):
        client.economic_calendar("2026-07-01", "2026-07-31")
