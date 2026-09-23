"""Unit tests for asset whitelist (equities: price/technical scope only, no ETFs)."""

import pytest

from project_titan_x.core.config import (
    AssetClass,
    get_asset,
    is_asset_supported,
    list_assets,
)


def test_equities_supported_price_technical_scope_only():
    """Equities were added 2026-07-19 for price/technical analysis and
    backtesting only (E02/E07/E24/E26/E27/E28/E51) -- NOT fundamental/
    credit analysis (e06_fundamental/e15_credit still have no per-company
    financials ingestion anywhere). See core/config/assets.py's module
    docstring for the full scope note."""
    assert is_asset_supported("AAPL")
    assert is_asset_supported("RELIANCE.NS")
    assert is_asset_supported("TSLA")


def test_forex_supported():
    assert is_asset_supported("EURUSD")
    assert is_asset_supported("EURUSD=X")


def test_crypto_supported():
    assert is_asset_supported("BTCUSD")
    assert is_asset_supported("BTC-USD")


def test_index_supported():
    assert is_asset_supported("NIFTY50")
    assert get_asset("NIFTY50").yahoo_symbol == "^NSEI"


def test_list_assets_includes_equity_class():
    assets = list_assets()
    classes = {a.asset_class for a in assets}
    assert AssetClass.FOREX in classes
    assert AssetClass.CRYPTO in classes
    assert AssetClass.COMMODITY in classes
    assert AssetClass.INDEX in classes
    assert AssetClass.EQUITY in classes


def test_list_assets_filters_by_equity_class():
    equities = list_assets(asset_class=AssetClass.EQUITY)
    symbols = {a.symbol for a in equities}
    assert "AAPL" in symbols
    assert "RELIANCE" in symbols
    assert all(a.asset_class == AssetClass.EQUITY for a in equities)


def test_etfs_still_not_supported():
    """Master prompt lists ETFs as an asset class; this platform
    deliberately excludes them (same no-equities rationale as stocks) --
    confirms adding BOND/FUTURES didn't accidentally open this door too."""
    assert not is_asset_supported("SPY")
    assert not is_asset_supported("QQQ")


def test_bond_supported():
    assert is_asset_supported("US10Y")
    assert is_asset_supported("ZN=F")
    asset = get_asset("US10Y")
    assert asset.asset_class == AssetClass.BOND
    assert asset.yahoo_symbol == "ZN=F"


def test_futures_supported():
    assert is_asset_supported("SP500")
    assert is_asset_supported("MES=F")
    asset = get_asset("SP500")
    assert asset.asset_class == AssetClass.FUTURES
    assert asset.yahoo_symbol == "MES=F"


def test_futures_asset_is_an_index_not_an_individual_equity():
    """The new FUTURES asset (SP500) must be an index future, not a
    single-company instrument -- keeps the no-equities boundary intact."""
    asset = get_asset("SP500")
    assert "S&P 500" in asset.name
    assert asset.symbol != "AAPL"  # sanity: not accidentally a stock ticker


def test_options_class_exists_but_has_no_dedicated_asset():
    """OPTIONS is a real AssetClass value (documented: options are a
    derivative overlay on BTCUSD/ETHUSD, covered by e13_derivatives, not a
    standalone SUPPORTED_ASSETS entry)."""
    assert AssetClass.OPTIONS == "options"
    assets = list_assets(asset_class=AssetClass.OPTIONS)
    assert assets == []


def test_list_assets_includes_bond_and_futures_classes():
    assets = list_assets()
    classes = {a.asset_class for a in assets}
    assert AssetClass.BOND in classes
    assert AssetClass.FUTURES in classes


def test_list_assets_filters_by_bond_class():
    bonds = list_assets(asset_class=AssetClass.BOND)
    assert len(bonds) == 1
    assert bonds[0].symbol == "US10Y"


# ---- shorthand aliases (SYMBOL_ALIASES) ----
# Regression coverage for a real user-facing bug: "BTC" (natural shorthand
# for Bitcoin) previously resolved to nothing -- get_asset/is_asset_supported
# only ever matched an exact SUPPORTED_ASSETS key or yahoo_symbol, with no
# fallback for common shorthand. dashboard/index.html's resolveSymbolInput
# has its own client-side mirror of this same alias table -- keep both in
# sync if either changes.


def test_btc_shorthand_resolves_to_btcusd():
    assert is_asset_supported("BTC")
    assert is_asset_supported("btc")
    asset = get_asset("BTC")
    assert asset.symbol == "BTCUSD"
    assert asset.yahoo_symbol == "BTC-USD"


def test_common_shorthand_aliases_resolve():
    assert get_asset("ETH").symbol == "ETHUSD"
    assert get_asset("XAUUSD").symbol == "GOLD"
    assert get_asset("OIL").symbol == "CRUDE"
    assert get_asset("WTI").symbol == "CRUDE"
    assert get_asset("NIFTY").symbol == "NIFTY50"
    assert get_asset("SPX").symbol == "SP500"


def test_unknown_shorthand_still_unsupported():
    assert get_asset("DOGE") is None
    assert not is_asset_supported("DOGE")
