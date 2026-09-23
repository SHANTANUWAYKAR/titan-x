"""
Module: run_pdf_matrix_offline.py
Description: ARCHETYPE x PAIR matrix for the data/strategy/*.pdf rules,
    run against LOCAL parquet data instead of live Yahoo fetches.

    Why offline: the network version (run_pdf_matrix.py) was repeatedly
    corrupted by transient Yahoo failures -- symbols that have fetched
    successfully dozens of times in this project returned "possibly
    delisted; no price data found", and the engine then reported
    "Insufficient OHLCV history". Those cells are indistinguishable in the
    output from a genuine "this strategy found nothing", which is the
    worst kind of silent error in a research result: a data outage
    masquerading as a finding.

    Every symbol/timeframe used here is already on disk in data/processed/,
    so the matrix is reproducible and a blank cell means what it says.

    Grades each archetype's own parameter grid with E26's real IS/OOS split
    and the same asset-class transaction costs the live sweeps use, so the
    numbers are comparable to everything else in this project.

    RESEARCH ONLY -- nothing is promoted, the live registry is untouched.
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

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
warnings.filterwarnings("ignore")

from project_titan_x.engines.e07_technical import TechnicalAnalysisEngine
from project_titan_x.engines.e24_strategy_research.engine import (
    ASSET_CLASS_COST_MULT, SYMBOL_COST_MULT, TRANSACTION_COSTS, BARS_PER_YEAR,
)
from project_titan_x.engines.e26_backtesting.engine import BacktestingEngine
from project_titan_x.research.pdf_strategies import PDF_STRATEGIES
from project_titan_x.research.run_pdf_backtest import GRIDS

_DATA = Path(__file__).resolve().parents[1] / "data" / "processed"
PAIRS = [("GOLD", "GC=F", "commodity"), ("SILVER", "SI=F", "commodity"),
         ("BTCUSD", "BTC-USD", "crypto"), ("ETHUSD", "ETH-USD", "crypto"),
         ("EURUSD", "EURUSD=X", "forex"), ("GBPUSD", "GBPUSD=X", "forex"),
         ("USDJPY", "USDJPY=X", "forex")]

# The PDH/PDL sweep was added after run_pdf_backtest.py's GRIDS was written.
EXTRA_GRIDS = {
    "pdh_pdl_sweep_reversal": [
        {"wick_ratio": w, "use_opposite_target": t, "rr": r}
        for w in (0.3, 0.5) for t, r in ((True, 2.0), (False, 2.0), (False, 3.0))
    ],
}


def _costs(symbol: str, asset_class: str, timeframe: str) -> tuple[float, float]:
    base = TRANSACTION_COSTS.get(timeframe, TRANSACTION_COSTS["1d"])
    mult = SYMBOL_COST_MULT.get(symbol, ASSET_CLASS_COST_MULT.get(asset_class, 1.0))
    return base["slippage_pct"] * mult, base["commission_pct"] * mult


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--timeframe", default="4h")
    args = p.parse_args()
    tf = args.timeframe

    ta, bt = TechnicalAnalysisEngine(), BacktestingEngine()
    ta.initialize()
    bt.initialize()
    grids = {**GRIDS, **EXTRA_GRIDS}
    ppy = BARS_PER_YEAR.get(tf, 252)

    frames: dict[str, pd.DataFrame] = {}
    for name, ysym, _cls in PAIRS:
        f = _DATA / f"{ysym}_{tf}.parquet"
        if f.exists():
            frames[name] = ta.analyze(pd.read_parquet(f).reset_index(drop=True)).data["df"]

    print(f"ARCHETYPE x PAIR MATRIX -- {tf}, local data, E26 unweakened bar")
    print(f"Loaded: {', '.join(f'{k}({len(v)} bars)' for k, v in frames.items())}\n")

    cells: dict = {}
    for arch, fn in PDF_STRATEGIES.items():
        grid = grids.get(arch, [{}])
        print(f"===== {arch}  ({len(grid)} configs) =====")
        print(f"  {'PAIR':8} {'PASS':>6} {'EXPECT%':>9} {'R:R':>6} {'WIN%':>6} {'PF':>6} {'TRD':>5}")
        for name, ysym, cls in PAIRS:
            enr = frames.get(name)
            if enr is None:
                print(f"  {name:8}   no local {tf} file")
                continue
            slip, comm = _costs(name, cls, tf)
            best, n_pass = None, 0
            for params in grid:
                try:
                    res = bt.run_backtest(
                        enr, lambda d, _f=fn, _p=params: _f(d, **_p),
                        periods_per_year=ppy, slippage_pct=slip, commission_pct=comm,
                    )
                except Exception:
                    continue
                if not res.success or res.data is None:
                    continue
                m = res.data.metrics
                if not res.data.passed_validation:
                    continue
                n_pass += 1
                if best is None or m.expectancy > best[0].expectancy:
                    best = (m, params)
            if best is None:
                print(f"  {name:8} {'0/' + str(len(grid)):>6}       --   nothing cleared")
                cells[f"{arch}|{name}"] = None
                continue
            m, params = best
            rr = abs(m.avg_win_r / m.avg_loss_r) if m.avg_loss_r else 0.0
            print(f"  {name:8} {str(n_pass) + '/' + str(len(grid)):>6} {m.expectancy:>9.3f} "
                  f"{rr:>5.2f}R {m.win_rate * 100:>5.1f}% {m.profit_factor:>6.2f} {m.total_trades:>5}   {params}")
            cells[f"{arch}|{name}"] = {
                "expectancy": round(m.expectancy, 4), "reward_risk": round(rr, 3),
                "win_rate": round(m.win_rate, 4), "profit_factor": round(m.profit_factor, 4),
                "trades": m.total_trades, "max_dd": round(m.max_drawdown_pct, 3),
                "n_passed": n_pass, "params": params,
            }
        print()

    by_arch, by_pair = {}, {}
    for key, v in cells.items():
        a, s = key.split("|")
        by_arch[a] = by_arch.get(a, 0) + (1 if v else 0)
        by_pair[s] = by_pair.get(s, 0) + (1 if v else 0)

    print("=" * 74)
    print("ARCHETYPES THAT TRAVEL (validated on how many pairs):")
    for a, n in sorted(by_arch.items(), key=lambda kv: -kv[1]):
        print(f"  {a:26} {n}/{len(PAIRS)}")
    print("\nPAIRS MOST RECEPTIVE (how many archetypes worked):")
    for s, n in sorted(by_pair.items(), key=lambda kv: -kv[1]):
        print(f"  {s:26} {n}/{len(PDF_STRATEGIES)}")

    ranked = sorted(((k, v) for k, v in cells.items() if v),
                    key=lambda kv: -kv[1]["expectancy"])[:8]
    if ranked:
        print("\nBEST CELLS overall (by expectancy):")
        for k, v in ranked:
            a, s = k.split("|")
            print(f"  {s:8} {a:26} exp {v['expectancy']:>7.3f}%  {v['reward_risk']:>4.2f}R  "
                  f"WR {v['win_rate']*100:>5.1f}%  PF {v['profit_factor']:>5.2f}  n={v['trades']}")

    dest = Path(__file__).resolve().parent / f"pdf_matrix_offline_{tf}.json"
    dest.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(),
                                "timeframe": tf, "cells": cells}, indent=2), encoding="utf-8")
    print(f"\nSaved to {dest}")


if __name__ == "__main__":
    main()
