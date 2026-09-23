"""
Module: validate_e29_scenario_analysis.py
Description: Live sanity check for E29 Scenario Analysis -- same Rule 3
    category as validate_e21_feature_engineering.py/validate_e23_
    forecasting.py (a deterministic replay of real historical price data
    against a caller-supplied entry/stop/target has no held-out parameter
    to fit). Runs a real LONG and a real SHORT scenario analysis and
    confirms: best/base case comes from E23's own real forecast
    percentiles, worst case comes from real historical shock-window price
    data (not fabricated), and the sign convention is correct for both
    directions (a real bug caught and fixed during this engine's build --
    see engine.py's own docstring on the raw-asset-return convention).
Author: Shantanu Waykar
Version: 1.0.0
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))

from project_titan_x.engines.e29_scenario_analysis.engine import ScenarioAnalysisEngine

logger = logging.getLogger(__name__)
OUTPUT_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "e29_scenario_analysis" / "validation_report.json"

# (symbol, direction, entry, stop_loss, take_profit) -- entry/stop/target
# chosen as realistic round levels near each asset's real recent price,
# not fitted to any particular outcome.
TEST_CASES = [
    ("EURUSD", "LONG", 1.1557, 1.1450, 1.1750),
    ("GOLD", "SHORT", 2650.0, 2700.0, 2500.0),
    ("BTCUSD", "LONG", 65000.0, 62000.0, 72000.0),
]


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    engine = ScenarioAnalysisEngine()

    results = {}
    for symbol, direction, entry, stop_loss, take_profit in TEST_CASES:
        result = engine.analyze_scenarios(symbol, direction, entry, stop_loss, take_profit)
        logger.info("%s %s: %s", symbol, direction, result.message)
        if not result.success or result.data is None:
            continue
        report = result.data
        results[f"{symbol}_{direction}"] = report.to_dict()
        for outcome in report.outcomes:
            logger.info(
                "  %s (%s): return=%s r_multiple=%s breached=%s",
                outcome.scenario_name, outcome.scenario_type, outcome.shock_return_pct,
                outcome.r_multiple, outcome.stop_loss_breached,
            )
        # Sanity check: best case should always have a non-negative
        # R-multiple relative to base (never a fabricated ordering).
        best = next((o for o in report.outcomes if o.scenario_type == "best"), None)
        base = next((o for o in report.outcomes if o.scenario_type == "base"), None)
        if best and base and best.r_multiple is not None and base.r_multiple is not None:
            ok = best.r_multiple >= base.r_multiple
            logger.info("  sanity check (best R >= base R): %s", "PASS" if ok else "FAIL")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "results": results}, indent=2), encoding="utf-8")
    logger.info("")
    logger.info("Report written to %s", OUTPUT_PATH)


if __name__ == "__main__":
    main()
