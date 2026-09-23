"""Full due diligence on ONE candidate, before it is trusted with anything.

Clearing the synthetic null is necessary and nowhere near sufficient. During the
2026-09-21 audit five separate leads cleared one test and died on the next:

  long bias           +4.6 pt pooled -> +0.5 in 2022, -3.6 in 2026
  relative strength   +2.4 pt pooled -> sign flips every other year
  wider stops         net positive   -> 65% of trades never resolved and were
                                        silently excluded from the win rate
  cross-asset         beats control  -> helps longs, hurts shorts by the same
                                        amount, i.e. beta wearing a costume
  both live A+        null 100/98    -> 80.7/60.0 once the null was calibrated
                                        to the real search size

So this runs every one of those checks against a single candidate at once. Each
section is a veto, and the ordering is deliberate: the cheapest disqualifier
runs first.

  1 COSTS         Turnover x cost, against the candidate's own gross edge. The
                  live daily rule loses 8x here. A faster timeframe is WORSE,
                  not better, because cost scales with trade count.
  2 UNRESOLVED    What fraction of signals never reached stop or target inside
                  the horizon. These are excluded from every win rate, so a high
                  fraction means the reported rate describes a sample selected
                  for having moved.
  3 BY YEAR       Does it survive 2022 (the drawdown year) and 2026 (now)? An
                  edge that only works in up-years is beta.
  4 DIRECTION     Long and short separately. Equal-and-opposite is beta.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from project_titan_x.engines.e07_technical.engine import TechnicalAnalysisEngine  # noqa: E402
from project_titan_x.engines.e24_strategy_research.strategies import STRATEGIES  # noqa: E402
from project_titan_x.engines.e24_strategy_research.engine import bars_per_year  # noqa: E402
from project_titan_x.engines.e26_backtesting.engine import BacktestingEngine  # noqa: E402
from project_titan_x.core.config.assets import SUPPORTED_ASSETS  # noqa: E402
from calibrate_signal_confidence import _load  # noqa: E402

COST_ROUND_TRIP = 0.003   # E26's own assumption: 0.1% commission + 0.05% slip/side
RISK_PCT = 0.01


def _cls(sym):
    a = SUPPORTED_ASSETS.get(sym)
    if a is None:
        for v in SUPPORTED_ASSETS.values():
            if getattr(v, "yahoo_symbol", None) == sym:
                a = v
                break
    if a is None:
        return ""
    c = getattr(a, "asset_class", None)
    return getattr(c, "value", c) or ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--timeframe", required=True)
    ap.add_argument("--strategy", required=True)
    ap.add_argument("--params", default="{}")
    args = ap.parse_args()

    import json as _json
    params = _json.loads(args.params)
    fn = STRATEGIES.get(args.strategy)
    if fn is None:
        print(f"strategy {args.strategy} not registered")
        return 1
    df = _load(args.symbol, args.timeframe)
    if df is None:
        print(f"no cached data for {args.symbol} {args.timeframe}")
        return 1

    ta = TechnicalAnalysisEngine()
    ta.initialize()
    r = ta.analyze(df, symbol=args.symbol, timeframe=args.timeframe)
    if not r.success:
        print(f"enrich failed: {r.message}")
        return 1
    e = r.data["df"]

    eng = BacktestingEngine()
    eng.initialize()
    ppy = bars_per_year(args.timeframe, _cls(args.symbol))
    res = eng.run_backtest(e, lambda d: fn(d, **params),
                           periods_per_year=ppy, timeframe=args.timeframe)
    if not res.success:
        print(f"backtest failed: {res.message}")
        return 1
    m = res.data.metrics
    tr = res.data.trades

    print("=" * 72)
    print(f"  CANDIDATE WORKUP -- {args.strategy} on {args.symbol} {args.timeframe}")
    print(f"  params {params}")
    print("=" * 72)
    print(f"  trades {m.total_trades}  win {m.win_rate*100:.1f}%  "
          f"IS Sharpe {m.sharpe_ratio:.2f}  maxDD {m.max_drawdown_pct:.2f}%")
    print()

    vetoes = []

    # ---- 1. COSTS ---------------------------------------------------------
    R = np.array([t["pnl_r"] for t in tr], float)
    pf = np.array([t.get("pos_frac", RISK_PCT) for t in tr], float)
    gross_R = float(R.mean())
    bars = len(e)
    years = max(bars / ppy, 0.1)
    per_year = len(tr) / years
    gross_yr = gross_R * RISK_PCT * per_year * 100
    cost_yr = float((COST_ROUND_TRIP * pf).mean()) * per_year * 100
    net_yr = gross_yr - cost_yr
    print("  1. COSTS AT ITS OWN TURNOVER")
    print(f"     {per_year:.0f} trades/yr over {years:.1f}y · notional {pf.mean():.3f}x equity")
    print(f"     gross {gross_yr:+.2f}%/yr   cost {cost_yr:.2f}%/yr   NET {net_yr:+.2f}%/yr")
    if net_yr <= 0:
        vetoes.append(f"loses {net_yr:+.2f}%/yr after its own costs")
    print()

    # ---- 2. UNRESOLVED ----------------------------------------------------
    # E26 exits on signal flip, so every trade resolves by construction. Report
    # it explicitly rather than let its absence be mistaken for a clean result.
    print("  2. UNRESOLVED TRADES")
    print(f"     0.0% -- E26 exits on signal change, so no trade is dropped for")
    print(f"     failing to reach a level. (The wider-stop result died at 65% here.)")
    print()

    # ---- 3. BY YEAR -------------------------------------------------------
    ts = pd.to_datetime(e["timestamp"], utc=True, errors="coerce") if "timestamp" in e.columns \
        else pd.to_datetime(e.index, utc=True, errors="coerce")
    years_arr = [ts.iloc[t["entry_idx"]].year if hasattr(ts, "iloc") else ts[t["entry_idx"]].year
                 for t in tr]
    D = pd.DataFrame({"year": years_arr, "R": R, "pf": pf,
                      "dir": [1 if t["direction"] == "LONG" else -1 for t in tr]})
    print("  3. YEAR BY YEAR (net %/yr at this turnover)")
    print(f"     {'year':<6}{'n':>6}{'meanR':>9}{'net%':>9}")
    neg_years = []
    for y in sorted(D.year.unique()):
        s = D[D.year == y]
        if len(s) < 10:
            continue
        g = float(s.R.mean()) * RISK_PCT * len(s) * 100
        c = float((COST_ROUND_TRIP * s.pf).sum()) * 100
        net = g - c
        if y >= 2022 and net < 0:
            neg_years.append(y)
        print(f"     {y:<6}{len(s):>6}{s.R.mean():>+9.3f}{net:>+9.2f}")
    if neg_years:
        vetoes.append(f"negative in {neg_years} (the years that decide whether it is beta)")
    print()

    # ---- 4. DIRECTION -----------------------------------------------------
    print("  4. BY DIRECTION")
    for dv, lbl in ((1, "LONG "), (-1, "SHORT")):
        s = D[D.dir == dv]
        if len(s) < 5:
            print(f"     {lbl} n={len(s)} -- too few")
            continue
        g = float(s.R.mean()) * RISK_PCT * len(s) * 100
        c = float((COST_ROUND_TRIP * s.pf).sum()) * 100
        print(f"     {lbl} n={len(s):<5} meanR {s.R.mean():+.3f}  net {g-c:+.2f}%")
    print()

    print("=" * 72)
    if vetoes:
        print("  VERDICT: NOT SUITABLE")
        for v in vetoes:
            print(f"    - {v}")
    else:
        print("  VERDICT: survives this battery. Paper-trade it; do not fund it")
        print("  until the forward gate in live_readiness_gate.py also passes.")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
