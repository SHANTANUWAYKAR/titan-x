"""
Module: validate_e48_execution_readiness.py
Description: Live sanity check for E48 Execution Readiness -- same
    Rule 3 category as E11 (the spread/liquidity read is inherited
    directly, real; the square-root market-impact model is a standard,
    documented quant convention, not fit to this platform's own data).
    Confirms a real cost/readiness estimate for a real position size on
    a real asset, and that the engine module genuinely exposes no
    order-placement method (the same check e47_governance's own
    no_execution_capability audit performs against the live registry).
Author: Shantanu Waykar
Version: 1.0.0
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))

from project_titan_x.engines.e48_execution_readiness.engine import ExecutionReadinessEngine
from project_titan_x.engines.registry import get_registry

logger = logging.getLogger(__name__)
OUTPUT_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "e48_execution_readiness" / "validation_report.json"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    registry = get_registry()
    engine = ExecutionReadinessEngine(microstructure_engine=registry.get("e11_microstructure"), market_data_engine=registry.get("e02_market_data"))

    no_execution_methods = not any(hasattr(engine, m) for m in ("place_order", "execute_trade", "submit_order", "send_order"))
    logger.info("Sanity check (no order-placement method exists on this engine): %s", "PASS" if no_execution_methods else "FAIL")

    results = {}
    for symbol, size in [("EURUSD", 5000.0), ("BTCUSD", 2000.0)]:
        result = engine.assess_execution_readiness(symbol, position_size_usd=size, timeframe="1d")
        logger.info("%s ($%.0f): %s", symbol, size, result.message)
        if result.success and result.data:
            results[symbol] = result.data.to_dict()

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "no_execution_methods": no_execution_methods, "results": results}, indent=2), encoding="utf-8")
    logger.info("Report written to %s", OUTPUT_PATH)


if __name__ == "__main__":
    main()
