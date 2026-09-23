"""
Module: assets.py
Description: Supported asset classes and symbols for PROJECT TITAN-X.
             Matches the master prompt's ASSET CLASSES list (Forex, Stocks,
             ETFs, Futures, Options, Commodities, Indices, Bonds,
             Cryptocurrency) minus ETFs (see EXCLUDED_ASSET_CLASSES).

             EQUITY scope, deliberately narrow: added at explicit user
             request (2026-07-19) for PRICE-BASED technical analysis and
             strategy backtesting only (E02/E07/E24/E26/E27/E28/E51) --
             NOT fundamental/credit analysis. e06_fundamental and
             e15_credit still have no per-company financials/earnings/AUM
             ingestion anywhere in this codebase, so a stock's
             fundamental_context/credit read stays the same honest gap it
             always was (same as e16_commodity limiting itself to
             GOLD/SILVER/CRUDE rather than fabricating coverage for
             copper/agriculture). ETFs remain excluded -- an ETF's
             genuine complexity (AUM flows, tracking error, creation/
             redemption mechanics) is a different, still-unaddressed gap
             from a single company's own price series.

             OPTIONS has no dedicated SUPPORTED_ASSETS entry: an option
             isn't a standalone tradable instrument the way spot/futures/
             bonds are, it's a derivative contract family on an existing
             underlying (already BTCUSD/ETHUSD here) -- see
             engines/e13_derivatives, which covers real BTC/ETH options
             data (Deribit) against those same two symbols.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-07-19
"""

from dataclasses import dataclass
from enum import Enum


class AssetClass(str, Enum):
    """Supported asset classes (no ETFs -- see module docstring)."""

    FOREX = "forex"
    CRYPTO = "crypto"
    COMMODITY = "commodity"
    INDEX = "index"
    BOND = "bond"
    FUTURES = "futures"
    EQUITY = "equity"  # price/technical scope only -- see module docstring
    OPTIONS = "options"  # no dedicated SUPPORTED_ASSETS entry -- see module docstring


@dataclass(frozen=True)
class AssetDefinition:
    """Definition of a tradable instrument."""

    symbol: str
    name: str
    asset_class: AssetClass
    yahoo_symbol: str
    min_lot_note: str
    typical_spread_pips: float


# Curated for small capital — forex, crypto, commodities, indices, bonds,
# futures, and (price/technical scope only, see module docstring) equities.
SUPPORTED_ASSETS: dict[str, AssetDefinition] = {
    # Forex (low minimum, high liquidity)
    "EURUSD": AssetDefinition("EURUSD", "Euro / US Dollar", AssetClass.FOREX, "EURUSD=X", "Micro lots from $1", 0.8),
    "GBPUSD": AssetDefinition("GBPUSD", "British Pound / US Dollar", AssetClass.FOREX, "GBPUSD=X", "Micro lots from $1", 1.0),
    "USDJPY": AssetDefinition("USDJPY", "US Dollar / Japanese Yen", AssetClass.FOREX, "USDJPY=X", "Micro lots from $1", 0.9),
    "USDINR": AssetDefinition("USDINR", "US Dollar / Indian Rupee", AssetClass.FOREX, "USDINR=X", "Exchange traded", 0.05),
    # Crypto (fractional units)
    "BTCUSD": AssetDefinition("BTCUSD", "Bitcoin", AssetClass.CRYPTO, "BTC-USD", "Fractional from ~$10", 0.0),
    "ETHUSD": AssetDefinition("ETHUSD", "Ethereum", AssetClass.CRYPTO, "ETH-USD", "Fractional from ~$5", 0.0),
    # Commodities
    "GOLD": AssetDefinition("GOLD", "Gold", AssetClass.COMMODITY, "GC=F", "Micro gold contracts", 0.3),
    "SILVER": AssetDefinition("SILVER", "Silver", AssetClass.COMMODITY, "SI=F", "Micro silver", 0.02),
    "CRUDE": AssetDefinition("CRUDE", "Crude Oil WTI", AssetClass.COMMODITY, "CL=F", "Micro contracts", 0.03),
    # Indices (futures / CFD — no individual stocks)
    "NIFTY50": AssetDefinition("NIFTY50", "NIFTY 50 Index", AssetClass.INDEX, "^NSEI", "Index futures lot", 0.0),
    "BANKNIFTY": AssetDefinition("BANKNIFTY", "Bank NIFTY Index", AssetClass.INDEX, "^NSEBANK", "Index futures lot", 0.0),
    # Bonds (government bond futures, not corporate bonds/individual issuers)
    "US10Y": AssetDefinition("US10Y", "10-Year US Treasury Note Futures", AssetClass.BOND, "ZN=F", "1 contract = $100,000 face value", 0.0),
    # Futures (non-commodity, non-bond -- an equity INDEX future, not an individual stock)
    "SP500": AssetDefinition("SP500", "Micro E-mini S&P 500 Futures", AssetClass.FUTURES, "MES=F", "Micro contract, $5 x index", 0.0),
    # Equities -- US (price/technical scope only, see module docstring)
    "AAPL": AssetDefinition("AAPL", "Apple Inc.", AssetClass.EQUITY, "AAPL", "1 share", 0.0),
    "MSFT": AssetDefinition("MSFT", "Microsoft Corp.", AssetClass.EQUITY, "MSFT", "1 share", 0.0),
    "NVDA": AssetDefinition("NVDA", "NVIDIA Corp.", AssetClass.EQUITY, "NVDA", "1 share", 0.0),
    "GOOGL": AssetDefinition("GOOGL", "Alphabet Inc. (Class A)", AssetClass.EQUITY, "GOOGL", "1 share", 0.0),
    "AMZN": AssetDefinition("AMZN", "Amazon.com Inc.", AssetClass.EQUITY, "AMZN", "1 share", 0.0),
    "TSLA": AssetDefinition("TSLA", "Tesla Inc.", AssetClass.EQUITY, "TSLA", "1 share", 0.0),
    "META": AssetDefinition("META", "Meta Platforms Inc.", AssetClass.EQUITY, "META", "1 share", 0.0),
    "JPM": AssetDefinition("JPM", "JPMorgan Chase & Co.", AssetClass.EQUITY, "JPM", "1 share", 0.0),
    # Equities -- India (NSE, price/technical scope only)
    "RELIANCE": AssetDefinition("RELIANCE", "Reliance Industries Ltd.", AssetClass.EQUITY, "RELIANCE.NS", "1 share", 0.0),
    "TCS": AssetDefinition("TCS", "Tata Consultancy Services Ltd.", AssetClass.EQUITY, "TCS.NS", "1 share", 0.0),
    "HDFCBANK": AssetDefinition("HDFCBANK", "HDFC Bank Ltd.", AssetClass.EQUITY, "HDFCBANK.NS", "1 share", 0.0),
    "INFY": AssetDefinition("INFY", "Infosys Ltd.", AssetClass.EQUITY, "INFY.NS", "1 share", 0.0),
    "ICICIBANK": AssetDefinition("ICICIBANK", "ICICI Bank Ltd.", AssetClass.EQUITY, "ICICIBANK.NS", "1 share", 0.0),
    "SBIN": AssetDefinition("SBIN", "State Bank of India", AssetClass.EQUITY, "SBIN.NS", "1 share", 0.0),
    "BHARTIARTL": AssetDefinition("BHARTIARTL", "Bharti Airtel Ltd.", AssetClass.EQUITY, "BHARTIARTL.NS", "1 share", 0.0),
    "ITC": AssetDefinition("ITC", "ITC Ltd.", AssetClass.EQUITY, "ITC.NS", "1 share", 0.0),
}

# Explicitly excluded asset classes -- ETFs only (equities/stocks were
# excluded here until 2026-07-19; see module docstring for the current,
# narrower equity scope and why ETFs specifically remain out).
EXCLUDED_ASSET_CLASSES = {"etf", "etfs"}

# Common shorthand a trader would naturally type that doesn't exactly match
# a SUPPORTED_ASSETS key or yahoo_symbol -- e.g. "BTC" for Bitcoin, "OIL"
# for Crude. Checked as a fallback in get_asset/is_asset_supported, never
# in place of the exact/yahoo_symbol match. Deliberately NOT exhaustive --
# only real, unambiguous shorthand for this platform's own 13 assets.
SYMBOL_ALIASES: dict[str, str] = {
    "BTC": "BTCUSD",
    "ETH": "ETHUSD",
    "XAUUSD": "GOLD",
    "XAU": "GOLD",
    "XAGUSD": "SILVER",
    "XAG": "SILVER",
    "OIL": "CRUDE",
    "WTI": "CRUDE",
    "USOIL": "CRUDE",
    "NIFTY": "NIFTY50",
    "SPX": "SP500",
    "SPX500": "SP500",
    "US10YR": "US10Y",
}


def is_asset_supported(symbol: str) -> bool:
    """Check if symbol is in the supported whitelist."""
    return get_asset(symbol) is not None


def get_asset(symbol: str) -> AssetDefinition | None:
    """Resolve asset definition from symbol, Yahoo ticker, or common
    shorthand (see SYMBOL_ALIASES, e.g. "BTC" -> BTCUSD)."""
    key = symbol.upper().replace("-", "").replace("=", "").replace("^", "")
    if key in SUPPORTED_ASSETS:
        return SUPPORTED_ASSETS[key]
    for asset in SUPPORTED_ASSETS.values():
        if asset.yahoo_symbol.upper() == symbol.upper() or asset.symbol == key:
            return asset
    if key in SYMBOL_ALIASES:
        return SUPPORTED_ASSETS.get(SYMBOL_ALIASES[key])
    return None


def list_assets(asset_class: AssetClass | None = None) -> list[AssetDefinition]:
    """List supported assets, optionally filtered by class."""
    assets = list(SUPPORTED_ASSETS.values())
    if asset_class:
        assets = [a for a in assets if a.asset_class == asset_class]
    return assets
