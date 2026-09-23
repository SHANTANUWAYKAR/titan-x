"""
Module: engine.py
Description: Engine 13 -- Derivatives Intelligence. Master prompt scope:
    "futures, options, swaps, structured products. Delta, Gamma, Theta,
    Vega, Rho. Volatility surface, implied vol, skew, term structure."

    Honest scope: Deribit's public API (core/data_providers/deribit.py) is
    the only genuinely free, no-auth options data source reachable from
    this platform's asset universe, and it only lists options on BTC and
    ETH. There is no free options-chain data source for this platform's
    forex pairs, commodities (GOLD/SILVER/CRUDE), or indices (NIFTY50/
    BANKNIFTY) -- CME/OCC/exchange options feeds are paid. For every
    non-crypto asset, analyze() returns an honest capability gap (success,
    no data, a clear message) rather than fabricating a volatility surface
    -- same principle as e05_economic_calendar not hardcoding FOMC dates
    it can't source from a real published rule.

    Skew/term-structure thresholds are static, documented market
    conventions (e.g. "a 10%-OTM put trading at meaningfully higher IV
    than a 10%-OTM call is put skew"), not backtested against options
    history -- Deribit's public API only serves the CURRENT live chain,
    with no historical archive, so there is no real historical IMPLIED-vol
    data to calibrate those specific thresholds against.

    What IS calibrated (scripts/training/train_e13_derivatives.py): this
    platform has deep real historical PRICE data for BTC-USD (2014-2026)
    and ETH-USD (2017-2026, both in data/processed/), enough to build a
    real historical distribution of REALIZED volatility -- the other half
    of the standard "volatility risk premium" (IV vs RV) comparison.
    analyze() computes today's 30-day realized vol from real recent price
    history and classifies it against that real historical percentile
    distribution (low/below_average/average/above_average/high), and
    separately reports today's ATM IV minus today's RV (the classic VRP
    spread) as a plain, un-classified number -- honestly, since there's no
    historical IV series to say whether the SPREAD itself is rich or cheap.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-07-16
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import yfinance as yf
from project_titan_x.core.data_providers.yahoo import ticker_history, ticker_info

from project_titan_x.core.config import get_asset, get_settings
from project_titan_x.core.data_providers import DeribitClient, DeribitError, get_deribit_client
from project_titan_x.core.data_providers.kite_option_chain import (
    KiteConnectError,
    KiteNotConfigured,
    OptionChainProvider,
    assemble_option_chain,
    filter_option_instruments,
    get_kite_client,
    list_available_expiries,
    underlying_quote_symbol,
)
from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus
from project_titan_x.engines.e01_knowledge.engine import KnowledgeEngine
from project_titan_x.engines.e13_derivatives.black_scholes import price_and_greeks

logger = logging.getLogger(__name__)

# Platform asset symbol -> Deribit currency code. Deribit lists options for
# only these two cryptos.
_SYMBOL_TO_DERIBIT_CURRENCY = {"BTCUSD": "BTC", "ETHUSD": "ETH"}
_CURRENCY_TO_YAHOO_TICKER = {"BTC": "BTC-USD", "ETH": "ETH-USD"}
# Platform asset symbols with real Indian index option-chain support via
# Kite Connect (see analyze_index_option_chain below) -- added 2026-08-21.
_KITE_SUPPORTED_INDEX_SYMBOLS = {"NIFTY50", "BANKNIFTY"}

OTM_SKEW_MONEYNESS = 0.10  # the "10%-OTM put vs 10%-OTM call" skew convention
SKEW_NOTABLE_THRESHOLD = 5.0  # vol points of IV difference before calling a skew "notable"

REALIZED_VOL_WINDOW_DAYS = 30
ANNUALIZATION_FACTOR = 365  # crypto trades 24/7/365, matching train_e13_derivatives.py
_REALIZED_VOL_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "models" / "e13_derivatives" / "realized_vol_baseline.json"
)


@dataclass
class ExpiryIVPoint:
    """ATM implied vol at one expiry -- one point on the term structure."""

    expiry: datetime
    days_to_expiry: int
    atm_strike: float
    atm_iv: float
    n_instruments: int


@dataclass
class DerivativesSnapshot:
    """Options-market read for one crypto currency (BTC or ETH)."""

    timestamp: datetime
    currency: str  # "BTC" | "ETH"
    spot_price: float
    put_call_ratio_oi: float
    put_call_ratio_volume: float
    nearest_expiry: Optional[datetime]
    nearest_expiry_atm_iv: Optional[float]
    term_structure: list[ExpiryIVPoint] = field(default_factory=list)
    skew_proxy: Optional[float] = None  # 10%-OTM put IV minus 10%-OTM call IV, nearest expiry
    skew_label: str = "unavailable"  # "put_skew" | "call_skew" | "flat" | "unavailable"
    atm_greeks: Optional[dict] = None  # {"call": {...}, "put": {...}} real greeks, nearest-expiry ATM
    # Added 2026-08-02: max_pain_strike (see _compute_max_pain) and a
    # cross-check comparing Deribit's own published ATM greeks against
    # this engine's own Black-Scholes calculation using the SAME spot/
    # strike/IV/time inputs (see _cross_check_greeks) -- previously this
    # engine could only ever REPORT whatever greeks Deribit published,
    # with no independent way to sanity-check them against the standard
    # closed-form model.
    max_pain_strike: Optional[float] = None
    greeks_cross_check: Optional[dict] = None
    realized_vol_30d: Optional[float] = None  # annualized, from real recent price history
    realized_vol_regime: str = "uncalibrated"  # "low"|"below_average"|"average"|"above_average"|"high"|"uncalibrated"
    iv_minus_rv: Optional[float] = None  # nearest_expiry_atm_iv - realized_vol_30d (plain VRP spread, not classified)
    notes: list[str] = field(default_factory=list)
    knowledge_context: Optional[dict] = None


def _parse_instrument(name: str) -> Optional[tuple[datetime, float, str]]:
    """Deribit option instrument names: "{CCY}-{DDMMMYY}-{STRIKE}-{C|P}",
    e.g. "BTC-16JUL26-56000-C". Returns (expiry, strike, "C"|"P") or None
    if the name doesn't match this shape (defensive -- Deribit could list
    other instrument kinds under the same currency in the future).

    Real bug caught 2026-08-02 while building the Black-Scholes greeks
    cross-check below: Deribit options settle at 08:00 UTC on the expiry
    date, not midnight -- a well-documented Deribit convention. Parsing
    the bare date alone (as this did before) defaults to midnight, which
    for a normal multi-week option is a negligible relative error, but
    for a same-day (0DTE) option is not: caught directly on a live
    BTC-2AUG26 call, where "now" was 2026-08-01 19:36 UTC -- the
    midnight-based calculation gave 4.4 hours to expiry, the correct
    08:00-UTC-based calculation gives 12.4 hours, a ~3x difference. That
    error was large enough to visibly distort the new Black-Scholes
    cross-check's delta for a near-expiry option (theoretical delta 0.73
    vs Deribit's own reported 0.48 on what should have been a near-ATM,
    near-0.5-delta option) before this fix."""
    parts = name.split("-")
    if len(parts) != 4:
        return None
    _, expiry_str, strike_str, option_type = parts
    try:
        expiry_date = datetime.strptime(expiry_str, "%d%b%y").replace(tzinfo=timezone.utc)
        expiry = expiry_date.replace(hour=8)
        strike = float(strike_str)
    except ValueError:
        return None
    if option_type not in ("C", "P"):
        return None
    return expiry, strike, option_type


class DerivativesIntelligenceEngine(BaseEngine):
    """
    Derivatives Intelligence Engine (#13) -- put/call ratio, implied
    volatility term structure, skew, and ATM greeks for BTC/ETH options via
    Deribit's free public API. Purely descriptive/interpretive -- reads a
    real live options chain, never places or recommends a trade.
    """

    engine_id = "e13_derivatives"
    engine_name = "Derivatives Intelligence Engine"
    version = "1.0.0"

    def __init__(
        self,
        knowledge_engine: Optional[KnowledgeEngine] = None,
        deribit_client: Optional[DeribitClient] = None,
        kite_client: Optional[OptionChainProvider] = None,
    ) -> None:
        super().__init__()
        self._knowledge_engine = knowledge_engine
        self._deribit = deribit_client if deribit_client is not None else get_deribit_client()
        # Added 2026-08-21: real NIFTY50/BANKNIFTY option-chain read via
        # Kite Connect (see analyze_index_option_chain below) -- kept as a
        # separate client/method from the Deribit crypto path above
        # rather than folded into analyze()/DerivativesSnapshot, since an
        # index option chain (per-strike IV/Greeks table) is a genuinely
        # different data shape than a crypto put/call-ratio+term-
        # structure summary, not a variant of the same one.
        #
        # Typed against OptionChainProvider (added 2026-09-13), NOT the
        # concrete KiteConnectClient -- docs/UPGRADE_BRIEF.md Phase 10
        # explicitly requires "do not hard-code a single broker into the
        # application." get_kite_client() (the default) still returns a
        # real KiteConnectClient; a future adapter for a different broker
        # is a drop-in here as long as it satisfies the same Protocol.
        self._kite: OptionChainProvider = kite_client if kite_client is not None else get_kite_client()
        self._realized_vol_baseline = self._load_realized_vol_baseline()

    def initialize(self) -> EngineResult:
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Derivatives Intelligence Engine initialized")

    @staticmethod
    def _load_realized_vol_baseline() -> dict[str, dict]:
        """Per-currency historical realized-vol percentiles from
        scripts/training/train_e13_derivatives.py. Empty (not fabricated)
        if the training script hasn't been run yet -- see Rule 4."""
        if not _REALIZED_VOL_BASELINE_PATH.exists():
            return {}
        try:
            data = json.loads(_REALIZED_VOL_BASELINE_PATH.read_text())
            return {
                currency: {int(k): v for k, v in entry["realized_vol_percentiles"].items()}
                for currency, entry in data.get("currencies", {}).items()
            }
        except Exception as e:
            logger.warning("Failed to load E13 realized-vol baseline: %s", e)
            return {}

    def health_check(self) -> EngineResult:
        try:
            book = self._deribit.get_book_summary_by_currency("BTC", "option")
            if not book:
                raise ValueError("Deribit returned no BTC option instruments")
            return EngineResult(success=True, message="Healthy")
        except Exception as e:
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def analyze(self, symbol: str = "BTCUSD") -> EngineResult:
        """Options-market read for `symbol`. Only BTCUSD/ETHUSD have real
        data behind them (see module docstring for why); every other
        supported asset returns an honest gap, not fabricated data."""
        asset = get_asset(symbol)
        symbol_key = asset.symbol if asset else symbol.upper()
        currency = _SYMBOL_TO_DERIBIT_CURRENCY.get(symbol_key)

        if currency is None:
            return EngineResult(
                success=True,
                data=None,
                message=(
                    f"No free options data source available for {symbol_key} -- Deribit "
                    "(this engine's only data source) lists options on BTC/ETH only. "
                    "Forex/commodity/index options require a paid exchange feed."
                ),
            )

        try:
            self._set_status(EngineStatus.RUNNING)
            book = self._deribit.get_book_summary_by_currency(currency, "option")
            if not book:
                return EngineResult(success=False, message=f"Deribit returned no live {currency} option instruments")

            spot_price = float(book[0]["underlying_price"])
            snapshot = self._build_snapshot(currency, spot_price, book)
            self._set_status(EngineStatus.IDLE)
            return EngineResult(
                success=True,
                data=snapshot,
                message=f"{currency} derivatives snapshot: P/C(OI)={snapshot.put_call_ratio_oi:.2f}, skew={snapshot.skew_label}",
                metadata={"currency": currency, "skew_label": snapshot.skew_label},
            )
        except DeribitError as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("Deribit request failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("Derivatives analysis failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def analyze_index_option_chain(self, symbol: str, expiry: Optional[str] = None) -> EngineResult:
        """Real NIFTY50/BANKNIFTY option chain (per-strike CE/PE LTP, OI,
        and Black-Scholes IV/Greeks inverted from that real LTP) via Kite
        Connect -- added 2026-08-21, closing the gap this engine's own
        module docstring previously flagged ("no free options-chain data
        source for... indices"). Separate from analyze() by design (see
        __init__ comment) rather than folded into DerivativesSnapshot.

        `expiry`: "YYYY-MM-DD", or None to use the nearest real, live-
        discovered expiry (see list_available_expiries -- never a
        fabricated/assumed weekly-Thursday schedule).

        Honest gaps returned as success=True/data=None (never fabricated):
        unsupported symbol, or Kite Connect not configured (no
        kite_api_key/kite_access_token in settings) -- same convention
        analyze() already uses for forex/commodity assets above."""
        asset = get_asset(symbol)
        symbol_key = asset.symbol if asset else symbol.upper()

        if symbol_key not in _KITE_SUPPORTED_INDEX_SYMBOLS:
            return EngineResult(
                success=True, data=None,
                message=f"No Indian index option-chain support for {symbol_key} -- only {sorted(_KITE_SUPPORTED_INDEX_SYMBOLS)} are covered.",
            )
        if not self._kite.is_configured:
            return EngineResult(
                success=True, data=None,
                message=(
                    "Kite Connect is not configured (kite_api_key/kite_access_token unset) -- "
                    "real NIFTY/BANKNIFTY option-chain data requires a paid Zerodha Kite Connect "
                    "developer subscription (developers.kite.trade) and a daily-refreshed access token."
                ),
            )

        try:
            self._set_status(EngineStatus.RUNNING)
            instruments = self._kite.get_instruments("NFO")

            if expiry is not None:
                expiry_date = datetime.strptime(expiry, "%Y-%m-%d").date()
            else:
                available = list_available_expiries(instruments, symbol_key)
                if not available:
                    return EngineResult(success=False, message=f"Kite lists no live {symbol_key} option expiries right now")
                expiry_date = available[0]

            option_instruments = filter_option_instruments(instruments, symbol_key, expiry_date)
            if option_instruments.empty:
                return EngineResult(success=False, message=f"No listed {symbol_key} options found for expiry {expiry_date}")

            quote_symbol = underlying_quote_symbol(symbol_key)
            underlying_quote = self._kite.get_quote([quote_symbol])
            spot_entry = underlying_quote.get(quote_symbol)
            if not spot_entry or not spot_entry.get("last_price"):
                return EngineResult(success=False, message=f"Kite returned no live quote for underlying {quote_symbol!r}")
            spot_price = float(spot_entry["last_price"])

            option_symbols = [f"NFO:{ts}" for ts in option_instruments["tradingsymbol"]]
            quotes = self._kite.get_quote(option_symbols)

            snapshot = assemble_option_chain(
                option_instruments=option_instruments, quotes=quotes, underlying_symbol=symbol_key,
                expiry=expiry_date, spot_price=spot_price, risk_free_rate=self._kite_risk_free_rate(),
            )
            self._set_status(EngineStatus.IDLE)
            return EngineResult(
                success=True, data=snapshot,
                message=f"{symbol_key} option chain for {expiry_date}: {len(snapshot.rows)} strikes, spot={spot_price:.2f}",
                metadata={"underlying": symbol_key, "expiry": expiry_date.isoformat(), "n_strikes": len(snapshot.rows)},
            )
        except KiteNotConfigured as e:
            self._set_status(EngineStatus.IDLE)
            return EngineResult(success=True, data=None, message=str(e))
        except KiteConnectError as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("Kite Connect request failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("Index option chain analysis failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    @staticmethod
    def _kite_risk_free_rate() -> float:
        return get_settings().kite_risk_free_rate

    def _build_snapshot(self, currency: str, spot_price: float, book: list[dict]) -> DerivativesSnapshot:
        notes: list[str] = []
        parsed = []
        for entry in book:
            result = _parse_instrument(entry["instrument_name"])
            if result is None:
                continue
            expiry, strike, option_type = result
            parsed.append({
                "expiry": expiry, "strike": strike, "type": option_type,
                "mark_iv": entry.get("mark_iv"), "open_interest": entry.get("open_interest") or 0.0,
                "volume": entry.get("volume") or 0.0, "instrument_name": entry["instrument_name"],
            })

        total_call_oi = sum(p["open_interest"] for p in parsed if p["type"] == "C")
        total_put_oi = sum(p["open_interest"] for p in parsed if p["type"] == "P")
        total_call_vol = sum(p["volume"] for p in parsed if p["type"] == "C")
        total_put_vol = sum(p["volume"] for p in parsed if p["type"] == "P")
        pc_ratio_oi = (total_put_oi / total_call_oi) if total_call_oi else float("nan")
        pc_ratio_vol = (total_put_vol / total_call_vol) if total_call_vol else float("nan")

        expiries = sorted({p["expiry"] for p in parsed})
        now = datetime.now(timezone.utc)
        term_structure = []
        for expiry in expiries:
            at_expiry = [p for p in parsed if p["expiry"] == expiry and p["mark_iv"]]
            if not at_expiry:
                continue
            atm = min(at_expiry, key=lambda p: abs(p["strike"] - spot_price))
            same_strike = [p for p in at_expiry if p["strike"] == atm["strike"]]
            atm_iv = sum(p["mark_iv"] for p in same_strike) / len(same_strike)
            term_structure.append(ExpiryIVPoint(
                expiry=expiry,
                days_to_expiry=max((expiry - now).days, 0),
                atm_strike=atm["strike"],
                atm_iv=round(atm_iv, 2),
                n_instruments=len(at_expiry),
            ))

        nearest_expiry = term_structure[0].expiry if term_structure else None
        nearest_atm_iv = term_structure[0].atm_iv if term_structure else None

        skew_proxy, skew_label = self._compute_skew(parsed, spot_price, nearest_expiry)
        atm_greeks = self._fetch_atm_greeks(parsed, spot_price, nearest_expiry)
        max_pain_strike = self._compute_max_pain(parsed, nearest_expiry)
        greeks_cross_check = self._cross_check_greeks(parsed, nearest_expiry, atm_greeks)
        realized_vol_30d = self._compute_realized_vol(currency)
        vol_regime = self._classify_vol_regime(currency, realized_vol_30d)
        iv_minus_rv = (
            round(nearest_atm_iv - realized_vol_30d, 2)
            if nearest_atm_iv is not None and realized_vol_30d is not None
            else None
        )

        if not term_structure:
            notes.append("No usable mark_iv data returned -- term structure unavailable")
        if skew_label == "unavailable":
            notes.append("No 10%-OTM put/call pair found near the nearest expiry -- skew unavailable")
        if realized_vol_30d is None:
            notes.append("Could not compute current realized volatility from recent price history")
        elif vol_regime == "uncalibrated":
            notes.append("No realized-vol baseline found -- run scripts/training/train_e13_derivatives.py")

        return DerivativesSnapshot(
            timestamp=now,
            currency=currency,
            spot_price=spot_price,
            put_call_ratio_oi=round(pc_ratio_oi, 3) if pc_ratio_oi == pc_ratio_oi else float("nan"),
            put_call_ratio_volume=round(pc_ratio_vol, 3) if pc_ratio_vol == pc_ratio_vol else float("nan"),
            nearest_expiry=nearest_expiry,
            nearest_expiry_atm_iv=nearest_atm_iv,
            term_structure=term_structure,
            skew_proxy=skew_proxy,
            skew_label=skew_label,
            atm_greeks=atm_greeks,
            max_pain_strike=max_pain_strike,
            greeks_cross_check=greeks_cross_check,
            realized_vol_30d=realized_vol_30d,
            realized_vol_regime=vol_regime,
            iv_minus_rv=iv_minus_rv,
            notes=notes,
            knowledge_context=self._build_knowledge_context(currency, skew_label, pc_ratio_oi, vol_regime),
        )

    @staticmethod
    def _compute_max_pain(parsed: list[dict], nearest_expiry: Optional[datetime]) -> Optional[float]:
        """Max Pain: the strike at which option WRITERS (sellers), in
        aggregate, have the smallest total payout obligation at expiry --
        equivalently, the strike that minimizes total intrinsic value paid
        out to option HOLDERS across every listed call and put. A
        well-known options-market concept (often cited as a "magnet"
        price into expiration, due to how market makers hedge their
        aggregate short-options book) -- computed here directly from the
        SAME open-interest-per-strike data this engine already fetches
        for the put/call ratio above, previously never used this way.
        Uses only strikes that actually have listed OI, not an arbitrary
        price grid."""
        if nearest_expiry is None:
            return None
        at_expiry = [p for p in parsed if p["expiry"] == nearest_expiry]
        strikes = sorted({p["strike"] for p in at_expiry})
        if not strikes:
            return None

        call_oi_by_strike = {p["strike"]: p["open_interest"] for p in at_expiry if p["type"] == "C"}
        put_oi_by_strike = {p["strike"]: p["open_interest"] for p in at_expiry if p["type"] == "P"}

        best_strike, best_total_payout = None, None
        for settle in strikes:
            payout = 0.0
            for k, oi in call_oi_by_strike.items():
                if settle > k:
                    payout += (settle - k) * oi
            for k, oi in put_oi_by_strike.items():
                if settle < k:
                    payout += (k - settle) * oi
            if best_total_payout is None or payout < best_total_payout:
                best_total_payout, best_strike = payout, settle
        return best_strike

    def _cross_check_greeks(
        self, parsed: list[dict], nearest_expiry: Optional[datetime], atm_greeks: Optional[dict]
    ) -> Optional[dict]:
        """Compares Deribit's own published ATM delta/gamma/vega against
        this engine's independent Black-Scholes calculation, using the
        SAME spot/strike/mark_iv/time-to-expiry Deribit itself reports --
        added 2026-08-02, previously this engine had no way to sanity-
        check the greeks it was reporting against the standard closed-
        form model every options textbook in the corpus builds on. Theta/
        rho are intentionally excluded from the comparison: Deribit prices
        with its own funding-rate/basis conventions for perpetual-adjacent
        products that don't map cleanly onto vanilla Black-Scholes theta/
        rho, so only the three Greeks with a clean, convention-independent
        definition (delta, gamma, vega) are cross-checked."""
        if atm_greeks is None or nearest_expiry is None:
            return None
        now = datetime.now(timezone.utc)
        time_to_expiry_years = max((nearest_expiry - now).total_seconds(), 0.0) / (365.0 * 86400.0)
        if time_to_expiry_years <= 0:
            return None

        at_expiry = [p for p in parsed if p["expiry"] == nearest_expiry]
        comparison: dict = {}
        for option_type, key in (("call", "C"), ("put", "P")):
            real = atm_greeks.get(option_type)
            if real is None or real.get("underlying_price") is None or real.get("mark_iv") is None:
                continue
            candidates = [p for p in at_expiry if p["type"] == key and p["instrument_name"] == real.get("instrument")]
            if not candidates:
                continue
            leg = candidates[0]
            try:
                # Uses THIS leg's own underlying_price/mark_iv (from its
                # own ticker() response, see _fetch_atm_greeks), not the
                # currency-wide spot_price/parsed-book mark_iv passed into
                # this method -- see this method's docstring for the real
                # bug this fixes.
                theoretical = price_and_greeks(
                    spot=real["underlying_price"], strike=leg["strike"], time_to_expiry_years=time_to_expiry_years,
                    volatility=real["mark_iv"] / 100.0, option_type=option_type,
                )
            except ValueError as e:
                logger.warning("Black-Scholes cross-check failed for %s: %s", real.get("instrument"), e)
                continue
            comparison[option_type] = {
                "instrument": real.get("instrument"),
                "deribit_delta": real.get("delta"), "theoretical_delta": theoretical.delta,
                "deribit_gamma": real.get("gamma"), "theoretical_gamma": theoretical.gamma,
                "deribit_vega": real.get("vega"), "theoretical_vega": theoretical.vega,
            }
        return comparison or None

    def _compute_realized_vol(self, currency: str) -> Optional[float]:
        """Today's REALIZED_VOL_WINDOW_DAYS-day annualized realized
        volatility from real recent price history (yfinance), same
        method/units as train_e13_derivatives.py so it's directly
        comparable to the persisted historical baseline."""
        ticker = _CURRENCY_TO_YAHOO_TICKER.get(currency)
        if ticker is None:
            return None
        try:
            hist = ticker_history(ticker, "60d", interval="1d", context="e13")
            if len(hist) < REALIZED_VOL_WINDOW_DAYS + 1:
                return None
            closes = hist["Close"].tail(REALIZED_VOL_WINDOW_DAYS + 1)
            log_returns = np.log(closes / closes.shift(1)).dropna()
            realized_vol = float(log_returns.std() * np.sqrt(ANNUALIZATION_FACTOR) * 100)
            return round(realized_vol, 2)
        except Exception as e:
            logger.warning("Realized vol computation failed for %s: %s", currency, e)
            return None

    def _classify_vol_regime(self, currency: str, realized_vol_30d: Optional[float]) -> str:
        """Classify today's realized vol against the real historical
        percentile distribution (train_e13_derivatives.py). Never
        fabricated: reports "uncalibrated" rather than guessing if no
        baseline exists for this currency."""
        if realized_vol_30d is None:
            return "uncalibrated"
        percentiles = self._realized_vol_baseline.get(currency)
        if not percentiles:
            return "uncalibrated"
        if realized_vol_30d < percentiles[10]:
            return "low"
        if realized_vol_30d < percentiles[25]:
            return "below_average"
        if realized_vol_30d <= percentiles[75]:
            return "average"
        if realized_vol_30d <= percentiles[90]:
            return "above_average"
        return "high"

    @staticmethod
    def _compute_skew(parsed: list[dict], spot_price: float, nearest_expiry: Optional[datetime]) -> tuple[Optional[float], str]:
        """10%-OTM put IV minus 10%-OTM call IV at the nearest expiry -- a
        standard risk-reversal skew convention. Positive => puts bid up
        relative to calls (downside-hedging demand, "put skew" -- the
        normal state for most risk assets); negative => "call skew"."""
        if nearest_expiry is None:
            return None, "unavailable"
        at_expiry = [p for p in parsed if p["expiry"] == nearest_expiry and p["mark_iv"]]
        puts = [p for p in at_expiry if p["type"] == "P" and p["strike"] < spot_price]
        calls = [p for p in at_expiry if p["type"] == "C" and p["strike"] > spot_price]
        if not puts or not calls:
            return None, "unavailable"

        target_put_strike = spot_price * (1 - OTM_SKEW_MONEYNESS)
        target_call_strike = spot_price * (1 + OTM_SKEW_MONEYNESS)
        nearest_put = min(puts, key=lambda p: abs(p["strike"] - target_put_strike))
        nearest_call = min(calls, key=lambda p: abs(p["strike"] - target_call_strike))

        skew = round(nearest_put["mark_iv"] - nearest_call["mark_iv"], 2)
        if skew > SKEW_NOTABLE_THRESHOLD:
            label = "put_skew"
        elif skew < -SKEW_NOTABLE_THRESHOLD:
            label = "call_skew"
        else:
            label = "flat"
        return skew, label

    def _fetch_atm_greeks(self, parsed: list[dict], spot_price: float, nearest_expiry: Optional[datetime]) -> Optional[dict]:
        """Real delta/gamma/theta/vega/rho for the nearest-expiry ATM call
        and put, via 2 extra Deribit ticker() calls (not derived/estimated
        -- Deribit computes and publishes these directly)."""
        if nearest_expiry is None:
            return None
        at_expiry = [p for p in parsed if p["expiry"] == nearest_expiry]
        calls = [p for p in at_expiry if p["type"] == "C"]
        puts = [p for p in at_expiry if p["type"] == "P"]
        if not calls or not puts:
            return None
        atm_call = min(calls, key=lambda p: abs(p["strike"] - spot_price))
        atm_put = min(puts, key=lambda p: abs(p["strike"] - spot_price))

        greeks = {}
        try:
            call_ticker = self._deribit.get_ticker(atm_call["instrument_name"])
            put_ticker = self._deribit.get_ticker(atm_put["instrument_name"])
            if call_ticker.get("greeks"):
                # underlying_price captured here too (added 2026-08-02,
                # see _cross_check_greeks) -- real bug found: each specific
                # option's OWN underlying_price (this is Deribit's forward
                # price for that expiry, not a single unified spot value)
                # can meaningfully differ from book[0]'s underlying_price
                # (a different, arbitrary instrument's forward price) that
                # this method's `spot_price` parameter was computed from.
                # Caught directly: a 12-hour BTC option's own
                # underlying_price was $196 (~0.3%) away from book[0]'s,
                # enough to visibly distort a near-expiry Black-Scholes
                # delta comparison.
                greeks["call"] = {
                    **call_ticker["greeks"], "instrument": atm_call["instrument_name"],
                    "underlying_price": call_ticker.get("underlying_price"), "mark_iv": call_ticker.get("mark_iv"),
                }
            if put_ticker.get("greeks"):
                greeks["put"] = {
                    **put_ticker["greeks"], "instrument": atm_put["instrument_name"],
                    "underlying_price": put_ticker.get("underlying_price"), "mark_iv": put_ticker.get("mark_iv"),
                }
        except Exception as e:
            logger.warning("ATM greeks fetch failed: %s", e)
            return None
        return greeks or None

    def _build_knowledge_context(self, currency: str, skew_label: str, pc_ratio_oi: float, vol_regime: str) -> Optional[dict]:
        """Relevant book content on options skew/positioning/volatility
        regime, attached for transparency -- informational only, never
        changes the computed put/call ratio, IV, skew, or vol regime. No
        query when nothing is notable (flat skew, unremarkable P/C ratio,
        average vol regime) -- same principle as e05_economic_calendar/
        e10_cross_asset: nothing flagged, no query."""
        if self._knowledge_engine is None:
            return None
        skew_notable = skew_label not in ("flat", "unavailable")
        pc_notable = pc_ratio_oi == pc_ratio_oi and pc_ratio_oi > 1.2
        vol_notable = vol_regime in ("low", "high")
        if not (skew_notable or pc_notable or vol_notable):
            return None
        try:
            query_parts = [f"{currency} options"]
            if skew_notable:
                query_parts.append(skew_label.replace("_", " "))
            if vol_notable:
                query_parts.append(f"{vol_regime} volatility regime")
            query_parts.append("put call ratio positioning")
            query = " ".join(query_parts)
            results = self._knowledge_engine.document_store.hybrid_search(query, limit=3)
        except Exception as e:
            logger.warning("Knowledge context unavailable: %s", e)
            return None
        if not results:
            return None
        return {"query": query, "results": [r.to_dict() for r in results]}
