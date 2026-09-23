"""Live sanity check for E63 Market Memory -- records real snapshots for
a few assets, backfills real outcomes, and runs a real similarity query.
No calibration (Rule 3): deterministic log + real distance metric."""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))

from project_titan_x.engines.e02_market_data.engine import MarketDataEngine
from project_titan_x.engines.e63_market_memory.engine import MarketMemoryEngine

logger = logging.getLogger(__name__)
OUTPUT_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "e63_market_memory" / "validation_report.json"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    md = MarketDataEngine()
    engine = MarketMemoryEngine(market_data_engine=md)

    r1 = engine.record_snapshot("GOLD", close=4296.5, macro_score=0.12, regime="ranging", adx=23.6, rsi=60.4, realized_vol_pct=1.8)
    logger.info("record: %s", r1.message)
    r2 = engine.backfill_outcomes("GOLD", "GC=F")
    logger.info("backfill: %s", r2.message)
    r3 = engine.find_similar_days("GOLD", macro_score=0.1, adx=24.0)
    logger.info("similarity: %s", r3.message)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "record": r1.success, "backfill": r2.message, "similarity": r3.message}, indent=2), encoding="utf-8")
    logger.info("Report written to %s", OUTPUT_PATH)


if __name__ == "__main__":
    main()
