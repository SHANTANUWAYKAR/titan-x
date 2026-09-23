"""
Module: retry_failed_a_plus_jobs.py
Description: Retry ONLY the (asset, timeframe) jobs that failed with a
    network/data-fetch error in the first A+ sweep (find_a_plus_gold_
    silver_btc_eth.py) -- BTCUSD 1d and ETHUSD 1h/4h/1d, all of which hit a
    live Yahoo Finance 429 (rate limit) mid-burst, not a real "no data"
    condition (binance ccxt ping succeeded immediately after). Runs
    sequentially (no process-pool burst) to avoid re-triggering the same
    rate limit, and merges its results into the existing summary JSON/
    report produced by the first sweep rather than overwriting the 8
    combos that already completed successfully.
Author: Shantanu Waykar
Version: 1.0.0
"""
from __future__ import annotations

import io
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from project_titan_x.engines.e24_strategy_research.engine import DEFAULT_STRATEGY_GRID, StrategyResearchEngine  # noqa: E402

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "models" / "e24_strategy_research"
REPORT_PATH = Path(__file__).resolve().parents[1] / "reports" / "A_PLUS_GOLD_SILVER_BTC_ETH_REPORT.md"
JSON_PATH = OUT_DIR / "a_plus_gold_silver_btc_eth_summary.json"

RETRY_JOBS = [("BTCUSD", "1d"), ("ETHUSD", "1h"), ("ETHUSD", "4h"), ("ETHUSD", "1d")]
YEARS = 10


def main() -> None:
    if not JSON_PATH.exists():
        raise SystemExit(f"missing {JSON_PATH} -- run find_a_plus_gold_silver_btc_eth.py first")
    summary = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    by_key = {(r["asset"], r["timeframe"]): r for r in summary["results"]}

    engine = StrategyResearchEngine()
    engine.initialize()

    for asset, tf in RETRY_JOBS:
        print(f"--- retry {asset} {tf} ---", flush=True)
        attempt_ok = False
        for attempt in range(1, 4):
            res = engine.research(
                asset, timeframe=tf, strategy_grid=DEFAULT_STRATEGY_GRID,
                years=YEARS, promote_if_validated=True,
            )
            if res.success:
                attempt_ok = True
                break
            print(f"  attempt {attempt} failed: {res.message} -- waiting 30s")
            time.sleep(30)

        if not attempt_ok:
            by_key[(asset, tf)] = {"asset": asset, "timeframe": tf, "error": res.message}
            print(f"  STILL FAILED after 3 attempts: {res.message}")
            continue

        report = res.data
        best = report.best
        row = {
            "asset": asset, "timeframe": tf,
            "n_candidates": report.n_candidates,
            "n_passed_stage0": len(report.passed),
            "promoted": report.promoted,
            "promotion_note": report.promotion_note,
        }
        if best is not None:
            row.update({
                "strategy": best.strategy, "params": best.params,
                "is_sharpe": round(best.is_sharpe, 3), "oos_sharpe": round(best.oos_sharpe, 3),
                "is_trades": best.is_trades, "win_rate": round(best.win_rate, 3),
                "is_max_dd": round(best.is_max_dd, 2), "expectancy": round(best.expectancy, 3),
                "avg_win_r": round(best.avg_win_r, 3), "avg_loss_r": round(best.avg_loss_r, 3),
                "profit_factor": round(best.profit_factor, 3),
            })
            print(f"  PASSED {len(report.passed)}/{report.n_candidates} -- BEST: {best.strategy}{best.params} "
                  f"IS_SR={best.is_sharpe:.2f} OOS_SR={best.oos_sharpe:.2f} trades={best.is_trades} "
                  f"win%={best.win_rate*100:.1f} -- promoted={report.promoted}")
        else:
            print(f"  0/{report.n_candidates} cleared Stage 0 -- no A+ strategy found for {asset} {tf}")
        by_key[(asset, tf)] = row

    # Rebuild ordered results in the original asset/timeframe order
    order = [("GOLD", "1h"), ("GOLD", "4h"), ("GOLD", "1d"),
             ("SILVER", "1h"), ("SILVER", "4h"), ("SILVER", "1d"),
             ("BTCUSD", "1h"), ("BTCUSD", "4h"), ("BTCUSD", "1d"),
             ("ETHUSD", "1h"), ("ETHUSD", "4h"), ("ETHUSD", "1d")]
    results = [by_key[k] for k in order if k in by_key]

    summary["results"] = results
    summary["generated_at"] = datetime.now(timezone.utc).isoformat()
    summary["note"] = "Merged: 8 combos from original sweep + retried BTCUSD_1d/ETHUSD_1h/4h/1d after Yahoo 429 cooldown."
    JSON_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nUpdated {JSON_PATH}")

    lines = [
        "# A+ Strategies -- GOLD, SILVER, BTCUSD, ETHUSD",
        "",
        f"Generated: {summary['generated_at']}",
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
    print(f"Updated {REPORT_PATH}")


if __name__ == "__main__":
    main()
