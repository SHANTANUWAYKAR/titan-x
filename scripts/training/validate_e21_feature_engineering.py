"""
Module: validate_e21_feature_engineering.py
Description: Live sanity check for E21 Feature Engineering -- same
    category as validate_e20_factor_research.py (a mechanical-assembly
    engine has no held-out parameter to fit, per Rule 3's own
    exception clause; what's validated is that real feature groups
    populate sensibly against real market data, not a threshold).
    Runs against a handful of real assets across asset classes and
    reports how many feature groups populated vs. honestly reported
    unavailable, plus a spot-check of the actual technical/time/
    volatility values.
Author: Shantanu Waykar
Version: 1.0.0
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))

from project_titan_x.core.config import get_asset
from project_titan_x.engines.e02_market_data.engine import MarketDataEngine
from project_titan_x.engines.e04_macro.engine import MacroIntelligenceEngine
from project_titan_x.engines.e07_technical.engine import TechnicalAnalysisEngine
from project_titan_x.engines.e21_feature_engineering.engine import FeatureEngineeringEngine

logger = logging.getLogger(__name__)
OUTPUT_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "e21_feature_engineering" / "validation_report.json"

TEST_ASSETS = ["EURUSD", "GOLD", "BTCUSD"]


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    market_data = MarketDataEngine()
    technical = TechnicalAnalysisEngine()
    macro = MacroIntelligenceEngine()
    engine = FeatureEngineeringEngine(technical_engine=technical, macro_engine=macro)

    results = {}
    for symbol in TEST_ASSETS:
        asset = get_asset(symbol)
        yahoo_symbol = asset.yahoo_symbol if asset else symbol
        fetch = market_data.fetch_ohlcv(yahoo_symbol, "1d", years=2)
        if not fetch.success or fetch.data is None or fetch.data.empty:
            logger.warning("%s: could not fetch OHLCV, skipping", symbol)
            continue
        result = engine.compute_features(symbol, fetch.data, timeframe="1d")
        logger.info("%s: %s", symbol, result.message)
        if result.success:
            fv = result.data
            results[symbol] = fv.to_dict()
            logger.info("  sample technical: rsi=%.1f adx=%.1f atr=%.4f", fv.technical.get("rsi", float("nan")), fv.technical.get("adx", float("nan")), fv.technical.get("atr", float("nan")))
            logger.info("  time features: %s", fv.time)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "results": results}, indent=2), encoding="utf-8")
    logger.info("")
    logger.info("Report written to %s", OUTPUT_PATH)


if __name__ == "__main__":
    main()
