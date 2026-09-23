"""
Module: run_forward_test.py
Description: Drives the forward test required by reports/statergy.txt
    NON-NEGOTIABLE #14 ("Paper trading / forward testing must precede live
    trading"). Two things happen per run, in this order:

      1. RESOLVE  -- every prediction whose horizon has now elapsed is settled
                     against real subsequent bars.
      2. RECORD   -- each VALIDATED override is run on the latest bar through
                     the SAME engine chain the live API uses, and whatever it
                     says is appended to the log before the outcome is knowable.

    Resolve runs first on purpose: it settles yesterday's predictions using
    bars that closed before today's prediction is even made, so a single run
    can never both create and settle the same record.

    ONLY VALIDATED OVERRIDES ARE TRACKED. The scanner reads
    data/models/e51_signals/*_strategy_override.json and skips anything whose
    `stage0.status` is not exactly "VALIDATED" -- the same deny-by-default rule
    `e51_signals._load_strategy_override` applies to live signals. Forward
    testing a rule that is not driving live decisions would burn calendar time
    on a question nobody is risking money on.

    THE ENGINE CHAIN IS THE LIVE ONE, NOT A REPLICA. E07 -> E04 -> E06 -> E08
    -> E51 in the same order and with the same arguments as
    api/main.py::generate_signal. A forward test of a reimplementation would
    measure the reimplementation. If any engine fails for a symbol, that symbol
    is SKIPPED and reported as skipped -- never filled in with a default, which
    would silently enter a fabricated prediction into the one log that is
    supposed to contain only real ones.

    RUN IT ON A SCHEDULE, ONCE PER BAR. For the two 1d strategies currently
    live, once daily after the UTC close. Running more often is harmless (a
    second call inside the same bar is a no-op), running less often is not:
    `forward_test.record_signal` refuses bars more than three bars stale, so
    missed days are lost rather than backfilled. That is the intended
    behaviour -- see the module docstring in
    engines/e24_strategy_research/forward_test.py.

Usage:
    python scripts/run_forward_test.py                 # resolve, then record
    python scripts/run_forward_test.py --resolve-only  # settle matured only
    python scripts/run_forward_test.py --report-only   # rebuild the report
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

from project_titan_x.engines.e24_strategy_research import forward_test as ft  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REPORT_MD = ROOT / "reports" / "FORWARD_TEST.md"
REPORT_JSON = ROOT / "data" / "models" / "e24_strategy_research" / "forward_test_summary.json"



def do_resolve() -> list[dict]:
    print("Resolving matured predictions...")
    from project_titan_x.engines.registry import get_registry
    written = ft.resolve_pending(ft.registry_bars_resolver(get_registry()))
    for r in written:
        print(f"  resolved {r['record_id']}: {r['outcome']} "
              f"{r['r_multiple']:+.2f}R in {r['bars_held']} bars"
              + ("  [ambiguous bar -> counted as stop]" if r["ambiguous_bar"] else ""))
    if not written:
        print("  nothing matured since the last run")
    return written


def do_record(overrides: list[dict]) -> dict:
    """Thin wrapper over forward_test.scan_and_record -- the engine chain lives
    there so the API's scheduler and this CLI cannot drift apart."""
    from project_titan_x.engines.registry import get_registry

    out = ft.scan_and_record(get_registry(), overrides,
                             source="scripts/run_forward_test.py")
    for r in out["recorded"]:
        print(f"  recorded {r['label']}: {r['direction']} @ {r['entry']} "
              f"(stop {r['stop_loss']}, target {r['take_profit']}, "
              f"conf {r['confidence']})")
    for label, why in out["silent"]:
        print(f"  - {label}: {why}")
    for label, why in out["skipped"]:
        print(f"  ! {label} SKIPPED -- {why}")
    return out


def write_report() -> dict:
    summary = ft.summarise()
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    inception = summary["inception"]
    lines = [
        "# Forward Test",
        "",
        f"Generated: {summary['generated_at']}",
        f"Inception: **{inception or 'not started'}**",
        f"Predictions: **{summary['total_predictions']}** · "
        f"Resolved: **{summary['total_resolved']}**",
        "",
        "Every row below was written **before its outcome was knowable**. "
        "`engines/e24_strategy_research/forward_test.py` refuses any record dated before this "
        "log's inception, dated in the future, or written more than three bars after its own "
        "bar closed — so this file cannot be padded with replayed history, which is the only "
        "thing that separates it from the backtests that already exist.",
        "",
        "Only overrides carrying an explicit `stage0.status == \"VALIDATED\"` tag are tracked, "
        "matching the deny-by-default rule that governs live signals.",
        "",
    ]

    if not summary["series"]:
        lines += [
            "## No predictions yet",
            "",
            "The log has been created but nothing has been recorded. Until resolved forward "
            "trades accumulate, **the live strategies are running on historical evidence "
            "alone** — an in-sample sweep, a walk-forward split and a synthetic-null "
            "percentile, all computed over bars that already existed when the search ran.",
            "",
            "Run `python scripts/run_forward_test.py` once per bar to begin accumulating.",
            "",
        ]
    else:
        lines += [
            "## Series",
            "",
            "| Instrument | TF | Strategy | Predicted | Resolved | Fwd win% | Fwd exp. (R) | "
            "Total R | Backtest win% | Verdict |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for s in summary["series"]:
            wr = f"{s['forward_win_rate']:.1%}" if s.get("forward_win_rate") is not None else "—"
            ex = f"{s['forward_expectancy_r']:+.2f}" if s.get("forward_expectancy_r") is not None else "—"
            tr = f"{s['forward_total_r']:+.2f}" if s.get("forward_total_r") is not None else "—"
            bw = s.get("backtest_claim", {}).get("win_rate")
            bws = f"{bw:.1%}" if bw else "—"
            lines.append(
                f"| {s['symbol']} | {s['timeframe']} | `{s['strategy']}` | {s['predictions']} | "
                f"{s['forward_trades']} | {wr} | {ex} | {tr} | {bws} | **{s['verdict']}** |"
            )

        lines += ["", "## How long until this means anything", ""]
        for s in summary["series"]:
            need = s.get("trades_to_detect_degradation")
            if not need:
                continue
            days = s.get("estimated_days_to_that_many")
            est = f" — at the observed signal rate, roughly **{days:.0f} days**" if days else ""
            rr, be = s.get("planned_reward_risk"), s.get("breakeven_win_rate")
            basis = (f"breakeven ({be:.1%}, implied by the planned {rr:.2f}:1 reward:risk)"
                     if be else "a coin flip (50%)")
            lines.append(
                f"- **{s['symbol']} {s['timeframe']}**: {need} resolved forward trades would be "
                f"needed to detect a fall from the claimed "
                f"{s['backtest_claim'].get('win_rate', 0):.1%} to {basis}{est}. "
                f"Currently {s['forward_trades']}."
            )

        lines += ["", "## Notes", ""]
        for s in summary["series"]:
            if s.get("notes"):
                lines.append(f"**{s['symbol']} {s['timeframe']} · {s['strategy']}**")
                lines.append("")
                for n in s["notes"]:
                    lines.append(f"- {n}")
                lines.append("")

    lines += [
        "## What this does and does not establish",
        "",
        "- A `consistent` verdict means the backtest claim has not yet been contradicted. It is "
        "not confirmation, and with a thin sample it is barely evidence — the credible interval "
        "does the talking, not the point estimate.",
        "- Ambiguous bars (range containing both stop and target) are counted as **stops**. "
        "OHLC cannot order two touches inside one bar, so the true result is never worse than "
        "what is reported here and may be better.",
        "- Bars with no signal are not logged. They are real observations about the strategy, "
        "but they are not trades, and padding a win-rate denominator with them would understate "
        "it.",
        "- Missed runs are lost, not backfilled. A gap in the log is a gap in the evidence.",
        "",
        "## Keeping this accumulating",
        "",
        "Evidence only accrues on bars that were actually observed. The scheduled job "
        "inside the API server fires **immediately on startup** and then every 6 hours, so "
        "starting the server at any point during a day captures that day's bar. Days when "
        "the server never runs are lost permanently — `record_signal` refuses bars more "
        "than three bars stale, which is the rule that makes this a forward test rather "
        "than a backtest.",
        "",
        "To accumulate without depending on the server being up, register the CLI as a "
        "daily Windows task (run it yourself; it changes system state, so it is not done "
        "for you):",
        "",
        "```",
        "schtasks /create /tn \"TitanX Forward Test\" /sc daily /st 02:00 \\",
        "        /tr \"<repo>/.venv/Scripts/python.exe <repo>/scripts/run_forward_test.py\"",
        "```",
        "",
        "Either route is enough on its own; running both is harmless, because a second "
        "call inside the same bar is a deduplicated no-op.",
        "",
    ]
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--resolve-only", action="store_true",
                    help="Settle matured predictions; record nothing new.")
    ap.add_argument("--report-only", action="store_true",
                    help="Rebuild the report from the existing log; touch nothing else.")
    args = ap.parse_args()

    print(f"Forward test run at {datetime.now(timezone.utc).isoformat()}")

    if not args.report_only:
        do_resolve()
        if not args.resolve_only:
            overrides = ft.validated_overrides()
            print(f"\n{len(overrides)} VALIDATED override(s) to track:")
            for ov in overrides:
                print(f"  {ov['yahoo_symbol']} {ov['timeframe']} -- {ov['strategy']} "
                      f"{ov['params']}")
            if overrides:
                print()
                do_record(overrides)
            else:
                print("  none -- nothing is currently cleared for live signals, "
                      "so there is nothing to forward test.")

    summary = write_report()
    print(f"\n{summary['total_predictions']} prediction(s), "
          f"{summary['total_resolved']} resolved")
    for s in summary["series"]:
        print(f"  {s['symbol']} {s['timeframe']} {s['strategy']}: {s['verdict']} "
              f"({s['forward_trades']} resolved)")
    print(f"\nWrote {REPORT_MD}")
    print(f"Wrote {REPORT_JSON}")


if __name__ == "__main__":
    main()
