"""Live sanity check for E84 Counterfactual -- replays real historical
episodes of a real condition for a real asset. No calibration (Rule 3):
deterministic episode lookup over real price/VIX data."""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))

from project_titan_x.engines.e02_market_data.engine import MarketDataEngine
from project_titan_x.engines.e84_counterfactual.engine import CounterfactualEngine

logger = logging.getLogger(__name__)
OUTPUT_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "e84_counterfactual" / "validation_report.json"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    engine = CounterfactualEngine(market_data_engine=MarketDataEngine())
    result = engine.replay_condition("GOLD", condition="vix_elevated", horizon_days=20)
    logger.info(result.message)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "result": result.data.to_dict() if result.data else None}, indent=2), encoding="utf-8")
    logger.info("Report written to %s", OUTPUT_PATH)


if __name__ == "__main__":
    main()
