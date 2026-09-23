"""
Module: train_e13_derivatives.py
Description: Calibrate Engine 13's realized-volatility baseline for BTC and
    ETH from real, long historical price data.

    Why this exists despite the engine's own "no calibration script"
    caveat: Deribit's public API (the engine's live options-chain source)
    only serves the CURRENT chain, with no historical archive -- so there
    is no real historical IMPLIED-vol data to calibrate against, and that
    honest gap still stands. But this platform DOES have deep real
    historical PRICE data for BTC-USD (2014-2026) and ETH-USD (2017-2026,
    both in data/processed/), which is enough to calibrate the historical
    distribution of REALIZED volatility -- a real, well-established
    quantity in its own right, and the other half of the standard
    "volatility risk premium" (IV vs RV) comparison.

    Method: compute a rolling 30-day annualized realized volatility series
    (std of daily log returns * sqrt(365), crypto's 24/7/365 convention)
    over each asset's full real price history, then persist the
    percentile distribution (10th/25th/50th/75th/90th) of that series.
    The live engine compares TODAY's 30-day realized vol against this real
    historical distribution to classify the current volatility regime
    (low/below_average/average/above_average/high) -- and separately
    reports today's ATM implied vol minus today's realized vol (the
    classic VRP spread) as a plain, un-classified number, since there is
    no historical IV series to say whether THAT spread itself is
    currently rich or cheap.
Author: Shantanu Waykar
Version: 1.0.0
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))

logger = logging.getLogger(__name__)

PROCESSED_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"
MODELS_DIR = Path(__file__).resolve().parents[2] / "data" / "models" / "e13_derivatives"

REALIZED_VOL_WINDOW_DAYS = 30
ANNUALIZATION_FACTOR = 365  # crypto trades 24/7/365, unlike equities' 252-day convention
PERCENTILES = (10, 25, 50, 75, 90)

_SOURCE_FILES = {"BTC": "BTC-USD_1d.parquet", "ETH": "ETH-USD_1d.parquet"}


def _rolling_realized_vol(df: pd.DataFrame) -> pd.Series:
    log_returns = np.log(df["close"] / df["close"].shift(1))
    rolling_std = log_returns.rolling(REALIZED_VOL_WINDOW_DAYS).std()
    return (rolling_std * np.sqrt(ANNUALIZATION_FACTOR) * 100).dropna()  # as a vol-point percentage, matching Deribit's mark_iv units


def _calibrate_one(currency: str) -> dict:
    path = PROCESSED_DIR / _SOURCE_FILES[currency]
    df = pd.read_parquet(path)
    df = df.sort_values("timestamp").reset_index(drop=True)

    rv_series = _rolling_realized_vol(df)
    percentiles = {str(p): round(float(np.percentile(rv_series, p)), 3) for p in PERCENTILES}

    return {
        "window_days": REALIZED_VOL_WINDOW_DAYS,
        "annualization_factor": ANNUALIZATION_FACTOR,
        "n_observations": int(len(rv_series)),
        "date_range": [str(df["timestamp"].iloc[0].date()), str(df["timestamp"].iloc[-1].date())],
        "realized_vol_percentiles": percentiles,
        "current_realized_vol_at_train_time": round(float(rv_series.iloc[-1]), 3),
    }


def train() -> dict:
    report: dict = {}
    for currency in _SOURCE_FILES:
        report[currency] = _calibrate_one(currency)

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    output = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "currencies": report,
        "caveat": (
            "Percentiles of REALIZED volatility (from real historical price data, not "
            "options data -- see module docstring for why no implied-vol history exists "
            "to calibrate against). Used only to classify whether TODAY's realized vol "
            "is high/low relative to its own real historical range; the IV-vs-RV spread "
            "(VRP) the engine also reports is a plain current-day number, not classified "
            "against a historical baseline, since no historical IV series exists to build "
            "one from."
        ),
    }
    calibration_path = MODELS_DIR / "realized_vol_baseline.json"
    calibration_path.write_text(json.dumps(output, indent=2))
    logger.info("Saved realized-vol baseline for %d currencies to %s", len(report), calibration_path)
    for currency, data in report.items():
        logger.info(
            "  %s: n=%d (%s..%s) percentiles=%s current=%.2f",
            currency, data["n_observations"], data["date_range"][0], data["date_range"][1],
            data["realized_vol_percentiles"], data["current_realized_vol_at_train_time"],
        )
    return output


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    train()
