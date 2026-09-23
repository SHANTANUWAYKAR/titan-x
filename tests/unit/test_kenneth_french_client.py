"""Unit tests for the Kenneth French Data Library client -- HTTP is mocked
except for the two tests explicitly marked @pytest.mark.network."""

import io
import zipfile

import httpx
import pytest

from project_titan_x.core.data_providers.kenneth_french import (
    KennethFrenchClient,
    KennethFrenchError,
)

_SAMPLE_3FACTOR_CSV = """This file was created by using the 202605 CRSP database.
The Tbill return is the simple daily rate.

,Mkt-RF,SMB,HML,RF
19260701,    0.09,   -0.25,   -0.27,    0.01
19260702,    0.45,   -0.33,   -0.06,    0.01

Copyright 2026 Eugene F. Fama and Kenneth R. French
"""

_SAMPLE_MOMENTUM_CSV = """This file was created by using the 202605 CRSP database.  It,,
contains a momentum factor, constructed from six value-weight portfolios,,
,,
Missing data are indicated by -99.99 or -999.,,
,,
,Mom,
19261103,0.35,
19261104,-99.99,
19261105,1.15,
"""


def _zip_bytes(inner_name: str, text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(inner_name, text)
    return buf.getvalue()


@pytest.fixture
def client(tmp_path):
    c = KennethFrenchClient(cache_dir=tmp_path)
    yield c
    c.close()


def test_parses_3factor_csv_correctly(client, monkeypatch):
    payload = _zip_bytes("F-F_Research_Data_Factors_daily.csv", _SAMPLE_3FACTOR_CSV)
    monkeypatch.setattr(httpx.Client, "get", lambda self, url, **kw: httpx.Response(200, content=payload, request=httpx.Request("GET", url)))
    df = client.get_factors_daily("3factor")
    assert list(df.columns) == ["Mkt-RF", "SMB", "HML", "RF"]
    assert len(df) == 2
    assert df.iloc[0]["Mkt-RF"] == pytest.approx(0.0009)  # 0.09% -> fraction
    assert df.iloc[0]["RF"] == pytest.approx(0.0001)


def test_header_detection_skips_blank_comma_lines_in_momentum_format(client, monkeypatch):
    """Real bug found and fixed 2026-07-20: a blank descriptive line
    (',,') earlier in the file matched a naive "starts with comma" header
    search before the REAL header row. This test locks in the fix using
    the exact structure that broke it."""
    payload = _zip_bytes("F-F_Momentum_Factor_daily.csv", _SAMPLE_MOMENTUM_CSV)
    monkeypatch.setattr(httpx.Client, "get", lambda self, url, **kw: httpx.Response(200, content=payload, request=httpx.Request("GET", url)))
    df = client.get_factors_daily("momentum")
    assert list(df.columns) == ["Mom"]
    assert len(df) == 3


def test_missing_data_sentinel_becomes_nan_not_a_fabricated_value(client, monkeypatch):
    payload = _zip_bytes("F-F_Momentum_Factor_daily.csv", _SAMPLE_MOMENTUM_CSV)
    monkeypatch.setattr(httpx.Client, "get", lambda self, url, **kw: httpx.Response(200, content=payload, request=httpx.Request("GET", url)))
    df = client.get_factors_daily("momentum")
    assert df["Mom"].isna().sum() == 1
    assert df.iloc[1].isna().all()  # the -99.99 row


def test_caches_to_disk_second_call_no_network(client, monkeypatch):
    payload = _zip_bytes("F-F_Research_Data_Factors_daily.csv", _SAMPLE_3FACTOR_CSV)
    calls = {"count": 0}

    def fake_get(self, url, **kw):
        calls["count"] += 1
        return httpx.Response(200, content=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    client.get_factors_daily("3factor")
    client.get_factors_daily("3factor")
    assert calls["count"] == 1


def test_unknown_dataset_raises():
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        c = KennethFrenchClient(cache_dir=Path(tmp))
        with pytest.raises(KennethFrenchError):
            c.get_factors_daily("not_a_real_dataset")
        c.close()


def test_non_200_response_raises(client, monkeypatch):
    monkeypatch.setattr(httpx.Client, "get", lambda self, url, **kw: httpx.Response(404, request=httpx.Request("GET", url)))
    with pytest.raises(KennethFrenchError):
        client.get_factors_daily("3factor")


def test_malformed_csv_raises_not_silently_empty(client, monkeypatch):
    payload = _zip_bytes("bad.csv", "not,a,real,fama,french,file\njust text\n")
    monkeypatch.setattr(httpx.Client, "get", lambda self, url, **kw: httpx.Response(200, content=payload, request=httpx.Request("GET", url)))
    with pytest.raises(KennethFrenchError):
        client.get_factors_daily("3factor")


@pytest.mark.network
def test_real_3factor_endpoint_returns_real_data():
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        c = KennethFrenchClient(cache_dir=Path(tmp))
        df = c.get_factors_daily("3factor")
        assert len(df) > 20000  # real file has 26,000+ real daily rows
        assert list(df.columns) == ["Mkt-RF", "SMB", "HML", "RF"]
        c.close()


@pytest.mark.network
def test_real_momentum_endpoint_parses_correctly_not_just_3factor():
    """The header-detection bug specifically affected the momentum file's
    real format -- a mocked test alone wouldn't catch a future real change
    on French's actual server, hence this real-network companion test."""
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        c = KennethFrenchClient(cache_dir=Path(tmp))
        df = c.get_factors_daily("momentum")
        assert len(df) > 20000
        assert list(df.columns) == ["Mom"]
        c.close()
