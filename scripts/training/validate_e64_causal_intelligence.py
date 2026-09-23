"""Live sanity check for E64 Causal Intelligence -- runs real Granger
causality tests on real KNOWN_CANDIDATE_LINKS. No calibration (Rule 3):
the statistical test itself is the real check, standard p<0.05."""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))

from project_titan_x.engines.e02_market_data.engine import MarketDataEngine
from project_titan_x.engines.e64_causal_intelligence.engine import CausalIntelligenceEngine

logger = logging.getLogger(__name__)
OUTPUT_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "e64_causal_intelligence" / "validation_report.json"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    engine = CausalIntelligenceEngine(market_data_engine=MarketDataEngine())
    result = engine.trace_causal_chain()
    logger.info(result.message)
    for link in result.data.links:
        logger.info("  %s -> %s: %s", link.cause_symbol, link.effect_symbol, link.note)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "result": result.data.to_dict()}, indent=2), encoding="utf-8")
    logger.info("Report written to %s", OUTPUT_PATH)


if __name__ == "__main__":
    main()
