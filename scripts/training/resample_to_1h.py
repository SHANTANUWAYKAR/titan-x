"""
Module: resample_to_1h.py
Description: Resample the deep 1-minute imported history (GBPUSD=X,
    USDJPY=X, SI=F -- see import_second_batch.py, 2001-2023 real MT-tick
    data) into 1h bars and save as data/processed/{symbol}_1h.parquet,
    merging with whatever 1h cache already exists there. This unlocks
    real historical coverage for train_e05_event_calibration.py (which
    only reads local 1h caches, not 1m -- resampling on the fly every
    run would be wasteful for a 4-8 million-row file) and any other
    training script that wants hourly granularity for these 3 assets
    without paying yfinance's ~730-day live-fetch cap.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-07-18
"""

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)
PROCESSED_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"

SYMBOLS = ["GBPUSD=X", "USDJPY=X", "SI=F"]


def resample_one(symbol: str) -> dict:
    src = PROCESSED_DIR / f"{symbol}_1m.parquet"
    if not src.exists():
        return {"symbol": symbol, "skipped": f"{src.name} not found"}

    df = pd.read_parquet(src)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    indexed = df.set_index("timestamp").sort_index()
    hourly = indexed[["open", "high", "low", "close", "volume"]].resample("1h").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna(subset=["open", "high", "low", "close"])
    hourly = hourly.reset_index()
    hourly["symbol"] = symbol
    hourly["timeframe"] = "1h"

    dest = PROCESSED_DIR / f"{symbol}_1h.parquet"
    if dest.exists():
        existing = pd.read_parquet(dest)
        existing["timestamp"] = pd.to_datetime(existing["timestamp"], utc=True)
        combined = pd.concat([existing, hourly], ignore_index=True)
        combined = combined.sort_values("timestamp").drop_duplicates(subset="timestamp", keep="last")
    else:
        combined = hourly.sort_values("timestamp")
    combined = combined.reset_index(drop=True)
    combined.to_parquet(dest, index=False)

    return {
        "symbol": symbol, "source_rows": len(df), "resampled_rows": len(hourly),
        "final_rows": len(combined),
        "final_range": [str(combined["timestamp"].iloc[0]), str(combined["timestamp"].iloc[-1])],
    }


def main() -> list[dict]:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    results = [resample_one(s) for s in SYMBOLS]
    for r in results:
        logger.info("%s", r)
    return results


if __name__ == "__main__":
    main()
