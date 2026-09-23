"""
Module: validate_e20_factor_research.py
Description: Real-data validation script for E20 Factor Research -- runs
    the real Fama-French 5-factor + momentum regression for all 8
    supported US equities and reports the results. Not a threshold-fitting
    "calibration" in the sense train_e16_commodity.py or
    train_e17_crypto.py are (T_STAT_SIGNIFICANCE=1.96 is a fixed, standard
    statistical convention, not something to fit against historical data --
    see e20_factor_research/engine.py's own module docstring for why).
    What this DOES validate, per Rule 3.2's "book knowledge" spirit: do
    the real regression outputs match well-established, real-world finance
    facts (e.g. AAPL/MSFT showing a large-cap growth-quality tilt, a
    textbook-obvious real-world fact, not a guess)? If a future data or
    methodology change made these come out nonsensical, this script is
    the re-runnable way to notice.
Author: Shantanu Waykar
Version: 1.0.0
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))

from project_titan_x.engines.e20_factor_research.engine import FactorResearchEngine, SUPPORTED_EQUITIES

logger = logging.getLogger(__name__)
OUTPUT_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "e20_factor_research" / "validation_report.json"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    engine = FactorResearchEngine()
    engine.initialize()

    results = {}
    for symbol in sorted(SUPPORTED_EQUITIES):
        result = engine.analyze(symbol, years=10)
        if not result.success:
            logger.warning("%s: %s", symbol, result.message)
            results[symbol] = {"error": result.message}
            continue
        results[symbol] = result.data.to_dict()
        sig = [e["tilt"] for e in results[symbol]["exposures"] if e["significant"] and e["tilt"] != "not_significant"]
        logger.info("%s: R2=%.2f, n=%d, significant tilts: %s", symbol, results[symbol]["r_squared"], results[symbol]["n_observations"], sig or "none")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "results": results}, indent=2))
    print(f"\nSaved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
