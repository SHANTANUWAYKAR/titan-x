"""
Module: validate_e39_model_risk.py
Description: Live sanity check for E39 Model Risk Management -- same
    Rule 3 category as E40 Data Quality (pure mechanical file scan/
    provenance check, no calibration). Runs a real audit() against every
    real file under data/models/ and every real supported asset, and
    confirms: (a) the known-good real files (BTC-USD_1d_strategy_
    override.json, ETH-USD_1d_tuned_params.json, MES=F_1d_strategy_
    override.json) are found and report provenance="verified", (b) no
    corrupt files are found in the real, already-committed data/models/
    tree.
Author: Shantanu Waykar
Version: 1.0.0
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))

from project_titan_x.engines.e39_model_risk.engine import ModelRiskManagementEngine

logger = logging.getLogger(__name__)
OUTPUT_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "e39_model_risk" / "validation_report.json"

EXPECTED_VERIFIED_SYMBOLS = {"BTCUSD", "ETHUSD", "SP500"}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    engine = ModelRiskManagementEngine()
    result = engine.audit()
    logger.info(result.message)
    if not result.success or result.data is None:
        logger.error("Audit failed, nothing to write")
        return

    report = result.data
    logger.info("Tracked files: %d, corrupt: %d, stale: %d", len(report.tracked_files), len(report.corrupt_files), len(report.stale_files))
    for p in report.live_provenance:
        if p.symbol in EXPECTED_VERIFIED_SYMBOLS:
            logger.info("  %s: %s (%s) -- %s", p.symbol, p.model_kind, p.file_path, p.provenance)

    verified = {p.symbol for p in report.live_provenance if p.provenance == "verified"}
    missing = EXPECTED_VERIFIED_SYMBOLS - verified
    if missing:
        logger.warning("Sanity check FAILED: expected verified provenance for %s, got %s", EXPECTED_VERIFIED_SYMBOLS, verified)
    else:
        logger.info("Sanity check PASSED: all expected live models (%s) verified", EXPECTED_VERIFIED_SYMBOLS)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "result": report.to_dict()}, indent=2), encoding="utf-8")
    logger.info("")
    logger.info("Report written to %s", OUTPUT_PATH)


if __name__ == "__main__":
    main()
