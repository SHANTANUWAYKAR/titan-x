"""
Module: metals_fx_backtest.py
Description: BACKTEST, VALIDATION AND REPORTING for
    metals_fx_strategy.london_sweep_continuation. Contains no strategy
    logic -- that lives entirely in metals_fx_strategy.py.

    Runs, in order:
      1. WALK-FORWARD      rolling train/test windows, never a single
                           in-sample number
      2. PER-INSTRUMENT    Gold, Silver and each FX pair reported
                           SEPARATELY -- never blended
      3. COST COMPARISON   with and without costs, side by side
      4. COST STRESS       reruns at 2x spread/slippage
      5. MONTE CARLO       bootstrapped trade order, 5th/50th/95th
                           percentile max drawdown
      6. PARAM SENSITIVITY stop/target shifted +/-20%
      7. HOLDOUT           most recent 20% touched exactly once, at the end
      8. GOLD REGIME SPLIT 2024-25 trend vs everything before it

    ON FRAMEWORK CHOICE (approved): vectorbt/backtrader are not used. E26
    already performs the walk-forward split with per-asset-class costs, is
    the same judge every live override was validated against, and has had
    all 11 of its metric formulas independently verified. Introducing two
    more frameworks would mean reconciling three different cost models
    against the live engine; the robustness checks E26 lacked (Monte
    Carlo, sensitivity, cost stress) are added here instead.

    KILL CRITERION (approved): an instrument that fails walk-forward OR
    collapses under 2x costs is DROPPED, not re-tuned. Re-tuning after
    seeing test results is how overfitting enters, so this script reports
    failure rather than searching for a passing configuration.

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
from typing import Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
warnings.filterwarnings("ignore")

from project_titan_x.engines.e07_technical import TechnicalAnalysisEngine
from project_titan_x.engines.e24_strategy_research.engine import (
    ASSET_CLASS_COST_MULT, BARS_PER_YEAR, SYMBOL_COST_MULT, TRANSACTION_COSTS,
)
from project_titan_x.engines.e26_backtesting.engine import BacktestingEngine
from project_titan_x.research.metals_fx_strategy import INSTRUMENTS, london_sweep_continuation

DATA = Path(__file__).resolve().parents[1] / "data" / "processed"
YSYM = {"GOLD": "GC=F", "SILVER": "SI=F", "EURUSD": "EURUSD=X",
        "GBPUSD": "GBPUSD=X", "USDJPY": "USDJPY=X"}
CLS = {"GOLD": "commodity", "SILVER": "commodity",
       "EURUSD": "forex", "GBPUSD": "forex", "USDJPY": "forex"}
HOLDOUT_FRAC = 0.20      # most recent 20%, touched once at the very end


def _costs(symbol: str, timeframe: str, multiplier: float = 1.0) -> dict:
    """Instrument-specific spread/slippage.

    Uses the SAME per-asset-class model the live sweeps use, so numbers
    here stay comparable with every promoted override. Metals and FX carry
    overnight financing that this model does not represent; on the 4h/1h
    holding periods here that is a small omission, but it IS an omission
    and is flagged in the report rather than hidden.
    """
    base = TRANSACTION_COSTS.get(timeframe, TRANSACTION_COSTS["1d"])
    m = SYMBOL_COST_MULT.get(symbol, ASSET_CLASS_COST_MULT.get(CLS[symbol], 1.0)) * multiplier
    return {"slippage_pct": base["slippage_pct"] * m, "commission_pct": base["commission_pct"] * m}


def _run(bt, enriched, symbol, timeframe, cost_mult=1.0, stop_atr=None, target_atr=None):
    p = INSTRUMENTS[symbol]
    c = _costs(symbol, timeframe, cost_mult)
    return bt.run_backtest(
        enriched,
        lambda d: london_sweep_continuation(d, p, stop_atr=stop_atr, target_atr=target_atr),
        periods_per_year=BARS_PER_YEAR.get(timeframe, 252),
        slippage_pct=c["slippage_pct"], commission_pct=c["commission_pct"],
    )


def _summary(result) -> Optional[dict]:
    if not result.success or result.data is None:
        return None
    m = result.data.metrics
    if m.total_trades == 0:
        return None
    rr = abs(m.avg_win_r / m.avg_loss_r) if m.avg_loss_r else 0.0
    return {"trades": m.total_trades, "win_rate": m.win_rate, "expectancy": m.expectancy,
            "reward_risk": rr, "profit_factor": m.profit_factor, "sharpe": m.sharpe_ratio,
            "sortino": m.sortino_ratio, "max_dd": m.max_drawdown_pct,
            "total_return": m.total_return_pct,
            "trade_pnl": [t["pnl_pct"] for t in result.data.trades]}


def _max_streak(pnls: list[float]) -> int:
    worst = run = 0
    for x in pnls:
        run = run + 1 if x < 0 else 0
        worst = max(worst, run)
    return worst


def _monte_carlo(pnls: list[float], n_sims: int = 1000, seed: int = 7) -> dict:
    """Bootstrap-resample the trade sequence.

    The historical equity curve is ONE ordering of the trades. Resampling
    with replacement shows the range of drawdowns the same edge could
    plausibly have produced -- which is the drawdown to plan for, not the
    single lucky or unlucky path that happened.
    """
    if len(pnls) < 5:
        return {}
    rng = np.random.default_rng(seed)
    arr = np.asarray(pnls, dtype=float)
    dds = []
    for _ in range(n_sims):
        path = rng.choice(arr, size=len(arr), replace=True)
        eq = np.cumsum(path)
        peak = np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:]
        dds.append(float(np.max(peak - eq)))
    return {"dd_p5": float(np.percentile(dds, 5)),
            "dd_p50": float(np.percentile(dds, 50)),
            "dd_p95": float(np.percentile(dds, 95))}


def _walk_forward(bt, enriched, symbol, timeframe, n_windows: int = 5) -> list[dict]:
    """Rolling out-of-sample windows.

    Each window TESTS on a segment the previous segments preceded. There
    is no parameter fitting inside the loop -- the instrument parameters
    are fixed in advance from instrument characteristics, so every window
    is genuinely out-of-sample rather than optimised-then-tested.
    """
    out = []
    seg = len(enriched) // (n_windows + 1)
    if seg < 500:
        return out
    for w in range(n_windows):
        test = enriched.iloc[seg * (w + 1): seg * (w + 2)].reset_index(drop=True)
        if len(test) < 300:
            continue
        s = _summary(_run(bt, test, symbol, timeframe))
        if s:
            out.append({"window": w + 1, "trades": s["trades"], "win_rate": s["win_rate"],
                        "expectancy": s["expectancy"], "profit_factor": s["profit_factor"],
                        "max_dd": s["max_dd"]})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--timeframe", default="4h")
    ap.add_argument("--bars", type=int, default=40000)
    ap.add_argument("--symbols", default=",".join(YSYM))
    args = ap.parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    ta, bt = TechnicalAnalysisEngine(), BacktestingEngine()
    ta.initialize(); bt.initialize()
    report: dict = {}

    print("=" * 94)
    print(f"LONDON-SWEEP CONTINUATION -- {args.timeframe} -- per-instrument, honest validation")
    print("=" * 94)

    for sym in symbols:
        path = DATA / f"{YSYM[sym]}_{args.timeframe}.parquet"
        if not path.exists():
            print(f"\n{sym}: no local data at {path.name}")
            continue
        df = pd.read_parquet(path).tail(args.bars).reset_index(drop=True)
        enriched = ta.analyze(df).data["df"]

        # HOLDOUT: reserved, untouched until the very end of this instrument.
        cut = int(len(enriched) * (1 - HOLDOUT_FRAC))
        dev, holdout = enriched.iloc[:cut].reset_index(drop=True), enriched.iloc[cut:].reset_index(drop=True)

        p = INSTRUMENTS[sym]
        print(f"\n{'=' * 94}\n{sym}  ({len(dev):,} dev bars / {len(holdout):,} holdout)")
        print(f"  params: stop {p.stop_atr}xATR  target {p.target_atr}xATR  "
              f"risk {p.max_risk_pct}%  sessions {[s.value for s in p.sessions]}")

        gross = _summary(_run(bt, dev, sym, args.timeframe, cost_mult=0.0))
        net = _summary(_run(bt, dev, sym, args.timeframe, cost_mult=1.0))
        stress = _summary(_run(bt, dev, sym, args.timeframe, cost_mult=2.0))
        if not net:
            print("  NO TRADES -- strategy never triggered. Dropped.")
            report[sym] = {"verdict": "no_trades"}
            continue

        print(f"\n  {'':16} {'TRD':>5} {'WIN%':>6} {'R:R':>6} {'PF':>6} {'SHARPE':>7} {'SORTINO':>8} {'MAXDD%':>7}")
        for label, s in (("no costs", gross), ("real costs", net), ("2x costs", stress)):
            if s:
                print(f"  {label:16} {s['trades']:>5} {s['win_rate']*100:>5.1f}% {s['reward_risk']:>5.2f}R "
                      f"{s['profit_factor']:>6.2f} {s['sharpe']:>7.2f} {s['sortino']:>8.2f} {s['max_dd']:>7.2f}")

        streak = _max_streak(net["trade_pnl"])
        mc = _monte_carlo(net["trade_pnl"])
        print(f"  worst losing streak: {streak} consecutive")
        if mc:
            print(f"  Monte Carlo max-DD (1000 sims): p5 {mc['dd_p5']:.2f}%  "
                  f"p50 {mc['dd_p50']:.2f}%  p95 {mc['dd_p95']:.2f}%")

        wf = _walk_forward(bt, dev, sym, args.timeframe)
        if wf:
            pos = sum(1 for w in wf if w["expectancy"] > 0)
            per_window = ", ".join("{:+.3f}".format(w["expectancy"]) for w in wf)
            print(f"  walk-forward: {pos}/{len(wf)} windows positive  [{per_window}]")
        else:
            pos = 0
            print("  walk-forward: not enough data for windows")

        print("  parameter sensitivity (+/-20% on stop and target):")
        sens = {}
        for lbl, sm, tm in (("-20%", 0.8, 0.8), ("base", 1.0, 1.0), ("+20%", 1.2, 1.2)):
            s = _summary(_run(bt, dev, sym, args.timeframe,
                              stop_atr=p.stop_atr * sm, target_atr=p.target_atr * tm))
            sens[lbl] = s["expectancy"] if s else None
            print(f"      {lbl:5} expectancy {s['expectancy']:+.4f}  PF {s['profit_factor']:.2f}" if s
                  else f"      {lbl:5} no trades")

        hold = _summary(_run(bt, holdout, sym, args.timeframe))
        print(f"  HOLDOUT (touched once): " + (
            f"{hold['trades']} trades, {hold['win_rate']*100:.1f}% win, PF {hold['profit_factor']:.2f}, "
            f"expectancy {hold['expectancy']:+.4f}" if hold else "no trades"))

        # Kill criterion, applied mechanically.
        fails = []
        if not wf or pos < len(wf) * 0.6:
            fails.append("walk-forward")
        if not stress or stress["profit_factor"] < 1.0:
            fails.append("2x costs")
        verdict = "KEEP" if not fails else f"DROP ({', '.join(fails)})"
        print(f"  >>> VERDICT: {verdict}")

        report[sym] = {"gross": {k: v for k, v in gross.items() if k != "trade_pnl"} if gross else None,
                       "net": {k: v for k, v in net.items() if k != "trade_pnl"},
                       "stress_2x": {k: v for k, v in stress.items() if k != "trade_pnl"} if stress else None,
                       "worst_losing_streak": streak, "monte_carlo": mc,
                       "walk_forward": wf, "sensitivity": sens,
                       "holdout": {k: v for k, v in hold.items() if k != "trade_pnl"} if hold else None,
                       "verdict": verdict}

        # GOLD REGIME SPLIT -- approved as a required check.
        if sym == "GOLD" and "timestamp" in dev.columns:
            ts = pd.to_datetime(dev["timestamp"], utc=True)
            recent = dev[ts >= "2024-01-01"].reset_index(drop=True)
            older = dev[ts < "2024-01-01"].reset_index(drop=True)
            print("\n  GOLD REGIME SPLIT (is the edge just the 2024-25 trend?)")
            for lbl, seg in (("2024-25 trend", recent), ("pre-2024", older)):
                s = _summary(_run(bt, seg, sym, args.timeframe)) if len(seg) > 500 else None
                print(f"      {lbl:16} " + (f"{s['trades']:>4} trades  {s['win_rate']*100:>5.1f}% win  "
                      f"PF {s['profit_factor']:.2f}  expectancy {s['expectancy']:+.4f}" if s else "insufficient data"))
                report.setdefault("GOLD_regime", {})[lbl] = (
                    {k: v for k, v in s.items() if k != "trade_pnl"} if s else None)

    keep = [s for s, r in report.items() if isinstance(r, dict) and r.get("verdict") == "KEEP"]
    print(f"\n{'=' * 94}")
    print(f"SURVIVED: {', '.join(keep) if keep else 'NONE'}")
    print("Costs exclude swap/rollover -- a real omission on multi-day holds, flagged not hidden.")

    dest = Path(__file__).resolve().parent / f"metals_fx_report_{args.timeframe}.json"
    dest.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(),
                                "timeframe": args.timeframe, "report": report}, indent=2, default=str),
                    encoding="utf-8")
    print(f"Saved to {dest}")


if __name__ == "__main__":
    main()
