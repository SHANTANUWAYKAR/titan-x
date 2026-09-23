"""
Module: import_news_archive.py
Description: Import the user-supplied historical news archive
    (data/database/NEWS.zip -- raw_analyst_ratings.csv + raw_partner_
    headlines.csv, both real Benzinga-sourced headline/publisher/date/
    ticker records) into a single queryable parquet file, the same
    pattern already used for the economic calendar history
    (data/macro/economic_calendar_history.parquet).

    E03 News Intelligence is currently LIVE-ONLY (RSS feeds, no
    historical archive at all) -- this is genuinely new capability, not
    a duplicate of anything already fetched live. Deliberately does NOT
    import analyst_ratings_processed.csv: spot-checked against
    raw_analyst_ratings.csv and confirmed to be the same underlying
    records with url/publisher stripped out -- a strict subset, importing
    both would double-count every row.

    This script only IMPORTS the data (parallel to import_economic_
    calendar.py's existing role for the calendar dataset) -- it does not
    wire a query method into e03_news/engine.py yet, since that requires
    a design decision (a new method there, or a separate historical-
    lookup helper) better made with this data actually loaded and
    inspected first.
Author: Shantanu Waykar
Version: 1.0.0
"""

import logging
import zipfile
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

ZIP_PATH = Path(__file__).resolve().parents[2] / "data" / "database" / "NEWS.zip"
OUTPUT_PATH = Path(__file__).resolve().parents[2] / "data" / "news" / "news_archive.parquet"


def _load_csv_from_zip(member: str, columns: list[str]) -> pd.DataFrame:
    with zipfile.ZipFile(ZIP_PATH) as zf:
        with zf.open(member) as f:
            df = pd.read_csv(f, index_col=0)
    df = df.rename(columns={c: c.lower() for c in df.columns})
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise ValueError(f"{member}: expected columns {columns}, missing {missing} (found {list(df.columns)})")
    return df[columns]


def main() -> None:
    logger.info("Loading raw_analyst_ratings.csv...")
    ratings = _load_csv_from_zip("raw_analyst_ratings.csv", ["headline", "url", "publisher", "date", "stock"])
    ratings["source"] = "analyst_ratings"
    logger.info("  %d rows", len(ratings))

    logger.info("Loading raw_partner_headlines.csv...")
    headlines = _load_csv_from_zip("raw_partner_headlines.csv", ["headline", "url", "publisher", "date", "stock"])
    headlines["source"] = "partner_headlines"
    logger.info("  %d rows", len(headlines))

    combined = pd.concat([ratings, headlines], ignore_index=True)
    # Real bug found 2026-07-28: this column mixes timezone-aware timestamps
    # ("2020-06-05 10:30:54-04:00") with timezone-naive ones at midnight
    # ("2020-05-22 00:00:00") in the SAME column. Without format="mixed",
    # pandas' format auto-inference gets confused by the inconsistency and
    # silently coerces ~98% of rows to NaT even though every individual
    # value is perfectly parseable on its own -- verified by parsing a
    # sample with and without format="mixed" (0 nulls vs thousands).
    combined["date"] = pd.to_datetime(combined["date"], errors="coerce", utc=True, format="mixed")
    before = len(combined)
    combined = combined.dropna(subset=["date", "headline", "stock"])
    if len(combined) != before:
        logger.warning("Dropped %d rows with unparseable date/missing headline/stock", before - len(combined))

    logger.info("Combined: %d total rows, %d distinct tickers, date range %s to %s",
                len(combined), combined["stock"].nunique(), combined["date"].min(), combined["date"].max())

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(OUTPUT_PATH, index=False)
    logger.info("Saved to %s (%.1f MB)", OUTPUT_PATH, OUTPUT_PATH.stat().st_size / 1e6)


if __name__ == "__main__":
    main()
