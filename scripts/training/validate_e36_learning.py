"""
Module: validate_e36_learning.py
Description: Live sanity check for E36 Learning Engine -- same Rule 3
    category as E34 Trade Attribution/E38 Alpha Decay Monitor (neither of
    which has a scripts/training/ entry either -- a statistical
    comparison of another engine's already-real trade-journal output has
    no parameter of its own to fit; Rule 4's real-collaborator-test
    requirement is instead met by this script running the REAL
    TradeAttributionEngine/PerformanceAnalyticsEngine, not a stub).

    This platform has no execution engine (CLAUDE.md Rule 5) -- every
    Trade row is a manually-logged, retrospective journal entry, so an
    empty or unreachable journal is an honest, expected real-world state,
    not a failure to work around. This script reports whichever real
    outcome actually occurs (lessons generated from a populated journal,
    or an honest insufficient_data/connection-error result from an empty
    one) rather than fabricating trade data to force a non-trivial
    report.
Author: Shantanu Waykar
Version: 1.0.0
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))

from project_titan_x.engines.e34_trade_attribution.engine import TradeAttributionEngine
from project_titan_x.engines.e35_performance_analytics.engine import PerformanceAnalyticsEngine
from project_titan_x.engines.e36_learning.engine import LearningEngine

logger = logging.getLogger(__name__)
OUTPUT_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "e36_learning" / "validation_report.json"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    performance_engine = PerformanceAnalyticsEngine()
    attribution_engine = TradeAttributionEngine(performance_engine=performance_engine)
    engine = LearningEngine(trade_attribution_engine=attribution_engine, performance_engine=performance_engine)

    result = engine.generate_lessons()
    logger.info(result.message)
    report = result.data
    if report is not None:
        logger.info("status=%s n_trades_analyzed=%d lessons=%d", report.status, report.n_trades_analyzed, len(report.lessons))
        for lesson in report.lessons[:10]:
            logger.info("  %s", lesson.statement)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "result": report.to_dict() if report else None}, indent=2),
        encoding="utf-8",
    )
    logger.info("")
    logger.info("Report written to %s", OUTPUT_PATH)


if __name__ == "__main__":
    main()
