"""
Module: test_cftc_client.py
Description: Unit tests for the CFTC COT report client -- real, no-auth
    public API, tested live (not mocked), same convention as
    test_derivatives_engine.py's Deribit tests.
Author: Shantanu Waykar
Version: 1.0.0
"""

import pytest

from project_titan_x.core.data_providers.cftc import SYMBOL_TO_CFTC_MARKET, get_cftc_client


def test_symbol_to_cftc_market_covers_expected_assets():
    assert SYMBOL_TO_CFTC_MARKET["GOLD"] == "GOLD - COMMODITY EXCHANGE INC."
    assert SYMBOL_TO_CFTC_MARKET["EURUSD"] == "EURO FX - CHICAGO MERCANTILE EXCHANGE"
    assert SYMBOL_TO_CFTC_MARKET["BTCUSD"] == "BITCOIN - CHICAGO MERCANTILE EXCHANGE"
    assert SYMBOL_TO_CFTC_MARKET["US10Y"] == "UST 10Y NOTE - CHICAGO BOARD OF TRADE"
    assert SYMBOL_TO_CFTC_MARKET["SP500"] == "E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE"
    # Indian-exchange instruments have no US futures contract -- no entry.
    assert "USDINR" not in SYMBOL_TO_CFTC_MARKET


@pytest.mark.network
def test_get_cot_report_bond_and_futures_return_real_data():
    client = get_cftc_client()
    bond = client.get_cot_report(SYMBOL_TO_CFTC_MARKET["US10Y"], limit=3)
    futures = client.get_cot_report(SYMBOL_TO_CFTC_MARKET["SP500"], limit=3)
    assert not bond.empty
    assert not futures.empty
    assert (bond["open_interest_all"] > 0).all()
    assert (futures["open_interest_all"] > 0).all()
    assert "NIFTY50" not in SYMBOL_TO_CFTC_MARKET


@pytest.mark.network
def test_get_cot_report_returns_real_gold_data():
    client = get_cftc_client()
    df = client.get_cot_report(SYMBOL_TO_CFTC_MARKET["GOLD"], limit=5)
    assert not df.empty
    assert len(df) <= 5
    assert "report_date" in df.columns
    assert "open_interest_all" in df.columns
    assert (df["open_interest_all"] > 0).all()
    # Sorted ascending by report_date (oldest first).
    assert df["report_date"].is_monotonic_increasing


@pytest.mark.network
def test_get_cot_report_bitcoin_is_real_and_distinct_from_gold():
    client = get_cftc_client()
    gold = client.get_cot_report(SYMBOL_TO_CFTC_MARKET["GOLD"], limit=1)
    btc = client.get_cot_report(SYMBOL_TO_CFTC_MARKET["BTCUSD"], limit=1)
    assert not gold.empty and not btc.empty
    assert gold["open_interest_all"].iloc[0] != btc["open_interest_all"].iloc[0]


@pytest.mark.network
def test_get_cot_report_unknown_market_returns_empty_not_error():
    client = get_cftc_client()
    df = client.get_cot_report("NOT A REAL MARKET NAME", limit=5)
    assert df.empty
