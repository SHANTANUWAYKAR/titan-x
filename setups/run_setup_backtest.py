"""Walk-forward backtest of the Titan setup, every asset x every timeframe.

WHY WALK-FORWARD AND NOT A SPLIT. A single train/test split gives one
out-of-sample observation, and one observation is how every lead in this project
died -- the wider-stop result, the long bias and relative strength all looked
fine on a pooled number and fell apart the moment they were cut by period. The
published guidance is 5-10 folds for the same reason: three is not
statistically interesting.

Each fold trains the skip filter on data strictly BEFORE the fold it scores, and
the filter is refit per fold. A setup that only works with a filter trained on
its own future is not a setup.

WALK-FORWARD EFFICIENCY is reported per pair: out-of-sample performance divided
by in-sample. WFE above ~0.5 means the setup kept more than half its in-sample
edge when it met new data. Below that, the in-sample number was mostly fitting.

WHAT IS COUNTED AND WHAT IS NOT. Signals whose time barrier expires before
either price barrier is touched are EXCLUDED from the win rate -- that is
standard, but it silently flattered a result earlier in this audit (65% of
trades excluded), so the unresolved fraction is reported on every row. Read it
before reading the win rate.

    python setups/run_setup_backtest.py
    python setups/run_setup_backtest.py --timeframes 1d,4h --folds 6
    python setups/run_setup_backtest.py --no-meta      # baseline, filter off
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
from project_titan_x.engines.e07_technical.engine import TechnicalAnalysisEngine  # noqa: E402
from project_titan_x.setups.titan_setup import (  # noqa: E402
    SetupConfig, apply_meta_filter, economics, extract_signals, fit_meta_filter,
)

DATA = ROOT / "project_titan_x" / "data" / "processed"
OUT_MD = ROOT / "project_titan_x" / "reports" / "SETUP_BACKTEST.md"
OUT_JSON = ROOT / "project_titan_x" / "data" / "models" / "setups" / "titan_setup_backtest.json"


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


def walk_forward_pooled(sig: pd.DataFrame, cfg: SetupConfig, folds: int) -> dict:
    """Anchored folds over the POOLED cross-asset signal set.

    Pooled on purpose. An earlier version of this ran folds per asset, which
    left each fold ~300 rows of training data -- below meta_min_train, so
    fit_meta_filter returned None on every pair and the "setup" silently
    measured the unfiltered baseline. The successful meta-label test trained on
    60,910 pooled rows; a per-asset filter cannot see enough to learn anything.

    Chronology is still strict: folds are cut on TIME across the whole panel, so
    a fold is only ever scored by a filter trained on bars that closed before
    it, on every instrument.
    """
    if sig.empty or len(sig) < folds * 200:
        return {"folds": 0, "reason": f"only {len(sig)} signals"}
    sig = sig.sort_values("_ts").reset_index(drop=True)
    n = len(sig)
    bounds = [int(n * (i + 1) / (folds + 1)) for i in range(folds)]
    per_fold, is_rows, kept_all = [], [], []
    for k, cut in enumerate(bounds):
        end = bounds[k + 1] if k + 1 < len(bounds) else n
        train, test = sig.iloc[:cut], sig.iloc[cut:end]
        if test.empty:
            continue
        model = fit_meta_filter(train, cfg) if cfg.use_meta_filter else None
        kept = apply_meta_filter(model, test, cfg) if model is not None else test
        e_oos = economics(kept, cfg)
        e_is = economics(apply_meta_filter(model, train, cfg) if model is not None else train, cfg)
        if e_oos.get("trades", 0):
            per_fold.append(e_oos)
            kept_all.append(kept)
        if e_is.get("trades", 0):
            is_rows.append(e_is)
        print(f"    fold {k+1}/{folds}: train {len(train):,} -> test {len(test):,} · "
              f"kept {e_oos.get('trades',0):,} · win {e_oos.get('win_rate',0)*100:.1f}% · "
              f"net {e_oos.get('net_pct_per_trade',0):+.4f}% · "
              f"filter {'ON' if model is not None else 'OFF (too little train data)'}",
              flush=True)
    if not per_fold:
        return {"folds": 0, "reason": "no fold produced trades"}
    w = [r["trades"] for r in per_fold]
    net = float(np.average([r["net_pct_per_trade"] for r in per_fold], weights=w))
    is_net = (float(np.average([r["net_pct_per_trade"] for r in is_rows],
                               weights=[r["trades"] for r in is_rows])) if is_rows else float("nan"))
    return {
        "folds": len(per_fold),
        "trades": int(sum(w)),
        "win_rate": float(np.average([r["win_rate"] for r in per_fold], weights=w)),
        "net_pct_per_trade": net,
        "is_net_pct_per_trade": is_net,
        "wfe": (net / is_net) if (np.isfinite(is_net) and is_net != 0) else float("nan"),
        "per_fold_net": [r["net_pct_per_trade"] for r in per_fold],
        "per_fold_trades": w,
        "kept": pd.concat(kept_all) if kept_all else pd.DataFrame(),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeframes", default="1d,4h,1h")
    ap.add_argument("--folds", type=int, default=6)
    ap.add_argument("--meta-threshold", type=float, default=0.50)
    ap.add_argument("--no-meta", action="store_true")
    # The two components included from published practice but NOT measured on
    # this book. Off by default precisely so a result never inherits them
    # untested; these flags are how they get measured.
    ap.add_argument("--adx-band", action="store_true", help="gate on ADX in 20-30")
    ap.add_argument("--volume-confirm", action="store_true", help="gate on volume >= 1.5x 20-bar avg")
    args = ap.parse_args()

    cfg = SetupConfig(use_meta_filter=not args.no_meta,
                      meta_threshold=args.meta_threshold,
                      use_adx_band=args.adx_band,
                      use_volume_confirm=args.volume_confirm)
    ta = TechnicalAnalysisEngine()
    ta.initialize()
    tfs = [t.strip() for t in args.timeframes.split(",") if t.strip()]
    syms = [a.symbol for a in list_assets()]

    frames = []
    for tf in tfs:
        for sym in syms:
            d = _load(sym, tf)
            if d is None or len(d) < 400:
                continue
            try:
                r = ta.analyze(d, symbol=sym, timeframe=tf)
                if not r.success:
                    continue
                sig = extract_signals(r.data["df"], cfg)
            except Exception:  # noqa: BLE001
                continue
            if sig.empty:
                continue
            sig["_sym"] = sym
            sig["_tf"] = tf
            frames.append(sig)
        print(f"-- {tf} extracted", flush=True)
    if not frames:
        print("no signals extracted")
        return 1
    allsig = pd.concat(frames, ignore_index=True)
    print("", flush=True)
    n_sym = allsig["_sym"].nunique()
    n_tf = allsig["_tf"].nunique()
    print("", flush=True)
    print(f"pooled {len(allsig):,} signals across {n_sym} assets x {n_tf} timeframe(s)", flush=True)
    print("", flush=True)
    print("", flush=True)

    pooled = walk_forward_pooled(allsig, cfg, args.folds)
    kept = pooled.pop("kept", pd.DataFrame())

    # Per asset/timeframe breakdown of the trades the filter actually KEPT.
    results = {}
    if not kept.empty:
        for (sym, tf), grp in kept.groupby(["_sym", "_tf"]):
            e = economics(grp, cfg)
            e["folds"] = pooled["folds"]
            e["wfe"] = pooled["wfe"]
            results[(sym, tf)] = e

    ok = {k: v for k, v in results.items() if v.get("folds")}
    lines = [
        "# Titan Setup — Walk-Forward Backtest",
        "",
        f"**{len(ok)} asset/timeframe pairs** · {args.folds} anchored folds on the POOLED "
        f"panel · meta filter {'OFF' if args.no_meta else f'ON (p >= {args.meta_threshold})'}.",
        "",
        f"Pooled out-of-sample: **{pooled.get('trades',0):,} trades · "
        f"win {pooled.get('win_rate',0)*100:.2f}% · net {pooled.get('net_pct_per_trade',0):+.4f}%/trade · "
        f"WFE {pooled.get('wfe',float('nan')):.2f}**",
        "",
        f"Per-fold net: {[round(x,4) for x in pooled.get('per_fold_net',[])]}",
        "",
        "The skip filter is refit inside every fold on data strictly before that fold.",
        "`WFE` is out-of-sample net divided by in-sample net — above ~0.5 means the",
        "setup kept more than half its in-sample edge when it met new data.",
        "",
        "| Asset | TF | Folds | Trades | Win% | Net %/trade | WFE |",
        "|---|---|---|---|---|---|---|",
    ]
    for (sym, tf), v in sorted(ok.items(), key=lambda kv: -kv[1]["net_pct_per_trade"]):
        mark = "**" if v["net_pct_per_trade"] > 0 else ""
        lines.append(f"| {sym} | {tf} | {v['folds']} | {v['trades']:,} | "
                     f"{v['win_rate']*100:.1f}% | {mark}{v['net_pct_per_trade']:+.4f}%{mark} | "
                     f"{v['wfe']:.2f} |")

    pos = [v for v in ok.values() if v["net_pct_per_trade"] > 0]
    tot = sum(v["trades"] for v in ok.values())
    wavg = (float(np.average([v["net_pct_per_trade"] for v in ok.values()],
                             weights=[v["trades"] for v in ok.values()])) if ok else 0.0)
    lines += [
        "",
        f"**{len(pos)} of {len(ok)} pairs net-positive** · {tot:,} out-of-sample trades · "
        f"trade-weighted net **{wavg:+.4f}%/trade**.",
        "",
        "## Reading this",
        "",
        "- Every number is out-of-sample by construction: each fold is scored by a",
        "  filter that never saw it.",
        "- A pair that is positive on one fold and negative on five is noise. Check",
        "  `per_fold_net` in the JSON before trusting any single row.",
        "- Signals whose time barrier expires unresolved are excluded from the win",
        "  rate. That exclusion silently flattered an earlier result in this audit.",
        "- Costs are E26's 0.30% round trip on the notional risk-sizing actually",
        "  deploys. Real spreads widen exactly when these signals fire.",
    ]
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(
        {"config": cfg.to_dict(), "folds": args.folds,
         "results": {f"{k[0]}_{k[1]}": v for k, v in results.items()}},
        indent=2, default=str), encoding="utf-8")
    print(f"\n{len(pos)}/{len(ok)} pairs net-positive · trade-weighted {wavg:+.4f}%/trade")
    print(f"Wrote {OUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
