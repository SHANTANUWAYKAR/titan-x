"""
Module: import_second_batch.py
Description: Second batch of user-downloaded historical datasets, merged
    into data/processed/{yahoo_symbol}_{timeframe}.parquet (same
    convention as import_downloaded_datasets.py):

    1. Indian indices (NIFTY 50 / NIFTY BANK / India VIX) -- real, recent
       yfinance-format daily data for NIFTY50/BANKNIFTY, this platform's
       actual Indian F&O assets.
    2. Global Financial Markets (multi-asset daily, 2000-now) -- filtered
       to only the symbols this platform actually trades; everything
       else in that file (individual country indices not on the
       watchlist, etc.) is deliberately left unused, not force-fit.
    3. Gold Price Regression (multi-asset daily since 2010) -- GOLD/
       SILVER/CRUDE OHLCV columns only; the single-value macro columns
       (us_rates/CPI/GDP/eur_usd spot) don't have real O/H/L so aren't
       merged into the OHLCV convention here.
    4. GBPUSD/USDJPY/XAGUSD (Silver) 1-minute history back to 2001, from
       the "Historical Forex Data" archive -- only the 3 files matching
       actual platform assets; the other 13 pairs in that archive
       (AUDJPY, EURCHF, etc.) are not imported since nothing on this
       platform trades them.

    Deliberately NOT imported (see conversation): "NEWS.zip"/"Stock-
    Market Sentiment Dataset" (individual-US-stock scope, this platform
    excludes equities) and the raw economic-calendar CSVs (real event
    data, but building E05's expanded per-event-type calibration from it
    is a genuinely separate, bigger task -- staged as a follow-up, not
    rushed into a half-built calibration here).
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-07-18
"""

import io
import logging
import zipfile
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

DOWNLOADS_DIR = Path.home() / "Downloads"
PROCESSED_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"


def _merge_and_save(new_df: pd.DataFrame, symbol: str, timeframe: str) -> dict:
    """Same merge philosophy as import_downloaded_datasets.py: existing
    cached data wins on exact-timestamp overlap, new data extends real
    range, no fabricated/forward-filled bars."""
    new_df = new_df.dropna(subset=["open", "high", "low", "close"]).sort_values("timestamp")
    new_df = new_df.drop_duplicates(subset="timestamp", keep="first")
    if new_df.empty:
        return {"symbol": symbol, "timeframe": timeframe, "skipped": "no usable rows after cleaning"}
    new_df["symbol"] = symbol
    new_df["timeframe"] = timeframe

    path = PROCESSED_DIR / f"{symbol}_{timeframe}.parquet"
    new_start, new_end = new_df["timestamp"].iloc[0], new_df["timestamp"].iloc[-1]

    if path.exists():
        existing = pd.read_parquet(path)
        combined = pd.concat([new_df, existing], ignore_index=True)
        combined = combined.sort_values("timestamp").drop_duplicates(subset="timestamp", keep="last")
        combined = combined.reset_index(drop=True)
    else:
        combined = new_df.reset_index(drop=True)

    combined.to_parquet(path, index=False)
    return {
        "symbol": symbol, "timeframe": timeframe,
        "imported_bars": len(new_df), "imported_range": [str(new_start.date()), str(new_end.date())],
        "final_bars": len(combined),
        "final_range": [str(combined["timestamp"].iloc[0].date()), str(combined["timestamp"].iloc[-1].date())],
    }


# ---- 1. Indian indices (yfinance MultiIndex-style CSV export) ----

INDIAN_INDICES_ZIP = DOWNLOADS_DIR / "Indian Stock Market Indices Daily Updates.zip"
INDIAN_INDICES_MAP = {
    "NIFTY 50.csv": "^NSEI",
    "NIFTY BANK.csv": "^NSEBANK",
    "India VIX.csv": "^INDIAVIX",
}


def _parse_yfinance_export_csv(raw: bytes) -> pd.DataFrame:
    """3-row header (Price/Ticker/Date), then Date,Close,High,Low,Open,Volume rows."""
    df = pd.read_csv(io.BytesIO(raw), skiprows=3, header=None, names=["timestamp", "close", "high", "low", "open", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df[["timestamp", "open", "high", "low", "close", "volume"]]


def import_indian_indices() -> list[dict]:
    if not INDIAN_INDICES_ZIP.exists():
        return [{"error": f"not found: {INDIAN_INDICES_ZIP}"}]
    results = []
    with zipfile.ZipFile(INDIAN_INDICES_ZIP) as zf:
        for csv_name, symbol in INDIAN_INDICES_MAP.items():
            try:
                raw = zf.read(csv_name)
            except KeyError:
                results.append({"symbol": symbol, "error": f"{csv_name} not in zip"})
                continue
            df = _parse_yfinance_export_csv(raw)
            result = _merge_and_save(df, symbol, "1d")
            results.append(result)
            logger.info("%s: %s", symbol, result)
    return results


# ---- 2. Global Financial Markets (multi-asset daily since 2000) ----

GLOBAL_MARKETS_ZIP = DOWNLOADS_DIR / "Global Financial Markets.zip"
GLOBAL_MARKETS_CSV = "global_financial_markets_2000_Now.csv"
# Only symbols this platform actually trades -- everything else in the
# source file (other countries' indices, other cryptos, other
# commodities) is deliberately left unused.
GLOBAL_MARKETS_SYMBOLS = {"BTC-USD", "ETH-USD", "EURUSD=X", "GBPUSD=X", "GC=F", "SI=F", "CL=F"}


def import_global_markets() -> list[dict]:
    if not GLOBAL_MARKETS_ZIP.exists():
        return [{"error": f"not found: {GLOBAL_MARKETS_ZIP}"}]
    with zipfile.ZipFile(GLOBAL_MARKETS_ZIP) as zf:
        raw = zf.read(GLOBAL_MARKETS_CSV)
    df = pd.read_csv(io.BytesIO(raw))
    df["timestamp"] = pd.to_datetime(df["date"], utc=True)

    results = []
    for symbol in GLOBAL_MARKETS_SYMBOLS:
        subset = df[df["symbol"] == symbol].copy()
        if subset.empty:
            results.append({"symbol": symbol, "skipped": "not present in this file"})
            continue
        result = _merge_and_save(subset, symbol, "1d")
        results.append(result)
        logger.info("%s: %s", symbol, result)
    return results


# ---- 3. Gold Price Regression (multi-asset daily since 2010) ----

GOLD_REGRESSION_ZIP = DOWNLOADS_DIR / "Gold Price Regression.zip"
GOLD_REGRESSION_CSV = "financial_regression.csv"
GOLD_REGRESSION_ASSETS = {
    "gold": "GC=F",
    "silver": "SI=F",
    "oil": "CL=F",
}


def import_gold_regression() -> list[dict]:
    if not GOLD_REGRESSION_ZIP.exists():
        return [{"error": f"not found: {GOLD_REGRESSION_ZIP}"}]
    with zipfile.ZipFile(GOLD_REGRESSION_ZIP) as zf:
        raw = zf.read(GOLD_REGRESSION_CSV)
    df = pd.read_csv(io.BytesIO(raw))
    df["timestamp"] = pd.to_datetime(df["date"], utc=True)

    results = []
    for prefix, symbol in GOLD_REGRESSION_ASSETS.items():
        cols = {f"{prefix} open": "open", f"{prefix} high": "high", f"{prefix} low": "low", f"{prefix} close": "close", f"{prefix} volume": "volume"}
        if not all(c in df.columns for c in cols):
            results.append({"symbol": symbol, "skipped": f"missing {prefix} columns"})
            continue
        subset = df[["timestamp", *cols.keys()]].rename(columns=cols)
        result = _merge_and_save(subset, symbol, "1d")
        results.append(result)
        logger.info("%s: %s", symbol, result)
    return results


# ---- 4. Historical Forex Data (1-minute, MT-style, since 2001) ----

FOREX_ZIP = DOWNLOADS_DIR / "Historical Forex Data.zip"
FOREX_FILE_MAP = {
    "Foerex Pairs/GBPUSD.txt": "GBPUSD=X",
    "Foerex Pairs/USDJPY.txt": "USDJPY=X",
    "Foerex Pairs/XAGUSD.txt": "SI=F",  # Silver spot proxy -- SI=F is this platform's silver symbol
}
FOREX_COLUMNS = ["ticker", "date", "time", "open", "high", "low", "close", "volume"]


def _parse_mt_ticks(raw: bytes) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(raw), header=0, names=FOREX_COLUMNS)
    df["timestamp"] = pd.to_datetime(
        df["date"].astype(str) + df["time"].astype(str).str.zfill(6), format="%Y%m%d%H%M%S", utc=True
    )
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df[["timestamp", "open", "high", "low", "close", "volume"]]


def import_forex_pairs() -> list[dict]:
    if not FOREX_ZIP.exists():
        return [{"error": f"not found: {FOREX_ZIP}"}]
    results = []
    with zipfile.ZipFile(FOREX_ZIP) as zf:
        for zip_path, symbol in FOREX_FILE_MAP.items():
            raw = zf.read(zip_path)
            df = _parse_mt_ticks(raw)
            result = _merge_and_save(df, symbol, "1m")
            results.append(result)
            logger.info("%s (1m): %s", symbol, result)
    return results


def main() -> dict:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    results = {}
    logger.info("=== 1/4: Indian indices ===")
    results["indian_indices"] = import_indian_indices()
    logger.info("=== 2/4: Global Financial Markets ===")
    results["global_markets"] = import_global_markets()
    logger.info("=== 3/4: Gold Price Regression ===")
    results["gold_regression"] = import_gold_regression()
    logger.info("=== 4/4: Historical Forex Data (GBPUSD/USDJPY/XAGUSD 1m) ===")
    results["forex_pairs"] = import_forex_pairs()
    return results


if __name__ == "__main__":
    main()
