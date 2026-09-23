"""Backtest the published high-profile ORB setup, and test its one real claim.

THE CLAIM UNDER TEST. Zarattini, Barbon & Aziz report that the same breakout
rules score Sharpe 0.48 unfiltered and 2.81 once the universe is restricted to
the top 20 instruments by opening relative volume. If that is a property of
markets rather than of their sample, the filter should lift this book too. If
the two columns come back the same, the filter is decoration here and the
headline does not transfer.

This runs BOTH columns on identical trades, so the comparison is the filter and
nothing else -- same entries, same stops, same costs, one subset of the other.

ALSO REPORTED: `breakeven_cost_bps`, the round-trip cost at which the edge is
exactly zero. That is the number the independent replication of this strategy
used to kill it (break-even ~2.2c/share against a ~1c spread), and it is the
only honest way to read a result whose stop is 10% of an ATR.

    python setups/run_high_profile.py
    python setups/run_high_profile.py --stop-model orb_opposite --entry open
    python setups/run_high_profile.py --cost-bps 5 --timeframe 5m
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
from project_titan_x.setups.high_profile_setup import (  # noqa: E402
    HighProfileConfig, apply_rvol_selection, extract_hp_signals, hp_economics,
)

DATA = ROOT / "project_titan_x" / "data" / "processed"
OUT_MD = ROOT / "project_titan_x" / "reports" / "HIGH_PROFILE_SETUP.md"
OUT_JSON = ROOT / "project_titan_x" / "data" / "models" / "setups" / "high_profile_setup.json"


def _yahoo(s):
    a = SUPPORTED_ASSETS.get(s)
    return getattr(a, "yahoo_symbol", s) if a else s


def _load(sym, tf):
    for c in (_yahoo(sym), sym):
        h = glob.glob(str(DATA / f"{c}_{tf}.parquet"))
        if h:
            return pd.read_parquet(h[0])
    return None


def _fmt(e: dict) -> str:
    if not e.get("trades"):
        return "| — | — | — | — | — |"
    return (f"| {e['trades']:,} | {e['win_rate_gross']*100:.1f}% | {e['win_rate']*100:.1f}% | "
            f"{e['expectancy_r_net']:+.4f} R | {e['sharpe_per_trade']:+.4f} | "
            f"{e['breakeven_cost_bps']:.1f} bps |")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeframe", default="5m")
    ap.add_argument("--orb-minutes", type=int, default=5)
    ap.add_argument("--entry", default="stop_order", choices=["stop_order", "open"])
    ap.add_argument("--stop-model", default="atr_pct", choices=["atr_pct", "orb_opposite"])
    ap.add_argument("--atr-stop-pct", type=float, default=0.10)
    ap.add_argument("--exit-model", default="eod", choices=["eod", "rr"])
    ap.add_argument("--max-r", type=float, default=10.0)
    ap.add_argument("--rr", type=float, default=2.0)
    ap.add_argument("--cost-bps", type=float, default=30.0)
    ap.add_argument("--rvol-min", type=float, default=1.0)
    ap.add_argument("--rvol-top-n", type=int, default=20)
    ap.add_argument("--out-suffix", default="",
                    help="so cost/stop variants do not overwrite each other")
    ap.add_argument("--sweep-rvol-min", default="",
                    help=("comma-separated relative-volume THRESHOLDS to evaluate on "
                          "one extraction, e.g. 0.5,1,1.5,2,3,4. The top-N sweep "
                          "showed the cross-sectional ranking does nothing on a "
                          "16-instrument universe; the threshold is the variable "
                          "that was actually moving."))
    ap.add_argument("--sweep-top-n", default="",
                    help=("comma-separated top-N cuts to evaluate on ONE extraction, "
                          "e.g. 1,2,3,5,10,20,29. Three points cannot establish a "
                          "dose-response; this is how the claim gets tested."))
    args = ap.parse_args()

    out_md, out_json = OUT_MD, OUT_JSON
    r_path = OUT_JSON.with_name(OUT_JSON.stem + "_rmultiples.json")
    if args.out_suffix:
        out_md = OUT_MD.with_name("HIGH_PROFILE_SETUP_" + args.out_suffix + ".md")
        out_json = OUT_JSON.with_name("high_profile_setup_" + args.out_suffix + ".json")
    r_path = out_json.with_name(out_json.stem + "_rmultiples.json")

    cfg = HighProfileConfig(
        orb_minutes=args.orb_minutes, entry_trigger=args.entry,
        stop_model=args.stop_model, atr_stop_pct=args.atr_stop_pct,
        exit_model=args.exit_model, max_r=args.max_r, reward_risk=args.rr,
        cost_bps_round_trip=args.cost_bps, rvol_min=args.rvol_min,
        rvol_top_n=args.rvol_top_n,
    )

    frames, per_asset = [], {}
    for a in list_assets():
        raw = _load(a.symbol, args.timeframe)
        if raw is None or len(raw) < 2000:
            continue
        try:
            sig = extract_hp_signals(raw, cfg, symbol=a.symbol)
        except Exception as exc:  # noqa: BLE001
            print(f"  {a.symbol:<12} error {str(exc)[:50]}", flush=True)
            continue
        if sig.empty:
            continue
        frames.append(sig)
        e = hp_economics(sig, cfg)
        per_asset[a.symbol] = e
        print(f"  {a.symbol:<12} {e['trades']:>5} tr  win(g) {e['win_rate_gross']*100:5.1f}%  "
              f"net {e['expectancy_r_net']:+.4f} R  "
              f"breakeven {e['breakeven_cost_bps']:7.1f} bps", flush=True)

    if not frames:
        print("no signals -- check the session window for this timeframe")
        return 1

    allsig = pd.concat(frames, ignore_index=True).sort_values("_ts")
    unfiltered = hp_economics(allsig, cfg)
    filtered_sig = apply_rvol_selection(allsig, cfg)
    filtered = hp_economics(filtered_sig, cfg)

    allsig["_year"] = pd.to_datetime(allsig["_ts"], utc=True).dt.year
    by_year = []
    for y, g in allsig.groupby("_year"):
        if len(g) < 30:
            continue
        gf = apply_rvol_selection(g, cfg)
        by_year.append((int(y), hp_economics(g, cfg), hp_economics(gf, cfg)))

    lines = [
        "# High-Profile Setup — the published ORB, measured here",
        "",
        f"{len(per_asset)} assets · {args.timeframe} · opening range "
        f"{cfg.orb_minutes} min · entry **{cfg.entry_trigger}** · stop "
        f"**{cfg.stop_model}**"
        + (f" ({cfg.atr_stop_pct:.0%} of 14-day ATR)" if cfg.stop_model == "atr_pct" else "")
        + f" · exit **{cfg.exit_model}** (cap {cfg.max_r:.0f}R) · "
        f"round-trip cost **{cfg.cost_bps_round_trip:.0f} bps**.",
        "",
        "## The claim under test",
        "",
        "Zarattini, Barbon & Aziz report the SAME breakout rules at Sharpe 0.48",
        "unfiltered and **2.81** once the universe is cut to the top "
        f"{cfg.rvol_top_n} by opening",
        "relative volume. Both columns below are the same trades; the only",
        "difference is the filter.",
        "",
        "| | Trades | Win% gross | Win% net | Net expectancy | Sharpe/trade | Break-even cost |",
        "|---|---|---|---|---|---|---|",
        f"| **Unfiltered** {_fmt(unfiltered)}",
        f"| **RVOL-filtered** {_fmt(filtered)}",
        "",
    ]
    if unfiltered.get("trades") and filtered.get("trades"):
        d_sharpe = filtered["sharpe_per_trade"] - unfiltered["sharpe_per_trade"]
        kept = 100.0 * filtered["trades"] / unfiltered["trades"]
        lines += [
            f"The filter keeps **{kept:.1f}%** of trades and moves Sharpe per trade by "
            f"**{d_sharpe:+.4f}**.",
            "",
        ]

    # ---- dose-response over the cut depth -------------------------------
    # The paper's claim is that HARDER selection is better. Two or three points
    # cannot tell a dose-response from two noisy draws; a monotone curve over
    # the whole range can. Evaluated on ONE extraction so the only thing
    # varying between rows is the cut.
    sweep = []
    if args.sweep_top_n:
        n_syms = allsig["_sym"].nunique()
        for raw_n in args.sweep_top_n.split(","):
            raw_n = raw_n.strip()
            if not raw_n:
                continue
            n = int(raw_n)
            sub = apply_rvol_selection(
                allsig, HighProfileConfig(**{**cfg.to_dict(), "rvol_top_n": n}))
            e = hp_economics(sub, cfg)
            if e.get("trades"):
                sweep.append((n, 100.0 * n / n_syms, e))
        if sweep:
            lines += [
                "## Dose-response: does a harder cut keep helping?",
                "",
                f"One extraction, {n_syms} instruments, only the cut depth varies. "
                "The paper cuts ~1,000 names to 20 (2%); the hardest cut available here "
                f"is 1 of {n_syms}.",
                "",
                "| Top-N | % of universe | Trades | Win% gross | Gross R | Break-even cost |",
                "|---|---|---|---|---|---|",
            ]
            for n, pct, e in sweep:
                lines.append(
                    f"| {n} | {pct:.0f}% | {e['trades']:,} | "
                    f"{e['win_rate_gross']*100:.2f}% | {e['expectancy_r_gross_sized']:+.4f} | "
                    f"{e['breakeven_cost_bps']:+.2f} bps |")
            gr = [e["expectancy_r_gross_sized"] for _, _, e in sweep]
            mono = all(x <= y for x, y in zip(gr, gr[1:]))
            lines += [
                "",
                f"**Monotone in the claimed direction: {'YES' if mono else 'NO'}** "
                "(gross R improving as the cut hardens). "
                + ("A monotone curve across every cut is what a real selection effect "
                   "looks like; noise does not order itself."
                   if mono else
                   "Without monotonicity the two or three favourable points are "
                   "consistent with sampling variation rather than a dose-response."),
                "",
            ]

    # ---- dose-response over the THRESHOLD -------------------------------
    rsweep = []
    if args.sweep_rvol_min:
        for raw in args.sweep_rvol_min.split(","):
            raw = raw.strip()
            if not raw:
                continue
            v = float(raw)
            sub = apply_rvol_selection(allsig, HighProfileConfig(
                **{**cfg.to_dict(), "rvol_min": v, "rvol_top_n": 0}))
            e = hp_economics(sub, cfg)
            if e.get("trades"):
                rsweep.append((v, e))
        if rsweep:
            base = hp_economics(allsig, cfg)
            lines += [
                "## Dose-response: the relative-volume THRESHOLD",
                "",
                "`rvol_top_n` is disabled here so the only thing varying is how unusual",
                "the opening volume has to be. This is the variable the cross-sectional",
                "sweep above showed was doing the work.",
                "",
                "| RVOL >= | Trades | % kept | Win% gross | Gross R | Break-even cost |",
                "|---|---|---|---|---|---|",
                f"| _(no filter)_ | {base['trades']:,} | 100% | "
                f"{base['win_rate_gross']*100:.2f}% | "
                f"{base['expectancy_r_gross_sized']:+.4f} | "
                f"{base['breakeven_cost_bps']:+.2f} bps |",
            ]
            for v, e in rsweep:
                lines.append(
                    f"| {v:g}x | {e['trades']:,} | "
                    f"{100.0*e['trades']/base['trades']:.0f}% | "
                    f"{e['win_rate_gross']*100:.2f}% | "
                    f"{e['expectancy_r_gross_sized']:+.4f} | "
                    f"{e['breakeven_cost_bps']:+.2f} bps |")
            gr = [e["expectancy_r_gross_sized"] for _, e in rsweep]
            mono = all(x <= y for x, y in zip(gr, gr[1:]))
            lines += [
                "",
                f"**Monotone as the threshold rises: {'YES' if mono else 'NO'}.** "
                + ("Gross expectancy improves at every step, which is what a real "
                   "selection effect looks like."
                   if mono else
                   "The curve is not ordered, so the favourable points are consistent "
                   "with sampling variation. Note the trade count collapses as the "
                   "threshold rises -- a thinner sample is a noisier estimate, not a "
                   "better one."),
                "",
            ]

    lines += [
        "## Break-even cost is the number to read first",
        "",
        "`breakeven_cost_bps` is the round-trip cost at which this setup's expectancy",
        "is exactly zero. A tight stop buys more notional per unit of risk, so cost in",
        "R units is `cost / stop_frac` — which is why a 10%-of-ATR stop is fragile on a",
        "retail cost base however good the entry is.",
        "",
        "The independent replication of this strategy on QQQ put its break-even at",
        "~2.2¢/share against a ~1¢ spread, and its bootstrap 95% CI on Sharpe at",
        "[0.05, 1.41] versus buy-and-hold QQQ's [−0.03, 1.47] — overlapping.",
        "",
        "## Year by year",
        "",
        "| Year | Trades | Win% gross | Net R (all) | Net R (RVOL top-N) |",
        "|---|---|---|---|---|",
    ]
    for y, e, ef in by_year:
        fr = f"{ef['expectancy_r_net']:+.4f}" if ef.get("trades") else "—"
        lines.append(f"| {y} | {e['trades']:,} | {e['win_rate_gross']*100:.1f}% | "
                     f"{e['expectancy_r_net']:+.4f} | {fr} |")
    pos = sum(1 for _, e, _ in by_year if e["expectancy_r_net"] > 0)
    posf = sum(1 for _, _, ef in by_year if ef.get("trades") and ef["expectancy_r_net"] > 0)
    lines += [
        "",
        f"**{pos} of {len(by_year)} years net-positive unfiltered · "
        f"{posf} of {len(by_year)} filtered.**",
        "",
        "## By asset",
        "",
        "| Asset | Trades | Win% gross | Net R | Break-even cost |",
        "|---|---|---|---|---|",
    ]
    for sym, e in sorted(per_asset.items(), key=lambda kv: -kv[1]["expectancy_r_net"]):
        lines.append(f"| {sym} | {e['trades']:,} | {e['win_rate_gross']*100:.1f}% | "
                     f"{e['expectancy_r_net']:+.4f} | {e['breakeven_cost_bps']:.1f} bps |")

    lines += [
        "",
        "## What this does not establish",
        "",
        "- The paper's universe is US equities screened to >$5, >1M shares/day and",
        "  >$0.50 ATR, then ranked daily across ~1,000 names. This book holds 29",
        "  instruments, so the cross-sectional 'top 20' is a much weaker cut than",
        "  the one that produced the published number. A null result here is",
        "  evidence about THIS universe, not a refutation of theirs.",
        "- A 24-hour instrument has no natural open. Those rows answer 'does the NY",
        "  open matter here', not 'what does the opening range do'.",
        "- Exit is at the session's last close. Real end-of-day exits pay the",
        "  closing auction, which is not modelled.",
    ]
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps({
        "config": cfg.to_dict(),
        "unfiltered": unfiltered,
        "rvol_filtered": filtered,
        "by_year": {str(y): {"all": e, "filtered": ef} for y, e, ef in by_year},
        "by_asset": per_asset,
        "r_multiples_file": r_path.name,
        "top_n_sweep": {str(n): {"pct_of_universe": pct, **e} for n, pct, e in sweep},
        "rvol_min_sweep": {str(v): e for v, e in rsweep},
    }, indent=2, default=str), encoding="utf-8")

    # The realised per-trade R multiples, so the challenge ladder can resample
    # the ACTUAL distribution. Reconstructing a pool from win rate and R:R
    # instead would make every win identical and every loss identical, removing
    # exactly the fat tails that decide whether a small account survives long
    # enough to compound.
    #
    # COMPACT, and in its own file: `indent=2` puts every float on its own line,
    # which turned a 19,663-trade dump into 19,663 lines of git diff sitting in
    # the middle of a report a human is meant to read.
    r_path.write_text(json.dumps({
        "r_net_all": [round(float(x), 6) for x in allsig["_r_net"].to_numpy()],
        "r_net_rvol_filtered": [round(float(x), 6)
                                for x in filtered_sig["_r_net"].to_numpy()],
    }, separators=(",", ":")), encoding="utf-8")

    print(f"\nunfiltered : {unfiltered['trades']:,} tr · win(g) {unfiltered['win_rate_gross']*100:.2f}% "
          f"· net {unfiltered['expectancy_r_net']:+.4f} R · "
          f"breakeven {unfiltered['breakeven_cost_bps']:.1f} bps")
    if filtered.get("trades"):
        print(f"rvol-filt  : {filtered['trades']:,} tr · win(g) {filtered['win_rate_gross']*100:.2f}% "
              f"· net {filtered['expectancy_r_net']:+.4f} R · "
              f"breakeven {filtered['breakeven_cost_bps']:.1f} bps")
    print(f"Wrote {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
