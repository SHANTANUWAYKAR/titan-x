"""
Module: retrain_all_e08.py
Description: Re-run train_e08_regime.train() for every platform asset
    against the now-deepened (multi-batch import) and deduped (see
    dedupe_daily_bars.py) data/processed/*_1d.parquet history. One-off
    runner, not itself part of the training pipeline.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-07-18
"""

import json
import logging

from project_titan_x.core.config.assets import list_assets
from project_titan_x.scripts.training.train_e08_regime import train

logger = logging.getLogger(__name__)


def main() -> dict:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    results = {}
    for asset in list_assets():
        try:
            report = train(symbol=asset.yahoo_symbol, timeframe="1d")
            results[asset.symbol] = {
                "yahoo_symbol": asset.yahoo_symbol,
                "n_bars": report.n_bars,
                "date_start": report.date_start,
                "date_end": report.date_end,
                "winner": report.winner,
            }
            logger.info("=== %s (%s): n_bars=%d range=%s -> %s winner=%s ===",
                        asset.symbol, asset.yahoo_symbol, report.n_bars,
                        report.date_start, report.date_end, report.winner)
        except Exception as e:
            results[asset.symbol] = {"error": str(e)}
            logger.error("%s failed: %s", asset.symbol, e)
    print(json.dumps(results, indent=2, default=str))
    return results


if __name__ == "__main__":
    main()
