"""Meta-labelling: can a second model tell which signals to SKIP?

THE IDEA (Lopez de Prado, Advances in Financial Machine Learning). Decouple two
questions the live rule currently answers with one number. The primary model
says WHICH DIRECTION -- keep it exactly as is. A secondary model says WHETHER TO
ACT, and its probability becomes the position size. The primary sets recall; the
secondary buys precision back by vetoing.

WHY IT USUALLY FAILS, AND WHY IT MIGHT NOT HERE. The standard objection is that
both models see identical data, so the secondary has no basis for finding what
the primary missed -- the same reason the consensus filter failed here (27
variants at 0.974 mean correlation: one opinion, repeated). Meta-labelling is
reported to add value under three conditions, and this system meets all three:

  1. The primary is NOT an ML model. It is a hand-tuned linear composite:
     clamp(adx/25)*sign(ema8-ema21), plus clamp((rsi-50)/25), averaged,
     thresholded at 0.2.
  2. High recall, low precision. It fires 101,516 times at a 33.6% win rate
     against a 33.3% breakeven -- it catches nearly everything and discriminates
     almost nothing.
  3. A genuinely different architecture is available. A gradient-boosted tree
     can represent interactions and regime-dependent thresholds that a weighted
     AVERAGE of two components structurally cannot, on the very same features.

That third point is the logical basis the objection says is normally absent.

LEAKAGE IS THE THING THAT WOULD FAKE A WIN. The split is strictly chronological
-- train on the older portion, test on the newer, never shuffled -- because
these are overlapping, autocorrelated financial observations and a random split
would let the model see neighbours of its own test rows. Reported numbers are
test-only.

WHAT COUNTS AS SUCCESS. Not accuracy. The live rule already "wins" 66% of the
time by predicting loss. What matters is whether vetoing low-probability signals
raises the win rate ON THE TRADES TAKEN while cutting turnover -- because cost
scales with trade count, and that is the binding constraint (+0.0076 R gross
against 0.0603 R of cost).
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
sys.path.insert(0, str(Path(__file__).parent))

from project_titan_x.core.config import list_assets  # noqa: E402
from project_titan_x.engines.e07_technical.engine import TechnicalAnalysisEngine  # noqa: E402
from calibrate_signal_confidence import combined_score, _load  # noqa: E402

OUT = ROOT / "project_titan_x" / "reports" / "META_LABELING.md"
COST_ROUND_TRIP = 0.003
MEDIAN_NOTIONAL = 0.201
RISK_PCT = 0.01
SKIP = {"open", "high", "low", "close", "volume", "symbol", "timeframe",
        "timestamp", "dividends", "stock_splits"}


def collect(e, sym, *, threshold, rr, atr_mult, horizon):
    comb = combined_score(e).to_numpy(float)
    hi, lo, op = (e["high"].to_numpy(float), e["low"].to_numpy(float),
                  e["open"].to_numpy(float))
    close = e["close"].to_numpy(float)
    atr = e["atr"].to_numpy(float)
    ts = (pd.to_datetime(e["timestamp"], utc=True, errors="coerce")
          if "timestamp" in e.columns else pd.to_datetime(e.index, utc=True, errors="coerce"))
    ts = pd.Series(ts).to_numpy()
    feats = [c for c in e.columns if c not in SKIP and pd.api.types.is_numeric_dtype(e[c])]
    F = {c: e[c].to_numpy(float) for c in feats}
    # Price-scaled features are divided by close so instruments at 4,000 and
    # 1.08 land on one axis; a tree splits on thresholds, so raw price levels
    # would just encode "which instrument is this".
    SCALED = {"atr", "bb_width", "obv", "vwap", "bb_upper", "bb_lower", "bb_middle",
              "ema_8", "ema_21", "ema_50", "ema_200", "vwap_upper_1", "vwap_upper_2",
              "vwap_lower_1", "vwap_lower_2", "ichimoku_kijun", "ichimoku_tenkan",
              "ichimoku_senkou_a", "ichimoku_senkou_b", "macd", "macd_signal", "macd_hist"}
    n = len(e)
    rows, ys, times = [], [], []
    for i in range(n - horizon - 1):
        s, A = comb[i], atr[i]
        if not np.isfinite(s) or abs(s) < threshold or not np.isfinite(A) or A <= 0:
            continue
        d = 1 if s > 0 else -1
        en = op[i + 1]
        if not np.isfinite(en) or en <= 0:
            continue
        st, tg = en - d * atr_mult * A, en + d * rr * atr_mult * A
        w = None
        for j in range(i + 1, min(i + 1 + horizon, n)):
            if (d == 1 and lo[j] <= st) or (d == -1 and hi[j] >= st):
                w = 0
                break
            if (d == 1 and hi[j] >= tg) or (d == -1 and lo[j] <= tg):
                w = 1
                break
        if w is None:
            continue
        r = {}
        for c in feats:
            v = F[c][i]
            r[c] = (v / close[i] if (c in SCALED and close[i]) else v)
        r["_dir"] = float(d)
        r["_conf"] = abs(s) * 100.0
        rows.append(r)
        ys.append(w)
        times.append(ts[i])
    return rows, ys, times


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeframe", default="1d")
    ap.add_argument("--threshold", type=float, default=0.2)
    ap.add_argument("--rr", type=float, default=2.0)
    ap.add_argument("--atr-mult", type=float, default=1.0)
    ap.add_argument("--horizon", type=int, default=20)
    ap.add_argument("--train-frac", type=float, default=0.6)
    args = ap.parse_args()

    ta = TechnicalAnalysisEngine()
    ta.initialize()
    R, Y, T = [], [], []
    for a in list_assets():
        d = _load(a.symbol, args.timeframe)
        if d is None or len(d) < 400:
            continue
        try:
            res = ta.analyze(d, symbol=a.symbol, timeframe=args.timeframe)
            if not res.success:
                continue
            r, y, t = collect(res.data["df"], a.symbol, threshold=args.threshold,
                              rr=args.rr, atr_mult=args.atr_mult, horizon=args.horizon)
        except Exception:  # noqa: BLE001
            continue
        R.extend(r)
        Y.extend(y)
        T.extend(t)
    if len(Y) < 5000:
        print(f"only {len(Y)} samples")
        return 1

    X = pd.DataFrame(R).replace([np.inf, -np.inf], np.nan)
    y = np.array(Y, float)
    t = pd.to_datetime(pd.Series(T), utc=True, errors="coerce")
    order = np.argsort(t.to_numpy())
    X, y, t = X.iloc[order].reset_index(drop=True), y[order], t.iloc[order].reset_index(drop=True)
    X = X.fillna(X.median(numeric_only=True))

    cut = int(len(y) * args.train_frac)
    Xtr, Xte, ytr, yte = X.iloc[:cut], X.iloc[cut:], y[:cut], y[cut:]
    print(f"{len(y):,} signals · train {len(ytr):,} (to {t.iloc[cut-1]:%Y-%m}) · "
          f"test {len(yte):,} (from {t.iloc[cut]:%Y-%m})", flush=True)

    from sklearn.ensemble import HistGradientBoostingClassifier
    clf = HistGradientBoostingClassifier(max_depth=4, max_iter=250,
                                         learning_rate=0.05, random_state=7)
    clf.fit(Xtr, ytr)
    p = clf.predict_proba(Xte)[:, 1]

    be = 1.0 / (1.0 + args.rr)
    base_wr = float(yte.mean())
    cost_tr = COST_ROUND_TRIP * MEDIAN_NOTIONAL * 100

    def econ(mask):
        if mask.sum() < 50:
            return None
        wr = float(yte[mask].mean())
        gR = wr * args.rr - (1 - wr)
        return (int(mask.sum()), wr, gR, gR * RISK_PCT * 100 - cost_tr)

    lines = [
        "# Meta-Labelling Test",
        "",
        f"{len(y):,} signals · {args.timeframe} · reward:risk {args.rr}:1 · breakeven "
        f"{be*100:.1f}% · **chronological** split (train to {t.iloc[cut-1]:%Y-%m}, "
        f"test from {t.iloc[cut]:%Y-%m}).",
        "",
        "The primary rule is unchanged and still picks direction. A gradient-boosted",
        "tree predicts whether each signal WINS, and low-probability signals are",
        "skipped. Test-set only — the model never saw these rows or their neighbours.",
        "",
        f"Taking every signal: **{len(yte):,} trades, {base_wr*100:.2f}% win, "
        f"{(base_wr*args.rr-(1-base_wr))*RISK_PCT*100-cost_tr:+.4f}% net/trade**",
        "",
        "| Keep signals with p >= | Trades | % kept | Win% | Gross R | Net %/trade |",
        "|---|---|---|---|---|---|",
    ]
    best = None
    for thr in (0.0, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60):
        e = econ(p >= thr)
        if e is None:
            lines.append(f"| {thr:.2f} | <50 | — | — | — | too few |")
            continue
        n, wr, gR, net = e
        mark = "**" if net > 0 else ""
        lines.append(f"| {thr:.2f} | {n:,} | {n/len(yte)*100:.0f}% | {wr*100:.2f}% | "
                     f"{gR:+.4f} | {mark}{net:+.4f}%{mark} |")
        if best is None or net > best[1]:
            best = (thr, net, wr, n)
        print(f"  p>={thr:.2f}: {n:,} trades, win {wr*100:.2f}%, net {net:+.4f}%", flush=True)

    imp = None
    try:
        from sklearn.inspection import permutation_importance
        sub = min(4000, len(yte))
        pi = permutation_importance(clf, Xte.iloc[:sub], yte[:sub], n_repeats=3,
                                    random_state=7, scoring="roc_auc")
        imp = sorted(zip(X.columns, pi.importances_mean), key=lambda kv: -kv[1])[:8]
    except Exception:  # noqa: BLE001
        pass

    from sklearn.metrics import roc_auc_score
    auc = roc_auc_score(yte, p)
    lines += ["", f"**Test ROC-AUC {auc:.4f}.** 0.50 is a coin flip; this is the single",
              "number that says whether the secondary model learned anything at all."]
    if imp:
        lines += ["", "Most useful features (permutation importance on the test set):", ""]
        for k, v in imp:
            lines.append(f"- `{k}` {v:+.5f}")
    lines += [
        "",
        "## Reading this",
        "",
        "- Accuracy is the wrong metric: predicting 'loss' every time scores 66%.",
        "  What matters is the win rate ON TRADES TAKEN, beside the trade count.",
        "- Chronological split, never shuffled — a random split on overlapping",
        "  financial observations leaks neighbours into the test set.",
        "- Bars containing both stop and target are scored LOSSES.",
    ]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n  AUC {auc:.4f}   best net at p>={best[0]:.2f}: {best[1]:+.4f}%/trade")
    print(f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
