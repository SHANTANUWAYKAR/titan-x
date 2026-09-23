"""
Module: import_xauusd_history.py
Description: Import the user-supplied deep intraday XAUUSD history
    (data/database/XAUUSD Gold Price Historical Data (2004-2026).zip)
    into queryable parquet files -- real value-add over this platform's
    existing live fetch chain (yfinance's free intraday history is only
    days/weeks deep, not the 2004-2026 range this dataset covers), giving
    E26/E27 real intraday backtesting depth for GOLD that wasn't
    previously possible.

    Deliberately imports only 1h/4h/1d/1w/1Month (all under ~13MB each) --
    NOT the 1m (348MB) or 5m/15m/30m (25-75MB) files. This platform's
    actual signal generation is daily-bar-oriented (see e51_signals'
    BTC-USD_1d_strategy_override.json precedent); importing multi-hundred-
    MB minute-level history with no current consumer for it would be
    speculative bulk, not a real, used capability -- exactly the kind of
    unjustified scope this project's own discipline (e16_commodity's
    copper/nat-gas exclusion, e17_crypto's on-chain-data honest gap) says
    to avoid. The finer timeframes remain in the original zip if a future,
    concretely-scoped need for them ever arises.
Author: Shantanu Waykar
Version: 1.0.0
"""

import logging
import zipfile
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

ZIP_PATH = Path(__file__).resolve().parents[2] / "data" / "database" / "XAUUSD Gold Price Historical Data (2004-2026).zip"
OUTPUT_DIR = Path(__file__).resolve().parents[2] / "data" / "commodity_history"

TIMEFRAMES = {
    "XAU_1h_data.csv": "1h",
    "XAU_4h_data.csv": "4h",
    "XAU_1d_data.csv": "1d",
    "XAU_1w_data.csv": "1w",
    "XAU_1Month_data.csv": "1M",
}


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ZIP_PATH) as zf:
        for member, tf in TIMEFRAMES.items():
            logger.info("Importing %s (%s)...", member, tf)
            with zf.open(member) as f:
                df = pd.read_csv(f, sep=";")
            df["Date"] = pd.to_datetime(df["Date"], format="%Y.%m.%d %H:%M", errors="coerce")
            before = len(df)
            df = df.dropna(subset=["Date"])
            if len(df) != before:
                logger.warning("  dropped %d rows with unparseable date", before - len(df))
            df = df.sort_values("Date").reset_index(drop=True)
            out_path = OUTPUT_DIR / f"XAUUSD_{tf}.parquet"
            df.to_parquet(out_path, index=False)
            logger.info("  %d rows, %s to %s -> %s (%.1f MB)",
                        len(df), df["Date"].min(), df["Date"].max(), out_path, out_path.stat().st_size / 1e6)


if __name__ == "__main__":
    main()
