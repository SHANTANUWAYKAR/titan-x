"""
Module: import_forex_history.py
Description: Import the user-supplied deep 1-minute forex history
    (data/database/Historical Forex Data.zip -- 16 pairs, 6.6GB
    uncompressed) into hourly OHLCV parquet files -- but ONLY for the two
    pairs this platform actually trades (core/config/assets.py:
    GBPUSD, USDJPY). EURUSD isn't even present in this particular
    dataset; USDINR isn't a major pair covered here either. The other 14
    pairs in the zip (AUDJPY, AUDUSD, CHFJPY, EURCAD, EURCHF, EURGBP,
    EURJPY, GBPCHF, GBPJPY, NZDJPY, NZDUSD, USDCAD, USDCHF, XAGUSD) are
    not tradable instruments on this platform -- importing them would be
    speculative bulk with no real consumer, the same scope discipline
    e16_commodity/e17_crypto already established for untradeable assets.

    Aggregates 1-minute bars to hourly (real intraday depth this
    platform's live yfinance fetch chain cannot provide -- free intraday
    history there is only days/weeks deep) rather than keeping raw
    minute-level ticks: this platform's actual signal generation is
    hourly/daily-bar-oriented, so minute-level granularity would be
    unused bulk, not a real capability gain. Raw minute data remains in
    the original zip if a genuinely scoped need for it ever arises.

    Reads each ~430MB source file in chunks (not a single
    pandas.read_csv over the whole file) to keep memory bounded while a
    separate, resource-heavy book-ingestion job may be running
    concurrently on this machine.
Author: Shantanu Waykar
Version: 1.0.0
"""

import logging
import zipfile
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

ZIP_PATH = Path(__file__).resolve().parents[2] / "data" / "database" / "Historical Forex Data.zip"
OUTPUT_DIR = Path(__file__).resolve().parents[2] / "data" / "forex_history"

# Only pairs this platform actually trades (core/config/assets.py) --
# see module docstring for why the other 14 in the zip are skipped.
PAIRS = {"GBPUSD": "Foerex Pairs/GBPUSD.txt", "USDJPY": "Foerex Pairs/USDJPY.txt"}
CHUNK_SIZE = 2_000_000  # rows per chunk -- bounds memory for a ~430MB/~10M-row file


def _aggregate_to_hourly(zip_member: str) -> pd.DataFrame:
    """Streams the raw 1-minute file in chunks, resampling each chunk to
    hourly OHLCV and accumulating -- avoids ever holding the full ~10M-row
    minute-level file in memory at once."""
    hourly_chunks = []
    with zipfile.ZipFile(ZIP_PATH) as zf:
        with zf.open(zip_member) as f:
            reader = pd.read_csv(
                f, chunksize=CHUNK_SIZE,
                names=["ticker", "date", "time", "open", "high", "low", "close", "volume"],
                header=0,
            )
            for i, chunk in enumerate(reader):
                chunk["datetime"] = pd.to_datetime(chunk["date"].astype(str) + chunk["time"].astype(str).str.zfill(6), format="%Y%m%d%H%M%S")
                chunk = chunk.set_index("datetime")
                hourly = chunk.resample("1h").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
                hourly = hourly.dropna(subset=["open"])
                hourly_chunks.append(hourly)
                logger.info("  chunk %d: %d minute-rows -> %d hourly bars so far this chunk", i + 1, len(chunk), len(hourly))

    # Chunk boundaries can split a single hour across two chunks -- re-
    # aggregate the concatenated hourly pieces once more to merge those.
    combined = pd.concat(hourly_chunks)
    combined = combined.groupby(combined.index).agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    return combined.sort_index()


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for pair, member in PAIRS.items():
        logger.info("Importing %s from %s (streaming, 1min -> 1h)...", pair, member)
        hourly = _aggregate_to_hourly(member)
        out_path = OUTPUT_DIR / f"{pair}_1h.parquet"
        hourly.to_parquet(out_path)
        logger.info("%s: %d hourly bars, %s to %s -> %s (%.1f MB)",
                    pair, len(hourly), hourly.index.min(), hourly.index.max(), out_path, out_path.stat().st_size / 1e6)


if __name__ == "__main__":
    main()
