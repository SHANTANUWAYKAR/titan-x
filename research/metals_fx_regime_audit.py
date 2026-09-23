"""
Module: metals_fx_regime_audit.py
Description: Answers the overfitting question the main backtest left open --
    requirement 5 of the approved spec: "tell me clearly if the strategy's
    performance depends heavily on a small number of large moves, and
    whether the parameter choices look tuned to specific past events."

    WHY THE 2-WAY SPLIT WAS THE WRONG TEST. metals_fx_backtest.py compares
    2024-25 against everything before it, and reported "insufficient data"
    for the recent era. That is not a data gap: the 20% holdout is by
    construction the most recent slice, so the 2024-25 gold trend sits
    almost entirely INSIDE the holdout and is deliberately absent from
    dev. Splitting dev in two could never answer the question.

    Three tests that actually can, run over the full 23-year history:

      1. PER-ERA -- performance in each of gold's distinct regimes
         (2003-11 bull, 2011-15 bear, 2015-18 range, 2018-20 bull,
         2020-22 range, 2022-26 bull). An edge that only exists in bull
         markets is a directional bet wearing a strategy's clothes.
      2. PROFIT CONCENTRATION -- what share of total profit comes from
         the best 1/5/10 trades. This is the direct measure of "depends
         on a small number of large moves". A strategy whose top 5 trades
         carry most of the profit did not find a repeatable edge; it
         caught a few moves.
      3. LONG vs SHORT -- gold rose over most of this history, so a
         long-biased rule looks good for a reason that has nothing to do
         with the strategy. If shorts are unprofitable, the "edge" is
         partly just being long gold.

    RESEARCH ONLY -- reports, never promotes.
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
from project_titan_x.engines.e26_backtesting.engine import BacktestingEngine
from project_titan_x.research.metals_fx_backtest import DATA, YSYM, _costs, _summary
from project_titan_x.research.metals_fx_strategy import INSTRUMENTS, london_sweep_continuation

# Gold's regimes, dated from its actual price history rather than round
# numbers -- the 2011 top and the 2015 bottom are real turning points.
ERAS = [
    ("2003-2011 bull", "2003-01-01", "2011-09-01"),
    ("2011-2015 bear", "2011-09-01", "2015-12-01"),
    ("2015-2018 range", "2015-12-01", "2018-08-01"),
    ("2018-2020 bull", "2018-08-01", "2020-08-01"),
    ("2020-2022 range", "2020-08-01", "2022-11-01"),
    ("2022-2026 bull", "2022-11-01", "2027-01-01"),
]


def _run_segment(bt, enriched, symbol, timeframe):
    p = INSTRUMENTS[symbol]
    c = _costs(symbol, timeframe)
    from project_titan_x.engines.e24_strategy_research.engine import BARS_PER_YEAR
    return bt.run_backtest(
        enriched, lambda d: london_sweep_continuation(d, p),
        periods_per_year=BARS_PER_YEAR.get(timeframe, 252),
        slippage_pct=c["slippage_pct"], commission_pct=c["commission_pct"],
    )


def concentration(trades: list[dict]) -> dict:
    """What share of gross profit comes from the largest few winners.

    Reported against GROSS profit (winners only), not net: netting losses
    first can push the ratio above 100% and make a fragile strategy look
    absurd rather than merely fragile. Gross keeps it interpretable.
    """
    pnl = sorted((t["pnl_pct"] for t in trades), reverse=True)
    wins = [p for p in pnl if p > 0]
    if not wins:
        return {}
    gross = sum(wins)
    return {
        "n_trades": len(pnl),
        "n_winners": len(wins),
        "top1_pct_of_gross": round(pnl[0] / gross * 100, 1),
        "top5_pct_of_gross": round(sum(pnl[:5]) / gross * 100, 1),
        "top10_pct_of_gross": round(sum(pnl[:10]) / gross * 100, 1),
    }


def direction_split(trades: list[dict]) -> dict:
    out = {}
    for side in ("LONG", "SHORT"):
        sub = [t for t in trades if t.get("direction") == side]
        if not sub:
            out[side] = None
            continue
        pnls = [t["pnl_pct"] for t in sub]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        out[side] = {
            "trades": len(sub),
            "win_rate": round(len(wins) / len(sub), 4),
            "total_pnl_pct": round(sum(pnls), 3),
            "profit_factor": round(sum(wins) / abs(sum(losses)), 2) if losses else None,
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--timeframe", default="4h")
    ap.add_argument("--symbols", default="GOLD,EURUSD")   # the two that survived
    args = ap.parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    ta, bt = TechnicalAnalysisEngine(), BacktestingEngine()
    ta.initialize(); bt.initialize()
    report: dict = {}

    for sym in symbols:
        path = DATA / f"{YSYM[sym]}_{args.timeframe}.parquet"
        if not path.exists():
            print(f"{sym}: no local data"); continue
        df = pd.read_parquet(path).reset_index(drop=True)
        ts = pd.to_datetime(df["timestamp"], utc=True)
        enriched = ta.analyze(df).data["df"]

        print("=" * 92)
        print(f"{sym}  {args.timeframe}  --  {len(df):,} bars, {ts.min().date()} to {ts.max().date()}")
        print("=" * 92)

        full = _run_segment(bt, enriched, sym, args.timeframe)
        s = _summary(full)
        if not s:
            print("  no trades over the full history"); continue
        trades = full.data.trades
        print(f"\nFULL HISTORY: {s['trades']} trades  {s['win_rate']*100:.1f}% win  "
              f"{s['reward_risk']:.2f}R  PF {s['profit_factor']:.2f}  Sharpe {s['sharpe']:.2f}")

        # 1. per-era
        print(f"\n1. PER-ERA (does it only work in one regime?)")
        print(f"   {'ERA':18} {'BARS':>7} {'TRD':>5} {'WIN%':>6} {'PF':>6} {'TOTAL%':>8}")
        eras = {}
        for name, start, end in ERAS:
            mask = (ts >= start) & (ts < end)
            seg = enriched[mask.to_numpy()].reset_index(drop=True)
            if len(seg) < 500:
                print(f"   {name:18} {len(seg):>7}   -- too few bars")
                eras[name] = None
                continue
            r = _run_segment(bt, seg, sym, args.timeframe)
            ss = _summary(r)
            if not ss:
                print(f"   {name:18} {len(seg):>7}     0   -- no trades")
                eras[name] = None
                continue
            tot = sum(t["pnl_pct"] for t in r.data.trades)
            print(f"   {name:18} {len(seg):>7} {ss['trades']:>5} {ss['win_rate']*100:>5.1f}% "
                  f"{ss['profit_factor']:>6.2f} {tot:>+8.2f}")
            eras[name] = {"trades": ss["trades"], "win_rate": ss["win_rate"],
                          "profit_factor": ss["profit_factor"], "total_pnl_pct": round(tot, 3)}

        profitable = [k for k, v in eras.items() if v and v["profit_factor"] > 1.0]
        tested = [k for k, v in eras.items() if v]
        print(f"   -> profitable in {len(profitable)}/{len(tested)} testable eras")

        # 2. concentration
        conc = concentration(trades)
        print(f"\n2. PROFIT CONCENTRATION (is it a few big moves?)")
        if conc:
            print(f"   best single trade = {conc['top1_pct_of_gross']}% of gross profit")
            print(f"   best 5 trades     = {conc['top5_pct_of_gross']}% of gross profit")
            print(f"   best 10 trades    = {conc['top10_pct_of_gross']}% of gross profit")
            print(f"   ({conc['n_winners']} winners out of {conc['n_trades']} trades)")

        # 3. long vs short
        dirs = direction_split(trades)
        print(f"\n3. LONG vs SHORT (is it just being long {sym}?)")
        for side, d in dirs.items():
            print(f"   {side:6} " + (f"{d['trades']:>4} trades  {d['win_rate']*100:>5.1f}% win  "
                  f"PF {d['profit_factor']}  total {d['total_pnl_pct']:+.2f}%" if d else "none"))

        report[sym] = {"full": {k: v for k, v in s.items() if k != "trade_pnl"},
                       "eras": eras, "concentration": conc, "direction": dirs,
                       "eras_profitable": len(profitable), "eras_tested": len(tested)}

        # verdict
        flags = []
        if tested and len(profitable) / len(tested) < 0.6:
            flags.append(f"works in only {len(profitable)}/{len(tested)} eras")
        if conc and conc["top5_pct_of_gross"] > 50:
            flags.append(f"top 5 trades = {conc['top5_pct_of_gross']}% of gross profit")
        both = [d for d in dirs.values() if d and d["profit_factor"]]
        if len(both) == 2 and min(d["profit_factor"] for d in both) < 1.0:
            flags.append("one direction is unprofitable")
        print(f"\n   >>> OVERFITTING RISK: " + ("; ".join(flags) if flags else
              "LOW -- profitable across eras, profit not concentrated, both directions work"))
        report[sym]["overfitting_flags"] = flags
        print()

    dest = Path(__file__).resolve().parent / f"regime_audit_{args.timeframe}.json"
    dest.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(),
                                "report": report}, indent=2, default=str), encoding="utf-8")
    print(f"Saved to {dest}")


if __name__ == "__main__":
    main()
