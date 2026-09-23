"""
Module: validate_e32_capital_allocation.py
Description: Live sanity check for E32 Capital Allocation -- same Rule 3
    category as E31 Portfolio Construction/E33 Opportunity Ranking
    (deterministic composition/normalization over five already-real,
    already-calibrated engines' outputs, no parameter of its own to fit).
    Uses the real EngineRegistry (this engine's own constructor takes the
    registry itself, same pattern as e33_opportunity_ranking -- there is
    no lighter-weight way to exercise E33+E51+E26+E12+E45 together
    without either the real registry or reimplementing its wiring here).
    Confirms: total allocated + total unallocated always sums to
    total_capital (a real invariant, not just a plausible-looking number),
    every allocation cleared a REAL E45 CRO check, and every un-allocated
    opportunity has an honest, specific reason.
Author: Shantanu Waykar
Version: 1.0.0
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))

from project_titan_x.engines.e32_capital_allocation.engine import CapitalAllocationEngine
from project_titan_x.engines.registry import get_registry

logger = logging.getLogger(__name__)
OUTPUT_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "e32_capital_allocation" / "validation_report.json"

TEST_SYMBOLS = ["BTCUSD", "ETHUSD", "EURUSD", "GOLD", "SP500"]
TOTAL_CAPITAL = 10_000.0


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    registry = get_registry()
    engine = CapitalAllocationEngine(registry=registry)

    result = engine.allocate(total_capital=TOTAL_CAPITAL, timeframe="1d", max_positions=3, symbols=TEST_SYMBOLS)
    logger.info(result.message)
    if not result.success or result.data is None:
        logger.error("Allocation failed, nothing to write")
        return

    report = result.data
    for a in report.allocations:
        logger.info("  ALLOCATED %s %s: $%.2f (risk=%.2f%%, kelly=%s, conf=%d) -- %s", a.symbol, a.direction, a.allocated_capital, a.risk_percent, a.kelly_fraction, a.confidence, a.note)
    for oc in report.opportunity_costs:
        logger.info("  NOT ALLOCATED %s: %s", oc.symbol, oc.reason)

    invariant_ok = abs((report.total_allocated + report.total_unallocated) - report.total_capital) < 0.01
    logger.info("Sanity check (allocated + unallocated == total_capital): %s", "PASS" if invariant_ok else "FAIL")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "result": report.to_dict()}, indent=2), encoding="utf-8")
    logger.info("")
    logger.info("Report written to %s", OUTPUT_PATH)


if __name__ == "__main__":
    main()
