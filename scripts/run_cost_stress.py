"""
Module: run_cost_stress.py
Description: PHASE 11 of `reports/upgrade statergy.txt` -- "Execution-cost
    stress / Slippage stress / Spread stress" against the strategies that are
    actually trading real money.

    THE QUESTION THIS ANSWERS. Every backtest here assumes E26's default fill
    quality: 0.1% commission + 0.05% slippage per side, 0.30% round trip. That
    is an assumption, not a measurement, and nobody has ever checked how much
    of a live strategy's edge survives worse fills. The number that matters to
    someone about to trade is not "what did it make at assumed costs" but
    "how bad can my fills get before this stops making money" -- because that
    is the difference between a backtest and a broker statement.

    WHY THIS IS NOT THE SAME AS E26's EXISTING PERTURBATION. E26 already
    perturbs commission by +/-10% as part of its robustness check. That
    measures sensitivity; it does not find the breaking point. A strategy can
    be perfectly insensitive to a 10% cost change and still die at 2x, and 2x
    is an ordinary outcome for a retail fill on a volatile open.

    NOTHING IS RE-VALIDATED HERE. This sweeps ONE axis -- cost -- across a
    strategy that has already been selected, and reports where expectancy
    crosses zero. It cannot promote anything, and a strategy surviving 5x cost
    is not thereby validated: it is the same in-sample result, priced
    differently.

Usage:
    python scripts/run_cost_stress.py
    python scripts/run_cost_stress.py --multiples 1,2,3,5
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

import pandas as pd  # noqa: E402

from project_titan_x.engines.e07_technical import TechnicalAnalysisEngine  # noqa: E402
from project_titan_x.engines.e24_strategy_research import forward_test as ft  # noqa: E402
from project_titan_x.engines.e24_strategy_research.engine import (  # noqa: E402
    BARS_PER_YEAR,
    _run_one_candidate_worker,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
REPORT = ROOT / "reports" / "COST_STRESS.md"
REPORT_JSON = ROOT / "data" / "models" / "e24_strategy_research" / "cost_stress.json"

# E26's shipped defaults, charged per side. One round trip is twice this.
BASE_COMMISSION = 0.001
BASE_SLIPPAGE = 0.0005
DEFAULT_MULTIPLES = (0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0)


def stress_one(enriched: pd.DataFrame, strategy: str, params: dict,
               timeframe: str, multiples) -> list[dict]:
    ppy = BARS_PER_YEAR.get(timeframe, 252)
    rows = []
    for m in multiples:
        r = _run_one_candidate_worker(
            enriched, strategy, params, None, ppy,
            BASE_SLIPPAGE * m, BASE_COMMISSION * m, timeframe=timeframe,
        )
        if r is None:
            rows.append({"multiple": m, "ran": False})
            continue
        rows.append({
            "multiple": m,
            "ran": True,
            "round_trip_pct": round(2 * (BASE_COMMISSION + BASE_SLIPPAGE) * m * 100, 4),
            "trades": r.get("is_trades"),
            "win_rate": r.get("win_rate"),
            "expectancy": r.get("expectancy"),
            "is_sharpe": r.get("is_sharpe"),
            "oos_sharpe": r.get("oos_sharpe"),
            "max_drawdown_pct": r.get("is_max_dd"),
            "profit_factor": r.get("profit_factor"),
            "passed_validation": r.get("passed_validation"),
        })
    return rows


def breakeven_multiple(rows: list[dict]) -> float | None:
    """Largest cost multiple at which expectancy is still positive.

    Returns None when even zero cost is unprofitable -- which is a finding in
    itself: the edge was never in the entry rule, it was in the cost
    assumption being generous."""
    ok = [r for r in rows if r.get("ran") and (r.get("expectancy") or 0) > 0]
    return max((r["multiple"] for r in ok), default=None)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--multiples", default=",".join(str(m) for m in DEFAULT_MULTIPLES))
    args = ap.parse_args()
    multiples = [float(x) for x in args.multiples.split(",") if x.strip()]

    overrides = ft.validated_overrides()
    if not overrides:
        print("No VALIDATED overrides -- nothing is trading, nothing to stress.")
        return

    ta = TechnicalAnalysisEngine()
    ta.initialize()
    results = []

    for ov in overrides:
        ysym, tf, strat = ov["yahoo_symbol"], ov["timeframe"], ov["strategy"]
        path = DATA / f"{ysym}_{tf}.parquet"
        if not path.exists():
            print(f"  ! {ysym} {tf}: no data at {path}")
            continue
        df = pd.read_parquet(path)
        enr = ta.analyze(df)
        if not enr.success:
            print(f"  ! {ysym} {tf}: e07 failed -- {enr.message}")
            continue
        print(f"stressing {ysym} {tf} {strat} {ov['params']} over {len(multiples)} cost levels...")
        rows = stress_one(enr.data["df"], strat, ov["params"], tf, multiples)
        be = breakeven_multiple(rows)
        results.append({
            "symbol": ysym, "timeframe": tf, "strategy": strat,
            "params": ov["params"], "backtest_claim": ov["claim"],
            "levels": rows, "breakeven_multiple": be,
        })
        for r in rows:
            if r.get("ran"):
                exp = r.get("expectancy")
                tr = r.get("trades")
                print(f"    {r['multiple']:>5.1f}x ({r['round_trip_pct']:.2f}% round trip): "
                      f"expectancy {exp if exp is None else round(exp, 3):>9}  "
                      f"trades {tr if tr is not None else '-':>4}  "
                      f"passed={r['passed_validation']}")

    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_commission_pct": BASE_COMMISSION, "base_slippage_pct": BASE_SLIPPAGE,
        "results": results,
    }, indent=2, default=str), encoding="utf-8")

    lines = [
        "# Execution-Cost Stress",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "PHASE 11 of `reports/upgrade statergy.txt`. Each live strategy is re-priced at "
        "multiples of E26's assumed fill quality (0.1% commission + 0.05% slippage per side "
        "= **0.30% round trip** at 1.0x). Everything else is held fixed.",
        "",
        "The number that matters is **breakeven multiple**: how much worse than assumed your "
        "fills can be before the strategy stops making money. A strategy that dies at 1.5x is "
        "not robust — a volatile open, a wide spread, or a partial fill can cost that much on "
        "a single trade.",
        "",
    ]

    for res in results:
        be = res["breakeven_multiple"]
        lines += [
            f"## {res['symbol']} {res['timeframe']} — `{res['strategy']}`",
            "",
            f"Params: `{res['params']}`",
            "",
            "| Cost multiple | Round trip | Trades | Win% | Expectancy | IS Sharpe | Passed E26 |",
            "|---|---|---|---|---|---|---|",
        ]
        for r in res["levels"]:
            if not r.get("ran"):
                lines.append(f"| {r['multiple']}x | — | did not run | | | | |")
                continue
            wr = f"{r['win_rate'] * 100:.1f}%" if r.get("win_rate") is not None else "—"
            lines.append(
                f"| {r['multiple']}x | {r['round_trip_pct']:.2f}% | {r['trades']} | {wr} | "
                f"{r['expectancy']:.3f} | "
                f"{round(r['is_sharpe'], 2) if r.get('is_sharpe') is not None else '—'} | "
                f"{r['passed_validation']} |")
        lines += [""]
        if be is None:
            lines += [
                "**Unprofitable even at zero cost.** The edge in this configuration was never "
                "in the entry rule — it was in the cost assumption. Treat any positive "
                "backtest result for it as an artefact.",
                "",
            ]
        elif be <= 1.0:
            lines += [
                f"**Breakeven at {be}x — this strategy has no cost headroom at all.** It stops "
                "making money at or below the fill quality its own backtest assumed. Any "
                "slippage worse than modelled turns it negative.",
                "",
            ]
        elif be < 2.0:
            lines += [
                f"**Breakeven at {be}x.** Thin. A single bad fill on a volatile open can cost "
                "more than this margin, and the backtest's assumed fills are optimistic for "
                "retail execution.",
                "",
            ]
        else:
            lines += [
                f"**Breakeven at {be}x** — the edge survives fills {be:.0f} times worse than "
                "assumed. That is real headroom, though it says nothing about whether the "
                "edge itself is real; this re-prices an in-sample result, it does not "
                "re-validate it.",
                "",
            ]

    lines += [
        "## What this does not establish",
        "",
        "- This sweeps ONE axis on an ALREADY-SELECTED strategy. Surviving 5x cost is not "
        "validation — it is the same in-sample result, priced differently.",
        "- Costs are modelled as a flat percentage. Real spreads widen exactly when these "
        "strategies want to trade (breakouts fire on volatility), so a flat multiple "
        "understates the correlation between bad fills and trade timing.",
        "- Partial fills, latency and market impact are still not modelled anywhere in E26.",
        "",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {REPORT}")
    print(f"Wrote {REPORT_JSON}")

    try:
        from project_titan_x.core import experiment as _ex
        _ex.record(
            kind="robustness",
            title=f"Execution-cost stress on {len(results)} live strategy/strategies",
            metrics={r["strategy"]: {"symbol": r["symbol"],
                                     "breakeven_multiple": r["breakeven_multiple"]}
                     for r in results},
            artifacts=[str(REPORT), str(REPORT_JSON)],
            conclusion="; ".join(
                f"{r['symbol']} {r['strategy']}: breakeven at "
                f"{r['breakeven_multiple']}x assumed cost" if r["breakeven_multiple"]
                else f"{r['symbol']} {r['strategy']}: unprofitable even at ZERO cost"
                for r in results) or "no live strategies stressed",
            notes=["Re-prices an already-selected strategy; promotes nothing and "
                   "re-validates nothing."],
        )
    except Exception as e:  # noqa: BLE001
        print(f"  (warning: could not record experiment lineage: {e})")


if __name__ == "__main__":
    main()
