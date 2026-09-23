"""
Module: validate_e23_forecasting.py
Description: REAL calibration validation for E23 Forecasting (Rule 3.3
    -- validated, not just fit). For each test asset, pulls real
    historical forward-return data and runs ForecastingEngine.
    check_coverage(): builds the 90% empirical interval from an EARLY
    window and checks what fraction of a LATER, genuinely unseen window
    actually falls inside it. A well-calibrated forecast should land
    close to 90% -- this is the honest, checkable proof behind this
    engine's entire "probabilistic, not deterministic" claim, run
    against real market data, not a synthetic distribution.
Author: Shantanu Waykar
Version: 1.0.0
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))

from project_titan_x.engines.e02_market_data.engine import MarketDataEngine
from project_titan_x.engines.e23_forecasting.engine import ForecastingEngine

logger = logging.getLogger(__name__)
OUTPUT_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "e23_forecasting" / "calibration_report.json"

TEST_ASSETS = [("EURUSD", "EURUSD=X"), ("GOLD", "GC=F"), ("BTCUSD", "BTC-USD"), ("GBPUSD", "GBPUSD=X")]
HORIZON_DAYS = 20


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    market_data = MarketDataEngine()
    results = {}

    for symbol, yahoo_symbol in TEST_ASSETS:
        fetch = market_data.fetch_ohlcv(yahoo_symbol, "1d", years=10)
        if not fetch.success or fetch.data is None or fetch.data.empty:
            logger.warning("%s: could not fetch OHLCV, skipping", symbol)
            continue
        df = fetch.data.copy().reset_index(drop=True)
        df["fwd"] = (df["close"].shift(-HORIZON_DAYS) / df["close"] - 1.0) * 100.0
        returns = df["fwd"].dropna()

        coverage = ForecastingEngine.check_coverage(returns)
        results[symbol] = coverage
        if coverage["status"] == "ok":
            logger.info(
                "%s: target 90%% coverage, actual %.1f%% (train n=%d, test n=%d)",
                symbol, coverage["actual_coverage_pct"], coverage["n_train"], coverage["n_test"],
            )
        else:
            logger.warning("%s: %s", symbol, coverage["status"])

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "horizon_days": HORIZON_DAYS, "results": results}, indent=2),
        encoding="utf-8",
    )
    logger.info("")
    logger.info("Calibration report written to %s", OUTPUT_PATH)


if __name__ == "__main__":
    main()
