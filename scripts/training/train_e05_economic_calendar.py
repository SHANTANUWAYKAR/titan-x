"""
Module: train_e05_economic_calendar.py
Description: Calibrate Engine 05's expected-volatility multiplier for US
    Non-Farm Payrolls releases -- the one event type shipped with a
    deterministic, published date rule (see e05_economic_calendar/engine.py
    for why FOMC/CPI/PPI aren't hardcoded) -- PER ASSET, against each
    supported instrument's own real historical price reaction, not one
    global number applied to every asset regardless of what it actually is.

    Method: for every historical NFP release date (first Friday of the
    month, 8:30am ET) covered by an asset's available hourly data, measure
    the realized absolute log return over a [-1h, +3h] window around the
    release, then compare the average of those realized moves against the
    average realized move over ALL non-overlapping 4-hour windows in the
    same history. The ratio is that asset's "expected_volatility_multiplier"
    for NFP.

    Data sources per asset:
    - BTC-USD: the project's own processed 1h parquet (data/processed/,
      built from real downloaded history spanning 2019-2026) -- by far the
      deepest history available for any single instrument here.
    - Every other supported asset (forex, other crypto, commodities,
      indices): fetched live via yfinance at 1h resolution. Yahoo only
      serves ~730 days of hourly history regardless of ticker, so these
      calibrations rest on a real but shorter (~18-24 month, ~18-24 NFP
      occurrences) sample than BTC-USD's -- reported honestly via
      n_nfp_samples/date_range per asset rather than padded or guessed.

    A cross_asset_average_multiplier (the mean of every successfully
    calibrated asset's own multiplier) is also persisted, purely as an
    honest fallback for a symbol the engine is asked about that has no
    per-asset calibration of its own -- never fabricated, always traceable
    back to real per-asset numbers.
Author: Shantanu Waykar
Version: 1.0.0
"""

import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))

from project_titan_x.core.config.assets import SUPPORTED_ASSETS
from project_titan_x.engines.e05_economic_calendar.engine import _first_friday_8_30am_et, _month_iter, _thursday_dates

logger = logging.getLogger(__name__)

PROCESSED_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"
MODELS_DIR = Path(__file__).resolve().parents[2] / "data" / "models" / "e05_economic_calendar"

WINDOW_BEFORE = timedelta(hours=1)
WINDOW_AFTER = timedelta(hours=3)
WINDOW_LEN = WINDOW_BEFORE + WINDOW_AFTER  # 4 hours, matched by the baseline windows below
LIVE_FETCH_PERIOD = "730d"  # yfinance's practical cap on 1h-resolution history
MIN_NFP_SAMPLES = 6  # below this, a per-asset multiplier is too noisy to persist

# Added 2026-08-02: each entry is (event_name, release_date_generator).
# release_date_generator(start, end) must return every real occurrence of
# that event's release time in range -- NFP's is monthly (_month_iter +
# _first_friday_8_30am_et per month), Jobless Claims' is weekly
# (_thursday_dates directly returns full datetimes). _calibrate_one below
# is generalized to accept either shape via `_iter_release_dates`.
EVENT_DATE_GENERATORS = {
    "US Non-Farm Payrolls": lambda start, end: [_first_friday_8_30am_et(y, m) for y, m in _month_iter(start, end)],
    "US Initial Jobless Claims": _thursday_dates,
}


def _realized_move(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> float:
    """Absolute log return of close price from the first bar at/after
    `start` to the last bar at/before `end`. Returns NaN if the window
    isn't covered by the data."""
    window = df[(df["timestamp"] >= start) & (df["timestamp"] <= end)]
    if len(window) < 2:
        return float("nan")
    return abs(np.log(window["close"].iloc[-1] / window["close"].iloc[0]))


def _load_btc_processed() -> pd.DataFrame:
    df = pd.read_parquet(PROCESSED_DIR / "BTC-USD_1h.parquet")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def _fetch_live_hourly(yahoo_symbol: str) -> pd.DataFrame:
    hist = yf.Ticker(yahoo_symbol).history(period=LIVE_FETCH_PERIOD, interval="1h")
    if hist.empty:
        return pd.DataFrame(columns=["timestamp", "close"])
    df = hist.reset_index()
    ts_col = "Datetime" if "Datetime" in df.columns else "Date"
    df = df.rename(columns={ts_col: "timestamp", "Close": "close"})
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df[["timestamp", "close"]]


def _calibrate_one(symbol_key: str, df: pd.DataFrame, date_generator) -> dict | None:
    """Generalized 2026-08-02 to accept any release_date_generator(start,
    end) (see EVENT_DATE_GENERATORS above) -- originally hardcoded to NFP's
    monthly first-Friday rule specifically; the realized-move-vs-baseline
    methodology itself was always event-agnostic."""
    if df.empty or len(df) < 20:
        logger.warning("%s: no usable hourly data, skipping", symbol_key)
        return None

    data_start, data_end = df["timestamp"].iloc[0], df["timestamp"].iloc[-1]
    event_moves = []
    for release in date_generator(data_start, data_end):
        release_utc = pd.Timestamp(release).tz_convert("UTC")
        move = _realized_move(df, release_utc - WINDOW_BEFORE, release_utc + WINDOW_AFTER)
        if not np.isnan(move):
            event_moves.append(move)

    if len(event_moves) < MIN_NFP_SAMPLES:
        logger.warning(
            "%s: only %d event samples in available history, skipping (need >= %d)",
            symbol_key, len(event_moves), MIN_NFP_SAMPLES,
        )
        return None

    indexed = df.set_index("timestamp")
    baseline_bars = indexed["close"].resample(WINDOW_LEN).ohlc().dropna()
    baseline_moves = np.abs(np.log(baseline_bars["close"] / baseline_bars["open"])).to_numpy()
    baseline_moves = baseline_moves[np.isfinite(baseline_moves)]

    event_mean = float(np.mean(event_moves))
    baseline_mean = float(np.mean(baseline_moves)) if len(baseline_moves) else float("nan")
    if not baseline_mean or np.isnan(baseline_mean):
        logger.warning("%s: no usable baseline windows, skipping", symbol_key)
        return None
    multiplier = event_mean / baseline_mean

    return {
        "n_nfp_samples": len(event_moves),
        "n_baseline_samples": int(len(baseline_moves)),
        "nfp_mean_abs_log_return": round(event_mean, 6),
        "baseline_mean_abs_log_return": round(baseline_mean, 6),
        "expected_volatility_multiplier": round(multiplier, 4),
        "date_range": [str(data_start.date()), str(data_end.date())],
    }


def _train_one_event(event_name: str, date_generator) -> dict | None:
    per_asset: dict[str, dict] = {}

    btc_result = _calibrate_one("BTCUSD", _load_btc_processed(), date_generator)
    if btc_result:
        per_asset["BTCUSD"] = btc_result

    for symbol_key, asset in SUPPORTED_ASSETS.items():
        if symbol_key == "BTCUSD":
            continue  # already done above from the richer processed dataset
        df = _fetch_live_hourly(asset.yahoo_symbol)
        result = _calibrate_one(symbol_key, df, date_generator)
        if result:
            per_asset[symbol_key] = result

    if not per_asset:
        logger.warning("%s: no asset produced a usable calibration -- skipping this event entirely", event_name)
        return None

    cross_asset_average = float(np.mean([a["expected_volatility_multiplier"] for a in per_asset.values()]))
    report = {
        "window": f"-{WINDOW_BEFORE}/+{WINDOW_AFTER} around 8:30am ET release",
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "cross_asset_average_multiplier": round(cross_asset_average, 4),
        "assets": per_asset,
        "caveat": (
            f"Per-asset ratio of realized volatility around historical {event_name} release "
            "times vs. an equivalent-length baseline window, computed independently "
            "for each asset from its own real price history (BTC-USD from the "
            "project's long processed 1h dataset, 2019-2026; every other asset from "
            "yfinance's live ~730-day hourly history -- see each asset's own "
            "date_range/n_nfp_samples). Not a guarantee of future reaction magnitude "
            "or direction -- this event's effect on non-USD-rates instruments (crypto, "
            "gold, NIFTY) is indirect and regime-dependent. cross_asset_average_multiplier "
            "is the mean of the calibrated per-asset numbers above, used only as a "
            "fallback for a symbol with no calibration of its own -- never a "
            "fabricated or guessed figure."
        ),
    }
    logger.info("%s: calibrated %d asset(s)", event_name, len(per_asset))
    for symbol_key, data in per_asset.items():
        logger.info(
            "  %-10s multiplier=%.3fx (n=%d, %s..%s)",
            symbol_key, data["expected_volatility_multiplier"], data["n_nfp_samples"],
            data["date_range"][0], data["date_range"][1],
        )
    logger.info("  cross_asset_average_multiplier=%.3fx", cross_asset_average)
    return report


def train() -> dict:
    all_reports: dict[str, dict] = {}
    for event_name, date_generator in EVENT_DATE_GENERATORS.items():
        report = _train_one_event(event_name, date_generator)
        if report:
            all_reports[event_name] = report

    if not all_reports:
        raise RuntimeError("No event produced a usable calibration -- nothing to persist")

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    calibration_path = MODELS_DIR / "volatility_calibration.json"
    # Merge with existing content rather than overwriting -- real bug found
    # 2026-08-18: this used to blindly write_text(all_reports), which
    # silently wiped out the 8 extended event calibrations
    # train_e05_event_calibration.py had separately merged into the SAME
    # file (that script always merged correctly; this one didn't), the
    # moment this script was re-run after Initial Jobless Claims was added
    # to EVENT_DATE_GENERATORS. Same merge pattern as that sibling script.
    existing_calibration: dict = {}
    if calibration_path.exists():
        existing_calibration = json.loads(calibration_path.read_text())
    merged = {**existing_calibration, **all_reports}
    calibration_path.write_text(json.dumps(merged, indent=2))
    logger.info(
        "Saved calibration for %d event type(s) to %s (preserving %d existing)",
        len(all_reports), calibration_path, len(existing_calibration),
    )
    return all_reports


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    train()
