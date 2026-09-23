"""
Module: validate_e46_chief_risk_officer.py
Description: Live sanity check for E46 CRO -- same Rule 3 category as
    E39/E44 (deterministic threshold comparison against E45's own real,
    already-configured limits). Confirms a real risk posture verdict and
    that reading E45's portfolio state never calls update_portfolio_state
    or evaluate_trade (verified by inspection in the engine's own
    docstring; this script exercises the real read path only).
Author: Shantanu Waykar
Version: 1.0.0
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))

from project_titan_x.engines.e46_chief_risk_officer.engine import ChiefRiskOfficerEngine
from project_titan_x.engines.registry import get_registry

logger = logging.getLogger(__name__)
OUTPUT_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "e46_chief_risk_officer" / "validation_report.json"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    registry = get_registry()
    engine = ChiefRiskOfficerEngine(risk_engine=registry.get("e45_risk"), stress_testing_engine=registry.get("e28_stress_testing"))

    result = engine.assess_risk_posture(symbols=["BTCUSD", "GOLD"], timeframe="1d")
    logger.info(result.message)
    if not result.success or result.data is None:
        logger.error("Assessment failed, nothing to write")
        return

    verdict = result.data
    for d in verdict.dimensions:
        logger.info("  %s: %.3f / %.1f -> %s", d.name, d.current, d.limit, d.status)
    sane = verdict.risk_posture in ("low", "normal", "elevated", "critical")
    logger.info("Sanity check (risk_posture is a real known value): %s", "PASS" if sane else "FAIL")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "result": verdict.to_dict()}, indent=2), encoding="utf-8")
    logger.info("Report written to %s", OUTPUT_PATH)


if __name__ == "__main__":
    main()
