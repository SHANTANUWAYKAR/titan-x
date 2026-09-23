"""Live sanity check for E74 Conflict Resolution -- compares two real
backtested philosophy archetypes' regime-conditional performance. No
calibration (Rule 3): real backtest + real regime attribution."""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))

from project_titan_x.engines.e02_market_data.engine import MarketDataEngine
from project_titan_x.engines.e07_technical.engine import TechnicalAnalysisEngine
from project_titan_x.engines.e26_backtesting.engine import BacktestingEngine
from project_titan_x.engines.e74_conflict_resolution.engine import ConflictResolutionEngine

logger = logging.getLogger(__name__)
OUTPUT_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "e74_conflict_resolution" / "validation_report.json"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    engine = ConflictResolutionEngine(market_data_engine=MarketDataEngine(), technical_engine=TechnicalAnalysisEngine(), backtesting_engine=BacktestingEngine())
    result = engine.compare_philosophies("GOLD", "trend_following_donchian", "mean_reversion_rsi")
    logger.info(result.message)
    for p in result.data.performance:
        logger.info("  %s", p.to_dict())

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "result": result.data.to_dict()}, indent=2), encoding="utf-8")
    logger.info("Report written to %s", OUTPUT_PATH)


if __name__ == "__main__":
    main()
