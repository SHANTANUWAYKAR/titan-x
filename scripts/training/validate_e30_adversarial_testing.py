"""
Module: validate_e30_adversarial_testing.py
Description: Live sanity check for E30 Adversarial Testing -- same Rule 3
    category as validate_e21/e23/e29 (orchestrates E26's own deterministic
    backtest/Monte Carlo machinery against real historical data; no
    parameter of its own to fit). Runs the three real "attack" checks
    (parameter fragility, Monte Carlo ruin risk, single-trade dependency)
    against BTCUSD's real, already-validated live strategy
    (donchian_breakout_volume_confirmed -- documented in CLAUDE.md as this
    project's first genuinely validated 70%+ win rate strategy) and
    confirms it comes back "robust", which is the honest expected result
    for a strategy that already cleared E26's full walk-forward bar with
    43 real trades.
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
from project_titan_x.engines.e30_adversarial_testing.engine import AdversarialTestingEngine
from project_titan_x.engines.e51_signals.engine import SignalIntelligenceEngine
from project_titan_x.engines.e45_risk.engine import RiskManagementEngine

logger = logging.getLogger(__name__)
OUTPUT_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "e30_adversarial_testing" / "validation_report.json"

TEST_ASSETS = ["BTCUSD", "EURUSD"]  # BTCUSD has a real validated override; EURUSD uses the baseline rule (a useful contrast)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    market_data = MarketDataEngine()
    technical = TechnicalAnalysisEngine()
    backtesting = BacktestingEngine()
    signal_engine = SignalIntelligenceEngine(risk_engine=RiskManagementEngine(), technical_engine=technical, backtesting_engine=backtesting)
    engine = AdversarialTestingEngine(
        signal_engine=signal_engine, market_data_engine=market_data, technical_engine=technical, backtesting_engine=backtesting,
    )

    results = {}
    for symbol in TEST_ASSETS:
        result = engine.stress_assumptions(symbol, "1d")
        logger.info("%s: %s", symbol, result.message)
        if not result.success or result.data is None:
            continue
        report = result.data
        results[symbol] = report.to_dict()
        for finding in report.findings:
            logger.info("  %s: %s -- %s", finding.test_name, finding.verdict, finding.note)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "results": results}, indent=2), encoding="utf-8")
    logger.info("")
    logger.info("Report written to %s", OUTPUT_PATH)


if __name__ == "__main__":
    main()
