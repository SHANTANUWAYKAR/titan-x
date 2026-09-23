"""
Module: train_all_assets.py
Description: Extends the BTC-only training pass to every other supported
    asset (see core/config/assets.py): fetches maximum available daily
    history via E02's fetch chain (Yahoo Finance for all 10 of these --
    no fallback needed), then runs the same E08 regime-HMM hyperparameter
    search and E16 signal-rule calibration already validated for BTC.

    BTC-USD is intentionally excluded here -- it already has a dedicated,
    higher-resolution training pass (train_engines.py) built from the
    user-supplied 5-minute data, which is a better dataset than a plain
    daily Yahoo Finance fetch.
Author: Shantanu Waykar
Version: 1.0.0
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import train_e08_regime
import train_e51_signals

from project_titan_x.core.config.assets import list_assets
from project_titan_x.engines.e02_market_data.engine import MarketDataEngine

logger = logging.getLogger(__name__)
MODELS_DIR = Path(__file__).resolve().parents[2] / "data" / "models"


def train_asset(yahoo_symbol: str, market_data_engine: MarketDataEngine) -> dict:
    result: dict = {"symbol": yahoo_symbol}

    fetch = market_data_engine.fetch_ohlcv(yahoo_symbol, "1d", years=15)
    if not fetch.success:
        result["error"] = f"fetch failed: {fetch.message}"
        return result
    result["n_bars"] = len(fetch.data)
    result["date_range"] = [str(fetch.data["timestamp"].iloc[0]), str(fetch.data["timestamp"].iloc[-1])]

    try:
        e08 = train_e08_regime.train(symbol=yahoo_symbol, timeframe="1d")
        result["e08_regime_winner"] = e08.winner
    except Exception as e:
        logger.warning("E08 regime training failed for %s: %s", yahoo_symbol, e)
        result["e08_regime_error"] = str(e)

    try:
        e16 = train_e51_signals.train(symbol=yahoo_symbol, timeframe="1d")
        result["e51_signals_decision"] = e16["decision"]
        result["e51_signals_winner"] = e16["winner"]
    except Exception as e:
        logger.warning("E16 signals training failed for %s: %s", yahoo_symbol, e)
        result["e51_signals_error"] = str(e)

    return result


def main() -> dict:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # Explicit absolute data_dir: MarketDataEngine defaults to a cwd-relative
    # "data/" path, which would land in the wrong place if this script isn't
    # run from the project root.
    project_root = Path(__file__).resolve().parents[2]
    market_data_engine = MarketDataEngine(data_dir=project_root / "data")
    market_data_engine.initialize()

    results = {}
    for asset in list_assets():
        if asset.symbol == "BTCUSD":
            continue
        logger.info("=== Training %s (%s) ===", asset.symbol, asset.yahoo_symbol)
        results[asset.symbol] = train_asset(asset.yahoo_symbol, market_data_engine)

    report = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "assets": results,
    }
    (MODELS_DIR / "all_assets_training_report.json").write_text(json.dumps(report, indent=2, default=str))
    return report


if __name__ == "__main__":
    main()
