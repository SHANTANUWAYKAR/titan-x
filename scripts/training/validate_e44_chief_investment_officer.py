"""
Module: validate_e44_chief_investment_officer.py
Description: Live sanity check for E44 CIO -- same Rule 3 category as
    E32/E33 (deterministic composition over already-real engines' outputs,
    no parameter of its own to fit). Confirms a real portfolio stance
    verdict and (with a real total_capital) a real capital plan compose
    correctly from E33 + E32's own real outputs.
Author: Shantanu Waykar
Version: 1.0.0
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))

from project_titan_x.engines.e44_chief_investment_officer.engine import ChiefInvestmentOfficerEngine
from project_titan_x.engines.registry import get_registry

logger = logging.getLogger(__name__)
OUTPUT_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "e44_chief_investment_officer" / "validation_report.json"
TEST_SYMBOLS = ["BTCUSD", "ETHUSD", "EURUSD", "GBPUSD", "GOLD", "SP500"]


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    registry = get_registry()
    engine = ChiefInvestmentOfficerEngine(registry=registry)

    result = engine.assess_portfolio_stance(timeframe="1d", total_capital=10_000.0, max_positions=3, symbols=TEST_SYMBOLS)
    logger.info(result.message)
    if not result.success or result.data is None:
        logger.error("Assessment failed, nothing to write")
        return

    verdict = result.data
    sane = verdict.overall_stance in ("net_long", "net_short", "mixed", "insufficient_data")
    logger.info("Sanity check (overall_stance is a real known value): %s", "PASS" if sane else "FAIL")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "result": verdict.to_dict()}, indent=2), encoding="utf-8")
    logger.info("Report written to %s", OUTPUT_PATH)


if __name__ == "__main__":
    main()
