"""Backtest every setup across every timeframe and asset, journal it, and
assign each setup to the trading style it actually belongs to.

STYLE IS ASSIGNED FROM EVIDENCE, NOT FROM THE TIMEFRAME LABEL. The usual
convention maps 1m-30m to Intraday, 1h-4h to Swing, 1d+ to Positional, and
that is where a setup is *tested*. Where it BELONGS is a different question,
answered here by which style band actually produced its best expectancy on a
sufficient sample. A setup can be conventionally "intraday" and still only
work positionally; saying so is the point of the exercise.

EVERY ASSIGNMENT CARRIES ITS GATES. A style assignment with a negative
expectancy is not a recommendation, and the report says so on the row. The
gates are the ones this repo already uses everywhere else:
    net expectancy > 0 · >= 100 trades · beats its own shuffled null

    python setups/run_trade_journal.py
    python setups/run_trade_journal.py --timeframes 1d,4h --setups sr_bounce
    python setups/run_trade_journal.py --export-csv
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from project_titan_x.core.config import list_assets  # noqa: E402
from project_titan_x.core.config.assets import SUPPORTED_ASSETS  # noqa: E402
from project_titan_x.setups.concept_lab import CONCEPTS, LabConfig, _atr  # noqa: E402
from project_titan_x.setups.trade_journal import (  # noqa: E402
    build_journal, compute_stats,
)

DATA = ROOT / "project_titan_x" / "data" / "processed"
REPORTS = ROOT / "project_titan_x" / "reports"
OUT_MD = REPORTS / "TRADE_JOURNAL.md"
OUT_CSV = REPORTS / "trade_journal.csv"
OUT_JSON = ROOT / "project_titan_x" / "data" / "models" / "setups" / "trade_journal.json"

# This project's own convention (api/main.py `_TF_STYLE`), unchanged.
TF_STYLE = {
    "1m": "Intraday", "5m": "Intraday", "15m": "Intraday", "30m": "Intraday",
    "1h": "Swing", "4h": "Swing",
    "1d": "Positional", "1wk": "Positional",
}


def _yahoo(s):
    a = SUPPORTED_ASSETS.get(s)
    return getattr(a, "yahoo_symbol", s) if a else s


def _load(sym, tf):
    for c in (_yahoo(sym), sym):
        h = glob.glob(str(DATA / f"{c}_{tf}.parquet"))
        if h:
            d = pd.read_parquet(h[0])
            d.columns = [x.lower() for x in d.columns]
            return d
    return None


def _null_expectancy(df, sig, cfg, atr, sym, tf, name, rng, paths=3):
    """Same trade count, random timing -- the bar a setup must clear."""
    out = []
    nz = np.nonzero(sig)[0]
    if nz.size == 0:
        return out
    lo, hi = 250, len(df) - cfg.horizon_bars - 2
    if hi <= lo:
        return out
    for _ in range(paths):
        ns = np.zeros(len(df), dtype=int)
        pk = rng.choice(np.arange(lo, hi), size=min(nz.size, hi - lo), replace=False)
        ns[pk] = sig[nz][:pk.size]
        rows = build_journal(df, ns, symbol=sym, timeframe=tf, setup_name=name,
                             atr=atr, atr_mult=cfg.atr_mult,
                             reward_risk=cfg.reward_risk,
                             horizon_bars=cfg.horizon_bars,
                             cost_round_trip=cfg.cost_round_trip)
        st = compute_stats(rows)
        if st:
            out.append(st.expectancy_r)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeframes", default="5m,15m,1h,4h,1d")
    ap.add_argument("--setups", default="", help="comma-separated subset")
    ap.add_argument("--rr", type=float, default=2.0)
    ap.add_argument("--horizon", type=int, default=20)
    ap.add_argument("--cost-bps", type=float, default=30.0)
    ap.add_argument("--null-paths", type=int, default=3)
    ap.add_argument("--export-csv", action="store_true",
                    help="write every journal row to reports/trade_journal.csv")
    ap.add_argument("--sample-rows", type=int, default=15,
                    help="how many example records to print in the report")
    args = ap.parse_args()

    cfg = LabConfig(reward_risk=args.rr, horizon_bars=args.horizon,
                    cost_round_trip=args.cost_bps / 10_000.0)
    tfs = [t.strip() for t in args.timeframes.split(",") if t.strip()]
    names = ([s.strip() for s in args.setups.split(",") if s.strip()]
             or list(CONCEPTS))
    syms = [a.symbol for a in list_assets()]
    rng = np.random.default_rng(13)

    # (setup, timeframe) -> stats ; plus every row for the CSV
    cell: dict[tuple[str, str], dict] = {}
    all_rows = []

    for tf in tfs:
        frames = {}
        for s in syms:
            d = _load(s, tf)
            if d is not None and len(d) >= 400:
                frames[s] = d
        if not frames:
            print(f"{tf}: no data", flush=True)
            continue
        print(f"\n=== {tf} ({TF_STYLE.get(tf,'?')}) · {len(frames)} assets ===", flush=True)
        for name in names:
            fn = CONCEPTS.get(name)
            if fn is None:
                continue
            rows, nulls = [], []
            for sym, df in frames.items():
                atr = _atr(df)
                try:
                    sig = fn(df, cfg)
                except Exception as exc:  # noqa: BLE001
                    print(f"  {name}/{sym}: {type(exc).__name__}", flush=True)
                    continue
                rows.extend(build_journal(
                    df, sig, symbol=sym, timeframe=tf, setup_name=name, atr=atr,
                    atr_mult=cfg.atr_mult, reward_risk=cfg.reward_risk,
                    horizon_bars=cfg.horizon_bars,
                    cost_round_trip=cfg.cost_round_trip))
                nulls.extend(_null_expectancy(df, sig, cfg, atr, sym, tf, name,
                                              rng, args.null_paths))
            st = compute_stats(rows)
            if st is None or st.trades < 100:
                print(f"  {name:<22} insufficient ({st.trades if st else 0} trades)", flush=True)
                continue
            nmean = float(np.mean(nulls)) if nulls else float("nan")
            np95 = float(np.percentile(nulls, 95)) if nulls else float("nan")
            cell[(name, tf)] = {
                "stats": st.to_dict(),
                "null_mean_r": nmean, "null_p95_r": np95,
                "beats_null_p95": bool(nulls and st.expectancy_r > np95),
            }
            all_rows.extend(rows)
            print(f"  {name:<22} n={st.trades:>6} win={st.win_rate*100:5.1f}% "
                  f"E={st.expectancy_r:+.4f}R PF={st.profit_factor:5.2f} "
                  f"maxDD={st.max_drawdown_r:7.1f}R streak={st.longest_losing_streak:>3} "
                  f"null={nmean:+.4f} {'BEATS p95' if cell[(name,tf)]['beats_null_p95'] else ''}",
                  flush=True)

    if not cell:
        print("nothing measured")
        return 1

    # ---- style assignment ------------------------------------------------
    assign = {}
    for name in names:
        per_style: dict[str, list[tuple[str, float, int]]] = {}
        for (n2, tf), v in cell.items():
            if n2 != name:
                continue
            style = TF_STYLE.get(tf, "?")
            per_style.setdefault(style, []).append(
                (tf, v["stats"]["expectancy_r"], v["stats"]["trades"]))
        if not per_style:
            continue
        # best style = highest expectancy on any timeframe within it
        best_style, best_tf, best_e = None, None, -1e9
        for style, items in per_style.items():
            tf, e, _n = max(items, key=lambda x: x[1])
            if e > best_e:
                best_style, best_tf, best_e = style, tf, e
        v = cell[(name, best_tf)]
        assign[name] = {
            "style": best_style, "timeframe": best_tf,
            "expectancy_r": best_e,
            "trades": v["stats"]["trades"],
            "win_rate": v["stats"]["win_rate"],
            "profit_factor": v["stats"]["profit_factor"],
            "beats_null_p95": v["beats_null_p95"],
            "tradeable": bool(best_e > 0 and v["stats"]["trades"] >= 100
                              and v["beats_null_p95"]),
            "per_style": {k: max(x, key=lambda y: y[1]) for k, x in per_style.items()},
        }

    # ---- report ----------------------------------------------------------
    pooled = compute_stats(all_rows)
    L = [
        "# Trade Journal — every setup, every timeframe, every asset",
        "",
        f"{len(syms)} assets · timeframes {', '.join(tfs)} · {len(names)} setups · "
        f"{cfg.reward_risk}:1 at {cfg.atr_mult} ATR · {cfg.horizon_bars}-bar limit · "
        f"{args.cost_bps:.0f} bps round trip · entry at the NEXT bar's open.",
        "",
        f"**{len(all_rows):,} journalled trades.**",
        "",
        "## Record format",
        "",
        "| Field | Source |",
        "|---|---|",
        "| Date / Pair / Setup | the trade |",
        "| Session | bar's UTC hour → Sydney / Tokyo / London / London-NY overlap / New York. `n/a` on daily+ |",
        "| HTF bias | 50 vs 200 EMA **computed on bars up to entry only** |",
        "| Entry / SL / TP / R:R | ATR-derived, fixed before entry |",
        "| Result in R | net of cost |",
        "| Screenshot | a backtest has none — a deterministic TradingView link is given instead |",
        "| Reason for entry | which rule fired, and the direction |",
        "| Reason for failure | the exit that actually happened + worst excursion |",
        "| Mistake | always *no mistake (mechanical)* — a rule-follower cannot make a discretionary error. The column matters for MANUAL trades. |",
        "",
        "## Sample records",
        "",
        "| Date | Pair | Session | HTF bias | Setup | Entry | SL | TP | R:R | Result R | Reason for entry | Reason for failure | Mistake |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in all_rows[: args.sample_rows]:
        L.append(
            f"| {r.date} | {r.pair} | {r.session} | {r.htf_bias} | `{r.setup}` | "
            f"{r.entry:g} | {r.sl:g} | {r.tp:g} | {r.rr:g} | **{r.result_r:+.3f}** | "
            f"{r.reason_for_entry} | {r.reason_for_failure} | {r.mistake} |")

    if pooled:
        pf = "∞" if not np.isfinite(pooled.profit_factor) else f"{pooled.profit_factor:.3f}"
        L += [
            "", "## Statistics — all journalled trades pooled", "",
            "| Metric | Value |", "|---|---|",
            f"| Trades | {pooled.trades:,} |",
            f"| Win rate | {pooled.win_rate*100:.2f}% |",
            f"| Average win | {pooled.average_win_r:+.4f} R |",
            f"| Average loss | {pooled.average_loss_r:+.4f} R |",
            f"| **Expectancy** | **{pooled.expectancy_r:+.4f} R** |",
            f"| Profit factor | {pf} |",
            f"| Maximum drawdown | {pooled.max_drawdown_r:,.1f} R |",
            f"| Longest losing streak | {pooled.longest_losing_streak} |",
            f"| Best session | {pooled.best_session[0]} ({pooled.best_session[1]:+.4f} R) |",
            f"| Worst session | {pooled.worst_session[0]} ({pooled.worst_session[1]:+.4f} R) |",
            f"| Best pair | {pooled.best_pair[0]} ({pooled.best_pair[1]:+.4f} R) |",
            f"| Worst pair | {pooled.worst_pair[0]} ({pooled.worst_pair[1]:+.4f} R) |",
            f"| Total | {pooled.total_r:,.1f} R |",
            "",
            "### By session", "",
            "| Session | Trades | Win% | Expectancy R | Total R |", "|---|---|---|---|---|",
        ]
        for k, v in sorted(pooled.by_session.items(), key=lambda kv: -kv[1]["expectancy_r"]):
            L.append(f"| {k} | {v['trades']:,} | {v['win_rate']*100:.1f}% | "
                     f"{v['expectancy_r']:+.4f} | {v['total_r']:,.1f} |")
        L += ["", "### By pair", "",
              "| Pair | Trades | Win% | Expectancy R | Total R |", "|---|---|---|---|---|"]
        for k, v in sorted(pooled.by_pair.items(), key=lambda kv: -kv[1]["expectancy_r"]):
            L.append(f"| {k} | {v['trades']:,} | {v['win_rate']*100:.1f}% | "
                     f"{v['expectancy_r']:+.4f} | {v['total_r']:,.1f} |")

    L += ["", "## Setup × timeframe — expectancy in R", "",
          "| Setup | " + " | ".join(f"{tf} ({TF_STYLE.get(tf,'?')[:4]})" for tf in tfs) + " |",
          "|---" * (len(tfs) + 1) + "|"]
    for name in names:
        if not any((name, tf) in cell for tf in tfs):
            continue
        cells = []
        for tf in tfs:
            v = cell.get((name, tf))
            cells.append("—" if not v else
                         f"{v['stats']['expectancy_r']:+.4f}"
                         + ("**" if v["beats_null_p95"] else ""))
        L.append(f"| `{name}` | " + " | ".join(cells) + " |")

    L += ["", "## Style assignment", "",
          "Each setup is assigned to the style band where it measured best — **not**",
          "to the band its timeframe label implies. `Tradeable` requires all three:",
          "positive expectancy, ≥100 trades, and beating its own shuffled null.",
          "",
          "| Setup | Assigned style | Best TF | Trades | Win% | Expectancy R | PF | Beats null | **Tradeable** |",
          "|---|---|---|---|---|---|---|---|---|"]
    for name, a in sorted(assign.items(), key=lambda kv: -kv[1]["expectancy_r"]):
        pf = "∞" if not np.isfinite(a["profit_factor"]) else f"{a['profit_factor']:.2f}"
        L.append(
            f"| `{name}` | **{a['style']}** | {a['timeframe']} | {a['trades']:,} | "
            f"{a['win_rate']*100:.1f}% | {a['expectancy_r']:+.4f} | {pf} | "
            f"{'yes' if a['beats_null_p95'] else 'no'} | "
            f"{'**YES**' if a['tradeable'] else 'no'} |")

    n_ok = sum(1 for a in assign.values() if a["tradeable"])
    L += ["", f"**{n_ok} of {len(assign)} setups are tradeable by all three gates.**", ""]
    if n_ok == 0:
        L += [
            "Nothing clears the gates. That is a result, not a gap in the testing:",
            "every setup here has positive GROSS edge and is turned negative by the",
            "~0.19 R cost term. See `reports/CONCEPT_LAB.md` for the decomposition and",
            "`reports/TRADING_ROADMAP.md` §5.1 for the arithmetic.",
            "",
        ]
    L += [
        "## What this cannot tell you",
        "",
        "- In-sample. These rankings decide what deserves a walk-forward test; they",
        "  are not out-of-sample results.",
        "- Many setups × many timeframes were tested at once, so the best row is",
        "  selected and its apparent significance is overstated.",
        "- One exit model and one cost assumption. A setup can be real and still die",
        "  under a different exit.",
        "- `Mistake` is mechanical here by construction. In a manual journal it is the",
        "  most valuable column; filling it with invented judgements would destroy that.",
    ]
    OUT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")

    if args.export_csv and all_rows:
        with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=[
                "date", "pair", "session", "htf_bias", "setup", "entry", "sl", "tp",
                "rr", "result_r", "screenshot", "reason_for_entry",
                "reason_for_failure", "mistake"])
            w.writeheader()
            for r in all_rows:
                d = r.to_dict()
                w.writerow({k: d[k] for k in w.fieldnames})
        print(f"Wrote {OUT_CSV} ({len(all_rows):,} rows)")

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps({
        "config": cfg.to_dict(), "timeframes": tfs,
        "pooled": pooled.to_dict() if pooled else None,
        "by_setup_timeframe": {f"{k[0]}|{k[1]}": v for k, v in cell.items()},
        "style_assignment": assign,
    }, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {OUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
