"""
Module: engine.py
Description: Engine 02 — Market Data ingestion and management. Institutional
    scope (per the master prompt's Market Data Acquisition Platform spec):
    multi-asset-class OHLCV acquisition with an automatic fallback chain,
    data-quality validation/repair (via e40_data_quality) and a real
    audit/versioning catalog (core/catalog.py) on every fetch, plus crypto
    derivatives context (funding rate, open interest) and regulator-published
    positioning data (CFTC COT reports) and market-wide sentiment (crypto
    Fear & Greed Index) -- all from genuinely free, no-auth sources.

    Honest scope: the full spec also names Polygon, Tiingo, Twelve Data,
    Dukascopy tick data, MT5, OANDA, Trading Economics, CME/ICE direct feeds,
    Bybit/Coinbase, and Glassnode's paid on-chain tiers. None of these are
    integrated -- they require a paid API key or a locally-running desktop
    platform (MT5), which this repository does not have configured. Adding
    a client that can't actually be exercised against a real, live source
    would violate this project's core rule: never fabricate a capability.
    News/RSS/SEC-filings/research-paper ingestion is e03_news + e01_knowledge's
    job, not this engine's; economic indicators (rates/inflation/GDP/PMI/CPI/
    yield curves) are e04_macro + e05_economic_calendar's job; options
    chains/vol surface/gamma exposure are e13_derivatives' job (Deribit).
    This engine routes to those, it does not duplicate them.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-07-16
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import ccxt
import pandas as pd
import yfinance as yf
from sqlalchemy.dialects.postgresql import insert

from project_titan_x.core.cache import cache_get_bytes, cache_set_bytes
from project_titan_x.core.catalog import DatasetCatalog
from project_titan_x.core.config import get_settings
from project_titan_x.core.config.assets import AssetClass, get_asset
from project_titan_x.core.data_providers import (
    SYMBOL_TO_CFTC_MARKET,
    get_alpha_vantage_client,
    get_alternative_me_client,
    get_cftc_client,
)
from project_titan_x.core.database import OHLCV, get_db_session
from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus
from project_titan_x.engines.e40_data_quality.engine import DataQualityEngine

logger = logging.getLogger(__name__)
settings = get_settings()

# e40_data_quality's expected_freq gap-detection assumes continuous
# trading (any interval longer than 1.5x the candle size is a "gap").
# That's true for crypto (24/7) but not for forex/commodities/indices,
# which close every weekend and on holidays -- passing an expected_freq
# for those would flag every single weekend as a "missing candle" and
# tank the quality score on perfectly normal data. Properly fixing this
# needs a real per-asset trading-calendar (market hours/holidays), which
# e40_data_quality doesn't have -- so gap-detection is intentionally left
# off here (None) rather than producing a misleading score; duplicate/
# bad-tick/null validation below is asset/session-agnostic and still runs.

# Yahoo-style symbol patterns this engine can translate into a fallback
# provider call. Commodity futures (GC=F, CL=F) are intentionally NOT
# mapped to any fallback: none of ccxt/nselib/Alpha Vantage's free
# endpoints cover futures, so guessing a lookup there would silently
# return the wrong instrument rather than fail loudly.
_FOREX_SYMBOL_RE = re.compile(r"^([A-Z]{3})([A-Z]{3})=X$")
_CRYPTO_SYMBOL_RE = re.compile(r"^([A-Z0-9]+)-([A-Z]{3,4})$")

# NSE index tickers -> the exact index name nselib/NSE India's site expects.
NSE_INDEX_MAP = {
    "^NSEI": "NIFTY 50",
    "^NSEBANK": "NIFTY BANK",
}

# ccxt (Binance) timeframe strings, keyed by this engine's own timeframe
# names. Binance supports 4h natively, unlike yfinance, so no resampling
# step is needed for the ccxt path.
CCXT_TIMEFRAME_MAP = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
    "1wk": "1w",
    "1mo": "1M",
}


def _alpha_vantage_fallback_params(symbol: str) -> Optional[tuple[str, dict]]:
    """Map a Yahoo-style symbol to an Alpha Vantage FX_DAILY/DIGITAL_CURRENCY_DAILY
    call, if this asset class has a clean, well-documented AV endpoint."""
    asset = get_asset(symbol)
    asset_class = asset.asset_class if asset else None

    m = _FOREX_SYMBOL_RE.match(symbol.upper())
    if m and asset_class in (None, AssetClass.FOREX):
        return "forex", {"from_symbol": m.group(1), "to_symbol": m.group(2)}

    m = _CRYPTO_SYMBOL_RE.match(symbol.upper())
    if m and asset_class in (None, AssetClass.CRYPTO):
        return "crypto", {"symbol": m.group(1), "market": m.group(2)}

    return None


def _ccxt_market_symbol(symbol: str) -> Optional[str]:
    """Map a crypto symbol -- Yahoo-style ('BTC-USD') or the platform's
    canonical form ('BTCUSD') -- to a Binance spot market (e.g. 'BTC/USDT')
    -- Binance quotes crypto in USDT, not USD."""
    asset = get_asset(symbol)
    if asset is not None and asset.asset_class != AssetClass.CRYPTO:
        return None
    # Resolve to the Yahoo-style form the regex expects, whether the input
    # was already Yahoo-style or the platform's canonical (no-dash) symbol.
    lookup = asset.yahoo_symbol if asset is not None else symbol
    m = _CRYPTO_SYMBOL_RE.match(lookup.upper())
    if m is None:
        return None
    base, quote = m.group(1), m.group(2)
    return f"{base}/USDT" if quote == "USD" else f"{base}/{quote}"


def _ccxt_perpetual_market_symbol(symbol: str) -> Optional[str]:
    """Map a Yahoo-style crypto symbol to ccxt's unified perpetual-swap
    market symbol (e.g. 'BTC-USD' -> 'BTC/USDT:USDT') -- funding rate and
    open interest are perpetual-futures concepts, not spot-market ones."""
    spot = _ccxt_market_symbol(symbol)
    if spot is None:
        return None
    base, quote = spot.split("/")
    return f"{base}/{quote}:{quote}"


TIMEFRAME_MAP = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "4h": "1h",  # yfinance uses 1h, resample for 4h
    "1d": "1d",
    "1wk": "1wk",
    "1mo": "1mo",
}

YFINANCE_PERIOD = {
    "1m": "7d",
    "5m": "60d",
    "15m": "60d",
    "30m": "60d",
    "1h": "730d",
    "4h": "730d",
    "1d": "max",
    "1wk": "max",
    "1mo": "max",
}



def _prune_empty_columns(df: "pd.DataFrame", symbol: str, timeframe: str) -> "pd.DataFrame":
    """Drop columns that are entirely empty before a frame is persisted.

    An all-null column carries no information by definition, and concat-based
    cache merging is what creates them: when a fetch returns a column the
    cached frame lacks (or vice versa), the union widens the file permanently
    and back-fills the other side with NaN. Left alone it compounds, because
    the next merge takes the widened file as its baseline.

    Measured 2026-09-15 across all 241 processed parquets: ETH-USD_1d -- one of
    the two instruments currently trading live -- had accumulated `date`,
    `asset_name`, `asset_type` and `region`, every one null in all 3,675 rows,
    while no other file carried them at all. `date` is the dangerous one: it is
    a plausible name for exactly what the file stores under `timestamp`, so a
    consumer reaching for it gets NaT for every bar rather than an error.

    Only ALL-null columns are dropped. A merely sparse column is real data --
    `dividends` is legitimately null on early rows for several symbols -- and
    is kept untouched.
    """
    try:
        empty_cols = [c for c in df.columns if df[c].isna().all()]
        if not empty_cols:
            return df
        logger.info("Dropping %d all-null column(s) from %s %s before save: %s",
                    len(empty_cols), symbol, timeframe, empty_cols)
        return df.drop(columns=empty_cols)
    except Exception as e:  # noqa: BLE001 - never lose a good fetch to cleanup
        logger.warning("Could not prune empty columns for %s %s: %s", symbol, timeframe, e)
        return df


class MarketDataEngine(BaseEngine):
    """
    Market Data Engine — fetches, stores, and serves OHLCV data.

    Sources: Yahoo Finance (primary), extensible to MT5, Alpha Vantage, etc.
    """

    engine_id = "e02_market_data"
    engine_name = "Market Data Engine"
    version = "1.0.0"

    def __init__(
        self,
        data_dir: Optional[Path] = None,
        data_quality_engine: Optional[DataQualityEngine] = None,
        catalog: Optional[DatasetCatalog] = None,
    ) -> None:
        super().__init__()
        self.data_dir = data_dir or Path("data")
        self.raw_dir = self.data_dir / "raw"
        self.processed_dir = self.data_dir / "processed"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        # Always-on infrastructure collaborators (not an optional add-on
        # like knowledge_context elsewhere) -- validation/repair and
        # auditability are core objectives of this engine, not extras.
        self._data_quality_engine = data_quality_engine if data_quality_engine is not None else DataQualityEngine()
        # Scoped to THIS engine's own data_dir by default -- not the global
        # get_catalog() singleton, which would ignore a custom data_dir
        # (e.g. a test's tmp_path) and silently read/write the real
        # project catalog instead.
        self._catalog = catalog if catalog is not None else DatasetCatalog(catalog_dir=self.data_dir / "catalog")

    def initialize(self) -> EngineResult:
        """Initialize data directories and verify connectivity."""
        try:
            self._set_status(EngineStatus.RUNNING)
            test = yf.Ticker("^GSPC")
            info = test.history(period="5d")
            if info.empty:
                raise ValueError("Yahoo Finance connectivity test failed")
            sources = [
                "yahoo_finance",
                "ccxt/binance (fallback: crypto, no key needed)",
                "nselib (fallback: NIFTY 50 / NIFTY BANK, no key needed)",
            ]
            if get_alpha_vantage_client().is_configured:
                sources.append("alpha_vantage (fallback: forex, crypto daily)")
            self._set_status(EngineStatus.IDLE)
            return EngineResult(
                success=True,
                message="Market Data Engine initialized",
                metadata={"sources": sources},
            )
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("Market Data Engine init failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def health_check(self) -> EngineResult:
        """Verify data source availability."""
        try:
            ticker = yf.Ticker("SPY")
            hist = ticker.history(period="1d")
            healthy = not hist.empty
            return EngineResult(
                success=healthy,
                message="Healthy" if healthy else "Data source unavailable",
            )
        except Exception as e:
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1d",
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        years: int = 10,
        allow_cache: bool = False,
    ) -> EngineResult:
        """
        Fetch OHLCV data (see _fetch_ohlcv_uncached for the real fetch
        logic and docstring).

        allow_cache: added 2026-08-21, default False -- a real, measured
        scan-performance fix, but deliberately OPT-IN, not a silent
        global behavior change. A live cProfile-style timing found
        fetch_ohlcv's own network I/O (~0.78s/asset, live-measured
        against Yahoo Finance) is the single largest remaining
        controllable cost in a multi-asset scan after generate_signal's
        own informational-context skip (see e51_signals.engine's
        include_extended_context). Only e51_signals.scan_all_assets
        passes allow_cache=True, for exactly that bulk-scan use case.

        REAL BUG this default avoids repeating: a first version of this
        cache wrapped every call unconditionally, which silently broke
        this engine's own documented "real audit/versioning catalog...
        on every fetch" guarantee -- self._catalog.record() and the
        audit log only ever run inside _fetch_ohlcv_uncached, so a cache
        hit was skipping them too, caught by two real, pre-existing
        tests (test_fetch_ohlcv_twice_increments_catalog_version,
        test_get_catalog_summary_reflects_fetched_datasets) failing.
        Rather than trying to replay catalog/audit recording from a
        cached payload (real complexity: source/quality_score/merged-
        row-count/parquet-disk-state would all need faithful
        reconstruction for an event that, semantically, didn't actually
        involve a new fetch), the correct fix is scoping the cache to
        only the one caller that has actually opted into "same data,
        served fast" semantics -- every other caller (including this
        engine's own catalog-sensitive tests) keeps its full guarantee,
        completely unchanged, by simply never setting this flag.

        When allow_cache=True: Redis was already an installed
        dependency and running container with zero real usage anywhere
        in this codebase before this (see core/cache.py's own
        docstring) -- best-effort, any Redis failure transparently
        falls back to the real, uncached fetch, exactly as if
        allow_cache had been False."""
        if not allow_cache:
            return self._fetch_ohlcv_uncached(symbol, timeframe, start, end, years)

        cache_key = self._ohlcv_cache_key(symbol, timeframe, start, end, years)
        # Defense in depth: core.cache's own cache_get_bytes/cache_set_bytes
        # already catch every Redis failure internally and return None/no-op
        # rather than raise -- but this real data fetch must stay correct
        # even if that internal handling were ever weakened by a future
        # edit, so it's not solely relied on here either.
        try:
            cached = cache_get_bytes(cache_key)
        except Exception as e:
            logger.warning("Cache read failed for %s (continuing without cache): %s", cache_key, e)
            cached = None
        if cached is not None:
            try:
                return self._deserialize_ohlcv_result(cached)
            except Exception as e:
                logger.warning("Cached OHLCV entry for %s unreadable, re-fetching fresh: %s", cache_key, e)

        result = self._fetch_ohlcv_uncached(symbol, timeframe, start, end, years)
        if result.success and result.data is not None and not result.data.empty:
            try:
                cache_set_bytes(cache_key, self._serialize_ohlcv_result(result), settings.ohlcv_cache_ttl_seconds)
            except Exception as e:
                logger.warning("Failed to cache OHLCV result for %s (non-fatal): %s", cache_key, e)
        return result

    @staticmethod
    def _ohlcv_cache_key(symbol: str, timeframe: str, start: Optional[datetime], end: Optional[datetime], years: int) -> str:
        """Every parameter that changes WHAT gets fetched must be part of
        the key -- omitting any of them would risk serving a different
        date range's data under a colliding key."""
        return (
            f"titanx:ohlcv:{symbol}:{timeframe}:years={years}:"
            f"start={start.isoformat() if start else ''}:end={end.isoformat() if end else ''}"
        )

    @staticmethod
    def _serialize_ohlcv_result(result: EngineResult) -> bytes:
        """The DataFrame itself is Parquet, not JSON -- preserves the
        tz-aware `timestamp` column's exact dtype on round-trip (a JSON
        round-trip would need to re-parse/re-localize it, an easy place
        to silently reintroduce the exact tz bugs this file's own
        comments already document fixing). The Parquet bytes are then
        base64-encoded into a small JSON envelope alongside message/
        metadata -- deliberately NOT pickle, which would tie the cache
        to this exact pandas/Python build and silently break (or worse,
        silently misdeserialize) across a version bump. Only `data` and
        `message`/`metadata` are cached -- `success`/`errors` aren't,
        since this is only ever called after confirming result.success."""
        import base64
        import io
        import json
        buf = io.BytesIO()
        result.data.to_parquet(buf, index=False)
        payload = {
            "parquet_b64": base64.b64encode(buf.getvalue()).decode("ascii"),
            "message": result.message, "metadata": result.metadata,
        }
        return json.dumps(payload).encode("utf-8")

    @staticmethod
    def _deserialize_ohlcv_result(raw: bytes) -> EngineResult:
        import base64
        import io
        import json
        payload = json.loads(raw)
        df = pd.read_parquet(io.BytesIO(base64.b64decode(payload["parquet_b64"])))
        return EngineResult(success=True, data=df, message=payload["message"] + " (cached)", metadata=payload["metadata"])

    def _fetch_ohlcv_uncached(
        self,
        symbol: str,
        timeframe: str = "1d",
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        years: int = 10,
    ) -> EngineResult:
        """
        Fetch OHLCV data from Yahoo Finance.

        Args:
            symbol: Ticker symbol (e.g., 'NIFTY50.NS', 'EURUSD=X', 'BTC-USD').
            timeframe: Candle timeframe.
            start: Start datetime (optional).
            end: End datetime (optional).
            years: Years of history if start not specified.

        Returns:
            EngineResult with DataFrame in data field.
        """
        try:
            self._set_status(EngineStatus.RUNNING)
            yf_interval = TIMEFRAME_MAP.get(timeframe, "1d")
            period = YFINANCE_PERIOD.get(timeframe, "max")

            if start is None:
                start = datetime.now(timezone.utc) - timedelta(days=365 * years)

            source = "yahoo_finance"
            df: Optional[pd.DataFrame] = None
            try:
                ticker = yf.Ticker(symbol)
                if end:
                    yf_df = ticker.history(
                        start=start.strftime("%Y-%m-%d"),
                        end=end.strftime("%Y-%m-%d"),
                        interval=yf_interval,
                    )
                elif yf_interval in ("1d", "1wk", "1mo"):
                    # No hard yfinance lookback cap for these timeframes --
                    # honor the caller's requested `years` (or explicit
                    # `start`) via a start-bounded fetch. The old
                    # `period=period` here resolved to "max" for every
                    # daily+ timeframe (see YFINANCE_PERIOD) regardless of
                    # what `years` was passed -- `years`/`start` were
                    # computed above but then silently never used, so every
                    # daily-timeframe caller across this codebase (E24/E27/
                    # E28/E51's own edge-gate, etc.) always got maximum
                    # available history no matter what it asked for. Not
                    # incorrect data, just a silently non-functional
                    # parameter -- real bug, fixed here rather than passed
                    # on quietly (CLAUDE.md Rule 4: price/data correctness).
                    yf_df = ticker.history(start=start.strftime("%Y-%m-%d"), interval=yf_interval)
                else:
                    # Intraday timeframes: yfinance enforces its own hard
                    # lookback caps (7d for 1m, 60d for 5m/15m, 730d for 1h)
                    # regardless of what's requested -- period= here is the
                    # correct, safe way to ask for "as much as yfinance
                    # allows", not the same bug as the daily case above.
                    yf_df = ticker.history(period=period, interval=yf_interval)
                if not yf_df.empty:
                    df = yf_df
            except Exception as e:
                logger.warning("Yahoo Finance fetch failed for %s: %s", symbol, e)

            if df is not None:
                df = df.reset_index()
                df.columns = [c.lower().replace(" ", "_") for c in df.columns]
                date_col = "date" if "date" in df.columns else "datetime"
                df = df.rename(columns={date_col: "timestamp"})
                if df["timestamp"].dt.tz is None:
                    df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")
                elif yf_interval in ("1d", "1wk", "1mo"):
                    # Daily+ bars mark a trading day, not an instant --
                    # yfinance returns them at local-exchange midnight
                    # (e.g. 00:00+05:30 for NSE, verified live). tz_convert
                    # preserves that instant but shifts positive-UTC-offset
                    # exchanges (NSE +5:30) back onto the previous calendar
                    # day (18:30 UTC the day before), corrupting the trading
                    # date. Relabel the wall-clock date as UTC instead of
                    # converting it, matching the nselib fallback's own
                    # (already date-preserving) handling below.
                    df["timestamp"] = df["timestamp"].dt.tz_localize(None).dt.tz_localize("UTC")
                else:
                    df["timestamp"] = df["timestamp"].dt.tz_convert("UTC")

                df["symbol"] = symbol
                df["timeframe"] = timeframe

                # Resample to 4h if needed
                if timeframe == "4h" and yf_interval == "1h":
                    df = self._resample_ohlcv(df, "4h")
            else:
                # Yahoo Finance failed/empty -- work through the fallback
                # chain in order of "least likely to burn a scarce quota":
                # ccxt (crypto, unlimited/no key) -> nselib (NSE indices, no
                # key) -> Alpha Vantage (forex/crypto daily, quota-limited).
                fallbacks = [
                    ("ccxt", lambda: self._fetch_ohlcv_ccxt(symbol, timeframe, start)),
                    ("nselib", lambda: self._fetch_ohlcv_nse(symbol, timeframe, start)),
                    ("alpha_vantage", lambda: self._fetch_ohlcv_alpha_vantage(symbol, timeframe, start)),
                ]
                for name, fetch_fn in fallbacks:
                    try:
                        candidate = fetch_fn()
                    except Exception as e:
                        logger.warning("%s fallback failed for %s: %s", name, symbol, e)
                        candidate = None
                    if candidate is not None and not candidate.empty:
                        df = candidate
                        source = name
                        break

            if df is None or df.empty:
                raise ValueError(
                    f"No data returned for {symbol} "
                    f"(tried yahoo_finance, ccxt, nselib, alpha_vantage)"
                )

            # Data quality: validate, and repair if the score is poor.
            # Best-effort -- a validation/repair failure must never block a
            # fetch that otherwise succeeded, since the raw data is still
            # usable and more valuable than nothing.
            quality_score: Optional[float] = None
            try:
                quality_result = self._data_quality_engine.validate(df)
                if quality_result.data is not None:
                    quality_score = quality_result.data.quality_score
                    if quality_score < 70.0:
                        repair_result = self._data_quality_engine.repair(df)
                        if repair_result.success and repair_result.data is not None:
                            df = repair_result.data
                            logger.info(
                                "Repaired %s %s data (pre-repair quality score %.1f)",
                                symbol, timeframe, quality_score,
                            )
            except Exception as e:
                logger.warning("Data quality check failed for %s %s: %s", symbol, timeframe, e)

            # Save to parquet -- MERGE with whatever's already cached here,
            # never blind-overwrite. A live fetch only ever requests a
            # bounded recent window (`years`, or yfinance's own free-tier
            # cap for intraday timeframes -- often just ~60 days for 1m
            # bars regardless of `years` requested); overwriting the whole
            # file with just that window would silently destroy any
            # deeper imported history sitting outside it (real bug, caught
            # live: a 1m GOLD fetch would have wiped a 22-year, 6.79M-row
            # imported dataset down to ~60 days). New data wins on exact
            # overlapping timestamps (freshest/most authoritative for the
            # window actually being fetched); every other cached row --
            # including all the older history a fetch didn't even touch
            # -- is preserved untouched.
            parquet_path = self.processed_dir / f"{symbol}_{timeframe}.parquet"
            if parquet_path.exists():
                try:
                    existing = pd.read_parquet(parquet_path)
                    combined = pd.concat([existing, df], ignore_index=True)
                    combined = combined.sort_values("timestamp").drop_duplicates(subset="timestamp", keep="last")
                    # CALENDAR-DAY DEDUP for daily+ timeframes (added
                    # 2026-09-11, closes a real, previously-documented gap --
                    # see CLAUDE.md's "systemic duplicate-calendar-day rows"
                    # note, 67,036 duplicate rows measured across 13 files
                    # before this fix). The drop_duplicates above only
                    # catches EXACT timestamp collisions; two fetches that
                    # each independently normalized "the same trading day"
                    # to a slightly different intraday UTC time (e.g. 00:00
                    # vs 04:00, both real values found in this project's own
                    # cached data) never collide on that check at all --
                    # a daily/weekly/monthly bar means exactly one row per
                    # calendar day, never two. Not applied to intraday
                    # timeframes, where multiple distinct real bars per
                    # calendar day are expected and correct.
                    if timeframe in ("1d", "1wk", "1mo"):
                        combined["_date"] = combined["timestamp"].dt.date
                        # Prefer the row already using this project's own
                        # established daily-bar convention (midnight UTC --
                        # see the tz_localize block above, "Relabel the
                        # wall-clock date as UTC instead of converting it").
                        # A non-midnight timestamp on a daily bar is itself
                        # evidence of the older, pre-fix normalization.
                        # Ties (both/neither midnight) fall back to
                        # keep="last", the SAME "freshest fetch wins" rule
                        # the exact-timestamp dedup above already applies --
                        # stable sort preserves concat's existing-then-new
                        # order within an equal-priority group.
                        combined["_is_midnight"] = combined["timestamp"].dt.hour == 0
                        combined = combined.sort_values(["_date", "_is_midnight"], ascending=[True, True])
                        combined = combined.drop_duplicates(subset="_date", keep="last")
                        combined = combined.drop(columns=["_date", "_is_midnight"])
                        combined = combined.sort_values("timestamp")
                    df_to_save = combined.reset_index(drop=True)
                except Exception as e:
                    logger.warning("Could not merge with existing cache for %s %s (saving fresh fetch only): %s", symbol, timeframe, e)
                    df_to_save = df
            else:
                df_to_save = df

            df_to_save = _prune_empty_columns(df_to_save, symbol, timeframe)

            df_to_save.to_parquet(parquet_path, index=False)

            # Catalog: record this fetch for auditability/versioning.
            # Best-effort, same reasoning as data quality above.
            try:
                self._catalog.record(
                    symbol=symbol, timeframe=timeframe, source=source, rows=len(df_to_save),
                    date_range=(df_to_save["timestamp"].iloc[0], df_to_save["timestamp"].iloc[-1]),
                    file_path=parquet_path, quality_score=quality_score,
                )
            except Exception as e:
                logger.warning("Catalog recording failed for %s %s: %s", symbol, timeframe, e)

            self._set_status(EngineStatus.IDLE)
            return EngineResult(
                success=True,
                data=df,
                message=f"Fetched {len(df)} candles for {symbol} ({source})",
                metadata={
                    "symbol": symbol, "timeframe": timeframe, "rows": len(df),
                    "source": source, "quality_score": quality_score,
                },
            )
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("Fetch failed for %s: %s", symbol, e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def _fetch_ohlcv_alpha_vantage(
        self, symbol: str, timeframe: str, start: datetime
    ) -> Optional[pd.DataFrame]:
        """Fallback fetch via Alpha Vantage FX_DAILY / DIGITAL_CURRENCY_DAILY.
        Returns None (not an error) when the timeframe/asset class isn't one
        Alpha Vantage's free endpoints cleanly cover -- the caller then
        surfaces the original "no data" failure instead of a fabricated one.
        """
        if timeframe != "1d":
            return None
        mapped = _alpha_vantage_fallback_params(symbol)
        if mapped is None:
            return None

        client = get_alpha_vantage_client()
        if not client.is_configured:
            return None

        kind, params = mapped
        if kind == "forex":
            df = client.fx_daily(params["from_symbol"], params["to_symbol"], outputsize="full")
        else:
            df = client.crypto_daily(params["symbol"], params["market"])

        if "volume" not in df.columns:
            df["volume"] = 0.0

        cutoff = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
        df = df[df["timestamp"] >= cutoff].reset_index(drop=True)
        df["symbol"] = symbol
        df["timeframe"] = timeframe
        return df

    def _fetch_ohlcv_ccxt(
        self, symbol: str, timeframe: str, start: datetime
    ) -> Optional[pd.DataFrame]:
        """Fallback fetch via ccxt's public Binance OHLCV endpoint -- crypto
        only, no API key required, and (unlike the Alpha Vantage fallback)
        supports intraday timeframes, not just daily. Returns None (not an
        error) when the symbol isn't a mapped crypto pair."""
        market = _ccxt_market_symbol(symbol)
        ccxt_timeframe = CCXT_TIMEFRAME_MAP.get(timeframe)
        if market is None or ccxt_timeframe is None:
            return None

        exchange = ccxt.binance()
        cutoff = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
        since = int(cutoff.timestamp() * 1000)
        rows: list = []
        for _ in range(50):  # hard cap: avoid unbounded pagination on bad data
            batch = exchange.fetch_ohlcv(market, timeframe=ccxt_timeframe, since=since, limit=1000)
            if not batch:
                break
            rows.extend(batch)
            last_ts = batch[-1][0]
            if last_ts <= since or len(batch) < 1000:
                break
            since = last_ts + 1

        if not rows:
            return None

        df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df = df.drop_duplicates(subset="timestamp").sort_values("timestamp").reset_index(drop=True)
        df["symbol"] = symbol
        df["timeframe"] = timeframe
        return df

    def _fetch_ohlcv_nse(
        self, symbol: str, timeframe: str, start: datetime
    ) -> Optional[pd.DataFrame]:
        """Fallback fetch via nselib's direct NSE India index history --
        daily only, no API key required. Returns None (not an error) when
        the symbol isn't a mapped NSE index (see NSE_INDEX_MAP)."""
        if timeframe != "1d":
            return None
        index_name = NSE_INDEX_MAP.get(symbol.upper())
        if index_name is None:
            return None

        from nselib import capital_market

        cutoff = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
        raw = capital_market.index_data(
            index=index_name,
            from_date=cutoff.strftime("%d-%m-%Y"),
            to_date=datetime.now(timezone.utc).strftime("%d-%m-%Y"),
        )
        if raw is None or raw.empty:
            return None

        df = pd.DataFrame({
            "timestamp": pd.to_datetime(raw["TIMESTAMP"], format="%d-%b-%Y", utc=True),
            "open": pd.to_numeric(raw["OPEN_INDEX_VAL"], errors="coerce"),
            "high": pd.to_numeric(raw["HIGH_INDEX_VAL"], errors="coerce"),
            "low": pd.to_numeric(raw["LOW_INDEX_VAL"], errors="coerce"),
            "close": pd.to_numeric(raw["CLOSE_INDEX_VAL"], errors="coerce"),
            "volume": pd.to_numeric(raw["TRADED_QTY"], errors="coerce"),
        })
        df = df.dropna(subset=["timestamp", "close"]).sort_values("timestamp").reset_index(drop=True)
        df["symbol"] = symbol
        df["timeframe"] = timeframe
        return df

    def store_ohlcv(self, df: pd.DataFrame) -> EngineResult:
        """
        Persist OHLCV DataFrame to PostgreSQL.

        Args:
            df: DataFrame with symbol, timeframe, timestamp, OHLCV columns.

        Returns:
            EngineResult with count of stored rows.
        """
        try:
            records = []
            for _, row in df.iterrows():
                records.append({
                    "symbol": row["symbol"],
                    "timeframe": row["timeframe"],
                    "timestamp": row["timestamp"],
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": int(row.get("volume", 0)),
                })

            with get_db_session() as session:
                stmt = insert(OHLCV).values(records)
                stmt = stmt.on_conflict_do_nothing(
                    index_elements=["symbol", "timeframe", "timestamp"]
                )
                session.execute(stmt)

            return EngineResult(
                success=True,
                message=f"Stored {len(records)} candles",
                metadata={"rows": len(records)},
            )
        except Exception as e:
            logger.error("Store OHLCV failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def load_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1d",
        from_parquet: bool = True,
    ) -> EngineResult:
        """
        Load OHLCV data from parquet cache or database.

        Args:
            symbol: Ticker symbol.
            timeframe: Candle timeframe.
            from_parquet: Prefer parquet cache over database.

        Returns:
            EngineResult with DataFrame.
        """
        try:
            parquet_path = self.processed_dir / f"{symbol}_{timeframe}.parquet"
            if from_parquet and parquet_path.exists():
                df = pd.read_parquet(parquet_path)
                return EngineResult(success=True, data=df, message="Loaded from cache")

            with get_db_session() as session:
                rows = (
                    session.query(OHLCV)
                    .filter(OHLCV.symbol == symbol, OHLCV.timeframe == timeframe)
                    .order_by(OHLCV.timestamp)
                    .all()
                )
                if not rows:
                    return EngineResult(
                        success=False,
                        message=f"No data for {symbol} {timeframe}",
                    )
                df = pd.DataFrame([
                    {
                        "symbol": r.symbol,
                        "timeframe": r.timeframe,
                        "timestamp": r.timestamp,
                        "open": float(r.open),
                        "high": float(r.high),
                        "low": float(r.low),
                        "close": float(r.close),
                        "volume": r.volume,
                    }
                    for r in rows
                ])
                return EngineResult(success=True, data=df, message=f"Loaded {len(df)} rows")
        except Exception as e:
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def fetch_funding_rate(self, symbol: str) -> EngineResult:
        """Current perpetual-futures funding rate for a crypto asset, via
        Binance's public futures API (ccxt, no key needed). Funding rate is
        a genuinely crypto-specific data point -- returns an honest gap
        (success, no data) for forex/commodity/index symbols rather than
        fabricating one."""
        market = _ccxt_perpetual_market_symbol(symbol)
        if market is None:
            return EngineResult(
                success=True, data=None,
                message=f"{symbol} has no perpetual futures market -- funding rate applies to crypto only",
            )
        try:
            exchange = ccxt.binance()
            fr = exchange.fetch_funding_rate(market)
            data = {
                "symbol": symbol,
                "market": market,
                "funding_rate": fr.get("fundingRate"),
                "next_funding_time": fr.get("fundingDatetime"),
                "timestamp": fr.get("datetime"),
            }
            return EngineResult(success=True, data=data, message=f"Funding rate for {symbol}: {fr.get('fundingRate')}")
        except Exception as e:
            logger.warning("Funding rate fetch failed for %s: %s", symbol, e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def fetch_open_interest(self, symbol: str) -> EngineResult:
        """Current perpetual-futures open interest for a crypto asset, via
        Binance's public futures API. Same crypto-only scope as
        fetch_funding_rate -- see that method's docstring."""
        market = _ccxt_perpetual_market_symbol(symbol)
        if market is None:
            return EngineResult(
                success=True, data=None,
                message=f"{symbol} has no perpetual futures market -- open interest applies to crypto only",
            )
        try:
            exchange = ccxt.binance()
            oi = exchange.fetch_open_interest(market)
            data = {
                "symbol": symbol,
                "market": market,
                "open_interest": oi.get("openInterestAmount"),
                "timestamp": oi.get("datetime"),
            }
            return EngineResult(success=True, data=data, message=f"Open interest for {symbol}: {oi.get('openInterestAmount')}")
        except Exception as e:
            logger.warning("Open interest fetch failed for %s: %s", symbol, e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def fetch_open_interest_history(self, symbol: str, days: int = 30) -> EngineResult:
        """Daily perpetual-futures open interest history for a crypto asset,
        via Binance's public futures API (ccxt fetchOpenInterestHistory, no
        key needed). Distinct from fetch_open_interest (a single current
        snapshot) -- this returns a real time series so a genuine trend can
        be read from it instead of guessed from one data point. Same
        crypto-only scope as fetch_open_interest/fetch_funding_rate."""
        market = _ccxt_perpetual_market_symbol(symbol)
        if market is None:
            return EngineResult(
                success=True, data=None,
                message=f"{symbol} has no perpetual futures market -- open interest applies to crypto only",
            )
        try:
            exchange = ccxt.binance()
            raw = exchange.fetch_open_interest_history(market, timeframe="1d", limit=days)
            if not raw:
                return EngineResult(success=False, message=f"No open interest history returned for {symbol}")
            df = pd.DataFrame([
                {"timestamp": r.get("datetime"), "open_interest": r.get("openInterestAmount")} for r in raw
            ])
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
            df = df.dropna().sort_values("timestamp").reset_index(drop=True)
            return EngineResult(success=True, data=df, message=f"Fetched {len(df)} day(s) of open interest history for {symbol}")
        except Exception as e:
            logger.warning("Open interest history fetch failed for %s: %s", symbol, e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def fetch_cot_report(self, symbol: str, limit: int = 52) -> EngineResult:
        """Weekly CFTC Commitment of Traders report (hedger/speculator
        positioning) for `symbol`, via CFTC's free public Socrata API.
        Only covers US-listed futures contracts (see
        core/data_providers/cftc.py's SYMBOL_TO_CFTC_MARKET) -- returns an
        honest gap for USDINR/NIFTY50/BANKNIFTY (Indian-exchange
        instruments, no US futures contract, no CFTC data)."""
        asset = get_asset(symbol)
        symbol_key = asset.symbol if asset else symbol.upper()
        market_name = SYMBOL_TO_CFTC_MARKET.get(symbol_key)
        if market_name is None:
            return EngineResult(
                success=True, data=None,
                message=f"No CFTC COT data available for {symbol_key} -- not a US-listed futures contract",
            )
        try:
            client = get_cftc_client()
            df = client.get_cot_report(market_name, limit=limit)
            if df.empty:
                return EngineResult(success=False, message=f"CFTC returned no data for {market_name}")
            return EngineResult(
                success=True, data=df,
                message=f"Fetched {len(df)} COT report(s) for {symbol_key}",
                metadata={"market": market_name, "rows": len(df)},
            )
        except Exception as e:
            logger.warning("COT report fetch failed for %s: %s", symbol, e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def fetch_fear_greed_index(self, limit: int = 30) -> EngineResult:
        """Crypto Fear & Greed Index (alternative.me, free, no key) --
        market-wide sentiment, not asset-specific (same reading regardless
        of which supported crypto asset is being analyzed)."""
        try:
            client = get_alternative_me_client()
            df = client.get_fear_greed_index(limit=limit)
            if df.empty:
                return EngineResult(success=False, message="alternative.me returned no data")
            latest = df.iloc[-1]
            return EngineResult(
                success=True, data=df,
                message=f"Fear & Greed Index: {int(latest['value'])} ({latest['classification']})",
                metadata={"latest_value": int(latest["value"]), "latest_classification": latest["classification"]},
            )
        except Exception as e:
            logger.warning("Fear & Greed Index fetch failed: %s", e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def get_catalog_summary(self) -> EngineResult:
        """Latest catalog entry for every dataset this engine has fetched
        (symbol, timeframe, source, rows, date range, quality score,
        checksum, version)."""
        datasets = self._catalog.list_datasets()
        return EngineResult(success=True, data=datasets, message=f"{len(datasets)} dataset(s) in catalog")

    def get_audit_log(self, limit: int = 100) -> EngineResult:
        """Most recent `limit` fetch events across every dataset, newest first."""
        entries = self._catalog.get_audit_log(limit=limit)
        return EngineResult(success=True, data=entries, message=f"{len(entries)} audit log entry/entries")

    @staticmethod
    def _resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
        """Resample OHLCV to a higher timeframe."""
        df = df.set_index("timestamp")
        resampled = df.resample(rule).agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
            "symbol": "first",
            "timeframe": "first",
        }).dropna()
        resampled["timeframe"] = rule
        return resampled.reset_index()
