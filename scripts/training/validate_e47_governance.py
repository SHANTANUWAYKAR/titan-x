"""
Module: validate_e47_governance.py
Description: Live sanity check for E47 Governance -- same Rule 3 category
    as E39/E40 (pure mechanical inspection of already-real engine/config
    state, no calibration). Confirms a real compliance audit runs clean
    against the live registry (49 engines, none execution-capable, all
    real risk limits sane, E39's own provenance check clean).
Author: Shantanu Waykar
Version: 1.0.0
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))

from project_titan_x.engines.e47_governance.engine import GovernanceEngine
from project_titan_x.engines.registry import get_registry

logger = logging.getLogger(__name__)
OUTPUT_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "e47_governance" / "validation_report.json"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    registry = get_registry()
    engine = GovernanceEngine(registry=registry, model_risk_engine=registry.get("e39_model_risk"))

    result = engine.audit_compliance()
    logger.info(result.message)
    if not result.success or result.data is None:
        logger.error("Audit failed, nothing to write")
        return

    report = result.data
    for c in report.checks:
        logger.info("  %s: %s -- %s", c.name, c.status, c.detail)
    logger.info("Sanity check (platform is compliant): %s", "PASS" if report.overall_status == "compliant" else "FAIL (real finding, not suppressed)")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "result": report.to_dict()}, indent=2), encoding="utf-8")
    logger.info("Report written to %s", OUTPUT_PATH)


if __name__ == "__main__":
    main()
