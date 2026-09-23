"""Two questions about the ML layer, answered with measurement.

  1. How much of the meta-filter's apparent skill was label leakage?
     Compares a naive chronological split against a PURGED + EMBARGOED one.
     Overlapping 20-bar labels mean training rows next to the boundary are
     labelled by price action inside the test block; the gap between the two
     numbers is the size of that leak.

  2. Is the model the limit, or the data? Five learners spanning linear to
     deep boosted trees, all on identical purged folds. If they land in the
     same place, more architecture cannot help and the ceiling is the features.

    python setups/run_ml_audit.py --timeframe 1d
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from project_titan_x.core.config import list_assets  # noqa: E402
from project_titan_x.engines.e07_technical.engine import TechnicalAnalysisEngine  # noqa: E402
from project_titan_x.setups.titan_setup import SetupConfig, extract_signals  # noqa: E402
from project_titan_x.setups.ml_validation import (  # noqa: E402
    model_zoo, purged_walk_forward,
)
from project_titan_x.setups.run_setup_backtest import _load  # noqa: E402

OUT = ROOT / "project_titan_x" / "reports" / "ML_AUDIT.md"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeframe", default="1d")
    ap.add_argument("--folds", type=int, default=6)
    args = ap.parse_args()

    cfg = SetupConfig()
    ta = TechnicalAnalysisEngine()
    ta.initialize()
    frames = []
    for a in list_assets():
        d = _load(a.symbol, args.timeframe)
        if d is None or len(d) < 400:
            continue
        try:
            r = ta.analyze(d, symbol=a.symbol, timeframe=args.timeframe)
            if not r.success:
                continue
            sig = extract_signals(r.data["df"], cfg)
        except Exception:  # noqa: BLE001
            continue
        if not sig.empty:
            frames.append(sig)
    allsig = pd.concat(frames, ignore_index=True).sort_values("_ts").reset_index(drop=True)
    cols = [c for c in allsig.columns if not c.startswith("_")]
    X = allsig[cols].replace([np.inf, -np.inf], np.nan)
    X = X.fillna(X.median(numeric_only=True))
    y = allsig["_win"].to_numpy(float)
    print(f"{len(y):,} signals · {len(cols)} features · base win {y.mean()*100:.2f}%\n", flush=True)

    zoo = model_zoo()
    base = zoo["gbt depth4 (base)"]

    # --- 1. leakage -------------------------------------------------------
    print("1. LEAKAGE: naive chronological vs purged+embargoed", flush=True)
    naive = purged_walk_forward(X, y, folds=args.folds, horizon=0, embargo=0, model_fn=base)
    purged = purged_walk_forward(X, y, folds=args.folds, horizon=cfg.horizon_bars,
                                 embargo=cfg.horizon_bars, model_fn=base)
    print(f"   naive  AUC {naive['auc_weighted']:.4f}  (folds {naive['folds']})", flush=True)
    print(f"   purged AUC {purged['auc_weighted']:.4f}  (folds {purged['folds']}, "
          f"{np.mean(purged['rows_purged_per_fold']):.0f} rows dropped/fold)", flush=True)
    leak = naive["auc_weighted"] - purged["auc_weighted"]
    print(f"   leakage = {leak:+.4f} AUC\n", flush=True)

    # --- 2. model vs data -------------------------------------------------
    print("2. MODEL OR DATA? identical purged folds, five learners", flush=True)
    rows = []
    for name, fn in zoo.items():
        try:
            r = purged_walk_forward(X, y, folds=args.folds, horizon=cfg.horizon_bars,
                                    embargo=cfg.horizon_bars, model_fn=fn)
            rows.append((name, r["auc_weighted"], r["auc_std"]))
            print(f"   {name:<22} AUC {r['auc_weighted']:.4f}  (sd {r['auc_std']:.4f})", flush=True)
        except Exception as e:  # noqa: BLE001
            rows.append((name, float("nan"), float("nan")))
            print(f"   {name:<22} failed: {str(e)[:40]}", flush=True)

    got = [r for r in rows if np.isfinite(r[1])]
    spread = (max(r[1] for r in got) - min(r[1] for r in got)) if got else float("nan")

    lines = [
        "# ML Audit — leakage, and whether the model is the limit",
        "",
        f"{len(y):,} signals · {args.timeframe} · {len(cols)} features · "
        f"{args.folds} anchored folds · base win rate {y.mean()*100:.2f}%.",
        "",
        "## 1. How much was label leakage?",
        "",
        "These labels overlap: a 20-bar horizon means the signal at bar *i+1* shares 19",
        "bars with the one at *i*. Training rows next to a split boundary are therefore",
        "labelled by price action **inside** the test block. Purging drops those rows;",
        "the embargo drops a buffer after the test block too.",
        "",
        "| Validation | ROC-AUC |",
        "|---|---|",
        f"| naive chronological | {naive['auc_weighted']:.4f} |",
        f"| **purged + embargoed** | **{purged['auc_weighted']:.4f}** |",
        f"| leakage | **{leak:+.4f}** |",
        "",
        f"Purging dropped ~{np.mean(purged['rows_purged_per_fold']):.0f} training rows per fold.",
        "",
        "## 2. Is the model the limit, or the data?",
        "",
        "Five learners spanning linear to deep boosted trees, on identical purged folds.",
        "",
        "| Model | ROC-AUC | sd across folds |",
        "|---|---|---|",
    ]
    for name, auc, sd in rows:
        lines.append(f"| {name} | {auc:.4f} | {sd:.4f} |" if np.isfinite(auc)
                     else f"| {name} | — | — |")
    lines += [
        "",
        f"**Spread across all five: {spread:.4f} AUC.**",
        "",
        ("A spread this small means capacity is not the constraint — a linear model and a "
         "600-tree forest extract the same amount, so the ceiling is the information in "
         "the features. More architecture cannot fix that."
         if np.isfinite(spread) and spread < 0.02 else
         "The models differ enough that capacity matters; the larger learners are finding "
         "structure the smaller ones miss."),
        "",
        "## Reading this",
        "",
        "- 0.50 AUC is a coin flip. These are probabilities of a signal WINNING, on a",
        "  base rate near 35%, so accuracy is meaningless here — predicting 'loss'",
        "  always would score 65%.",
        "- Purging and embargo make results worse by design. The gap is the size of the",
        "  lie the naive split was telling.",
    ]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n   spread across models: {spread:.4f} AUC")
    print(f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
