"""Unit tests for the FRED client -- HTTP is mocked, no live calls."""

import httpx
import pytest

from project_titan_x.core.data_providers import fred as fred_module
from project_titan_x.core.data_providers.fred import (
    FredClient,
    FredError,
    FredNotConfigured,
)


@pytest.fixture(autouse=True)
def no_throttle(monkeypatch):
    monkeypatch.setattr(fred_module, "MIN_SECONDS_BETWEEN_CALLS", 0.0)


@pytest.fixture
def client(tmp_path):
    c = FredClient(api_key="abcdefghijklmnopqrstuvwxyz012345", cache_dir=tmp_path)
    yield c
    c.close()


def _mock_response(status: int, payload) -> httpx.Response:
    return httpx.Response(status, json=payload, request=httpx.Request("GET", fred_module.BASE_URL))


def test_not_configured_raises(tmp_path):
    c = FredClient(api_key=None, cache_dir=tmp_path)
    with pytest.raises(FredNotConfigured):
        c.series_observations("WALCL")


def test_series_observations_parses_and_caches(client, monkeypatch):
    payload = {"observations": [
        {"date": "2026-06-01", "value": "7500000"},
        {"date": "2026-06-08", "value": "7510000"},
    ]}
    calls = {"count": 0}

    def fake_get(self, url, params=None, **kwargs):
        calls["count"] += 1
        return _mock_response(200, payload)

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    obs = client.series_observations("WALCL")
    assert len(obs) == 2
    assert obs[0]["date"] == "2026-06-01"
    assert calls["count"] == 1

    # Second call within TTL must hit the disk cache, not the network.
    obs2 = client.series_observations("WALCL")
    assert calls["count"] == 1
    assert len(obs2) == 2


def test_missing_key_shape_raises(client, monkeypatch):
    monkeypatch.setattr(httpx.Client, "get", lambda self, url, params=None, **kw: _mock_response(200, {}))
    with pytest.raises(FredError):
        client.series_observations("WALCL")


def test_400_raises_with_clear_message(client, monkeypatch):
    monkeypatch.setattr(
        httpx.Client, "get",
        lambda self, url, params=None, **kw: _mock_response(400, {"error_code": 400, "error_message": "bad api_key"}),
    )
    with pytest.raises(FredError, match="400"):
        client.series_observations("WALCL")


def test_429_raises_rate_limit_error(client, monkeypatch):
    monkeypatch.setattr(
        httpx.Client, "get",
        lambda self, url, params=None, **kw: _mock_response(429, {"error": "limit exceeded"}),
    )
    with pytest.raises(FredError, match="429"):
        client.series_observations("WALCL")


@pytest.mark.network
def test_real_fred_endpoint_requires_a_real_key():
    """Live proof (Rule 4): FRED's real REST endpoint rejects an
    unconfigured/demo key with a real 400, not a silent success -- confirms
    this client's is_configured gate reflects a real requirement, not an
    assumed one."""
    c = FredClient(api_key="demo")
    with pytest.raises(FredError, match="400"):
        c.series_observations("WALCL")
    c.close()


@pytest.mark.network
def test_real_fred_csv_endpoint_needs_no_key(tmp_path):
    """Live proof (Rule 4, the other direction): the public CSV download
    endpoint DOES work with no API key at all -- real 200, real historical
    WALCL data. This is the endpoint e19_global_liquidity actually uses;
    the REST API above requiring a key does not mean FRED has no free
    access path."""
    c = FredClient(api_key=None, cache_dir=tmp_path)
    obs = c.series_observations_csv("WALCL")
    assert len(obs) > 100
    assert obs[0]["date"] < obs[-1]["date"]
    c.close()
