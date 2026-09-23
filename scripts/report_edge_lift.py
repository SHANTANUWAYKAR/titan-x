"""How much of a candidate's prop-challenge pass rate is actually EARNED.

A raw pass probability is close to meaningless on its own, because a profit
target is a level you need to touch once while a drawdown limit must be avoided
at every point. That asymmetry hands a ZERO-EDGE strategy a large pass rate for
free. `edge_lift` = pass_rate - null_pass_rate is the part the edge contributed.

Run against the graded candidates only. Re-backtesting every one of ~107k rows
would take longer than the sweep that produced them, and a candidate that
cannot reach a grade is not a candidate anyone would fund.

REAL TRADES, NOT SYNTHETIC. The R-multiples come from re-running each
candidate's backtest, not from reconstructing a pool out of win-rate and profit
factor. A synthetic pool makes every win identical and every loss identical,
which removes exactly the fat tails that cause drawdown breaches -- so it would
report a flatteringly high pass rate. That is the error this report exists to
expose, so committing it here would be self-defeating.

    python scripts/report_edge_lift.py
    python scripts/report_edge_lift.py --grades A+,A,B --risk 0.5
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# STRATEGIES is the master registry every plugin registers into. Looking the
# name up on the `strategies` MODULE only finds the archetypes defined there,
# which is why the PDF-library candidates came back "no strategy fn".
from project_titan_x.engines.e24_strategy_research.strategies import STRATEGIES  # noqa: E402
from project_titan_x.engines.e07_technical.engine import TechnicalAnalysisEngine  # noqa: E402
from project_titan_x.engines.e24_strategy_research.engine import bars_per_year  # noqa: E402
from project_titan_x.engines.e26_backtesting.engine import BacktestingEngine  # noqa: E402
from project_titan_x.engines.e45_risk.prop_challenge import simulate  # noqa: E402
from project_titan_x.core.config.assets import SUPPORTED_ASSETS  # noqa: E402

LB = ROOT / "project_titan_x" / "data" / "models" / "e24_strategy_research" / "strategy_leaderboard.json"
OUT = ROOT / "project_titan_x" / "reports" / "EDGE_LIFT.md"
DATA = ROOT / "project_titan_x" / "data" / "processed"
_TA = None


def _asset_class(sym):
    a = SUPPORTED_ASSETS.get(sym)
    if a is None:
        for v in SUPPORTED_ASSETS.values():
            if getattr(v, "yahoo_symbol", None) == sym:
                a = v
                break
    if a is None:
        return None
    c = getattr(a, "asset_class", None)
    return getattr(c, "value", c)


def _yahoo(sym):
    a = SUPPORTED_ASSETS.get(sym)
    return getattr(a, "yahoo_symbol", sym) if a else sym


def _load(sym, tf):
    for cand in (_yahoo(sym), sym):
        hits = glob.glob(str(DATA / f"{cand}_{tf}.parquet"))
        if hits:
            df = pd.read_parquet(hits[0])
            df.columns = [c.lower() for c in df.columns]
            return df
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--grades", default="A+,A")
    ap.add_argument("--risk", type=float, default=0.5, help="percent of account per trade")
    ap.add_argument("--sims", type=int, default=4000)
    args = ap.parse_args()
    want = {g.strip() for g in args.grades.split(",") if g.strip()}

    rows = json.loads(LB.read_text(encoding="utf-8"))["rows"]
    graded = [r for r in rows if r.get("grade") in want]
    print(f"{len(graded)} candidate(s) at grade {sorted(want)}", flush=True)

    eng = BacktestingEngine()
    eng.initialize()
    global _TA
    _TA = TechnicalAnalysisEngine()
    _TA.initialize()
    out = []
    for r in graded:
        sym, tf, name, params = r["symbol"], r["timeframe"], r["strategy"], r.get("params") or {}
        fn = STRATEGIES.get(name)
        df = _load(sym, tf)
        if fn is None or df is None:
            out.append((r, None, "no strategy fn" if fn is None else "no cached data"))
            continue
        try:
            # Strategies read indicator columns (ema_200, atr, ...) that only
            # exist after e07 enrichment -- the sweep enriches before
            # backtesting, and skipping it here surfaced as a bare KeyError.
            ta = _TA.analyze(df, symbol=sym, timeframe=tf)
            if not ta.success:
                out.append((r, None, f"enrich failed: {ta.message[:30]}"))
                continue
            df = ta.data["df"]
            res = eng.run_backtest(
                df, lambda d, _f=fn, _p=params: _f(d, **_p),
                periods_per_year=bars_per_year(tf, _asset_class(sym) or ""),
                timeframe=tf,
            )
            if not res.success:
                out.append((r, None, res.message[:40]))
                continue
            tr = [t["pnl_r"] for t in res.data.trades]
            c = simulate(tr, risk_pct=args.risk, n_sims=args.sims)
            out.append((r, c, None if c else f"only {len(tr)} trades (need 30)"))
        except Exception as e:  # noqa: BLE001
            out.append((r, None, str(e)[:40]))
        print(f"  {sym} {tf} {name}", flush=True)

    lines = [
        "# Edge Lift — how much of the pass rate is earned",
        "",
        f"Risk per trade **{args.risk}%** · {args.sims} simulations · "
        "8% profit target, 10% max total drawdown, 5% max daily.",
        "",
        "`null` is the SAME strategy with its expectancy forced to zero and its win rate",
        "and R:R kept intact. `lift` is the difference — the only part the edge earned.",
        "A high pass rate with a low lift means the challenge rules were generous, not",
        "that the strategy was good.",
        "",
        "| Strategy | Instrument | TF | Trades | Win% | R:R | Pass% | Null% | **Lift** |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r, c, err in sorted(out, key=lambda x: -(x[1].edge_lift if x[1] else -1)):
        base = f"| `{r['strategy']}` | {r['symbol']} | {r['timeframe']} |"
        if c is None:
            lines.append(f"{base} — | — | — | — | — | _{err}_ |")
            continue
        lines.append(
            f"{base} {int(r['trades'] or 0)} | {c.win_rate*100:.1f} | {c.reward_risk:.2f} | "
            f"{c.pass_rate*100:.1f} | {c.null_pass_rate*100:.1f} | **{c.edge_lift*100:+.1f} pt** |"
        )
    lines += [
        "",
        "## What this does not establish",
        "",
        "- Trades are resampled i.i.d., so losing streaks never cluster the way a real",
        "  regime makes them. Every pass rate here is an **upper bound**.",
        "- Passing a challenge is not the same as being profitable. The two objectives",
        "  differ, and a strategy can be optimised for one at the other's expense.",
        "- The pool cannot invent variety it does not contain; a thin trade count makes",
        "  every figure in its row correspondingly thin.",
    ]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nWrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
