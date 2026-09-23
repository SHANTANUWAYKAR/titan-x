"""
Module: train_e05_event_calibration.py
Description: Extend Engine 05's volatility calibration beyond US Non-Farm
    Payrolls (the only event with a deterministic FUTURE-date rule) to a
    curated set of high-impact recurring event TYPES, using their REAL
    historical release timestamps from the imported Investing.com-style
    calendar (see import_economic_calendar.py, data/macro/
    economic_calendar_history.parquet, 2011-2021, 110,971 rows).

    Same methodology as train_e05_economic_calendar.py's NFP calibration:
    for every historical occurrence of an event type, measure the
    realized absolute log return over a [-1h, +3h] window around the
    release for each platform asset with hourly (or daily, for assets
    without deep hourly history) price data, and compare against a
    baseline of equivalent-length windows across that asset's history.

    IMPORTANT SCOPE LIMIT: this dataset ends 2021-04 and gives no rule
    for predicting the NEXT occurrence of a non-deterministic event
    (Fed/ECB/BoE/BoJ decisions, CPI, PMI... none of these follow a fixed
    calendar day the way NFP does). So this calibration is saved into
    the SAME file as NFP's (data/models/e05_economic_calendar/
    volatility_calibration.json) but is NOT wired into
    EconomicCalendarEngine._recurring_events / upcoming_events() --
    there is no live/future date source for any of these event types.
    It's real, honest, ready-to-use calibration for the day a live
    calendar feed or published schedule is added for one of these events
    (see engine.py's register_recurring_event) -- not a claim that E05
    can forecast these live today.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-07-18
"""

import json
import logging
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from project_titan_x.core.config.assets import SUPPORTED_ASSETS

logger = logging.getLogger(__name__)

PROCESSED_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"
CALENDAR_PATH = Path(__file__).resolve().parents[2] / "data" / "macro" / "economic_calendar_history.parquet"
CALIBRATION_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "e05_economic_calendar" / "volatility_calibration.json"

WINDOW_BEFORE = timedelta(hours=1)
WINDOW_AFTER = timedelta(hours=3)
WINDOW_LEN = WINDOW_BEFORE + WINDOW_AFTER
LIVE_FETCH_PERIOD = "730d"
MIN_SAMPLES = 6

# (country, event name) -> engine-facing event key. Curated for real
# relevance to this platform's actual asset roster (forex/crypto/gold/
# silver/crude/Indian F&O), each with >= 75 real historical occurrences
# in the 2011-2021 dataset.
TARGET_EVENTS: dict[tuple[str, str], str] = {
    ("United States", "Fed Interest Rate Decision"): "US Fed Interest Rate Decision",
    ("United States", "Core CPI"): "US Core CPI",
    ("United States", "ISM Manufacturing PMI"): "US ISM Manufacturing PMI",
    ("United States", "Crude Oil Inventories"): "US Crude Oil Inventories",
    ("Euro Zone", "ECB Interest Rate Decision"): "ECB Interest Rate Decision",
    ("United Kingdom", "BoE Interest Rate Decision"): "BoE Interest Rate Decision",
    ("Japan", "BoJ Monetary Policy Statement"): "BoJ Monetary Policy Statement",
    ("India", "Interest Rate Decision"): "India Interest Rate Decision",
}


def _realized_move(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> float:
    window = df[(df["timestamp"] >= start) & (df["timestamp"] <= end)]
    if len(window) < 2:
        return float("nan")
    return abs(np.log(window["close"].iloc[-1] / window["close"].iloc[0]))


def _load_price_history(symbol_key: str, yahoo_symbol: str) -> tuple[pd.DataFrame, str]:
    """Prefer real deep local 1h cache; fall back to a live 730d fetch
    (yfinance's practical hourly-history cap) if no local cache exists."""
    local_1h = PROCESSED_DIR / f"{yahoo_symbol}_1h.parquet"
    if local_1h.exists():
        df = pd.read_parquet(local_1h)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        return df[["timestamp", "close"]], "local_1h_cache"

    hist = yf.Ticker(yahoo_symbol).history(period=LIVE_FETCH_PERIOD, interval="1h")
    if hist.empty:
        return pd.DataFrame(columns=["timestamp", "close"]), "live_fetch_empty"
    df = hist.reset_index()
    ts_col = "Datetime" if "Datetime" in df.columns else "Date"
    df = df.rename(columns={ts_col: "timestamp", "Close": "close"})
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df[["timestamp", "close"]], "live_fetch_730d"


def _calibrate_event_for_asset(symbol_key: str, price_df: pd.DataFrame, event_times: list[pd.Timestamp]) -> dict | None:
    if price_df.empty or len(price_df) < 20:
        return None

    data_start, data_end = price_df["timestamp"].iloc[0], price_df["timestamp"].iloc[-1]
    relevant_times = [t for t in event_times if data_start <= t <= data_end]

    moves = []
    for t in relevant_times:
        move = _realized_move(price_df, t - WINDOW_BEFORE, t + WINDOW_AFTER)
        if not np.isnan(move):
            moves.append(move)

    if len(moves) < MIN_SAMPLES:
        return None

    indexed = price_df.set_index("timestamp")
    baseline_bars = indexed["close"].resample(WINDOW_LEN).ohlc().dropna()
    baseline_moves = np.abs(np.log(baseline_bars["close"] / baseline_bars["open"])).to_numpy()
    baseline_moves = baseline_moves[np.isfinite(baseline_moves)]
    if len(baseline_moves) == 0:
        return None

    event_mean = float(np.mean(moves))
    baseline_mean = float(np.mean(baseline_moves))
    if not baseline_mean:
        return None

    return {
        "n_event_samples": len(moves),
        "n_baseline_samples": int(len(baseline_moves)),
        "event_mean_abs_log_return": round(event_mean, 6),
        "baseline_mean_abs_log_return": round(baseline_mean, 6),
        "expected_volatility_multiplier": round(event_mean / baseline_mean, 4),
        "date_range": [str(data_start.date()), str(data_end.date())],
    }


def train() -> dict:
    if not CALENDAR_PATH.exists():
        raise RuntimeError(f"Run import_economic_calendar.py first -- missing {CALENDAR_PATH}")
    calendar = pd.read_parquet(CALENDAR_PATH)

    existing_calibration: dict = {}
    if CALIBRATION_PATH.exists():
        existing_calibration = json.loads(CALIBRATION_PATH.read_text())

    price_cache: dict[str, tuple[pd.DataFrame, str]] = {}
    results: dict[str, dict] = {}

    for (country, event_name), engine_key in TARGET_EVENTS.items():
        event_times = calendar.loc[
            (calendar["country"] == country) & (calendar["event"] == event_name), "timestamp"
        ].tolist()
        if not event_times:
            logger.warning("%s: no historical occurrences found in calendar, skipping", engine_key)
            continue

        per_asset: dict[str, dict] = {}
        for symbol_key, asset in SUPPORTED_ASSETS.items():
            if symbol_key not in price_cache:
                price_cache[symbol_key] = _load_price_history(symbol_key, asset.yahoo_symbol)
            price_df, source = price_cache[symbol_key]
            result = _calibrate_event_for_asset(symbol_key, price_df, event_times)
            if result:
                result["price_source"] = source
                per_asset[symbol_key] = result

        if not per_asset:
            logger.warning("%s: %d historical occurrences, but no asset had enough overlapping price history", engine_key, len(event_times))
            continue

        cross_asset_average = float(np.mean([a["expected_volatility_multiplier"] for a in per_asset.values()]))
        results[engine_key] = {
            "window": f"-{WINDOW_BEFORE}/+{WINDOW_AFTER} around release",
            "source_country": country,
            "source_event_name": event_name,
            "n_historical_occurrences": len(event_times),
            "cross_asset_average_multiplier": round(cross_asset_average, 4),
            "assets": per_asset,
            "not_wired_to_live_schedule": (
                "This event has no deterministic future-date rule (unlike NFP's "
                "'first Friday of the month'), so it is NOT registered in "
                "EconomicCalendarEngine._recurring_events and will not appear in "
                "upcoming_events()/analyze(). This calibration is real and ready to "
                "use the moment a live feed or published schedule is added for it."
            ),
        }
        logger.info(
            "%s: %d occurrences, calibrated for %d asset(s), cross-asset avg=%.3fx",
            engine_key, len(event_times), len(per_asset), cross_asset_average,
        )

    if not results:
        raise RuntimeError("No target event produced a usable calibration -- nothing to persist")

    merged = {**existing_calibration, **results}
    CALIBRATION_PATH.parent.mkdir(parents=True, exist_ok=True)
    CALIBRATION_PATH.write_text(json.dumps(merged, indent=2))
    logger.info("Saved %d new event calibration(s) to %s (preserving %d existing)", len(results), CALIBRATION_PATH, len(existing_calibration))
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    train()
