"""
Module: find_a_plus_gold_silver_btc_eth.py
Description: Find and PROMOTE the best real, Stage-0-validated strategy for
    each of the user's four main pairs (GOLD, SILVER, BTCUSD, ETHUSD) across
    1h/4h/1d, using the exact same engine/bar every other live override on
    this platform is held to (StrategyResearchEngine.research() ->
    BacktestingEngine.run_backtest(..., timeframe=tf) -> the measured,
    timeframe-aware Stage 0 selection-score floor in
    engines/e26_backtesting/engine.py's STAGE0_TIMEFRAME_THRESHOLDS).

    "A+" here means: cleared a bar calibrated to beat 95% of what a
    167+-candidate grid manufactures from PURE NOISE at that timeframe (see
    docs/STAGE0_FINDINGS.md). It does not mean "big Sharpe" or "looks good" --
    those numbers are cheap and this project has direct proof (137/150 noise
    paths clearing the OLD bar at 4h) that they lie. Reports an honest zero
    for any (asset, timeframe) where nothing clears it -- never fabricates a
    pass. promote_if_validated=True is used deliberately: the user explicitly
    asked for A+ strategies to be created for these four assets, so writing
    the resulting strategy_override.json (which e51_signals reads live) is
    the intended, user-approved action here -- same mechanism
    research_best_strategy_universe.py deliberately leaves OFF by default.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import io
import json
import logging
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from project_titan_x.engines.e24_strategy_research.engine import DEFAULT_STRATEGY_GRID, StrategyResearchEngine  # noqa: E402

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.WARNING, format="%(message)s")

ASSETS = ["GOLD", "SILVER", "BTCUSD", "ETHUSD"]
TIMEFRAMES = ["1h", "4h", "1d"]
YEARS = 10
OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "models" / "e24_strategy_research"
REPORT_PATH = Path(__file__).resolve().parents[1] / "reports" / "A_PLUS_GOLD_SILVER_BTC_ETH_REPORT.md"
JSON_PATH = OUT_DIR / "a_plus_gold_silver_btc_eth_summary.json"


def _workers() -> int:
    return max(1, min(6, (os.cpu_count() or 4)))


def main() -> None:
    engine = StrategyResearchEngine()
    engine.initialize()

    n_workers = _workers()
    print(f"Grid size: {sum(len(v) for v in DEFAULT_STRATEGY_GRID.values())} candidates/run")
    print(f"Jobs: {len(ASSETS)} assets x {len(TIMEFRAMES)} timeframes = {len(ASSETS)*len(TIMEFRAMES)}")
    print(f"Workers: {n_workers}\n")

    pool = ProcessPoolExecutor(max_workers=n_workers)
    results = []
    for asset in ASSETS:
        for tf in TIMEFRAMES:
            print(f"--- {asset} {tf} ---", flush=True)
            try:
                res = engine.research(
                    asset, timeframe=tf, strategy_grid=DEFAULT_STRATEGY_GRID,
                    years=YEARS, promote_if_validated=True,
                    parallel=True, executor=pool,
                )
            except BrokenProcessPool:
                print("  pool died -- rebuilding, retrying sequentially")
                pool.shutdown(wait=False)
                pool = ProcessPoolExecutor(max_workers=n_workers)
                res = engine.research(
                    asset, timeframe=tf, strategy_grid=DEFAULT_STRATEGY_GRID,
                    years=YEARS, promote_if_validated=True,
                )

            if not res.success:
                print(f"  FAILED: {res.message}")
                results.append({"asset": asset, "timeframe": tf, "error": res.message})
                continue

            report = res.data
            best = report.best
            row = {
                "asset": asset,
                "timeframe": tf,
                "n_candidates": report.n_candidates,
                "n_passed_stage0": len(report.passed),
                "promoted": report.promoted,
                "promotion_note": report.promotion_note,
            }
            if best is not None:
                row.update({
                    "strategy": best.strategy,
                    "params": best.params,
                    "is_sharpe": round(best.is_sharpe, 3),
                    "oos_sharpe": round(best.oos_sharpe, 3),
                    "is_trades": best.is_trades,
                    "win_rate": round(best.win_rate, 3),
                    "is_max_dd": round(best.is_max_dd, 2),
                    "expectancy": round(best.expectancy, 3),
                    "avg_win_r": round(best.avg_win_r, 3),
                    "avg_loss_r": round(best.avg_loss_r, 3),
                    "profit_factor": round(best.profit_factor, 3),
                })
                print(f"  PASSED {len(report.passed)}/{report.n_candidates} -- "
                      f"BEST: {best.strategy}{best.params} IS_SR={best.is_sharpe:.2f} "
                      f"OOS_SR={best.oos_sharpe:.2f} trades={best.is_trades} "
                      f"win%={best.win_rate*100:.1f} avgWinR={best.avg_win_r:.2f} "
                      f"avgLossR={best.avg_loss_r:.2f} -- promoted={report.promoted}")
            else:
                print(f"  0/{report.n_candidates} cleared Stage 0 -- no A+ strategy found for {asset} {tf}")
            results.append(row)

    pool.shutdown(wait=True)

    JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "years": YEARS, "assets": ASSETS, "timeframes": TIMEFRAMES,
        "bar": "engines/e26_backtesting/engine.py STAGE0_TIMEFRAME_THRESHOLDS (timeframe-aware, "
               "measured 95th percentile vs synthetic no-edge null; see docs/STAGE0_FINDINGS.md)",
        "results": results,
    }, indent=2), encoding="utf-8")
    print(f"\nSaved machine-readable summary to {JSON_PATH}")

    # Markdown report
    lines = [
        "# A+ Strategies -- GOLD, SILVER, BTCUSD, ETHUSD",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "**Bar used:** Stage 0 timeframe-aware selection-score floor "
        "(`engines/e26_backtesting/engine.py::STAGE0_TIMEFRAME_THRESHOLDS`) -- "
        "measured as the 95th percentile of the best score a 200+ candidate grid "
        "manufactures from pure-noise (no-edge) synthetic data at that timeframe. "
        "See `docs/STAGE0_FINDINGS.md`. This is a materially stricter bar than "
        "\"positive Sharpe\" -- most candidates that look good on IS Sharpe alone "
        "do NOT clear it.",
        "",
        "| Asset | TF | Candidates | Passed Stage0 | Best strategy | IS Sharpe | OOS Sharpe | Trades | Win% | AvgWinR | AvgLossR | PF | Promoted |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        if "error" in r:
            lines.append(f"| {r['asset']} | {r['timeframe']} | -- | -- | ERROR: {r['error']} | | | | | | | |")
            continue
        if "strategy" in r:
            lines.append(
                f"| {r['asset']} | {r['timeframe']} | {r['n_candidates']} | {r['n_passed_stage0']} | "
                f"{r['strategy']}{r['params']} | {r['is_sharpe']} | {r['oos_sharpe']} | {r['is_trades']} | "
                f"{r['win_rate']*100:.1f}% | {r['avg_win_r']} | {r['avg_loss_r']} | {r['profit_factor']} | "
                f"{'YES' if r['promoted'] else 'no'} |"
            )
        else:
            lines.append(
                f"| {r['asset']} | {r['timeframe']} | {r['n_candidates']} | 0 | "
                f"*none cleared Stage 0* | -- | -- | -- | -- | -- | -- | -- | no |"
            )
    lines.append("")
    n_promoted = sum(1 for r in results if r.get("promoted"))
    lines.append(f"**{n_promoted} of {len(results)} (asset, timeframe) combos produced a live-promotable A+ strategy.**")
    lines.append("")
    lines.append("A zero-pass row is a real, honest result -- it means the grid found nothing at that "
                 "timeframe that beats what pure noise already produces 95% of the time, not a bug.")
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Saved report to {REPORT_PATH}")


if __name__ == "__main__":
    main()
