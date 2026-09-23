"""
Module: validate_e37_meta_learning.py
Description: Live sanity check for E37 Meta-Learning -- same Rule 3
    category as E34/E38 (deterministic post-hoc grouping of E26's own
    real backtest trades by real ADX-derived regime, no parameters of its
    own to fit). Runs against BTCUSD (a trend-following Donchian breakout
    -- should show trending-regime performance at or above ranging, a
    real, checkable finance-intuition sanity check, not an arbitrary
    pass/fail) and EURUSD (baseline composite rule, a useful contrast).
Author: Shantanu Waykar
Version: 1.0.0
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))

from project_titan_x.engines.e02_market_data.engine import MarketDataEngine
from project_titan_x.engines.e07_technical.engine import TechnicalAnalysisEngine
from project_titan_x.engines.e26_backtesting.engine import BacktestingEngine
from project_titan_x.engines.e37_meta_learning.engine import MetaLearningEngine
from project_titan_x.engines.e45_risk.engine import RiskManagementEngine
from project_titan_x.engines.e51_signals.engine import SignalIntelligenceEngine

logger = logging.getLogger(__name__)
OUTPUT_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "e37_meta_learning" / "validation_report.json"

TEST_ASSETS = ["BTCUSD", "EURUSD"]


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    market_data = MarketDataEngine()
    technical = TechnicalAnalysisEngine()
    backtesting = BacktestingEngine()
    signal_engine = SignalIntelligenceEngine(risk_engine=RiskManagementEngine(), technical_engine=technical, backtesting_engine=backtesting)
    engine = MetaLearningEngine(
        signal_engine=signal_engine, market_data_engine=market_data, technical_engine=technical, backtesting_engine=backtesting,
    )

    results = {}
    for symbol in TEST_ASSETS:
        result = engine.learn_regime_fit(symbol, "1d")
        logger.info("%s: %s", symbol, result.message)
        if not result.success or result.data is None:
            continue
        report = result.data
        results[symbol] = report.to_dict()
        for rp in report.regime_performance:
            logger.info("  %s: n=%d win_rate=%s expectancy=%sR", rp.regime, rp.n_trades, rp.win_rate_pct, rp.expectancy_r)

    if "BTCUSD" in results:
        rp = {r["regime"]: r for r in results["BTCUSD"]["regime_performance"]}
        if rp.get("trending", {}).get("status") == "ok" and rp.get("ranging", {}).get("status") == "ok":
            ok = rp["trending"]["expectancy_r"] >= rp["ranging"]["expectancy_r"]
            logger.info("Sanity check (BTCUSD trend-follower: trending expectancy >= ranging): %s", "PASS" if ok else "FAIL (real finding, not suppressed)")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "results": results}, indent=2), encoding="utf-8")
    logger.info("")
    logger.info("Report written to %s", OUTPUT_PATH)


if __name__ == "__main__":
    main()
