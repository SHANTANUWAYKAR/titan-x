"""
Module: run_pdf_matrix.py
Description: Full ARCHETYPE x PAIR matrix for the strategies distilled from
    data/strategy/*.pdf -- every strategy against every pair, rather than
    only each pair's winner.

    run_pdf_backtest.py answers "what is the best archetype for GOLD?".
    This answers the different question the matrix actually supports:
    "does THIS strategy work anywhere, and where?" A strategy that is
    second-best on six pairs is a more interesting result than one that
    wins a single pair, and only the full grid shows that.

    Each cell is the best parameter set for that archetype on that pair,
    graded on E26's unweakened walk-forward bar with real costs. Cells
    where nothing cleared the bar are printed as a dash -- that is a
    result, not a gap.

    RESEARCH ONLY. Registers archetypes temporarily and removes them in a
    finally block; the live registry is untouched and nothing is promoted.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
warnings.filterwarnings("ignore")

from project_titan_x.engines.e24_strategy_research import strategies as strategies_mod
from project_titan_x.engines.e24_strategy_research.engine import StrategyResearchEngine
from project_titan_x.research.pdf_strategies import PDF_STRATEGIES
from project_titan_x.research.run_pdf_backtest import GRIDS

SYMBOLS = ("GOLD", "SILVER", "BTCUSD", "ETHUSD", "EURUSD", "GBPUSD", "USDJPY")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--timeframe", default="4h")
    p.add_argument("--symbols", default=",".join(SYMBOLS))
    args = p.parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    engine = StrategyResearchEngine()
    engine.initialize()
    for name, fn in PDF_STRATEGIES.items():
        strategies_mod.STRATEGIES[name] = fn

    cells: dict = {}
    try:
        print(f"ARCHETYPE x PAIR MATRIX -- {args.timeframe}, E26 unweakened bar, real costs")
        print(f"Each cell = that archetype's best parameter set on that pair.\n")
        for name in PDF_STRATEGIES:
            grid = {name: GRIDS[name]}
            print(f"===== {name}  ({len(GRIDS[name])} configs) =====")
            print(f"  {'PAIR':8} {'PASS':>7} {'EXPECT%':>9} {'R:R':>6} {'WIN%':>6} {'PF':>6} {'OOS':>6} {'TRD':>5}")
            any_pass = False
            for sym in symbols:
                try:
                    r = engine.research(sym, timeframe=args.timeframe, strategy_grid=grid,
                                        years=10, promote_if_validated=False)
                except Exception as e:
                    print(f"  {sym:8}   ERROR {type(e).__name__}")
                    continue
                if not r.success:
                    print(f"  {sym:8}   {r.message[:44]}")
                    continue
                best = r.data.best
                if not best:
                    print(f"  {sym:8} {'0/' + str(r.data.n_candidates):>7}        --  nothing cleared")
                    cells[f"{name}|{sym}"] = None
                    continue
                any_pass = True
                rr = abs(best.avg_win_r / best.avg_loss_r) if best.avg_loss_r else 0.0
                print(f"  {sym:8} {str(len(r.data.passed)) + '/' + str(r.data.n_candidates):>7} "
                      f"{best.expectancy:>9.3f} {rr:>5.2f}R {best.win_rate * 100:>5.1f}% "
                      f"{best.profit_factor:>6.2f} {best.oos_sharpe:>6.2f} {best.is_trades:>5}")
                cells[f"{name}|{sym}"] = {**best.to_dict(), "reward_risk": round(rr, 3),
                                          "n_passed": len(r.data.passed)}
            if not any_pass:
                print("  -> this archetype validated on NO pair at this timeframe")
            print()
    finally:
        for name in PDF_STRATEGIES:
            strategies_mod.STRATEGIES.pop(name, None)

    # Which archetypes travel, and which pairs are receptive?
    by_arch: dict[str, int] = {}
    by_pair: dict[str, int] = {}
    for key, v in cells.items():
        arch, sym = key.split("|")
        by_arch[arch] = by_arch.get(arch, 0) + (1 if v else 0)
        by_pair[sym] = by_pair.get(sym, 0) + (1 if v else 0)

    print("=" * 72)
    print("ARCHETYPES THAT TRAVEL (validated on how many pairs):")
    for a, n in sorted(by_arch.items(), key=lambda kv: -kv[1]):
        print(f"  {a:26} {n}/{len(symbols)}")
    print("\nPAIRS MOST RECEPTIVE (how many archetypes worked):")
    for s, n in sorted(by_pair.items(), key=lambda kv: -kv[1]):
        print(f"  {s:26} {n}/{len(PDF_STRATEGIES)}")

    dest = Path(__file__).resolve().parent / f"pdf_matrix_{args.timeframe}.json"
    dest.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(),
                                "timeframe": args.timeframe, "cells": cells}, indent=2),
                    encoding="utf-8")
    print(f"\nSaved to {dest}")


if __name__ == "__main__":
    main()
