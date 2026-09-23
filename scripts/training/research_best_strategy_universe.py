"""
Module: research_best_strategy_universe.py
Description: Runs e24_strategy_research.StrategyResearchEngine across
    EVERY currently supported asset (forex, crypto, commodities, indices,
    bonds, futures, and the new price/technical-scope equities -- see
    core/config/assets.py) with a comprehensive strategy/parameter grid,
    graded by E26 Backtesting Laboratory's real IS/OOS validation bar
    (never weakened). "Best strategy ever" is not a single asserted
    archetype -- this is the same honest discipline as every other
    research script in this project (research_signal_strategies*.py):
    test every major known archetype (trend-following EMA stack, golden/
    death cross, MACD crossover, Donchian/Turtle breakout, RSI mean-
    reversion, Bollinger mean-reversion, regime-adaptive) against every
    asset, and report what actually clears the bar -- honestly reporting
    zero passes for an asset if that's the real result, same as every
    prior research run this project has done.

    years=10 -- matches the master prompt's own "10+ years data where
    possible" backtesting requirement; assets with a shorter real history
    (MES=F futures since ~2019, BTCUSD/ETHUSD since ~2014-2015, some
    equities) simply get whatever real history actually exists (now
    correctly bounded since the e02_market_data.fetch_ohlcv years-bug fix
    made during this same session -- years was previously silently
    ignored for every daily-timeframe fetch).

    promote_if_validated is NOT used here -- this script only reports.
    Wiring a winner into e51_signals live is a deliberate, separate,
    user-approved follow-up step (see e24_strategy_research/engine.py's
    own promote_if_validated flag), never automatic.
Author: Shantanu Waykar
Version: 1.0.0
"""

import json
import logging
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))

from project_titan_x.core.config.assets import list_assets
from project_titan_x.engines.e24_strategy_research.engine import DEFAULT_STRATEGY_GRID, StrategyResearchEngine

logger = logging.getLogger(__name__)

_MODELS_DIR = Path(__file__).resolve().parents[2] / "data" / "models" / "e24_strategy_research"
YEARS = 10


def _default_workers() -> int:
    """Memory-bound, not CPU-bound: every worker re-imports this project's
    full dependency tree (pandas/scipy/sklearn, and transitively torch/
    transformers via the engine package), so worker count is limited by
    RAM per process, not by core count. Found the hard way 2026-08-21 --
    a first attempt at max_workers=os.cpu_count() (16 here) killed a
    child process outright, and because ProcessPoolExecutor poisons the
    whole pool when any worker dies abruptly, EVERY remaining asset in
    the sweep then failed with "the process pool is not usable anymore"
    (28 of 29 assets lost in one run). Capped at 6 and made recoverable
    below."""
    return max(1, min(6, (os.cpu_count() or 4)))


class _PoolManager:
    """Owns the shared worker pool for a whole sweep and survives its
    death. Reusing ONE warmed pool across all 29 assets is the real win
    (e24.research()'s `executor` docstring calls this exact script out as
    the intended caller) -- each worker pays the heavy import cost once
    for the life of the pool instead of once per symbol. But a shared
    pool is also a shared point of failure, so a broken pool is rebuilt
    and the asset retried once, then falls back to this engine's ordinary
    sequential path rather than abandoning the rest of the sweep."""

    def __init__(self, workers: Optional[int]) -> None:
        self._workers = workers or _default_workers()
        self._executor: Optional[ProcessPoolExecutor] = None
        logger.info("Parallel candidate search across %d worker process(es).", self._workers)

    def _get(self) -> ProcessPoolExecutor:
        if self._executor is None:
            self._executor = ProcessPoolExecutor(max_workers=self._workers)
        return self._executor

    def close(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=True)
            self._executor = None

    def research(self, engine, asset, timeframe: str, years: int):
        for attempt in (1, 2):
            try:
                return engine.research(
                    asset.symbol, timeframe=timeframe, strategy_grid=DEFAULT_STRATEGY_GRID,
                    years=years, promote_if_validated=False,
                    parallel=True, executor=self._get(),
                )
            except BrokenProcessPool:
                logger.warning(
                    "Worker pool died on %s (attempt %d) -- rebuilding.", asset.symbol, attempt
                )
                self.close()
        logger.warning("Falling back to sequential search for %s.", asset.symbol)
        return engine.research(
            asset.symbol, timeframe=timeframe, strategy_grid=DEFAULT_STRATEGY_GRID,
            years=years, promote_if_validated=False,
        )


def main() -> None:
    # Added 2026-08-21: --timeframe/--years CLI args, both defaulting to
    # this script's original hardcoded behavior ("1d", YEARS=10) so
    # `python research_best_strategy_universe.py` with no args is
    # completely unchanged. Real gap this closes: intraday timeframes
    # had essentially zero validated-strategy coverage (only
    # BTC-USD_1d had a live override going into this) -- this script was
    # the only real sweep tool that existed, but was daily-only.
    # Intraday timeframes have real, honest history caps from Yahoo
    # Finance regardless of YEARS requested (1h->730d, 15m/5m->60d,
    # 1m->7d -- see e02_market_data.engine.YFINANCE_PERIOD) --
    # research()/fetch_ohlcv already bound to whatever's actually
    # available, never fabricate the rest, so passing YEARS=10 for an
    # intraday run is harmless (just unused past the real cap), not
    # dishonest.
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeframe", default="1d")
    parser.add_argument("--years", type=int, default=YEARS)
    parser.add_argument(
        "--workers", type=int, default=None,
        help="Worker processes for the parallel candidate search (default: min(6, cpu_count)).",
    )
    args = parser.parse_args()
    timeframe, years = args.timeframe, args.years

    # Timeframe-specific output file -- an intraday run must never
    # silently overwrite the daily sweep's own real, already-reviewed
    # report.
    output_path = _MODELS_DIR / (
        "universe_sweep_report.json" if timeframe == "1d" else f"universe_sweep_report_{timeframe}.json"
    )

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    engine = StrategyResearchEngine()
    engine.initialize()

    assets = list_assets()
    logger.info(
        "Running strategy sweep across %d assets, %d strategy archetypes (timeframe=%s, years=%d)...",
        len(assets), len(DEFAULT_STRATEGY_GRID), timeframe, years,
    )

    # ONE shared, already-warmed ProcessPoolExecutor reused across every
    # asset -- exactly the usage e24.research()'s own `executor` docstring
    # calls out as "where this feature's real payoff is": each worker pays
    # this project's heavy import cost (pandas/scipy/sklearn) ONCE for the
    # life of the pool instead of once per symbol. Every sweep before
    # 2026-08-21 ran fully sequential on one core despite the parallel
    # path existing and being tested, because `parallel` defaults to False
    # and this script never passed it. Nothing about WHAT is computed
    # changes -- each candidate still runs through E26's real, unchanged
    # run_backtest; only which core it runs on does.
    all_results: dict[str, dict] = {}
    pool = _PoolManager(args.workers)
    try:
        for asset in assets:
            logger.info("--- %s (%s) ---", asset.symbol, asset.yahoo_symbol)
            result = pool.research(engine, asset, timeframe, years)
            if not result.success:
                logger.warning("%s: %s", asset.symbol, result.message)
                all_results[asset.symbol] = {"error": result.message}
                continue
            report = result.data
            logger.info("%s: %d/%d passed. Best: %s", asset.symbol, len(report.passed), report.n_candidates, report.best.to_dict() if report.best else "none")
            all_results[asset.symbol] = {
                "asset_class": asset.asset_class.value,
                "n_candidates": report.n_candidates,
                "passed": [c.to_dict() for c in report.passed],
                "best": report.best.to_dict() if report.best else None,
            }
    finally:
        pool.close()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "timeframe": timeframe,
        "years_requested": years,
        "validation_bar": "IS trades>=30, IS Sharpe>0.5, max DD<25%, OOS Sharpe>0 (E26 Backtesting Laboratory)",
        "n_assets": len(assets),
        "results": all_results,
    }
    output_path.write_text(json.dumps(summary, indent=2))

    winners = {sym: r["best"] for sym, r in all_results.items() if r.get("best")}
    print(f"\n{'='*100}")
    print(f"{len(winners)} of {len(assets)} assets have at least one validated strategy.")
    print(f"{'='*100}")
    for sym, best in sorted(winners.items(), key=lambda kv: -kv[1]["oos_sharpe"]):
        print(f"  {sym:<12} {best['strategy']:<20} {best['params']!s:<28} IS Sharpe={best['is_sharpe']:>6.2f}  OOS Sharpe={best['oos_sharpe']:>6.2f}  WinRate={best['win_rate']*100:>5.1f}%  Trades={best['is_trades']}")
    no_edge = [sym for sym in all_results if sym not in winners and "error" not in all_results[sym]]
    if no_edge:
        print(f"\nNo validated edge found for: {', '.join(sorted(no_edge))}")
    errored = [sym for sym, r in all_results.items() if "error" in r]
    if errored:
        print(f"\nCould not evaluate (data error): {', '.join(sorted(errored))}")
    print(f"\nFull report saved to {output_path}")


if __name__ == "__main__":
    main()
