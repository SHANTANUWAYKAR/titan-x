"""
Module: run_improvement_loop.py
Description: Runs PHASE 23's continuous improvement engine
    (engines/e24_strategy_research/improvement_loop.py) against the strategies
    that are actually live, and writes a review for a human to approve or
    ignore.

    This is the honest form of the "self-improving trading agent" pattern: the
    loop diagnoses what is failing, proposes ONE-variable changes drawn from
    the grid the null campaigns were calibrated against, tests each out of
    sample, rejects anything that improves in-sample at out-of-sample expense,
    and records every attempt including the failures.

    IT DEPLOYS NOTHING. The output is a markdown proposal. Going live still
    requires a deliberate Stage 0 tag written by a different pass, which is
    what PHASE 33 ("Human Approval") and non-negotiable 20 require.

Usage:
    python scripts/run_improvement_loop.py
    python scripts/run_improvement_loop.py --max-trials 20
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import argparse
import io
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import pandas as pd  # noqa: E402

from project_titan_x.engines.e07_technical import TechnicalAnalysisEngine  # noqa: E402
from project_titan_x.engines.e24_strategy_research import forward_test as ft  # noqa: E402
from project_titan_x.engines.e24_strategy_research import improvement_loop as il  # noqa: E402
from project_titan_x.engines.e24_strategy_research.engine import (  # noqa: E402
    BARS_PER_YEAR,
    DEFAULT_STRATEGY_GRID,
    _run_one_candidate_worker,
)
from project_titan_x.engines.e26_backtesting.engine import (  # noqa: E402
    STAGE0_TIMEFRAME_THRESHOLDS,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
REPORT = ROOT / "reports" / "IMPROVEMENT_REVIEW.md"

COMMISSION, SLIPPAGE = 0.001, 0.0005


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max-trials", type=int, default=il.DEFAULT_MAX_TRIALS)
    ap.add_argument("--min-improvement", type=float, default=il.DEFAULT_MIN_IMPROVEMENT)
    args = ap.parse_args()

    overrides = ft.validated_overrides()
    if not overrides:
        print("No VALIDATED overrides -- nothing live to improve.")
        return

    ta = TechnicalAnalysisEngine()
    ta.initialize()
    summaries = []

    for ov in overrides:
        ysym, tf, strat = ov["yahoo_symbol"], ov["timeframe"], ov["strategy"]
        path = DATA / f"{ysym}_{tf}.parquet"
        if not path.exists():
            print(f"  ! {ysym} {tf}: no data")
            continue
        enr = ta.analyze(pd.read_parquet(path))
        if not enr.success:
            print(f"  ! {ysym} {tf}: e07 failed -- {enr.message}")
            continue
        frame = enr.data["df"]
        ppy = BARS_PER_YEAR.get(tf, 252)
        bar = (STAGE0_TIMEFRAME_THRESHOLDS.get(tf) or {}).get("min_selection_score")

        def run_candidate(params: dict, _f=frame, _tf=tf, _s=strat, _ppy=ppy):
            return _run_one_candidate_worker(
                _f, _s, params, None, _ppy, SLIPPAGE, COMMISSION, timeframe=_tf)

        incumbent = run_candidate(ov["params"])
        if not incumbent:
            print(f"  ! {ysym} {tf} {strat}: incumbent did not run")
            continue

        diag = il.diagnose(strat, ysym, tf, incumbent, bar=bar)
        print(f"\n{ysym} {tf} {strat}")
        print(f"  incumbent: selection {diag.selection_score:.4f} "
              f"(IS {diag.is_sharpe:.3f} / OOS {diag.oos_sharpe:.3f}), "
              f"{diag.trades} trades, bar {bar}")
        print(f"  diagnosis: {diag.primary_failure}")

        variants = il.propose_variants(ov["params"], DEFAULT_STRATEGY_GRID, diag,
                                       max_variants=args.max_trials)
        print(f"  {len(variants)} single-variable variant(s) available")
        results, trials = il.evaluate(
            variants, run_candidate,
            incumbent_selection=diag.selection_score,
            incumbent_oos=diag.oos_sharpe,
            min_improvement=args.min_improvement,
            max_trials=args.max_trials,
        )
        summary = il.summarise_run(diag, results, trials, max_trials=args.max_trials)
        eid = il.record_run(summary)
        summary["experiment_id"] = eid
        summaries.append(summary)

        if summary["proposal"]:
            p = summary["proposal"]
            print(f"  PROPOSAL (not deployed): {p['changed']} -> selection "
                  f"{p['selection_score']:.4f}")
        else:
            print(f"  no variant improved out of sample ({summary['n_rejected']} rejected)")

    lines = [
        "# Improvement Review",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "PHASE 23 of `reports/upgrade statergy.txt`: diagnose, hypothesise, modify ONE "
        "variable, test out of sample, accept or reject — run against the strategies that "
        "are currently live.",
        "",
        "**Nothing here is deployed.** These are proposals for a human to approve or "
        "ignore. Going live still requires a deliberate Stage 0 tag, which this loop "
        "cannot write (PHASE 33; non-negotiable 20).",
        "",
        "**Read the trial count before the result.** This loop is itself a search: "
        "best-of-N climbs on noise alone, so a variant that wins after 30 trials is a much "
        "weaker claim than one that wins after 3. That is the failure mode that makes most "
        "self-tuning trading agents lose money — they improve their way into fitting noise, "
        "and report only the winner.",
        "",
    ]

    for s in summaries:
        d = s["diagnosis"]
        lines += [
            f"## {s['symbol']} {s['timeframe']} — `{s['strategy']}`",
            "",
            f"**Diagnosis.** {d['primary_failure']}",
            "",
        ]
        if len(d["all_failures"]) > 1:
            lines += ["Also:", ""] + [f"- {f}" for f in d["all_failures"][1:]] + [""]
        lines += [
            f"Incumbent selection score **{d['selection_score']:.4f}** against a bar of "
            f"{d['bar']} (margin {d['margin']:+.4f}).",
            "",
            f"**Trials consumed: {s['trials_consumed']}** · accepted {s['n_accepted']} · "
            f"rejected {s['n_rejected']}",
            "",
        ]
        if s["proposal"]:
            p = s["proposal"]
            lines += [
                "### Proposal (NOT deployed)",
                "",
                f"- **Change:** `{p['changed']}`",
                f"- **Hypothesis:** {p['hypothesis']}",
                f"- **Result:** selection {p['selection_score']:.4f} "
                f"(IS {p['is_sharpe']:.3f} / OOS {p['oos_sharpe']:.3f}), {p['trades']} trades",
                f"- **Why accepted:** {p['reason']}",
                "",
            ]
        else:
            lines += [
                "### No proposal",
                "",
                "No single-variable change improved the selection score without costing "
                "out-of-sample performance. **This is a real result, not a failed run** — it "
                "says the incumbent parameterisation is already the best of those tested, and "
                "that the strategy's problem is not its parameters.",
                "",
            ]
        if s["rejections"]:
            lines += ["### Rejected (kept — non-negotiables 8 and 9)", "",
                      "| Change | Selection | OOS Sharpe | Why rejected |", "|---|---|---|---|"]
            for r in s["rejections"][:25]:
                sel = f"{r['selection_score']:.4f}" if r["selection_score"] is not None else "—"
                oos = f"{r['oos_sharpe']:.3f}" if r["oos_sharpe"] is not None else "—"
                lines.append(f"| `{r['changed']}` | {sel} | {oos} | {r['reason']} |")
            if len(s["rejections"]) > 25:
                lines.append(f"| … | | | {len(s['rejections']) - 25} more in the experiment log |")
            lines += [""]
        lines += ["### Caveats", ""] + [f"- {c}" for c in s["caveats"]] + [""]
        if s.get("experiment_id"):
            lines += [f"Recorded as experiment `{s['experiment_id']}`.", ""]
        lines += ["---", ""]

    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {REPORT}")


if __name__ == "__main__":
    main()
