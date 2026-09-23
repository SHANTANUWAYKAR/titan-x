"""
Module: train_e22_alpha_research.py
Description: Runs every curated E22 hypothesis against real historical
    data and writes results to the persistent alpha database (data/
    models/e22_alpha_research/alpha_database.json). Re-runnable later
    against fresh data (Rule 3.4) -- each run overwrites that
    hypothesis+symbol's entry with the current real result, never
    accumulates stale duplicates.

    Reports results HONESTLY regardless of outcome -- a hypothesis that
    does NOT hold up (e.g. this run's real finding that "gold performs
    better in risk-off" does not hold over the last 10 years at a 20-day
    horizon) is exactly as valuable a result as one that does, and is
    stored/reported the same way, never suppressed.
Author: Shantanu Waykar
Version: 1.0.0
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))

from project_titan_x.engines.e22_alpha_research.engine import ALPHA_DB_PATH, AlphaResearchFactoryEngine

logger = logging.getLogger(__name__)

# Curated hypothesis set -- (symbol, yahoo_symbol) pairs to test against
# each of this engine's two hypothesis TYPES. Small and explicit rather
# than an open-ended NLP-generated list (this project has no LLM access
# for genuine hypothesis extraction from text -- see e01_knowledge's own
# documented honesty limitation on rule-based extraction).
RISK_OFF_ASSETS = [("GOLD", "GC=F"), ("SILVER", "SI=F")]
TREND_REGIME_ASSETS = [("BTCUSD", "BTC-USD"), ("EURUSD", "EURUSD=X"), ("GOLD", "GC=F")]


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    engine = AlphaResearchFactoryEngine()

    logger.info("=== Risk-off hypothesis (master prompt's own example) ===")
    for symbol, yahoo_symbol in RISK_OFF_ASSETS:
        result = engine.test_risk_off_hypothesis(symbol=symbol, yahoo_symbol=yahoo_symbol)
        logger.info(result.message)
        if result.success:
            engine.store_result(result.data)

    logger.info("")
    logger.info("=== Trending-regime hypothesis ===")
    for symbol, yahoo_symbol in TREND_REGIME_ASSETS:
        result = engine.test_trending_regime_hypothesis(symbol=symbol, yahoo_symbol=yahoo_symbol)
        logger.info(result.message)
        if result.success:
            engine.store_result(result.data)

    logger.info("")
    logger.info("Alpha database written to %s", ALPHA_DB_PATH)


if __name__ == "__main__":
    main()
