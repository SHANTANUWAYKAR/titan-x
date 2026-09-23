"""
Module: set_best_strategy_per_pair.py
Description: Find and promote the best REAL, Stage-0-validated strategy per
    (pair, timeframe), fixing the specific methodological flaw found in
    scripts/find_a_plus_gold_silver_btc_eth.py on 2026-09-14.

    THE FLAW THIS FIXES. find_a_plus_gold_silver_btc_eth.py searched with
    `YEARS = 10` for every timeframe, but the Stage 0 scorer
    (research/score_overrides_stage0.py) validates on `df.tail(12000)` --
    the most RECENT 12,000 bars. Selection and validation therefore ran on
    different windows, and on gold the gap was decisive: the A+ report
    recorded GC=F_1h at IS Sharpe 2.844 / OOS 3.563 over ~10 years, while
    the scorer re-measured the SAME strategy on recent data at IS Sharpe
    0.073, null percentile 15.3 -- i.e. worse than 85% of pure noise. Same
    story at 4h (2.549 -> 0.195, percentile 10.0). Both were correctly
    tagged UNVALIDATED and never went live (the deny-by-default gate did
    its job), but the SEARCH had spent its whole budget optimising for a
    window that no longer resembles the market being traded.

    Gold is the one asset scored against its OWN null rather than a
    cross-asset proxy (`null_is_proxy: False`), which makes that the most
    trustworthy measurement in the entire book -- and it says the edge is
    not present recently.

    THE FIX. Align the selection window to the validation window, per
    timeframe, so the grid optimises on the same data the bar will judge
    it on. Bar counts mirror the Stage 0 null campaigns' own calibration
    (docs/STAGE0_FINDINGS.md section 2): 1h and 4h nulls were run on
    12,000 bars, 1d on 6,000.

    This does NOT make a passing result more likely -- if anything it makes
    it harder, by removing the option of winning on stale history. That is
    the point: a strategy that only worked 8 years ago is not a strategy
    to trade next week.

    Promotion still writes a strategy_override.json, but that file is
    INERT until it carries an explicit `"stage0": {"status": "VALIDATED"}`
    tag (e51_signals._load_strategy_override is deny-by-default since
    2026-09-13). So this script is only step 1 of 3; run the scorer and
    the tagger afterwards:

        python research/score_overrides_stage0.py --bars 12000 --workers 6
        python scripts/apply_stage0_tags.py

    Nothing goes live on this script's say-so alone.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import argparse
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

from project_titan_x.engines.e24_strategy_research.engine import (  # noqa: E402
    DEFAULT_STRATEGY_GRID,
    StrategyResearchEngine,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.WARNING, format="%(message)s")

DEFAULT_PAIRS = ["GOLD", "SILVER", "BTCUSD", "ETHUSD"]
TIMEFRAMES = ["1h", "4h", "1d"]

# This project's OWN style convention, read off reports/
# MASTER_BACKTEST_RESULTS.csv's tf_style column rather than invented here
# (1m/5m/15m -> Intraday, 1h/4h -> Swing, 1d -> Positional), and matching
# the strategies_by_style/{INTRADAY,SWING,POSITIONAL} directories.
TF_STYLE = {
    "1m": "Intraday", "5m": "Intraday", "15m": "Intraday", "30m": "Intraday",
    "1h": "Swing", "4h": "Swing",
    "1d": "Positional", "1wk": "Positional",
}

# Timeframes with a real synthetic no-edge null (research/
# synthetic_null_GCF_*.json). A winner at any OTHER timeframe CANNOT be
# scored against noise at all -- it is a search result, not a validated
# edge, and this script labels it that way rather than letting it read
# like the 1h/4h/1d rows beside it.
TF_WITH_NULL = {"1h", "4h", "1d"}

# Selection window per timeframe, chosen to land near the SAME bar count
# the Stage 0 null was calibrated on (and the scorer validates on), rather
# than a single flat `years` for every timeframe. Approximate by design --
# real availability bounds these anyway (fetch_ohlcv never fabricates
# history), and the scorer's own tail(12000) is the authority regardless.
SELECTION_YEARS_BY_TF = {
    # ~13k bars on a 6.5h equity session, far more on 24/7 crypto. There is
    # no 15m null to match against (see TF_WITH_NULL), so this one is chosen
    # for a sane bar/trade count rather than to mirror a null's calibration.
    "15m": 2,
    "1h": 2,    # ~12,000 hourly bars
    "4h": 8,    # ~12,000 4-hour bars
    "1d": 10,   # 1d null used 6,000 bars (~24y); 10 is what most assets actually have
}

REPORT_PATH = Path(__file__).resolve().parents[1] / "reports" / "BEST_STRATEGY_PER_PAIR.md"
JSON_PATH = (
    Path(__file__).resolve().parents[1]
    / "data" / "models" / "e24_strategy_research" / "best_strategy_per_pair.json"
)


def _workers() -> int:
    return max(1, min(6, (os.cpu_count() or 4)))


def _write_json(results: list[dict]) -> None:
    JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "selection_years_by_tf": SELECTION_YEARS_BY_TF,
        "tf_style": TF_STYLE,
        "timeframes_with_null": sorted(TF_WITH_NULL),
        "results": results,
    }, indent=2), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", nargs="*", default=DEFAULT_PAIRS, help="Asset symbols (registry names).")
    ap.add_argument("--timeframes", nargs="*", default=TIMEFRAMES)
    ap.add_argument("--no-promote", action="store_true", help="Search and report only; write no override files.")
    args = ap.parse_args()

    engine = StrategyResearchEngine()
    engine.initialize()

    n_workers = _workers()
    grid_size = sum(len(v) for v in DEFAULT_STRATEGY_GRID.values())
    jobs = len(args.pairs) * len(args.timeframes)
    print(f"Grid: {grid_size} candidates/run | Jobs: {jobs} | Workers: {n_workers}")
    print(f"Selection window per tf (aligned to the Stage 0 validation window): {SELECTION_YEARS_BY_TF}\n", flush=True)

    pool = ProcessPoolExecutor(max_workers=n_workers)
    results: list[dict] = []

    for pair in args.pairs:
        for tf in args.timeframes:
            years = SELECTION_YEARS_BY_TF.get(tf, 10)
            print(f"--- {pair} {tf} (selection window: {years}y) ---", flush=True)
            kwargs = dict(
                timeframe=tf, strategy_grid=DEFAULT_STRATEGY_GRID, years=years,
                promote_if_validated=not args.no_promote,
            )
            try:
                res = engine.research(pair, parallel=True, executor=pool, **kwargs)
            except BrokenProcessPool:
                print("  pool died -- rebuilding, retrying sequentially", flush=True)
                pool.shutdown(wait=False)
                pool = ProcessPoolExecutor(max_workers=n_workers)
                res = engine.research(pair, **kwargs)

            if not res.success:
                print(f"  FAILED: {res.message}", flush=True)
                results.append({"pair": pair, "timeframe": tf, "error": res.message})
                continue

            report = res.data
            passed = list(getattr(report, "passed", []) or [])
            best = getattr(report, "best", None)
            row: dict = {
                "pair": pair,
                "timeframe": tf,
                "selection_years": years,
                "candidates": grid_size,
                "n_passed": len(passed),
            }
            if best is None or not passed:
                row["best"] = None
                print("  -> nothing cleared the Stage 0 selection floor (honest zero)", flush=True)
            else:
                # expectancy/profit_factor are reported deliberately, not just
                # Sharpe and win rate: this engine's own field comment records a
                # real measured case (ETHUSD 1d, 65.1% win rate, avg win +7.16 vs
                # avg loss -33.99, expectancy -7.195) where a good-looking win
                # rate carried a NEGATIVE expectancy. Expectancy is the number
                # that decides whether a rule is tradeable.
                row["best"] = {
                    "strategy": best.strategy,
                    "params": best.params,
                    "is_sharpe": best.is_sharpe,
                    "oos_sharpe": best.oos_sharpe,
                    "is_trades": best.is_trades,
                    "is_max_dd": best.is_max_dd,
                    "win_rate": best.win_rate,
                    "expectancy": best.expectancy,
                    "profit_factor": best.profit_factor,
                    "avg_win_r": best.avg_win_r,
                    "avg_loss_r": best.avg_loss_r,
                }
                b = row["best"]
                flag = "" if b["expectancy"] > 0 else "   <-- NEGATIVE EXPECTANCY"
                print(f"  -> {b['strategy']} IS={b['is_sharpe']} OOS={b['oos_sharpe']} "
                      f"trades={b['is_trades']} exp={b['expectancy']} PF={b['profit_factor']}{flag}", flush=True)
            row["style"] = TF_STYLE.get(tf, "Unknown")
            row["null_available"] = tf in TF_WITH_NULL
            results.append(row)

            # Checkpoint after EVERY job, not once at the end. A full
            # 29-pair sweep is hours long, and this session has already
            # lost two multi-hour background runs to an editor/extension
            # crash -- writing incrementally means a crash costs one job,
            # not the whole sweep.
            _write_json(results)

    pool.shutdown(wait=True)
    _write_json(results)

    lines = [
        "# Best strategy per pair -- selection window aligned to the validation window",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "Selection ran on the SAME recent window the Stage 0 scorer validates on "
        "(see this script's own docstring for the gold 2.844 -> 0.073 discrepancy that motivated it). "
        "A promoted override here is still INERT until `scripts/apply_stage0_tags.py` writes an "
        "explicit VALIDATED tag -- promotion alone does not put anything live.",
        "",
        "**A row at a timeframe with no synthetic null (anything outside 1h/4h/1d) is a SEARCH "
        "RESULT, not a validated edge.** It has not been, and cannot currently be, compared against "
        "what the same grid manufactures from pure noise -- which is the entire point of Stage 0. "
        "Those rows are marked `NO NULL` and must not be traded on this evidence alone.",
        "",
    ]
    for style in ("Intraday", "Swing", "Positional"):
        style_rows = [r for r in results if r.get("style") == style]
        if not style_rows:
            continue
        lines += [
            f"## {style}",
            "",
            "| Pair | TF | Null? | Passed floor | Best strategy | IS SR | OOS SR | Trades | Win% | Expectancy | PF |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for r in style_rows:
            nul = "yes" if r.get("null_available") else "**NO NULL**"
            if r.get("error"):
                lines.append(f"| {r['pair']} | {r['timeframe']} | {nul} | ERROR | {r['error'][:40]} | -- | -- | -- | -- | -- | -- |")
            elif not r.get("best"):
                lines.append(f"| {r['pair']} | {r['timeframe']} | {nul} | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |")
            else:
                b = r["best"]
                lines.append(f"| {r['pair']} | {r['timeframe']} | {nul} | {r['n_passed']} | "
                             f"{b['strategy']} | {b['is_sharpe']:.3f} | {b['oos_sharpe']:.3f} | {b['is_trades']} | "
                             f"{b['win_rate']:.3f} | {b['expectancy']:.3f} | {b['profit_factor']:.3f} |")
        lines.append("")
    lines += [
        "",
        "**Next, required before anything trades:**",
        "```bash",
        "python research/score_overrides_stage0.py --bars 12000 --workers 6",
        "python scripts/apply_stage0_tags.py",
        "```",
    ]
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {REPORT_PATH}")
    print(f"Wrote {JSON_PATH}")


if __name__ == "__main__":
    main()
