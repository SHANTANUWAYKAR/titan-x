"""
Module: run_ict_smc_research.py
Description: Grades research/ict_smc_confluence.py against E26's real,
    unweakened validation bar across the focus markets, and reports what
    actually happens -- including "nothing validated", which is a result.

    Runs through StrategyResearchEngine so the ICT/SMC candidate is judged
    by exactly the same walk-forward split, transaction costs and
    pass/fail criteria as every shipped strategy. Injecting it into the
    STRATEGIES registry for the duration of the run is what makes that
    possible; the entry is removed again in a finally block so nothing
    leaks into the live registry (research/ must not change engines/).

    promote_if_validated is never passed. This script only reports.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from project_titan_x.engines.e24_strategy_research import strategies as strategies_mod
from project_titan_x.engines.e24_strategy_research.engine import StrategyResearchEngine
from project_titan_x.research.ict_smc_confluence import ict_smc_confluence

NAME = "ict_smc_confluence"
FOCUS = ["GOLD", "SILVER", "BTCUSD", "ETHUSD", "EURUSD", "GBPUSD", "USDJPY"]

GRID = [
    {"min_confluence": c, "atr_mult": a, "max_bars_sweep_to_entry": w,
     "require_killzone": kz, "use_cvd": cvd}
    for c in (2, 3, 4)
    for a in (2.0, 3.0)
    for w in (10, 20)
    for kz in (False, True)
    for cvd in (True, False)
]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--timeframe", action="append", choices=("1h", "4h", "1d"))
    p.add_argument("--symbols", default=",".join(FOCUS))
    args = p.parse_args()
    timeframes = tuple(args.timeframe) if args.timeframe else ("4h", "1d")
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    engine = StrategyResearchEngine()
    engine.initialize()

    # Temporary registration -- removed in `finally` so the live registry is
    # byte-identical after this script runs.
    strategies_mod.STRATEGIES[NAME] = ict_smc_confluence
    out: dict = {}
    try:
        print(f"Grading {NAME} on {len(GRID)} configs x {len(symbols)} symbols "
              f"x {len(timeframes)} timeframe(s), against E26's unweakened bar.\n")
        print(f"{'ASSET':8} {'TF':4} {'PASSED':>10} {'EXPECT':>8} {'R:R':>6} {'WIN%':>6} {'OOS':>6} {'TRD':>5}  BEST CONFIG")
        for sym in symbols:
            for tf in timeframes:
                try:
                    r = engine.research(sym, timeframe=tf, strategy_grid={NAME: GRID},
                                        years=10, promote_if_validated=False)
                except Exception as e:
                    print(f"{sym:8} {tf:4}  ERROR {type(e).__name__}: {str(e)[:40]}")
                    continue
                if not r.success:
                    print(f"{sym:8} {tf:4}  {r.message[:56]}")
                    continue
                best, n = r.data.best, r.data.n_candidates
                key = f"{sym}_{tf}"
                if not best:
                    print(f"{sym:8} {tf:4} {'0/' + str(n):>10}   -- no config cleared the bar")
                    out[key] = None
                    continue
                rr = abs(best.avg_win_r / best.avg_loss_r) if best.avg_loss_r else 0.0
                print(f"{sym:8} {tf:4} {str(len(r.data.passed)) + '/' + str(n):>10} "
                      f"{best.expectancy:>8.2f} {rr:>5.2f}R {best.win_rate * 100:>5.1f}% "
                      f"{best.oos_sharpe:>6.2f} {best.is_trades:>5}  {best.params}")
                out[key] = {**best.to_dict(), "reward_risk": round(rr, 3)}
    finally:
        strategies_mod.STRATEGIES.pop(NAME, None)

    wins = [k for k, v in out.items() if v]
    print(f"\n{len(wins)} of {len(out)} asset/timeframe pairs validated.")
    if not wins:
        print("No ICT/SMC confluence configuration cleared the bar on these markets.")
        print("That is a real finding, not a failure of the run -- reported as-is.")

    dest = Path(__file__).resolve().parent / "ict_smc_results.json"
    dest.write_text(json.dumps(
        {"generated_at": datetime.now(timezone.utc).isoformat(),
         "n_configs": len(GRID), "results": out}, indent=2), encoding="utf-8")
    print(f"\nSaved to {dest}")


if __name__ == "__main__":
    main()
