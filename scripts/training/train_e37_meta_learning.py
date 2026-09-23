"""
Module: train_e37_meta_learning.py
Description: Builds `data/models/e37_meta_learning/regime_fit_database.json`
    -- runs E37's real learn_regime_fit() (a full E26 backtest per asset)
    ONCE per supported asset and persists each verdict, so
    e51_signals.generate_signal() can read a cheap precomputed file
    instead of re-running a real backtest on every live signal call (the
    same "don't compute the same expensive thing twice" lesson
    train_e22_alpha_research.py's own docstring already documents).
    Re-written on every run against fresh data, never accumulating stale
    duplicates -- same convention as train_e22_alpha_research.py.
Author: Shantanu Waykar
Version: 1.0.0
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))

from project_titan_x.core.config import list_assets
from project_titan_x.engines.e02_market_data.engine import MarketDataEngine
from project_titan_x.engines.e07_technical.engine import TechnicalAnalysisEngine
from project_titan_x.engines.e26_backtesting.engine import BacktestingEngine
from project_titan_x.engines.e37_meta_learning.engine import REGIME_FIT_DB_PATH, MetaLearningEngine
from project_titan_x.engines.e45_risk.engine import RiskManagementEngine
from project_titan_x.engines.e51_signals.engine import SignalIntelligenceEngine

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    market_data = MarketDataEngine()
    technical = TechnicalAnalysisEngine()
    backtesting = BacktestingEngine()
    signal_engine = SignalIntelligenceEngine(risk_engine=RiskManagementEngine(), technical_engine=technical, backtesting_engine=backtesting)
    engine = MetaLearningEngine(
        signal_engine=signal_engine, market_data_engine=market_data, technical_engine=technical, backtesting_engine=backtesting,
    )

    db: dict[str, dict] = {}
    for asset in list_assets():
        result = engine.learn_regime_fit(asset.symbol, "1d")
        if not result.success or result.data is None:
            logger.warning("%s: %s -- skipped", asset.symbol, result.message)
            continue
        report = result.data
        logger.info("%s: %s", asset.symbol, result.message)
        db[asset.symbol] = {
            "verdict": report.verdict,
            "best_regime": report.best_regime,
            "strategy_label": report.strategy_label,
            "regime_performance": [rp.to_dict() for rp in report.regime_performance],
            "generated_at": report.generated_at.isoformat(),
        }

    REGIME_FIT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGIME_FIT_DB_PATH.write_text(json.dumps(db, indent=2), encoding="utf-8")
    logger.info("")
    regime_dependent = [s for s, v in db.items() if v["verdict"] == "regime_dependent"]
    logger.info("Regime-dependent assets (will get a live confluence nudge): %s", regime_dependent)
    logger.info("Database written to %s (%d asset(s))", REGIME_FIT_DB_PATH, len(db))


if __name__ == "__main__":
    main()
