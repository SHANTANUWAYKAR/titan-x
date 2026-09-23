"""
Module: import_downloaded_datasets.py
Description: Merge user-downloaded historical OHLCV datasets (MT4/5-style
    broker exports for GOLD across 9 timeframes 2004-2026, EURUSD hourly
    2020-2024) into data/processed/{yahoo_symbol}_{timeframe}.parquet --
    the SAME convention E02 Market Data's own fetch-cache and every
    training script (train_e08_regime.py, train_e51_thresholds.py, etc.)
    already read from. Same merge philosophy as load_btc_data.py: real
    gaps are never fabricated/forward-filled.

    Where a parquet file already exists (auto-cached from a live yfinance
    fetch earlier this session), the EXISTING data wins on any exact
    overlapping timestamp -- it's what every backtest/signal this session
    has already been validated against -- while the newly imported data
    extends real history further back (and, for intraday timeframes,
    often deeper than yfinance's free-tier lookback window allows at all).
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-07-18
"""

import logging
import zipfile
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

DOWNLOADS_DIR = Path.home() / "Downloads"
PROCESSED_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"

GOLD_ZIP = DOWNLOADS_DIR / "XAUUSD Gold Price Historical Data (2004-2026).zip"
GOLD_SYMBOL = "GC=F"
GOLD_TIMEFRAME_MAP = {
    "XAU_1m_data.csv": "1m",
    "XAU_5m_data.csv": "5m",
    "XAU_15m_data.csv": "15m",
    "XAU_30m_data.csv": "30m",
    "XAU_1h_data.csv": "1h",
    "XAU_4h_data.csv": "4h",
    "XAU_1d_data.csv": "1d",
    "XAU_1w_data.csv": "1w",
    "XAU_1Month_data.csv": "1mo",
}

EURUSD_ZIP = DOWNLOADS_DIR / "URUSD - 1H - 2020-2024 September FOREX.zip"
EURUSD_SYMBOL = "EURUSD=X"
EURUSD_CSV_NAME = "EURUSD_1H_2020-2024.csv"
EURUSD_TIMEFRAME = "1h"


def _parse_mt_csv(raw: bytes) -> pd.DataFrame:
    """MT4/5-style export: semicolon-delimited, Date;Open;High;Low;Close;Volume,
    date format YYYY.MM.DD HH:MM."""
    import io

    df = pd.read_csv(io.BytesIO(raw), sep=";")
    df["timestamp"] = pd.to_datetime(df["Date"], format="%Y.%m.%d %H:%M", utc=True)
    df = df.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)
    return df[["timestamp", "open", "high", "low", "close", "volume"]]


def _parse_eurusd_csv(raw: bytes) -> pd.DataFrame:
    """MetaTrader tick-export style: comma-delimited, time,open,high,low,
    close,tick_volume,spread,real_volume."""
    import io

    df = pd.read_csv(io.BytesIO(raw))
    df["timestamp"] = pd.to_datetime(df["time"], utc=True)
    df = df.rename(columns={"tick_volume": "volume"})
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)
    return df[["timestamp", "open", "high", "low", "close", "volume"]]


def _merge_and_save(new_df: pd.DataFrame, symbol: str, timeframe: str) -> dict:
    """Concatenate with any existing cached parquet for this exact
    symbol+timeframe; existing data wins on overlapping timestamps
    (already validated against this session's live work), new data
    extends real range. No fabricated bars, no forward-fill."""
    new_df = new_df.dropna(subset=["open", "high", "low", "close"]).sort_values("timestamp")
    new_df = new_df.drop_duplicates(subset="timestamp", keep="first")
    new_df["symbol"] = symbol
    new_df["timeframe"] = timeframe

    path = PROCESSED_DIR / f"{symbol}_{timeframe}.parquet"
    new_start, new_end = new_df["timestamp"].iloc[0], new_df["timestamp"].iloc[-1]

    if path.exists():
        existing = pd.read_parquet(path)
        # existing second in the concat + keep="last" below means existing
        # wins on any exact-timestamp overlap.
        combined = pd.concat([new_df, existing], ignore_index=True)
        combined = combined.sort_values("timestamp").drop_duplicates(subset="timestamp", keep="last")
        combined = combined.reset_index(drop=True)
    else:
        combined = new_df.reset_index(drop=True)

    combined.to_parquet(path, index=False)
    return {
        "symbol": symbol, "timeframe": timeframe, "path": str(path),
        "imported_bars": len(new_df), "imported_range": [str(new_start.date()), str(new_end.date())],
        "final_bars": len(combined),
        "final_range": [str(combined["timestamp"].iloc[0].date()), str(combined["timestamp"].iloc[-1].date())],
    }


def import_gold() -> list[dict]:
    if not GOLD_ZIP.exists():
        raise FileNotFoundError(f"Not found: {GOLD_ZIP}")
    results = []
    with zipfile.ZipFile(GOLD_ZIP) as zf:
        for csv_name, timeframe in GOLD_TIMEFRAME_MAP.items():
            raw = zf.read(csv_name)
            df = _parse_mt_csv(raw)
            result = _merge_and_save(df, GOLD_SYMBOL, timeframe)
            results.append(result)
            logger.info(
                "GOLD %-4s: imported %d bars (%s -> %s), file now %d bars (%s -> %s)",
                timeframe, result["imported_bars"], *result["imported_range"],
                result["final_bars"], *result["final_range"],
            )
    return results


def import_eurusd() -> dict:
    if not EURUSD_ZIP.exists():
        raise FileNotFoundError(f"Not found: {EURUSD_ZIP}")
    with zipfile.ZipFile(EURUSD_ZIP) as zf:
        raw = zf.read(EURUSD_CSV_NAME)
    df = _parse_eurusd_csv(raw)
    result = _merge_and_save(df, EURUSD_SYMBOL, EURUSD_TIMEFRAME)
    logger.info(
        "EURUSD %-4s: imported %d bars (%s -> %s), file now %d bars (%s -> %s)",
        EURUSD_TIMEFRAME, result["imported_bars"], *result["imported_range"],
        result["final_bars"], *result["final_range"],
    )
    return result


def main() -> dict:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    gold_results = import_gold()
    eurusd_result = import_eurusd()
    return {"gold": gold_results, "eurusd": eurusd_result}


if __name__ == "__main__":
    main()
