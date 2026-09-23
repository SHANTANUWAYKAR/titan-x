"""
Module: import_eurusd_history.py
Description: Import the user-supplied EURUSD hourly history
    (data/database/URUSD - 1H - 2020-2024 September FOREX.zip, a
    MetaTrader5-format broker export) into a queryable parquet file --
    real value-add over this platform's existing live fetch chain.

    Verified live 2026-07-28: yfinance's EURUSD=X 1h interval only goes
    back to 2024-07-29 (its standard ~2-year intraday retention window),
    while this file covers 2020-01-02 through 2024-09, i.e. the ~4 years
    of hourly EURUSD history that live yfinance cannot currently serve at
    all. EURUSD is a platform-supported pair (core/config/assets.py) that
    the earlier GBPUSD/USDJPY import (import_forex_history.py) did not
    cover -- that source zip didn't contain EURUSD. This corrects an
    earlier pass that mistakenly flagged this file as redundant with the
    live-fetch chain without actually checking yfinance's real intraday
    depth first.

    Already hourly in the source file (no 1-minute aggregation needed,
    unlike import_forex_history.py's GBPUSD/USDJPY).
Author: Shantanu Waykar
Version: 1.0.0
"""

import logging
import zipfile
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

ZIP_PATH = Path(__file__).resolve().parents[2] / "data" / "database" / "URUSD - 1H - 2020-2024 September FOREX.zip"
MEMBER = "EURUSD_1H_2020-2024.csv"
OUTPUT_PATH = Path(__file__).resolve().parents[2] / "data" / "forex_history" / "EURUSD_1h.parquet"


def main() -> None:
    logger.info("Importing %s from %s...", MEMBER, ZIP_PATH.name)
    with zipfile.ZipFile(ZIP_PATH) as zf:
        with zf.open(MEMBER) as f:
            df = pd.read_csv(f)

    df["time"] = pd.to_datetime(df["time"], format="%Y-%m-%d %H:%M:%S", errors="coerce")
    before = len(df)
    df = df.dropna(subset=["time"])
    if len(df) != before:
        logger.warning("  dropped %d rows with unparseable time", before - len(df))

    df = df.rename(columns={"time": "datetime"}).set_index("datetime").sort_index()

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUTPUT_PATH)
    logger.info("EURUSD: %d hourly bars, %s to %s -> %s (%.1f MB)",
                len(df), df.index.min(), df.index.max(), OUTPUT_PATH, OUTPUT_PATH.stat().st_size / 1e6)


if __name__ == "__main__":
    main()
