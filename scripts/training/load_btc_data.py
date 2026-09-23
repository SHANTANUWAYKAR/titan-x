"""
Module: load_btc_data.py
Description: Build the canonical BTC-USD 5-minute OHLCV dataset, plus
    resampled higher timeframes, following the same
    `data/processed/{symbol}_{timeframe}.parquet` convention E02 Market Data
    already uses so the rest of the codebase can load it the same way.

    Two real sources, tried in order:
    1. User-supplied Binance BTC/USD(C) 5-minute kline CSVs
       (~/Downloads/BTC/BTCUSD*-5m-*.csv), when present. BTCUSD and
       BTCUSDC files cover non-overlapping month ranges (Binance switched
       which quote asset it exported over time) -- USDC is a USD-pegged
       stablecoin, so treating BTCUSDC bars as a BTC-USD price proxy is the
       standard simplification.
    2. Fallback (added 2026-08-20, this machine no longer has the Binance
       CSVs locally): Dukascopy's own BTC/USD 5-minute bid-price history
       (data/raw/dukascopy/BTCUSD_m5_dukascopy.csv, downloaded via
       `npx dukascopy-node -i btcusd -t m5`), which starts 2017-05-07 (vs.
       Binance's later start) and is Dukascopy's own CFD/spot BTC/USD
       quote, not Binance's -- a genuinely different real venue, so prices
       can differ slightly from a true Binance series even though both are
       real. Whichever source is used is logged explicitly; never silently
       substituted without saying so.

    Both tagged symbol="BTC-USD" (E02's yahoo_symbol for BTCUSD) so this
    feeds straight into the same training/backtesting path as any other
    fetched asset.
Author: Shantanu Waykar
Version: 1.0.0
"""

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

RAW_CSV_DIR = Path.home() / "Downloads" / "BTC"
DUKASCOPY_CSV_PATH = Path(__file__).resolve().parents[2] / "data" / "raw" / "dukascopy" / "BTCUSD_m5_dukascopy.csv"
PROCESSED_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"
CANONICAL_SYMBOL = "BTC-USD"
NATIVE_TIMEFRAME = "5m"

RESAMPLE_RULES = {
    "15m": "15min",
    "1h": "1h",
    "4h": "4h",
    "1d": "1D",
}

KLINE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "count",
    "taker_buy_base_volume", "taker_buy_quote_volume",
]


def _load_one_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, header=0, names=KLINE_COLUMNS)
    df["timestamp"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)
    return df[["timestamp", "open", "high", "low", "close", "volume"]]


def load_merged_5m() -> pd.DataFrame:
    """Load and merge every BTCUSD*/BTCUSDC*-5m-*.csv file into one
    chronologically sorted, deduplicated OHLCV DataFrame."""
    csv_paths = sorted(RAW_CSV_DIR.glob("BTCUSD*-5m-*.csv"))
    if not csv_paths:
        raise FileNotFoundError(f"No BTC 5m CSVs found under {RAW_CSV_DIR}")

    frames = [_load_one_csv(p) for p in csv_paths]
    merged = pd.concat(frames, ignore_index=True)
    merged = merged.sort_values("timestamp").drop_duplicates(subset="timestamp", keep="first")
    merged = merged.reset_index(drop=True)
    merged["symbol"] = CANONICAL_SYMBOL
    merged["timeframe"] = NATIVE_TIMEFRAME
    return merged


def load_dukascopy_5m() -> pd.DataFrame:
    """Fallback native-5m source: Dukascopy's own timestamp,open,high,low,
    close,volume CSV (epoch-ms timestamp), a much simpler schema than
    Binance's 11-column kline export."""
    if not DUKASCOPY_CSV_PATH.exists():
        raise FileNotFoundError(f"No Dukascopy BTC/USD 5m CSV found at {DUKASCOPY_CSV_PATH}")
    df = pd.read_csv(DUKASCOPY_CSV_PATH)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)
    df = df.sort_values("timestamp").drop_duplicates(subset="timestamp", keep="first").reset_index(drop=True)
    df["symbol"] = CANONICAL_SYMBOL
    df["timeframe"] = NATIVE_TIMEFRAME
    return df[["timestamp", "open", "high", "low", "close", "volume", "symbol", "timeframe"]]


def load_native_5m() -> pd.DataFrame:
    """Binance user-supplied CSVs first (established methodology, kept
    whenever present); Dukascopy only as a fallback when they're not on
    this machine. Always logs which real source was actually used."""
    try:
        native = load_merged_5m()
        logger.info("Loaded native 5m BTC-USD from Binance CSVs under %s (%d rows)", RAW_CSV_DIR, len(native))
        return native
    except FileNotFoundError:
        logger.warning("No Binance CSVs under %s -- falling back to Dukascopy 5m history", RAW_CSV_DIR)
        native = load_dukascopy_5m()
        logger.info("Loaded native 5m BTC-USD from Dukascopy CSV (%d rows)", len(native))
        return native


def resample(df: pd.DataFrame, rule: str, timeframe_label: str) -> pd.DataFrame:
    """Resample 5m OHLCV bars up to a coarser timeframe (open=first,
    high=max, low=min, close=last, volume=sum). Empty bins (real gaps in
    the source data) are dropped rather than forward-filled, so no
    fabricated price action ever enters the training set."""
    indexed = df.set_index("timestamp")
    agg = indexed.resample(rule).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    agg = agg.dropna(subset=["open", "high", "low", "close"])
    agg = agg.reset_index()
    agg["symbol"] = CANONICAL_SYMBOL
    agg["timeframe"] = timeframe_label
    return agg


def _merge_and_save(frame: pd.DataFrame, path: Path) -> pd.DataFrame:
    """Merge with whatever's already cached at `path`, never blind-overwrite
    -- same discipline as E02 Market Data's own fetch_ohlcv (see its
    docstring: a blind overwrite there once wiped a 22-year, 6.79M-row
    imported GOLD dataset down to a ~60-day fetch window). This dataset's
    real native range only starts where Dukascopy/Binance data starts
    (2017-05-07 for the Dukascopy fallback); any older cached history
    (e.g. BTC-USD_1d.parquet's yfinance-sourced rows back to 2010) must
    survive untouched, not get truncated to this script's own range. New
    rows win on exact overlapping timestamps; everything else is kept."""
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


def build_all(save: bool = True) -> dict[str, pd.DataFrame]:
    """Build the native 5m series plus every resampled timeframe, merging
    into data/processed/BTC-USD_{timeframe}.parquet (never overwriting
    older cached history outside this run's own real date range)."""
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    native = load_native_5m()

    datasets = {NATIVE_TIMEFRAME: native}
    for label, rule in RESAMPLE_RULES.items():
        datasets[label] = resample(native, rule, label)

    if save:
        for label, frame in datasets.items():
            path = PROCESSED_DIR / f"{CANONICAL_SYMBOL}_{label}.parquet"
            saved = _merge_and_save(frame, path)
            datasets[label] = saved
            logger.info("Saved %s (%d rows total after merge) -> %s", label, len(saved), path)

    return datasets


def summarize(datasets: dict[str, pd.DataFrame]) -> str:
    lines = ["BTC-USD historical data summary:"]
    for label, frame in datasets.items():
        if frame.empty:
            lines.append(f"  {label:>4}: EMPTY")
            continue
        start, end = frame["timestamp"].iloc[0], frame["timestamp"].iloc[-1]
        lines.append(f"  {label:>4}: {len(frame):>7} bars   {start.date()} -> {end.date()}")
    return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    data = build_all(save=True)
    print(summarize(data))
