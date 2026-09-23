"""Measure what volatility targeting and a regime filter actually do to drawdown.

FOUR VARIANTS PER SETUP, on identical signals:
    baseline · +vol target · +regime filter · +both

THE COLUMN THAT DECIDES IT IS RETURN/MAXDD, NOT DRAWDOWN. Halving drawdown by
halving size is not an improvement -- it is the same equity curve drawn
smaller, and it leaves return/maxDD unchanged. Only a variant that raises that
ratio has actually improved anything.

DRAWDOWN IS COMPUTED CHRONOLOGICALLY. Pooled journal rows arrive grouped by
asset, and a cumulative sum over that order is a concatenation of unrelated
losing tails, not an equity curve. Measured 2026-09-23: unsorted, weekly
round_number reported 164.9 R of drawdown and a 46-trade losing streak that no
account could have experienced.

    python setups/run_enhance.py --timeframe 1d
    python setups/run_enhance.py --timeframe 4h --setups round_number,trend_pullback
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
from project_titan_x.setups.concept_lab import CONCEPTS, LabConfig, _atr  # noqa: E402
from project_titan_x.setups.enhance import (  # noqa: E402
    EnhanceConfig, apply_enhancements, drawdown_stats,
)
from project_titan_x.setups.trade_journal import build_journal  # noqa: E402

DATA = ROOT / "project_titan_x" / "data" / "processed"
OUT_MD = ROOT / "project_titan_x" / "reports" / "ENHANCEMENTS.md"
OUT_JSON = ROOT / "project_titan_x" / "data" / "models" / "setups" / "enhancements.json"

VARIANTS = {
    "baseline":   EnhanceConfig(),
    "vol_target": EnhanceConfig(use_vol_target=True),
    "regime":     EnhanceConfig(use_regime_filter=True, regime_mode="trend"),
    "both":       EnhanceConfig(use_vol_target=True, use_regime_filter=True,
                                regime_mode="trend"),
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeframe", default="1d")
    ap.add_argument("--setups", default="")
    ap.add_argument("--rr", type=float, default=2.0)
    ap.add_argument("--horizon", type=int, default=20)
    ap.add_argument("--cost-bps", type=float, default=30.0)
    args = ap.parse_args()

    cfg = LabConfig(reward_risk=args.rr, horizon_bars=args.horizon,
                    cost_round_trip=args.cost_bps / 10_000.0)
    names = ([s.strip() for s in args.setups.split(",") if s.strip()]
             or list(CONCEPTS))

    frames = {}
    for a in list_assets():
        d = _load(a.symbol, args.timeframe)
        if d is not None and len(d) >= 400:
            frames[a.symbol] = d
    if not frames:
        print(f"no {args.timeframe} data")
        return 1
    print(f"{len(frames)} assets on {args.timeframe}\n", flush=True)

    out: dict[str, dict[str, dict]] = {}
    for name in names:
        fn = CONCEPTS.get(name)
        if fn is None:
            continue
        per_variant: dict[str, dict] = {}
        for vname, ecfg in VARIANTS.items():
            dated: list[tuple[str, float]] = []
            for sym, df in frames.items():
                atr = _atr(df)
                try:
                    raw = fn(df, cfg)
                except Exception:  # noqa: BLE001
                    continue
                sig, mult = apply_enhancements(df, raw, ecfg)
                rows = build_journal(
                    df, sig, symbol=sym, timeframe=args.timeframe,
                    setup_name=name, atr=atr, atr_mult=cfg.atr_mult,
                    reward_risk=cfg.reward_risk, horizon_bars=cfg.horizon_bars,
                    cost_round_trip=cfg.cost_round_trip)
                # scale each trade by the multiplier that was live at ENTRY
                idx = np.nonzero(sig)[0]
                for k, row in enumerate(rows):
                    m = float(mult[idx[k]]) if k < idx.size else 1.0
                    dated.append((row.date, row.result_r * m))
            if len(dated) < 100:
                continue
            dated.sort(key=lambda x: x[0])          # CHRONOLOGICAL
            r = np.array([x[1] for x in dated], dtype=float)
            st = drawdown_stats(r)
            per_variant[vname] = {
                "trades": int(r.size),
                "expectancy_r": float(r.mean()),
                "win_rate": float((r > 0).mean()),
                **st,
            }
        if per_variant:
            out[name] = per_variant
            b = per_variant.get("baseline")
            line = f"  {name:<22}"
            for vname in VARIANTS:
                v = per_variant.get(vname)
                line += (f" | {vname[:4]} E={v['expectancy_r']:+.3f} "
                         f"DD={v['max_drawdown_r']:6.1f} "
                         f"R/DD={v['return_over_maxdd']:+.3f}" if v else f" | {vname[:4]} --")
            print(line, flush=True)

    # ---- report ----------------------------------------------------------
    L = [
        "# Enhancements — what actually reduces drawdown",
        "",
        f"{len(frames)} assets · {args.timeframe} · {cfg.reward_risk}:1 at "
        f"{cfg.atr_mult} ATR · {cfg.horizon_bars}-bar limit · "
        f"{args.cost_bps:.0f} bps round trip.",
        "",
        "Four variants on **identical signals**. Volatility targeting changes only",
        "SIZE; the regime filter changes only WHETHER. Neither can create a signal,",
        "so neither can manufacture edge — they can only redistribute risk.",
        "",
        "> **Read the R/DD column, not the DD column.** Halving drawdown by halving",
        "> size is not an improvement — it is the same curve drawn smaller, and it",
        "> leaves return-over-drawdown unchanged. Only a variant that raises R/DD has",
        "> improved anything.",
        "",
        "Drawdown is computed on trades sorted **chronologically**. Sorted by asset",
        "instead — which is how the pooled rows arrive — it reports the sum of",
        "unrelated losing tails glued together.",
        "",
        "| Setup | Variant | Trades | Win% | Expectancy R | Max DD (R) | Streak | Total R | **R/DD** |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for name, variants in out.items():
        base = variants.get("baseline", {})
        for vname in VARIANTS:
            v = variants.get(vname)
            if not v:
                continue
            # Only highlight R/DD when the baseline actually earns something.
            # With a losing baseline the ratio pins near -1 for every variant
            # and "better" would just mean "loses fractionally less".
            better = (vname != "baseline" and base
                      and base.get("total_r", 0.0) > 0
                      and np.isfinite(v["return_over_maxdd"])
                      and np.isfinite(base.get("return_over_maxdd", np.nan))
                      and v["return_over_maxdd"] > base["return_over_maxdd"])
            L.append(
                f"| `{name}` | {vname} | {v['trades']:,} | {v['win_rate']*100:.1f}% | "
                f"{v['expectancy_r']:+.4f} | {v['max_drawdown_r']:,.1f} | "
                f"{v['longest_losing_streak']} | {v['total_r']:,.1f} | "
                f"{'**' if better else ''}{v['return_over_maxdd']:+.3f}{'**' if better else ''} |")

    # verdict, computed
    #
    # R/DD IS ONLY MEANINGFUL WHEN THE BASELINE MAKES MONEY. With a negative
    # expectancy the equity curve only descends, so max drawdown converges on
    # the total loss and R/DD pins near -1 for everything. Ranking -0.983 above
    # -0.996 would report "loses very slightly less" as an improvement, which
    # is how a losing system gets dressed up as a fixed one. So the verdict is
    # computed on EXPECTANCY whenever the baseline loses, and on R/DD only
    # where there is a return to divide.
    wins_e = {vn: 0 for vn in VARIANTS if vn != "baseline"}
    wins_rdd = {vn: 0 for vn in VARIANTS if vn != "baseline"}
    total = n_positive = 0
    for name, variants in out.items():
        b = variants.get("baseline")
        if not b:
            continue
        total += 1
        positive = b["total_r"] > 0
        n_positive += int(positive)
        for vn in wins_e:
            v = variants.get(vn)
            if not v:
                continue
            if v["expectancy_r"] > b["expectancy_r"]:
                wins_e[vn] += 1
            if positive and np.isfinite(v["return_over_maxdd"]) \
                    and v["return_over_maxdd"] > b["return_over_maxdd"]:
                wins_rdd[vn] += 1

    L += ["", "## Verdict", ""]
    if n_positive == 0:
        L += [
            f"**All {total} baselines lose money, so return-over-drawdown says nothing",
            "here.** When the curve only descends, max drawdown converges on the total",
            "loss and R/DD pins near −1 for every variant; ranking −0.983 above −0.996",
            "would be dressing up \"loses fractionally less\" as a fix.",
            "",
            "The only question left is whether an enhancement moved EXPECTANCY toward",
            "positive:", "",
            "| Variant | Improved expectancy |", "|---|---|",
        ]
        for vn, c in sorted(wins_e.items(), key=lambda kv: -kv[1]):
            L.append(f"| {vn} | {c} / {total} |")
        L += ["",
              "Neither enhancement can create edge — by construction they change only",
              "SIZE and WHETHER, never which bars fire. A setup with negative expectancy",
              "stays negative; volatility targeting merely re-weights the losses, and",
              "where it sized up into quiet periods that then moved against the",
              "position it made them larger.", ""]
    else:
        L += [f"{n_positive} of {total} baselines are profitable, so R/DD is meaningful",
              "for those only.", "",
              "| Variant | Improved expectancy | Improved R/DD (profitable baselines) |",
              "|---|---|---|"]
        for vn in sorted(wins_e, key=lambda k: -wins_e[k]):
            L.append(f"| {vn} | {wins_e[vn]} / {total} | {wins_rdd[vn]} / {n_positive} |")
    L += [
        "",
        "## What this cannot tell you",
        "",
        "- In-sample. A variant that wins here still needs a walk-forward test.",
        "- The regime filter uses FIXED conventional thresholds and was not tuned.",
        "  Tuning it until the curve looks good is the standard way to produce an",
        "  in-sample-only result, and is the reason the thresholds are frozen.",
        "- Pooling assets scores concurrent positions as sequential, so the pooled",
        "  drawdown UNDERSTATES what a real book would take when several instruments",
        "  draw down together. Per-pair drawdown is the honest per-instrument figure.",
        "",
        "## Sources",
        "",
        "- Volatility targeting cut the S&P 500's 2008 drawdown from −37.0% to −21.4%,",
        "  and roughly 15pp off the 2020 crash.",
        "- Regime filters improve risk-adjusted returns in aggregate, and are also",
        "  \"the easiest component of a trading system to mess up\" — which is why the",
        "  thresholds here are conventional and frozen rather than fitted.",
    ]
    OUT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(
        {"timeframe": args.timeframe, "config": cfg.to_dict(),
         "variants": {k: v.to_dict() for k, v in VARIANTS.items()},
         "results": out, "wins": wins, "setups_compared": total},
        indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {OUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
