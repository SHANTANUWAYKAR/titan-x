"""
Module: validate_e25_strategy_lifecycle.py
Description: Live sanity check for E25 Strategy Lifecycle -- same Rule 3
    category as E33/E39 (pure mechanical state derivation from four other
    engines' already-real outputs, no parameter of its own to fit). Runs
    a real audit() across every real supported asset and confirms the
    three symbols with a real, committed live model file
    (BTCUSD/ETHUSD/SP500 -- same files E39's own validation report
    verifies) come back as "live_validated", never "not_researched" or
    "live_unverified_provenance".
Author: Shantanu Waykar
Version: 1.0.0
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))

from project_titan_x.engines.e25_strategy_lifecycle.engine import StrategyLifecycleEngine
from project_titan_x.engines.e35_performance_analytics.engine import PerformanceAnalyticsEngine
from project_titan_x.engines.e38_alpha_decay_monitor.engine import AlphaDecayMonitorEngine

logger = logging.getLogger(__name__)
OUTPUT_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "e25_strategy_lifecycle" / "validation_report.json"

EXPECTED_LIVE_VALIDATED = {"BTCUSD", "ETHUSD", "SP500"}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    decay_engine = AlphaDecayMonitorEngine(performance_engine=PerformanceAnalyticsEngine())
    engine = StrategyLifecycleEngine(alpha_decay_monitor_engine=decay_engine)

    result = engine.audit()  # None -> every real supported asset
    logger.info(result.message)
    if not result.success or result.data is None:
        logger.error("Audit failed, nothing to write")
        return

    report = result.data
    for s in report.statuses:
        if s.lifecycle_stage != "researched_not_promoted":
            logger.info("  %s: stage=%s live_model=%s provenance_verified=%s decay=%s", s.symbol, s.lifecycle_stage, s.live_model_kind, s.provenance_verified, s.decay_verdict)

    live_validated = {s.symbol for s in report.statuses if s.lifecycle_stage in ("live_validated", "decaying")}
    missing = EXPECTED_LIVE_VALIDATED - live_validated
    if missing:
        logger.warning("Sanity check FAILED: expected %s at live_validated/decaying, missing %s", EXPECTED_LIVE_VALIDATED, missing)
    else:
        logger.info("Sanity check PASSED: %s all reached live_validated/decaying", EXPECTED_LIVE_VALIDATED)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "result": report.to_dict()}, indent=2), encoding="utf-8")
    logger.info("")
    logger.info("Report written to %s", OUTPUT_PATH)


if __name__ == "__main__":
    main()
