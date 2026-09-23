"""
Module: dedupe_daily_bars.py
Description: One-time repair for a real data-corruption bug found while
    scoping the multi-batch dataset import: several daily-timeframe
    parquet files under data/processed/ ended up with TWO rows per
    calendar day, because two different source vendors stamped their
    end-of-day bar at a different hour (e.g. 00:00 UTC vs 04:00 UTC) --
    the exact-timestamp dedup used by both the import scripts and
    e02_market_data.fetch_ohlcv's cache merge never collides on these,
    since the timestamps genuinely differ, even though they represent
    the same trading day.

    Confirmed scope (data/processed/*_1d.parquet):
      - SI=F, CL=F: ~50% of rows are exact-value duplicates (same OHLC,
        just double-stamped) -- these silently insert a fake zero-return
        bar between every real one, which would corrupt any volatility/
        return-based calibration (HMM regime fitting, Sharpe calc,
        threshold tuning).
      - GBPUSD=X: ~29% of rows are duplicate calendar days with
        GENUINELY DIFFERENT vendor prices (not just re-stamped) -- two
        real, disagreeing EOD quotes for the same day.
      - ^NSEI, ^NSEBANK: minor (~0.4%), same root cause.

    Resolution: collapse to one row per calendar day. Prefer the row
    with non-null dividends/stock_splits columns (yfinance's own native
    export -- this platform's designated PRIMARY source per
    e02_market_data's fallback ordering) when both exist for a day;
    otherwise keep whichever single row is present. This is an
    architectural consistency choice (defer to the source the LIVE
    engine already treats as authoritative), not a guessed data value.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-07-18
"""

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)
PROCESSED_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"


def dedupe_file(path: Path) -> dict:
    df = pd.read_parquet(path)
    before = len(df)
    date_key = df["timestamp"].dt.date
    dupe_days = date_key.duplicated().sum()
    if dupe_days == 0:
        return {"file": path.name, "before": before, "after": before, "removed": 0}

    df = df.assign(_date=date_key)
    if "dividends" in df.columns:
        # Non-null dividends/stock_splits marks a genuine yfinance-native
        # row -- prefer it. sort so those rows sort LAST, then
        # drop_duplicates(keep="last") keeps them over a same-day row
        # from an imported CSV without those columns.
        df = df.assign(_is_native=df["dividends"].notna())
        df = df.sort_values(["_date", "_is_native"], kind="stable")
        df = df.drop_duplicates(subset="_date", keep="last")
        df = df.drop(columns=["_is_native"])
    else:
        df = df.drop_duplicates(subset="_date", keep="first")
    df = df.drop(columns=["_date"]).sort_values("timestamp").reset_index(drop=True)

    df.to_parquet(path, index=False)
    after = len(df)
    return {"file": path.name, "before": before, "after": after, "removed": before - after}


def main() -> list[dict]:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    results = []
    for path in sorted(PROCESSED_DIR.glob("*_1d.parquet")):
        result = dedupe_file(path)
        if result["removed"] > 0:
            logger.info("%s: %d -> %d rows (removed %d duplicate-day rows)",
                        result["file"], result["before"], result["after"], result["removed"])
        results.append(result)
    return results


if __name__ == "__main__":
    main()
