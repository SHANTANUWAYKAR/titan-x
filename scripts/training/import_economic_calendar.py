"""
Module: import_economic_calendar.py
Description: Import the real historical economic-calendar dataset
    ("Economic calendar Invest Forex.zip", 2011-2021, ~91k rows across
    D2011-13.csv/D2014-18.csv/D2019-21.csv) into a single clean parquet
    at data/macro/economic_calendar_history.parquet.

    This is REAL, PUBLISHED historical release data (country, event name,
    impact level, actual/forecast/previous values, exact release
    timestamp) -- not a live/current feed. It fills a real gap: E05
    (e05_economic_calendar/engine.py) only calibrates volatility around
    US Non-Farm Payrolls because that's the only event type with a
    published, DETERMINISTIC future-date rule (first Friday of the
    month); every other event type (CPI, FOMC, GDP, central bank rate
    decisions...) was left uncalibrated because there was no real
    historical release-date data to calibrate against, and Rule 4
    forbids guessing those dates from memory. This dataset provides the
    real dates -- see train_e05_event_calibration.py for what it's used
    for. It does NOT solve the separate "what's the CURRENT/FUTURE
    schedule" problem (the dataset ends in 2021), so it does not, by
    itself, let E05 forecast upcoming non-NFP events live.

    Source times are in US Eastern time (verified: Nonfarm Payrolls rows
    consistently show 8:30:00, the real BLS release time; Fed Interest
    Rate Decision rows show 14:00:00, the real FOMC statement time) --
    converted to UTC on import.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-07-18
"""

import html
import io
import logging
import zipfile
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

logger = logging.getLogger(__name__)

DOWNLOADS_DIR = Path.home() / "Downloads"
ZIP_PATH = DOWNLOADS_DIR / "Economic calendar Invest Forex.zip"
OUTPUT_PATH = Path(__file__).resolve().parents[2] / "data" / "macro" / "economic_calendar_history.parquet"
CSV_FILES = ["D2011-13.csv", "D2014-18.csv", "D2019-21.csv"]
_ET = ZoneInfo("America/New_York")

COLUMNS = ["date", "time", "country", "impact", "event", "surprise", "unit", "actual", "forecast", "previous"]


def _parse_one(raw: bytes) -> pd.DataFrame:
    # D2011-13.csv is comma-delimited with quoted fields; D2014-18.csv and
    # D2019-21.csv are semicolon-delimited, unquoted -- detect per file
    # rather than assuming one format for all three.
    first_line = raw.split(b"\n", 1)[0]
    sep = ";" if first_line.count(b";") >= 5 else ","
    df = pd.read_csv(
        io.BytesIO(raw), sep=sep, header=None, names=COLUMNS,
        encoding="utf-8", on_bad_lines="warn",
    )
    for c in ("country", "impact", "event", "surprise", "unit", "previous"):
        df[c] = df[c].astype(str).str.strip().map(html.unescape)

    naive_et = pd.to_datetime(df["date"].str.strip() + " " + df["time"].str.strip(), format="%Y/%m/%d %H:%M:%S")
    df["timestamp"] = naive_et.dt.tz_localize(_ET, ambiguous="NaT", nonexistent="NaT").dt.tz_convert("UTC")
    df["actual"] = pd.to_numeric(df["actual"], errors="coerce")
    df["forecast"] = pd.to_numeric(df["forecast"], errors="coerce")
    return df.dropna(subset=["timestamp"])[
        ["timestamp", "country", "impact", "event", "surprise", "unit", "actual", "forecast", "previous"]
    ]


def import_calendar() -> dict:
    if not ZIP_PATH.exists():
        return {"error": f"not found: {ZIP_PATH}"}

    frames = []
    with zipfile.ZipFile(ZIP_PATH) as zf:
        for name in CSV_FILES:
            try:
                raw = zf.read(name)
            except KeyError:
                logger.warning("%s not in zip, skipping", name)
                continue
            frame = _parse_one(raw)
            frames.append(frame)
            logger.info("%s: %d rows parsed", name, len(frame))

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(subset=["timestamp", "country", "event"]).sort_values("timestamp")
    combined = combined.reset_index(drop=True)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(OUTPUT_PATH, index=False)

    result = {
        "rows": len(combined),
        "date_range": [str(combined["timestamp"].min()), str(combined["timestamp"].max())],
        "countries": int(combined["country"].nunique()),
        "event_types": int(combined["event"].nunique()),
        "saved_to": str(OUTPUT_PATH),
    }
    logger.info("Saved combined economic calendar history: %s", result)
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    import_calendar()
