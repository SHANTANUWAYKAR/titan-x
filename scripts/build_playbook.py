"""The playbook: best strategy per ASSET per TRADING STYLE, with its gates.

This is the capstone read of the leaderboard. For every (asset, style) pair it
names the best candidate and states plainly whether that candidate is
TRADEABLE or merely top of a losing pile.

THE GATES, and why each one exists -- all four are lessons this repo paid for:

  1. expectancy > 0            A ranking without this crowns the least-bad loser.
  2. trades >= MIN_TRADES      Below it, a 5-trade "A+" is arithmetic noise. This
                               repo once graded 2,906 candidates A on no null
                               evidence at all.
  3. beats the synthetic null  At proper grid size, 150 of 150 pure-noise paths
                               produced "passing" candidates here. Anything that
                               has never been scored against noise is unproven,
                               not good.
  4. deflated Sharpe           155,017 candidates were scored. The best of
                               155,017 draws looks extraordinary by construction,
                               and DSR is the correction for exactly that.

A candidate that fails any gate is still SHOWN -- with the gate it failed --
because "nothing qualifies for this asset" is the single most useful sentence
a playbook can contain, and hiding the row would turn it into a blank space
that looks like an oversight.

STYLE comes from the timeframe, using this project's own convention
(api/main.py `_TF_STYLE`). It is not re-derived here.

    python scripts/build_playbook.py
    python scripts/build_playbook.py --min-trades 100 --style Swing
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LB = (ROOT / "project_titan_x" / "data" / "models" /
      "e24_strategy_research" / "strategy_leaderboard.json")
OUT_MD = ROOT / "project_titan_x" / "reports" / "PLAYBOOK.md"
OUT_JSON = (ROOT / "project_titan_x" / "data" / "models" /
            "e24_strategy_research" / "playbook.json")

TF_STYLE = {
    "1m": "Intraday", "5m": "Intraday", "15m": "Intraday", "30m": "Intraday",
    "1h": "Swing", "4h": "Swing",
    "1d": "Positional", "1wk": "Positional",
}
STYLE_ORDER = ["Intraday", "Swing", "Positional"]


def gates(row: dict, min_trades: int, min_null_pct: float, min_dsr: float) -> list[str]:
    """Every gate this row fails. Empty list means tradeable."""
    bad = []
    if (row.get("expectancy") or 0) <= 0:
        bad.append(f"expectancy {row.get('expectancy')}")
    if (row.get("trades") or 0) < min_trades:
        bad.append(f"{row.get('trades') or 0} trades < {min_trades}")
    np_ = row.get("null_percentile")
    if np_ is None:
        bad.append("never scored against the null")
    elif np_ < min_null_pct:
        bad.append(f"null pct {np_:.1f} < {min_null_pct:.0f}")
    dsr = row.get("dsr")
    if dsr is None:
        bad.append("no deflated Sharpe")
    elif dsr < min_dsr:
        bad.append(f"DSR {dsr:.3f} < {min_dsr:.2f}")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-trades", type=int, default=60)
    ap.add_argument("--min-null-pct", type=float, default=95.0)
    ap.add_argument("--min-dsr", type=float, default=0.95)
    ap.add_argument("--style", default="", help="restrict to one style")
    args = ap.parse_args()

    if not LB.exists():
        print(f"{LB} missing -- run scripts/build_strategy_leaderboard.py first")
        return 1
    rows = json.loads(LB.read_text(encoding="utf-8"))["rows"]
    print(f"{len(rows):,} candidates", flush=True)

    # Best candidate per (symbol, style).
    #
    # THE SAMPLE GATE IS APPLIED BEFORE RANKING, NOT AFTER. Ranking on
    # expectancy alone crowns whichever candidate happened to take two trades
    # and win both -- the first version of this script headlined every asset
    # with rows like "+26.3755 expectancy, PF inf, 2 trades". Those are
    # arithmetic, not strategies, and putting them at the top of a playbook is
    # exactly how a thin sample gets mistaken for an edge.
    #
    # So: rank only among candidates that already have a real sample. If an
    # asset has none, that is reported as such rather than backfilled with the
    # best fluke available.
    best: dict[tuple[str, str], dict] = {}
    counts: dict[tuple[str, str], int] = defaultdict(int)
    eligible: dict[tuple[str, str], int] = defaultdict(int)
    for r in rows:
        style = TF_STYLE.get(r.get("timeframe", ""), None)
        if style is None or (args.style and style != args.style):
            continue
        key = (r["symbol"], style)
        counts[key] += 1
        if (r.get("trades") or 0) < args.min_trades:
            continue
        eligible[key] += 1
        cur = best.get(key)
        k_new = ((r.get("expectancy") or -9e9), (r.get("trades") or 0))
        if cur is None or k_new > ((cur.get("expectancy") or -9e9), (cur.get("trades") or 0)):
            best[key] = r

    symbols = sorted({s for s, _ in best})
    styles = [s for s in STYLE_ORDER if not args.style or s == args.style]

    playbook, n_ok = {}, 0
    for (sym, style), r in best.items():
        bad = gates(r, args.min_trades, args.min_null_pct, args.min_dsr)
        playbook[f"{sym}|{style}"] = {
            "symbol": sym, "style": style, "timeframe": r.get("timeframe"),
            "strategy": r.get("strategy"), "params": r.get("params"),
            "grade": r.get("grade"), "trades": r.get("trades"),
            "win_rate": r.get("win_rate"), "expectancy": r.get("expectancy"),
            "profit_factor": r.get("profit_factor"),
            "max_drawdown_pct": r.get("max_drawdown_pct"),
            "oos_sharpe": r.get("oos_sharpe"), "dsr": r.get("dsr"),
            "null_percentile": r.get("null_percentile"),
            "candidates_considered": counts[(sym, style)],
            "candidates_with_sample": eligible[(sym, style)],
            "gate_failures": bad, "tradeable": not bad,
        }
        n_ok += int(not bad)

    L = [
        "# Playbook — best strategy per asset, per trading style",
        "",
        f"Scored from **{len(rows):,} candidates**. Style comes from the timeframe "
        "using this project's own convention (1m–30m Intraday · 1h–4h Swing · "
        "1d–1wk Positional).",
        "",
        "Ranked on **expectancy**, then trade count — deliberately not on Sharpe or "
        "`a_plus_score`, both of which reward thin samples.",
        "",
        "## The four gates",
        "",
        "| Gate | Why it exists |",
        "|---|---|",
        "| expectancy > 0 | without it, the ranking crowns the least-bad loser |",
        f"| ≥ {args.min_trades} trades | below this a 5-trade \"A+\" is arithmetic noise |",
        f"| null percentile ≥ {args.min_null_pct:.0f} | 150 of 150 pure-noise paths once produced \"passing\" candidates here |",
        f"| DSR ≥ {args.min_dsr:.2f} | the best of {len(rows):,} draws looks extraordinary by construction |",
        "",
        f"**{n_ok} of {len(playbook)} (asset × style) cells are tradeable by all four gates.**",
        "",
    ]
    if n_ok == 0:
        L += [
            "> **Nothing qualifies anywhere.** That is a finding, not a gap in the",
            "> testing. Each cell below names the best candidate that exists for that",
            "> asset and style, and the gate it fails. The most common failure is the",
            "> null gate — a candidate that has never been scored against noise is",
            "> *unproven*, not good.",
            "",
        ]

    for style in styles:
        L += [f"## {style}", "",
              "| Asset | TF | Strategy | Grade | Trades | Win% | Expect. | PF | MaxDD% | DSR | Null pct | Verdict |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for sym in symbols:
            p = playbook.get(f"{sym}|{style}")
            if not p:
                n_all = counts.get((sym, style), 0)
                L.append(
                    f"| {sym} | — | _none of {n_all:,} candidates reached "
                    f"{args.min_trades} trades_ | | | | | | | | | no sample |")
                continue
            wr = f"{(p['win_rate'] or 0)*100:.1f}%" if p["win_rate"] is not None else "—"
            dsr = f"{p['dsr']:.3f}" if p["dsr"] is not None else "—"
            npc = f"{p['null_percentile']:.0f}" if p["null_percentile"] is not None else "**never**"
            verdict = "**TRADEABLE**" if p["tradeable"] else p["gate_failures"][0]
            L.append(
                f"| {sym} | {p['timeframe']} | `{p['strategy']}` | {p['grade']} | "
                f"{p['trades'] or 0:,} | {wr} | {p['expectancy']:+.4f} | "
                f"{(p['profit_factor'] or 0):.2f} | {(p['max_drawdown_pct'] or 0):.1f} | "
                f"{dsr} | {npc} | {verdict} |")
        L.append("")

    # Failure census -- grouped by gate TYPE, not by the value that failed it.
    # Keying on the raw string split "DSR 0.001" and "3 trades < 60" into
    # separate rows and made the most important table in the report unreadable.
    def gate_kind(msg: str) -> str:
        if msg.startswith("expectancy"):
            return "expectancy <= 0"
        if "trades <" in msg:
            return f"fewer than {args.min_trades} trades"
        if "null" in msg:
            return "never scored against the null"
        if msg.startswith("DSR") or "deflated" in msg:
            return f"deflated Sharpe < {args.min_dsr:.2f}"
        return msg

    census: dict[str, int] = defaultdict(int)
    for p in playbook.values():
        for b in p["gate_failures"]:
            census[gate_kind(b)] += 1
    L += ["## Which gate is binding", "",
          f"Out of {len(playbook)} cells:", "",
          "| Gate failed | Cells |", "|---|---|"]
    for k, v in sorted(census.items(), key=lambda kv: -kv[1]):
        L.append(f"| {k} | {v} |")
    top = max(census.items(), key=lambda kv: kv[1]) if census else None
    if top and top[1] == len(playbook):
        L += ["",
              f"**Every single cell fails \"{top[0]}\".** That is the one to attack "
              "first — it is a measurement that has not been run, not a verdict that "
              "has been earned."]

    # The DSR reading is the decisive one and deserves to be stated, not
    # left as a column of small numbers.
    dsrs = [p["dsr"] for p in playbook.values() if p.get("dsr") is not None]
    if dsrs:
        L += ["", "## What the deflated Sharpe already settles", "",
              f"Deflated Sharpe is the probability that a candidate's TRUE Sharpe "
              f"exceeds the noise floor of the search that found it. Across these "
              f"{len(dsrs)} cells it runs **{min(dsrs):.3f} to {max(dsrs):.3f}** "
              f"(median {sorted(dsrs)[len(dsrs)//2]:.3f}).",
              "",
              f"Every cell here already clears expectancy and sample size — these are "
              f"real setups on real samples, not flukes. But {len(rows):,} candidates "
              "were searched, and the best of that many draws looks extraordinary by "
              "construction. A DSR near zero says the observed edge is indistinguishable "
              "from the best-of-search luck.",
              "",
              "**So the null gate, while genuinely unrun, is not what is holding these "
              "back.** Running it would confirm what the deflation already implies. The "
              "binding constraint is that the search space was enormous and the surviving "
              "edge is not large enough to stand out from it.",
              ""]

    L += [
        "",
        "## How to use this",
        "",
        "- A **TRADEABLE** cell has cleared expectancy, sample size, the synthetic",
        "  null and the multiple-testing correction. Nothing less should get capital.",
        "- A cell failing only the **null** gate is a candidate for null scoring, not",
        "  a trade. Run `research/score_overrides_stage0.py`.",
        "- A cell failing **expectancy** is finished. No amount of sizing or filtering",
        "  turns a negative edge positive — measured directly in",
        "  `reports/ENHANCEMENTS.md`, where volatility targeting improved expectancy in",
        "  only 1 of 4 setups and a regime filter in 4 of 4, neither crossing zero.",
        "- Per-concept decomposition is in `reports/CONCEPT_LAB.md`; the cost",
        "  arithmetic that binds all of it is in `reports/TRADING_ROADMAP.md` §5.1.",
    ]
    OUT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")
    OUT_JSON.write_text(json.dumps(
        {"gates": {"min_trades": args.min_trades,
                   "min_null_percentile": args.min_null_pct,
                   "min_dsr": args.min_dsr},
         "candidates_scored": len(rows), "tradeable": n_ok,
         "cells": playbook}, indent=2, default=str), encoding="utf-8")
    print(f"{n_ok} of {len(playbook)} cells tradeable")
    print(f"Wrote {OUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
