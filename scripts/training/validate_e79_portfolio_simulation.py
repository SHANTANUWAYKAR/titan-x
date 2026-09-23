"""Live sanity check for E79 Portfolio Simulation -- runs a real
historical-bootstrap Monte Carlo over 2 real positions. No calibration
(Rule 3): real resampled returns, no fitted parameters."""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))

from project_titan_x.engines.e02_market_data.engine import MarketDataEngine
from project_titan_x.engines.e79_portfolio_simulation.engine import PortfolioSimulationEngine, PositionInput

logger = logging.getLogger(__name__)
OUTPUT_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "e79_portfolio_simulation" / "validation_report.json"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    engine = PortfolioSimulationEngine(market_data_engine=MarketDataEngine())
    positions = [
        PositionInput("GOLD", "LONG", 4296.5, 4250.0, 5000.0),
        PositionInput("EURUSD", "LONG", 1.1557, 1.145, 5000.0),
    ]
    result = engine.simulate_forward(positions, horizon_days=20, n_simulations=1000)
    logger.info(result.message)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "result": result.data.to_dict() if result.data else None}, indent=2), encoding="utf-8")
    logger.info("Report written to %s", OUTPUT_PATH)


if __name__ == "__main__":
    main()
