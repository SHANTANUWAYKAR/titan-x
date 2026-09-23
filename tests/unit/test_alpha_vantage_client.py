"""Unit tests for the Alpha Vantage client -- HTTP is mocked, no live calls."""

import httpx
import pytest

from project_titan_x.core.data_providers import alpha_vantage as av_module
from project_titan_x.core.data_providers.alpha_vantage import (
    AlphaVantageClient,
    AlphaVantageError,
    AlphaVantageNotConfigured,
    AlphaVantageQuotaExceeded,
)


@pytest.fixture(autouse=True)
def no_throttle(monkeypatch):
    """Free-tier throttle is a real 12s sleep between live calls; tests only
    ever make one live call per case so this is defensive, not load-bearing."""
    monkeypatch.setattr(av_module, "MIN_SECONDS_BETWEEN_CALLS", 0.0)


@pytest.fixture
def client(tmp_path):
    c = AlphaVantageClient(api_key="demo", daily_limit=3, cache_dir=tmp_path)
    yield c
    c.close()


def _mock_response(payload: dict) -> httpx.Response:
    return httpx.Response(200, json=payload, request=httpx.Request("GET", av_module.BASE_URL))


def test_not_configured_raises(tmp_path):
    c = AlphaVantageClient(api_key=None, cache_dir=tmp_path)
    with pytest.raises(AlphaVantageNotConfigured):
        c.time_series_daily("IBM")


def test_fx_daily_parses_sorted_and_caches(client, monkeypatch):
    payload = {
        "Time Series FX (Daily)": {
            "2026-07-13": {"1. open": "1.10", "2. high": "1.12", "3. low": "1.09", "4. close": "1.11"},
            "2026-07-12": {"1. open": "1.08", "2. high": "1.11", "3. low": "1.07", "4. close": "1.10"},
        }
    }
    calls = {"count": 0}

    def fake_get(self, url, params=None, **kwargs):
        calls["count"] += 1
        return _mock_response(payload)

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    df = client.fx_daily("EUR", "USD")
    assert list(df["close"]) == [1.10, 1.11]  # sorted ascending by timestamp
    assert calls["count"] == 1

    # Second call within TTL must hit the disk cache, not the network.
    df2 = client.fx_daily("EUR", "USD")
    assert calls["count"] == 1
    assert len(df2) == 2


def test_crypto_daily_parses(client, monkeypatch):
    payload = {
        "Time Series (Digital Currency Daily)": {
            "2026-07-13": {
                "1. open": "50000",
                "2. high": "51000",
                "3. low": "49000",
                "4. close": "50500",
                "5. volume": "1234.5",
            },
        }
    }
    monkeypatch.setattr(httpx.Client, "get", lambda self, url, params=None, **kw: _mock_response(payload))
    df = client.crypto_daily("BTC", "USD")
    assert df.loc[0, "close"] == 50500.0
    assert df.loc[0, "volume"] == 1234.5


def test_economic_indicator_parses(client, monkeypatch):
    payload = {"data": [{"date": "2026-06-01", "value": "3.1"}, {"date": "2026-07-01", "value": "3.3"}]}
    monkeypatch.setattr(httpx.Client, "get", lambda self, url, params=None, **kw: _mock_response(payload))
    df = client.cpi()
    assert list(df["value"]) == [3.1, 3.3]


def test_error_payload_raises(client, monkeypatch):
    monkeypatch.setattr(
        httpx.Client,
        "get",
        lambda self, url, params=None, **kw: _mock_response({"Note": "rate limit hit"}),
    )
    with pytest.raises(AlphaVantageError):
        client.time_series_daily("IBM")


def test_daily_quota_enforced(client, monkeypatch):
    monkeypatch.setattr(
        httpx.Client,
        "get",
        lambda self, url, params=None, **kw: _mock_response(
            {"data": [{"date": "2026-07-01", "value": "1.0"}]}
        ),
    )
    client.cpi()
    client.federal_funds_rate()
    client.unemployment()  # 3rd distinct call -- daily_limit=3 now exhausted
    with pytest.raises(AlphaVantageQuotaExceeded):
        client.real_gdp()
