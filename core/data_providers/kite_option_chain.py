"""
Module: kite_option_chain.py
Description: Zerodha Kite Connect v3 REST client + NIFTY/BANKNIFTY option-
    chain assembly -- the real live options-data source e13_derivatives'
    own module docstring flagged as missing for Indian indices ("CME/OCC/
    exchange options feeds are paid... no free options-chain data source
    for... indices (NIFTY50/BANKNIFTY)").

    Added 2026-08-21 after auditing two GitHub reference repos
    (pramakrishn/express-option-chain, anurag-roy/kite-option-chain) for
    this exact purpose. Neither was used as a dependency or copy-paste
    source -- both are stale (2-3+ years untouched) and, more
    importantly, both explicitly DON'T support what this module exists
    for: express-option-chain's own code disables underlying-value
    lookup for any symbol containing "NIFTY", and kite-option-chain never
    touches index instruments at all (hardcoded single-stock-equity
    watchlist only). Neither computes implied volatility or any Greek.
    This module is a from-scratch implementation against Zerodha's
    documented Kite Connect v3 REST API (https://kite.trade/docs/
    connect/v3/), following this codebase's own established
    core.data_providers pattern (a thin httpx REST client, no exchange
    SDK dependency -- same as deribit.py, alpha_vantage.py, fred.py),
    reusing the existing engines.e13_derivatives.black_scholes module
    (price_and_greeks, and the new implied_volatility added alongside
    this file) for the IV/Greeks computation neither reference repo did.

    HONEST LIMITATION -- read before connecting this to anything live:
    this module has NOT been exercised against a real Kite Connect
    account (no live API key/access token was available while writing
    it). The REST endpoint shapes, header format, and instrument-schema
    field names below are Zerodha's own documented, stable Kite Connect
    v3 conventions (token-based Authorization header, CSV instrument
    dump, batched quote() calls, "NFO-OPT" segment, CE/PE instrument_type)
    -- not scraped or guessed from the audited repos -- but a live smoke
    test against a real developers.kite.trade app is a REQUIRED step
    before this reads real money-adjacent data, per this platform's own
    "cannot risk $1" risk posture. All the option-chain ASSEMBLY logic
    below (strike-ladder pairing, underlying-symbol mapping, IV/Greeks)
    is pure Python taking already-fetched data as input and is fully
    unit-tested without live credentials; only the two thin HTTP methods
    (get_instruments, get_quote) are unverified against a live server.

    Rule 5 (no execution engine, non-negotiable): this module is READ-ONLY
    market data. It never calls, wraps, or exposes Kite Connect's order-
    placement/modification/cancellation endpoints.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional, Protocol, runtime_checkable

import httpx
import pandas as pd

from project_titan_x.core.config import get_settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.kite.trade"
KITE_API_VERSION = "3"

# Platform canonical index symbol -> the real Kite/NSE quote instrument
# ("EXCHANGE:TRADINGSYMBOL", including the literal space in "NIFTY 50" --
# a well-documented NSE/Kite quirk, not a typo) and the NFO instrument-
# dump "name" column value its listed options are filed under. This
# mapping is the exact gap both audited reference repos left unfilled --
# express-option-chain explicitly disables underlying lookup for any
# "NIFTY"-containing symbol, kite-option-chain never lists an index at
# all (see module docstring).
_UNDERLYING_QUOTE_SYMBOL = {
    "NIFTY50": "NSE:NIFTY 50",
    "NIFTY": "NSE:NIFTY 50",
    "BANKNIFTY": "NSE:NIFTY BANK",
}
_UNDERLYING_NFO_NAME = {
    "NIFTY50": "NIFTY",
    "NIFTY": "NIFTY",
    "BANKNIFTY": "BANKNIFTY",
}


class KiteConnectError(Exception):
    """Raised when Kite Connect returns an error payload or an HTTP failure."""


class KiteNotConfigured(KiteConnectError):
    """Raised when no api_key/access_token is configured."""


@runtime_checkable
class OptionChainProvider(Protocol):
    """Added 2026-09-13, closing a real docs/UPGRADE_BRIEF.md Phase 10
    requirement confirmed unmet by direct inspection: "Design a clean
    OptionChainProvider interface with adapters. Do not hard-code a
    single broker into the application." -- engines/e13_derivatives/
    engine.py's constructor previously typed its collaborator directly as
    `KiteConnectClient`, which is exactly hard-coding one broker.

    The minimal read-only surface `assemble_option_chain`/
    `get_option_chain_snapshot` actually need -- KiteConnectClient
    already satisfies this structurally with ZERO changes (Protocol is
    structural typing, not inheritance), and a future adapter for a
    different broker (Upstox, Fyers, Angel One, ...) only needs to
    implement these same three members to be a drop-in replacement
    everywhere this Protocol is used as the type hint. No order-placement
    member exists on this interface by design -- see Rule 5."""

    @property
    def is_configured(self) -> bool: ...

    def get_instruments(self, exchange: Optional[str] = None) -> pd.DataFrame: ...

    def get_quote(self, instruments: list[str]) -> dict: ...


class KiteConnectClient:
    """Thin REST client for the read-only subset of Kite Connect v3 this
    platform needs (instrument dump, quotes). No order-placement method
    exists on this class by design -- see Rule 5 in the module docstring.
    Structurally satisfies the OptionChainProvider Protocol above (this
    is the ONLY adapter that exists today, but nothing that consumes this
    class is typed against it directly anymore -- see e13_derivatives'
    own constructor)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        access_token: Optional[str] = None,
        timeout: float = 15.0,
    ) -> None:
        self.api_key = api_key
        self.access_token = access_token
        self._client = httpx.Client(timeout=timeout, base_url=BASE_URL)

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.access_token)

    def close(self) -> None:
        self._client.close()

    def _headers(self) -> dict:
        if not self.is_configured:
            raise KiteNotConfigured("kite_api_key / kite_access_token are not set")
        return {
            "Authorization": f"token {self.api_key}:{self.access_token}",
            "X-Kite-Version": KITE_API_VERSION,
        }

    def get_instruments(self, exchange: Optional[str] = None) -> pd.DataFrame:
        """Full (or per-exchange) instrument master. Kite Connect's real
        /instruments endpoint returns CSV, not JSON -- a genuine, well-
        documented quirk of this specific endpoint (every other endpoint
        on this API is JSON)."""
        path = f"/instruments/{exchange}" if exchange else "/instruments"
        response = self._client.get(path, headers=self._headers())
        response.raise_for_status()
        return pd.read_csv(io.StringIO(response.text))

    def get_quote(self, instruments: list[str]) -> dict:
        """Real-time quote for one or more "EXCHANGE:TRADINGSYMBOL"
        instruments in a single batched call, keyed by that same string
        in the response. Kite documents a per-call instrument-count cap
        on this endpoint; this client does not itself chunk `instruments`
        into multiple calls -- a caller requesting more than that
        documented cap in one call must chunk it themselves (left to the
        caller since the exact cap should be re-confirmed against Kite's
        live docs at integration time, not hardcoded here from memory)."""
        if not instruments:
            return {}
        params = [("i", i) for i in instruments]
        response = self._client.get("/quote", headers=self._headers(), params=params)
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") != "success":
            raise KiteConnectError(f"Kite quote error: {payload}")
        return payload.get("data", {})


_client: Optional[KiteConnectClient] = None


def get_kite_client() -> KiteConnectClient:
    """Process-wide cached Kite Connect client singleton, matching every
    other core.data_providers client's get_*_client() convention."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = KiteConnectClient(api_key=settings.kite_api_key, access_token=settings.kite_access_token)
    return _client


def underlying_quote_symbol(underlying_symbol: str) -> Optional[str]:
    """Real Kite quote-lookup instrument for `underlying_symbol`
    ("NIFTY50" | "BANKNIFTY", case-insensitive), or None if unsupported."""
    return _UNDERLYING_QUOTE_SYMBOL.get(underlying_symbol.upper())


def list_available_expiries(instruments_df: pd.DataFrame, underlying_symbol: str, as_of: Optional[date] = None) -> list[date]:
    """Every distinct, not-yet-expired expiry date listed for
    `underlying_symbol`'s options in a full NFO instrument dump, sorted
    nearest-first. Used to pick a default expiry when a caller doesn't
    specify one -- real, live-discovered expiries only, never a
    fabricated/assumed weekly-Thursday schedule (NSE has moved index
    weekly-expiry days more than once, and monthly-vs-weekly cadence
    differs by underlying, so this deliberately reads it from the actual
    instrument dump rather than hardcoding a rule)."""
    as_of = as_of or datetime.now(timezone.utc).date()
    nfo_name = _UNDERLYING_NFO_NAME.get(underlying_symbol.upper())
    if nfo_name is None:
        return []
    expiry_col = pd.to_datetime(instruments_df["expiry"]).dt.date
    mask = (instruments_df["name"] == nfo_name) & instruments_df["instrument_type"].isin(["CE", "PE"]) & (expiry_col >= as_of)
    return sorted(expiry_col[mask].unique())


def filter_option_instruments(instruments_df: pd.DataFrame, underlying_symbol: str, expiry: date) -> pd.DataFrame:
    """Filters a full NFO instrument dump (from get_instruments("NFO"))
    down to this underlying's CE/PE rows for one specific expiry. Pure
    function over already-fetched data -- fully unit-testable with a
    synthetic DataFrame, no live client needed."""
    nfo_name = _UNDERLYING_NFO_NAME.get(underlying_symbol.upper())
    if nfo_name is None:
        return instruments_df.iloc[0:0]
    expiry_col = pd.to_datetime(instruments_df["expiry"]).dt.date
    mask = (
        (instruments_df["name"] == nfo_name)
        & instruments_df["instrument_type"].isin(["CE", "PE"])
        & (expiry_col == expiry)
    )
    return instruments_df[mask].copy()


@dataclass
class OptionChainRow:
    strike: float
    ce_ltp: Optional[float] = None
    ce_oi: Optional[float] = None
    ce_volume: Optional[float] = None
    ce_iv: Optional[float] = None
    ce_greeks: Optional[dict] = None
    # "moneyness" from the underlying's perspective at this strike --
    # ATM/ITM/OTM means something DIFFERENT for a call vs. a put at the
    # same strike (a call is ITM below spot... no, ABOVE spot is wrong for
    # a put -- see classify_moneyness's own docstring), so this is two
    # separate fields, not one shared value for the row.
    ce_moneyness: Optional[str] = None
    pe_ltp: Optional[float] = None
    pe_oi: Optional[float] = None
    pe_volume: Optional[float] = None
    pe_iv: Optional[float] = None
    pe_greeks: Optional[dict] = None
    pe_moneyness: Optional[str] = None


@dataclass
class OptionChainSnapshot:
    underlying_symbol: str
    expiry: date
    spot_price: float
    timestamp: datetime
    rows: list[OptionChainRow] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    # Chain-level aggregates (added 2026-09-13, Phase 10), computed once
    # here rather than left for every caller to re-derive -- see
    # put_call_ratio/max_pain_strike's own docstrings for what each means
    # and why it can be None (not a fabricated number).
    atm_strike: Optional[float] = None
    pcr_oi: Optional[float] = None
    pcr_volume: Optional[float] = None
    max_pain: Optional[float] = None


def assemble_option_chain(
    option_instruments: pd.DataFrame,
    quotes: dict,
    underlying_symbol: str,
    expiry: date,
    spot_price: float,
    risk_free_rate: float,
    as_of: Optional[datetime] = None,
) -> OptionChainSnapshot:
    """Builds a strike-sorted CE/PE option chain with real IV (inverted
    from each leg's own LTP via black_scholes.implied_volatility) and
    Greeks (from that same IV via black_scholes.price_and_greeks) --
    coverage neither audited reference repo had at all (see module
    docstring). `quotes` is the dict returned by
    KiteConnectClient.get_quote(), keyed by "NFO:TRADINGSYMBOL". A leg
    with no quote entry, a non-positive LTP, or an IV that couldn't be
    inverted (see implied_volatility's own docstring for why that
    happens) contributes None fields rather than a fabricated number --
    it still appears in the chain at its strike, just without pricing."""
    # Deliberately a local, not module-level, import: engines.e13_derivatives
    # is a HIGHER layer than core.data_providers (engines depend on
    # providers, not the reverse) -- a module-level import here created a
    # real circular import the moment engine.py itself imports this
    # module (core.data_providers.__init__ -> kite_option_chain ->
    # engines.e13_derivatives.__init__ -> engine.py -> back to
    # kite_option_chain, still mid-initialization). Deferring the import
    # to call time breaks the cycle without restructuring either module.
    from project_titan_x.engines.e13_derivatives.black_scholes import implied_volatility, price_and_greeks

    as_of = as_of or datetime.now(timezone.utc)
    time_to_expiry_years = max((datetime.combine(expiry, datetime.min.time(), tzinfo=timezone.utc) - as_of).total_seconds(), 0.0) / (365.0 * 86400.0)

    rows_by_strike: dict[float, OptionChainRow] = {}
    notes: list[str] = []
    if time_to_expiry_years <= 0:
        notes.append(f"Expiry {expiry} has already passed as of {as_of.isoformat()} -- no IV/Greeks computed")

    for _, inst in option_instruments.iterrows():
        strike = float(inst["strike"])
        quote_key = f"NFO:{inst['tradingsymbol']}"
        quote = quotes.get(quote_key)
        row = rows_by_strike.setdefault(strike, OptionChainRow(strike=strike))

        ltp = quote.get("last_price") if quote else None
        oi = quote.get("oi") if quote else None
        volume = quote.get("volume") if quote else None
        iv = None
        greeks = None
        if ltp and ltp > 0 and time_to_expiry_years > 0:
            option_type = "call" if inst["instrument_type"] == "CE" else "put"
            iv = implied_volatility(
                market_price=float(ltp), spot=spot_price, strike=strike,
                time_to_expiry_years=time_to_expiry_years, option_type=option_type,
                risk_free_rate=risk_free_rate,
            )
            if iv is not None:
                theo = price_and_greeks(
                    spot=spot_price, strike=strike, time_to_expiry_years=time_to_expiry_years,
                    volatility=iv, option_type=option_type, risk_free_rate=risk_free_rate,
                )
                greeks = {"delta": theo.delta, "gamma": theo.gamma, "theta": theo.theta, "vega": theo.vega, "rho": theo.rho}

        if inst["instrument_type"] == "CE":
            row.ce_ltp, row.ce_oi, row.ce_volume, row.ce_iv, row.ce_greeks = ltp, oi, volume, iv, greeks
        else:
            row.pe_ltp, row.pe_oi, row.pe_volume, row.pe_iv, row.pe_greeks = ltp, oi, volume, iv, greeks

    sorted_rows = sorted(rows_by_strike.values(), key=lambda r: r.strike)
    atm_strike = find_atm_strike(sorted_rows, spot_price)
    for row in sorted_rows:
        row.ce_moneyness = classify_moneyness(row.strike, spot_price, atm_strike, "CE")
        row.pe_moneyness = classify_moneyness(row.strike, spot_price, atm_strike, "PE")

    return OptionChainSnapshot(
        underlying_symbol=underlying_symbol.upper(),
        expiry=expiry,
        spot_price=spot_price,
        timestamp=as_of,
        rows=sorted_rows,
        notes=notes,
        atm_strike=atm_strike,
        pcr_oi=put_call_ratio(sorted_rows, by="oi"),
        pcr_volume=put_call_ratio(sorted_rows, by="volume"),
        max_pain=max_pain_strike(sorted_rows),
    )


def find_atm_strike(rows: list[OptionChainRow], spot_price: float) -> Optional[float]:
    """The single listed strike closest to spot -- the standard "at the
    money" convention (a spot price essentially never lands exactly on a
    listed strike). None for an empty chain."""
    if not rows:
        return None
    return min((r.strike for r in rows), key=lambda k: abs(k - spot_price))


def classify_moneyness(strike: float, spot_price: float, atm_strike: Optional[float], option_type: str) -> str:
    """ITM/ATM/OTM for ONE leg at ONE strike -- a call and a put at the
    SAME strike classify oppositely (a call is ITM when spot is ABOVE the
    strike -- you'd only exercise it to buy below market; a put is ITM
    when spot is BELOW the strike, the mirror image), so this takes
    option_type ("CE"/"PE") rather than returning one shared value per
    row. ATM is defined as the strike returned by find_atm_strike, shared
    by both legs at that strike by market convention even though neither
    is exactly at-the-money in the literal sense."""
    if atm_strike is not None and strike == atm_strike:
        return "ATM"
    if option_type == "CE":
        return "ITM" if spot_price > strike else "OTM"
    return "ITM" if spot_price < strike else "OTM"


def put_call_ratio(rows: list[OptionChainRow], by: str = "oi") -> Optional[float]:
    """Put/Call Ratio across the whole chain -- total put OI (or volume,
    `by="volume"`) divided by total call OI (or volume). Conventionally
    read as > 1 leaning bearish (more put interest), < 1 leaning bullish
    -- a real, standard descriptive positioning metric; this function
    makes no directional claim of its own beyond the ratio itself. None
    (not a fabricated 0.0 or inf) when total call OI/volume is zero or no
    row has the requested field populated at all."""
    key_ce, key_pe = ("ce_oi", "pe_oi") if by == "oi" else ("ce_volume", "pe_volume")
    total_ce = sum(getattr(r, key_ce) or 0 for r in rows)
    total_pe = sum(getattr(r, key_pe) or 0 for r in rows)
    if total_ce <= 0:
        return None
    return total_pe / total_ce


def max_pain_strike(rows: list[OptionChainRow]) -> Optional[float]:
    """The strike at which option WRITERS collectively owe the least
    intrinsic-value payout at expiry -- a real, standard options-market
    concept (not this platform's own invention), computed directly from
    definition: for each candidate settlement price (every listed
    strike), sum every strike's intrinsic value times its OI (call
    intrinsic = max(0, settle-strike)*ce_oi, put intrinsic =
    max(0, strike-settle)*pe_oi across ALL strikes, not just the
    candidate's own), then pick the settlement price minimizing that
    total. Often cited as a magnet price gravitates toward near expiry --
    that folk claim is NOT asserted here, only the computation. None when
    the chain is empty or carries no OI data on any leg at all."""
    strikes = [r.strike for r in rows]
    if not strikes or not any((r.ce_oi or r.pe_oi) for r in rows):
        return None
    best_strike: Optional[float] = None
    best_payout: Optional[float] = None
    for settle in strikes:
        payout = 0.0
        for r in rows:
            if r.ce_oi:
                payout += max(0.0, settle - r.strike) * r.ce_oi
            if r.pe_oi:
                payout += max(0.0, r.strike - settle) * r.pe_oi
        if best_payout is None or payout < best_payout:
            best_payout, best_strike = payout, settle
    return best_strike


def get_option_chain_snapshot(
    client: KiteConnectClient,
    underlying_symbol: str,
    expiry: date,
    risk_free_rate: Optional[float] = None,
) -> OptionChainSnapshot:
    """Live orchestration: fetch the NFO instrument dump, the underlying
    index spot quote, the option legs' quotes, and assemble the chain.
    Raises KiteNotConfigured (via the client) if no credentials are set --
    callers (e13_derivatives.engine) are expected to catch that and
    report an honest capability gap, same convention as every other
    optional-data-source path in this engine."""
    if risk_free_rate is None:
        risk_free_rate = get_settings().kite_risk_free_rate

    quote_symbol = underlying_quote_symbol(underlying_symbol)
    if quote_symbol is None:
        raise KiteConnectError(f"No Kite quote-symbol mapping for {underlying_symbol!r}")

    instruments = client.get_instruments("NFO")
    option_instruments = filter_option_instruments(instruments, underlying_symbol, expiry)
    if option_instruments.empty:
        raise KiteConnectError(f"No listed {underlying_symbol} options found for expiry {expiry}")

    underlying_quote = client.get_quote([quote_symbol])
    spot_entry = underlying_quote.get(quote_symbol)
    if not spot_entry or not spot_entry.get("last_price"):
        raise KiteConnectError(f"Kite returned no live quote for underlying {quote_symbol!r}")
    spot_price = float(spot_entry["last_price"])

    option_symbols = [f"NFO:{ts}" for ts in option_instruments["tradingsymbol"]]
    quotes = client.get_quote(option_symbols)

    return assemble_option_chain(
        option_instruments=option_instruments, quotes=quotes, underlying_symbol=underlying_symbol,
        expiry=expiry, spot_price=spot_price, risk_free_rate=risk_free_rate,
    )
