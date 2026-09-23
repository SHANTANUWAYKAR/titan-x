"""
Module: capture_bybit_trades.py
Description: Thin CLI wrapper around core.data_providers.bybit_trade_feed.
    capture_and_persist -- the real logic (feed, aggregation,
    merge-not-overwrite persistence) lives there as an importable library
    function, not here, so it's reusable from Python directly (e.g.
    e00_titan_brain.engine.TitanBrainEngine.schedule_bybit_capture calls
    it as a recurring job) without shelling out to this script.

    This script remains useful on its own for a manual, one-shot capture
    (e.g. `python scripts/streaming/capture_bybit_trades.py --duration 300`),
    or for wiring into an OS-level scheduler (Task Scheduler/cron) as an
    alternative to E00's in-process scheduler.
Author: Shantanu Waykar
Version: 1.0.0
"""

import argparse
import asyncio
import logging

from project_titan_x.core.data_providers.bybit_trade_feed import capture_and_persist

logger = logging.getLogger(__name__)


def main() -> dict[str, int]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=int, default=300, help="Capture window in seconds")
    parser.add_argument("--bar-seconds", type=int, default=60, help="Footprint bar duration in seconds")
    parser.add_argument("--symbols", nargs="+", default=["BTCUSD", "ETHUSD"])
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    counts = asyncio.run(capture_and_persist(args.duration, args.bar_seconds, args.symbols))
    for symbol, n in counts.items():
        logger.info("%s: %d total bars now saved (data/processed/live_order_flow/)", symbol, n)
    return counts


if __name__ == "__main__":
    main()
