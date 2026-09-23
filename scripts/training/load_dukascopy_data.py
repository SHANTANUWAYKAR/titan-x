"""
Module: load_dukascopy_data.py
Description: Build canonical 5m/15m/1h/4h/1d OHLCV parquet files from
    Dukascopy's free, no-key historical data (github.com/Leo4815162342/
    dukascopy-node), for platform assets whose intraday history is
    genuinely shallow or entirely missing in data/processed/ -- verified
    per-asset before pulling, not assumed (EUR/USD, GBP/USD, USD/JPY,
    SILVER only had ~3 months of 5m data via yfinance's own free-tier
    intraday retention; ETH-USD and every platform stock had NONE at
    5m). GOLD's 5m is already deep from a prior import
    (import_xauusd_history.py's sibling import job) -- pulled anyway
    since it's a real, different, free source and the merge is safe, but
    it isn't closing a gap the way the others are.

    Same merge-not-overwrite discipline as load_btc_data.py's
    _merge_and_save() (itself matching E02 Market Data's own
    fetch_ohlcv): never truncates older cached history outside this
    run's own real date range.

    Raw CSVs expected at data/raw/dukascopy/{instrument}_m5.csv
    (timestamp,open,high,low,close,volume -- epoch-ms timestamp), one per
    INSTRUMENTS entry below. Downloaded via:
      npx dukascopy-node -i {instrument} -from {date} -to now -t m5 -v \
          -f csv -dir data/raw/dukascopy -fn {instrument}_m5
Author: Shantanu Waykar
Version: 1.0.0
"""

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw" / "dukascopy"
PROCESSED_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"
NATIVE_TIMEFRAME = "5m"

RESAMPLE_RULES = {
    "15m": "15min",
    "1h": "1h",
    "4h": "4h",
    "1d": "1D",
}

# dukascopy instrument code -> this platform's yahoo_symbol (the parquet
# filename convention E02 Market Data / load_btc_data.py both already use).
INSTRUMENTS = {
    "eurusd": "EURUSD=X",
    "gbpusd": "GBPUSD=X",
    "usdjpy": "USDJPY=X",
    "xauusd": "GC=F",
    "xagusd": "SI=F",
    "ethusd": "ETH-USD",
    "aaplususd": "AAPL",
    "msftususd": "MSFT",
    "nvdaususd": "NVDA",
    "googlususd": "GOOGL",
    "amznususd": "AMZN",
    "tslaususd": "TSLA",
    "fbususd": "META",
    "jpmususd": "JPM",
}


def _load_one(instrument: str, yahoo_symbol: str) -> pd.DataFrame:
    path = RAW_DIR / f"{instrument}_m5.csv"
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)
    df = df.sort_values("timestamp").drop_duplicates(subset="timestamp", keep="first").reset_index(drop=True)
    df["symbol"] = yahoo_symbol
    df["timeframe"] = NATIVE_TIMEFRAME
    return df[["timestamp", "open", "high", "low", "close", "volume", "symbol", "timeframe"]]


def resample(df: pd.DataFrame, rule: str, timeframe_label: str, yahoo_symbol: str) -> pd.DataFrame:
    """Empty bins (real gaps -- weekends, market closed) are dropped, not
    forward-filled, so no fabricated price action enters the training set."""
    indexed = df.set_index("timestamp")
    agg = indexed.resample(rule).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    agg = agg.dropna(subset=["open", "high", "low", "close"])
    agg = agg.reset_index()
    agg["symbol"] = yahoo_symbol
    agg["timeframe"] = timeframe_label
    return agg


def _merge_and_save(frame: pd.DataFrame, path: Path) -> pd.DataFrame:
    """Never blind-overwrite -- see load_btc_data.py's own _merge_and_save
    for the real-bug precedent this mirrors (a blind overwrite once wiped
    a 22-year GOLD dataset down to a 60-day fetch window)."""
    if path.exists():
        try:
            existing = pd.read_parquet(path)
            combined = pd.concat([existing, frame], ignore_index=True)
            combined = combined.sort_values("timestamp").drop_duplicates(subset="timestamp", keep="last")
            frame = combined.reset_index(drop=True)
        except Exception as e:
            logger.warning("Could not merge with existing cache at %s (saving fresh build only): %s", path, e)
    frame.to_parquet(path, index=False)
    return frame


def build_one(instrument: str, yahoo_symbol: str, save: bool = True) -> dict[str, int]:
    path = RAW_DIR / f"{instrument}_m5.csv"
    if not path.exists():
        logger.warning("Skipping %s (%s): no CSV at %s", instrument, yahoo_symbol, path)
        return {}
    native = _load_one(instrument, yahoo_symbol)
    if native.empty:
        logger.warning("Skipping %s (%s): CSV has 0 real rows", instrument, yahoo_symbol)
        return {}

    datasets = {NATIVE_TIMEFRAME: native}
    for label, rule in RESAMPLE_RULES.items():
        datasets[label] = resample(native, rule, label, yahoo_symbol)

    counts = {}
    for label, frame in datasets.items():
        if save:
            out_path = PROCESSED_DIR / f"{yahoo_symbol}_{label}.parquet"
            saved = _merge_and_save(frame, out_path)
            counts[label] = len(saved)
        else:
            counts[label] = len(frame)
    return counts


def build_all(save: bool = True) -> dict[str, dict[str, int]]:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    results = {}
    for instrument, yahoo_symbol in INSTRUMENTS.items():
        logger.info("=== %s (%s) ===", instrument, yahoo_symbol)
        counts = build_one(instrument, yahoo_symbol, save=save)
        if counts:
            results[yahoo_symbol] = counts
            logger.info("  " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    results = build_all(save=True)
    print(f"\nBuilt {len(results)} instrument(s): {list(results.keys())}")
