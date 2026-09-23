"""Measure every retail-education concept through one evaluator, and rank them.

WHY THIS IS THE RIGHT EXPERIMENT. "Does SMC work?" is unanswerable in public
because every published test uses a different exit, cost and sample. Here every
concept emits the same thing -- a direction at a bar -- and is scored by the
same triple barrier, the same costs and the same year cut. Differences between
rows are then about the concepts and not about the harness.

TWO CONTROLS ARE BUILT IN, and they matter more than the ranking:

  engulfing_at_level vs engulfing_anywhere
      The corpus's single most repeated claim is "a pattern in the middle of
      nowhere is noise." That is a testable prediction: these two rows must
      separate. If they do not, the claim is decoration.

  SHUFFLED NULL, per concept
      The same signal count, placed at random bars. A concept must beat its own
      null, not zero -- with a 2R target and a time barrier, even random entries
      have a non-zero expectancy, and that is the bar to clear.

    python setups/run_concept_lab.py
    python setups/run_concept_lab.py --timeframe 1h --null-paths 50
"""
from __future__ import annotations

import argparse
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
from project_titan_x.setups.concept_lab import (  # noqa: E402
    CONCEPTS, LabConfig, evaluate,
)

DATA = ROOT / "project_titan_x" / "data" / "processed"
OUT_MD = ROOT / "project_titan_x" / "reports" / "CONCEPT_LAB.md"
OUT_JSON = ROOT / "project_titan_x" / "data" / "models" / "setups" / "concept_lab.json"


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


def _shuffled_null(df, signals, cfg, rng):
    """Same number of signals, same direction mix, random bars.

    Not a sign flip and not a bootstrap of outcomes: the point is to hold the
    concept's ACTIVITY constant and destroy only its TIMING. Whatever is left
    is what the exit rules and the instrument give away for free.
    """
    n = len(signals)
    nz = np.nonzero(signals)[0]
    if nz.size == 0:
        return None
    out = np.zeros(n, dtype=int)
    # keep away from the edges so the time barrier can always resolve
    lo, hi = 250, n - cfg.horizon_bars - 2
    if hi <= lo:
        return None
    picks = rng.choice(np.arange(lo, hi), size=min(nz.size, hi - lo), replace=False)
    out[picks] = signals[nz][:picks.size]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeframe", default="1d")
    ap.add_argument("--null-paths", type=int, default=20)
    ap.add_argument("--rr", type=float, default=2.0)
    ap.add_argument("--horizon", type=int, default=20)
    ap.add_argument("--cost-bps", type=float, default=30.0)
    ap.add_argument("--out-suffix", default="")
    ap.add_argument("--scale-horizon", action="store_true",
                    help="scale the time barrier with the stop width (removes the confound)")
    ap.add_argument("--sweep-stop", default="",
                    help=("comma-separated ATR stop multiples to sweep, e.g. "
                          "0.5,1,1.5,2,3,4. cost_R = cost/stop_frac, so a wider "
                          "stop mechanically pays less cost per unit of risk -- "
                          "this is the one lever that can move a concept whose "
                          "gross edge is already positive."))
    args = ap.parse_args()

    cfg = LabConfig(reward_risk=args.rr, horizon_bars=args.horizon,
                    cost_round_trip=args.cost_bps / 10_000.0)
    out_md = (OUT_MD if not args.out_suffix
              else OUT_MD.with_name(f"CONCEPT_LAB_{args.out_suffix}.md"))
    out_json = (OUT_JSON if not args.out_suffix
                else OUT_JSON.with_name(f"concept_lab_{args.out_suffix}.json"))

    frames = {}
    for a in list_assets():
        d = _load(a.symbol, args.timeframe)
        if d is not None and len(d) >= 400:
            frames[a.symbol] = d
    if not frames:
        print(f"no {args.timeframe} data")
        return 1
    print(f"{len(frames)} assets on {args.timeframe}\n", flush=True)

    rng = np.random.default_rng(7)
    results, nulls = {}, {}
    for name, fn in CONCEPTS.items():
        pooled_sig, pooled_df = [], []
        for sym, df in frames.items():
            try:
                pooled_sig.append(fn(df, cfg))
                pooled_df.append(df)
            except Exception as exc:  # noqa: BLE001
                print(f"  {name}/{sym}: {type(exc).__name__} {str(exc)[:50]}", flush=True)
        # Evaluated per asset then pooled: concatenating price frames would
        # create a fake bar at every seam and invent trades that never existed.
        rows, null_rows = [], []
        for sig, df in zip(pooled_sig, pooled_df):
            r = evaluate(df, sig, cfg, name)
            if r is not None:
                rows.append(r)
            for _ in range(max(1, args.null_paths // max(len(pooled_df), 1))):
                ns = _shuffled_null(df, sig, cfg, rng)
                if ns is None:
                    continue
                nr = evaluate(df, ns, cfg, name + "_null")
                if nr is not None:
                    null_rows.append(nr.net_r)
        if not rows:
            print(f"  {name:<22} insufficient (< {cfg.min_trades} trades on every asset)", flush=True)
            continue
        w = np.array([r.trades for r in rows], dtype=float)
        agg = {
            "trades": int(w.sum()),
            "assets": len(rows),
            "win_rate": float(np.average([r.win_rate for r in rows], weights=w)),
            "gross_r": float(np.average([r.gross_r for r in rows], weights=w)),
            "cost_r": float(np.average([r.cost_r for r in rows], weights=w)),
            "net_r": float(np.average([r.net_r for r in rows], weights=w)),
            "breakeven_cost_bps": float(np.average(
                [r.breakeven_cost_bps for r in rows], weights=w)),
            "t_stat": float(np.average([r.t_stat for r in rows], weights=w)),
            "years_positive": int(sum(r.years_positive for r in rows)),
            "years_total": int(sum(r.years_total for r in rows)),
            "assets_positive": int(sum(1 for r in rows if r.net_r > 0)),
        }
        agg["null_mean_r"] = float(np.mean(null_rows)) if null_rows else float("nan")
        agg["null_p95_r"] = float(np.percentile(null_rows, 95)) if null_rows else float("nan")
        agg["beats_null_p95"] = bool(
            null_rows and agg["net_r"] > agg["null_p95_r"])
        agg["edge_over_null"] = (agg["net_r"] - agg["null_mean_r"]
                                 if null_rows else float("nan"))
        results[name] = agg
        nulls[name] = null_rows
        print(f"  {name:<22} n={agg['trades']:>6}  win={agg['win_rate']*100:5.1f}%  "
              f"gross={agg['gross_r']:+.4f}R  net={agg['net_r']:+.4f}R  "
              f"vs null {agg['null_mean_r']:+.4f}R  "
              f"{'BEATS p95' if agg['beats_null_p95'] else '-'}", flush=True)

    # ---- stop-width sweep ------------------------------------------------
    # Every concept measured above has POSITIVE gross R and NEGATIVE net R,
    # so cost is the whole problem. Widening the stop cuts cost_R
    # proportionally -- but it also changes the trades themselves (a wider
    # stop is hit less often and the 2R target is further away), so the net
    # effect is not arithmetic and has to be measured.
    sweep: dict[str, list[tuple[float, dict]]] = {}
    if args.sweep_stop:
        mults = [float(x) for x in args.sweep_stop.split(",") if x.strip()]
        for name in sorted(results, key=lambda k: -results[k]["gross_r"])[:4]:
            fn = CONCEPTS[name]
            sweep[name] = []
            for m in mults:
                # Scale the time barrier WITH the stop. Holding horizon fixed
                # confounds the sweep: at 4 ATR the 2R target sits 8 ATR away
                # and simply cannot be reached in 20 bars, so gross collapses
                # for a reason that has nothing to do with the stop's merit.
                # Measured without this, gross went +0.1164 -> -0.4706 across
                # the sweep, which is the time barrier talking, not the stop.
                h2 = (int(round(cfg.horizon_bars * m / cfg.atr_mult))
                      if args.scale_horizon else cfg.horizon_bars)
                c2 = LabConfig(**{**cfg.to_dict(), "atr_mult": m,
                                  "horizon_bars": max(h2, 5)})
                rows = []
                for sym, df in frames.items():
                    try:
                        r = evaluate(df, fn(df, c2), c2, name)
                    except Exception:  # noqa: BLE001
                        continue
                    if r is not None:
                        rows.append(r)
                if not rows:
                    continue
                w = np.array([r.trades for r in rows], dtype=float)
                # A swept setting must carry its OWN null and its OWN
                # long/short split. Measured 2026-09-22: round_number at
                # 4 ATR / 80 bars looked like +0.2988 R until the shuffled
                # null at the SAME settings came back +0.1807 R and the split
                # came back longs +0.3400 / shorts -0.3365. A wide stop with a
                # long horizon captures drift no matter where you enter, so a
                # sweep that reports net R alone will always find a "winner".
                nl, ls, ss = [], [], []
                for sym2, df2 in frames.items():
                    try:
                        sg = fn(df2, c2)
                    except Exception:  # noqa: BLE001
                        continue
                    rl = evaluate(df2, np.where(sg > 0, 1, 0), c2, name)
                    rs = evaluate(df2, np.where(sg < 0, -1, 0), c2, name)
                    if rl:
                        ls.append((rl.net_r, rl.trades))
                    if rs:
                        ss.append((rs.net_r, rs.trades))
                    for _ in range(3):
                        ns = _shuffled_null(df2, sg, c2, rng)
                        if ns is None:
                            continue
                        rn = evaluate(df2, ns, c2, name)
                        if rn:
                            nl.append(rn.net_r)
                wavg = lambda xs: (float(np.average([a for a, _ in xs],
                                                    weights=[b for _, b in xs]))
                                   if xs else float("nan"))
                net_r = float(np.average([r.net_r for r in rows], weights=w))
                sweep[name].append((m, {
                    "trades": int(w.sum()),
                    "win_rate": float(np.average([r.win_rate for r in rows], weights=w)),
                    "gross_r": float(np.average([r.gross_r for r in rows], weights=w)),
                    "cost_r": float(np.average([r.cost_r for r in rows], weights=w)),
                    "net_r": net_r,
                    "unresolved_frac": float(np.average(
                        [r.unresolved_frac for r in rows], weights=w)),
                    "null_mean_r": float(np.mean(nl)) if nl else float("nan"),
                    "null_p95_r": float(np.percentile(nl, 95)) if nl else float("nan"),
                    "beats_null_p95": bool(nl and net_r > np.percentile(nl, 95)),
                    "long_net_r": wavg(ls),
                    "short_net_r": wavg(ss),
                }))
                print(f"    {name:<20} stop={m:>4}ATR h={c2.horizon_bars:>3}  n={w.sum():>7.0f}  "
                      f"gross={sweep[name][-1][1]['gross_r']:+.4f}  "
                      f"cost={sweep[name][-1][1]['cost_r']:.4f}  "
                      f"net={sweep[name][-1][1]['net_r']:+.4f}", flush=True)

    order = sorted(results, key=lambda k: -results[k]["net_r"])
    lines = [
        "# Concept Lab — every retail concept, one evaluator",
        "",
        f"{len(frames)} assets · {args.timeframe} · triple barrier "
        f"{cfg.reward_risk}:1 at {cfg.atr_mult} ATR · {cfg.horizon_bars}-bar time limit · "
        f"round-trip cost {args.cost_bps:.0f} bps · entry at the NEXT bar's open.",
        "",
        "Every concept below emits the same thing — a direction at a bar — and is",
        "scored by the same rules, so the rows are comparable to each other. They",
        "are **not** comparable to numbers from anyone else's backtest.",
        "",
        "| Concept | Trades | Win% | Gross R | Cost R | **Net R** | vs null | Beats null p95 | t | Years + |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for k in order:
        r = results[k]
        lines.append(
            f"| `{k}` | {r['trades']:,} | {r['win_rate']*100:.1f}% | {r['gross_r']:+.4f} | "
            f"{r['cost_r']:.4f} | **{r['net_r']:+.4f}** | {r['null_mean_r']:+.4f} | "
            f"{'**yes**' if r['beats_null_p95'] else 'no'} | {r['t_stat']:+.2f} | "
            f"{r['years_positive']}/{r['years_total']} |")

    if sweep:
        lines += ["", "## Stop-width sweep — the only lever that moves cost", "",
                  "`cost_R = cost / stop_frac`, so a wider stop mechanically pays less cost",
                  "per unit of risk. It also changes the trades: a wider stop is hit less",
                  "often, and a 2R target sits further away. The net effect is measured,",
                  "not assumed.", ""]
        for name, rows in sweep.items():
            lines += [f"### `{name}`", "",
                      "| Stop (ATR) | Trades | Unres. | Gross R | Cost R | Net R | Null | Null p95 | Beats p95 | Longs | Shorts |",
                      "|---|---|---|---|---|---|---|---|---|---|---|"]
            for m, r in rows:
                lines.append(
                    f"| {m} | {r['trades']:,} | {r['unresolved_frac']*100:.0f}% | "
                    f"{r['gross_r']:+.4f} | {r['cost_r']:.4f} | {r['net_r']:+.4f} | "
                    f"{r['null_mean_r']:+.4f} | {r['null_p95_r']:+.4f} | "
                    f"{'**YES**' if r['beats_null_p95'] else 'no'} | "
                    f"{r['long_net_r']:+.4f} | {r['short_net_r']:+.4f} |")
            best = max(rows, key=lambda kv: kv[1]["net_r"])
            b = best[1]
            beta = (np.isfinite(b["long_net_r"]) and np.isfinite(b["short_net_r"])
                    and b["long_net_r"] > 0 > b["short_net_r"]
                    and abs(b["long_net_r"] + b["short_net_r"]) < 0.5 * abs(b["long_net_r"]))
            lines += ["",
                      f"Best net at **{best[0]} ATR**: {b['net_r']:+.4f} R.",
                      ""]
            if not b["beats_null_p95"]:
                lines.append(
                    f"**It does not clear its own null.** Random entries at the same "
                    f"settings score {b['null_mean_r']:+.4f} R (p95 {b['null_p95_r']:+.4f}). "
                    "A wide stop with a long horizon captures drift wherever you enter, "
                    "so a positive net R here is the exit structure, not the concept.")
            if beta:
                lines.append(
                    f"**And it is directional.** Longs {b['long_net_r']:+.4f} R against "
                    f"shorts {b['short_net_r']:+.4f} R — near-equal and opposite, which is "
                    "beta wearing a costume, not an edge.")
            lines.append("")

    lines += ["", "## The control that matters most", ""]
    if "engulfing_at_level" in results and "engulfing_anywhere" in results:
        a, b = results["engulfing_at_level"], results["engulfing_anywhere"]
        gap = a["net_r"] - b["net_r"]
        lines += [
            "The corpus's most repeated claim is that **a pattern only means something",
            "at a level**. That is a testable prediction, and this is the test:",
            "",
            "| | Trades | Win% | Net R |",
            "|---|---|---|---|",
            f"| engulfing **at a level** | {a['trades']:,} | {a['win_rate']*100:.1f}% | {a['net_r']:+.4f} |",
            f"| engulfing **anywhere** | {b['trades']:,} | {b['win_rate']*100:.1f}% | {b['net_r']:+.4f} |",
            "",
            (f"**The level filter is worth {gap:+.4f} R per trade.** The claim holds "
             "in the direction it was stated." if gap > 0 else
             f"**The level filter is worth {gap:+.4f} R per trade — it does not help here.** "
             "The claim does not reproduce on this book."),
            "",
        ]

    lines += [
        "## How to read this",
        "",
        "- **Net R** is after costs. It is the only column that decides anything.",
        "- **vs null** is the same concept with its signal COUNT and direction mix held",
        "  constant and its TIMING destroyed. A concept must beat its own null, not",
        "  zero — a 2R target with a time barrier pays something even at random.",
        "- **t** is on the mean net R. |t| > 2 is the conventional bar and it is a LOW",
        "  bar here: ten concepts were tested at once, so the best row is selected and",
        "  its t is inflated. Treat a single |t| just above 2 as noise.",
        "- **Years +** counts asset-years with positive mean net R. A concept that only",
        "  works in some years is regime exposure, not edge.",
        "",
        "## What the published evidence said before this ran",
        "",
        "- **Support/resistance** has the strongest academic backing of anything here.",
        "  Osler ([J. Finance 2003](https://onlinelibrary.wiley.com/doi/abs/10.1111/1540-6261.00588),",
        "  [FRBNY 2000](https://www.newyorkfed.org/medialibrary/media/research/epr/00v06n2/0007osle.pdf))",
        "  showed take-profit orders cluster **at** round numbers and stop-loss orders",
        "  cluster **just beyond** them — which predicts both reversal at a level and",
        "  acceleration through it. `round_number` tests that mechanism directly.",
        "- **Order blocks / SMC**: weak. One published backtest put order blocks on SPY",
        "  at t = +1.22, below the |t| > 2 bar; a reported 648 ICT backtests failed to",
        "  beat buy-and-hold. These are practitioner sources, not journals.",
        "- **Fair value gaps**: \"fill ~70% of the time\" is a fill RATE, not an edge —",
        "  it says nothing about what happens when they do not fill.",
        "- **Candlestick patterns**: academic results mixed; most patterns' mean returns",
        "  are not statistically distinguishable from zero.",
        "",
        "## What this cannot tell you",
        "",
        "- Ten concepts were tested. The best one is selected, so its apparent",
        "  significance is overstated. A deflated-Sharpe style correction is the",
        "  honest next step before anything here is traded.",
        "- One timeframe, one exit, one cost assumption. A concept can be real and",
        "  still die under a different exit.",
        "- Nothing here is out-of-sample. These are in-sample rankings used to decide",
        "  what is worth a walk-forward test, not results to trade.",
    ]
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(
        {"config": cfg.to_dict(), "timeframe": args.timeframe,
         "assets": len(frames), "results": results,
         "stop_sweep": {k: [{"atr_mult": m, **r} for m, r in v] for k, v in sweep.items()}},
        indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
