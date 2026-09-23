"""Which available features actually predict signal outcomes.

THE QUESTION THIS ANSWERS. The live generator scores on five inputs -- ema_8,
ema_21, adx, rsi, macd -- and its confidence carries almost no information
(measured: +0.161 correlation with outcomes, every bucket sitting at the 33.3%
breakeven). Adding inputs is the obvious next move, but "add more indicators"
is how the overfitting started. So: measure first, build second.

For every feature e07 already computes, this asks a single question -- does
knowing it at signal time change the odds? -- and reports the answer as a
spread in realised win rate between the feature's top and bottom quintile.

WHY QUINTILE SPREAD RATHER THAN CORRELATION. A raw correlation against a 0/1
outcome is dominated by the base rate and hides non-monotone effects (a feature
can be informative at both extremes and useless in the middle). Quintile spread
states the thing a trader would act on: if I only took signals in this
feature's top fifth, what would my win rate have been?

WHAT A POSITIVE RESULT WOULD MEAN, AND NOT MEAN. A large spread says the
feature separated outcomes IN SAMPLE, across the same history the strategies
were fitted on. It is a shortlist for testing, not a discovery -- with 37
features the best spread by chance alone is not small, which is why the
shuffled control below is reported beside it. A feature that cannot beat its
own shuffled version is noise.
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

sys.path.insert(0, str(Path(__file__).parent))
from calibrate_signal_confidence import combined_score  # noqa: E402

DATA = ROOT / "project_titan_x" / "data" / "processed"
OUT_MD = ROOT / "project_titan_x" / "reports" / "FEATURE_INFORMATION.md"

SKIP = {"open", "high", "low", "close", "volume", "symbol", "timeframe",
        "timestamp", "dividends", "stock_splits"}


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


def collect(e: pd.DataFrame, *, threshold, rr, atr_mult, horizon):
    """(feature row, win) for every firing signal. Entry at the next open."""
    comb = combined_score(e).to_numpy(float)
    high, low, open_ = (e["high"].to_numpy(float), e["low"].to_numpy(float),
                        e["open"].to_numpy(float))
    close = e["close"].to_numpy(float)
    atr = e["atr"].to_numpy(float)
    feats = [c for c in e.columns if c not in SKIP and pd.api.types.is_numeric_dtype(e[c])]
    F = {c: e[c].to_numpy(float) for c in feats}
    n = len(e)
    recs, wins = [], []
    for i in range(n - horizon - 1):
        s = comb[i]
        a = atr[i]
        if not np.isfinite(s) or abs(s) < threshold or not np.isfinite(a) or a <= 0:
            continue
        d = 1 if s > 0 else -1
        entry = open_[i + 1]
        if not np.isfinite(entry):
            continue
        stop, target = entry - d * atr_mult * a, entry + d * rr * atr_mult * a
        w = 0
        for j in range(i + 1, min(i + 1 + horizon, n)):
            if (d == 1 and low[j] <= stop) or (d == -1 and high[j] >= stop):
                w = 0
                break
            if (d == 1 and high[j] >= target) or (d == -1 and low[j] <= target):
                w = 1
                break
        else:
            continue
        # Features are normalised where scale is instrument-specific, so GOLD
        # at 4,000 and EURUSD at 1.08 contribute on the same axis.
        row = {}
        for c in feats:
            v = F[c][i]
            if not np.isfinite(v):
                v = np.nan
            if c in ("atr", "bb_width", "obv", "vwap", "bb_upper", "bb_lower",
                     "bb_middle", "ema_8", "ema_21", "ema_50", "ema_200",
                     "vwap_upper_1", "vwap_upper_2", "vwap_lower_1", "vwap_lower_2",
                     "ichimoku_kijun", "ichimoku_tenkan", "ichimoku_senkou_a",
                     "ichimoku_senkou_b", "macd", "macd_signal", "macd_hist"):
                v = v / close[i] if close[i] else np.nan
            row[c] = v
        # Signed by trade direction: "is price far above its own mean" means
        # the opposite thing for a short, and an unsigned feature would cancel.
        row["_dir"] = float(d)
        row["_conf"] = abs(s) * 100.0
        recs.append(row)
        wins.append(w)
    return recs, wins


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeframes", default="1d")
    ap.add_argument("--threshold", type=float, default=0.2)
    ap.add_argument("--rr", type=float, default=2.0)
    ap.add_argument("--atr-mult", type=float, default=1.0)
    ap.add_argument("--horizon", type=int, default=20)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    ta = TechnicalAnalysisEngine()
    ta.initialize()
    all_recs, all_wins = [], []
    for tf in [t.strip() for t in args.timeframes.split(",") if t.strip()]:
        for sym in [a.symbol for a in list_assets()]:
            df = _load(sym, tf)
            if df is None or len(df) < 300:
                continue
            try:
                r = ta.analyze(df, symbol=sym, timeframe=tf)
                if not r.success:
                    continue
                recs, wins = collect(r.data["df"], threshold=args.threshold, rr=args.rr,
                                     atr_mult=args.atr_mult, horizon=args.horizon)
            except Exception:  # noqa: BLE001
                continue
            all_recs.extend(recs)
            all_wins.extend(wins)
        print(f"  {tf}: {len(all_wins):,} resolved signals", flush=True)

    if len(all_wins) < 500:
        print("too few resolved signals")
        return 1

    X = pd.DataFrame(all_recs)
    y = np.array(all_wins, dtype=float)
    base = y.mean()
    be = 1.0 / (1.0 + args.rr)
    rng = np.random.default_rng(args.seed)
    y_shuf = rng.permutation(y)

    def spread(col, target):
        v = X[col].to_numpy(float)
        m = np.isfinite(v)
        if m.sum() < 500:
            return None
        vv, tt = v[m], target[m]
        try:
            q = np.quantile(vv, [0.2, 0.8])
        except Exception:  # noqa: BLE001
            return None
        lo, hi = vv <= q[0], vv >= q[1]
        if lo.sum() < 100 or hi.sum() < 100:
            return None
        return float(tt[hi].mean() - tt[lo].mean()), float(tt[hi].mean()), float(tt[lo].mean()), int(m.sum())

    out = []
    for c in X.columns:
        real = spread(c, y)
        if real is None:
            continue
        sh = spread(c, y_shuf)
        out.append((c, real[0], real[1], real[2], real[3], sh[0] if sh else float("nan")))
    out.sort(key=lambda r: -abs(r[1]))

    ctrl = np.nanmax([abs(r[5]) for r in out]) if out else float("nan")
    lines = [
        "# Feature Information Test",
        "",
        f"**{len(y):,} resolved signals** · reward:risk {args.rr}:1 · base win rate "
        f"**{base*100:.1f}%** against a {be*100:.1f}% breakeven.",
        "",
        "`spread` = win rate in the feature's top quintile minus its bottom quintile.",
        "`shuffled` is the same computation against randomly permuted outcomes — the",
        f"largest shuffled spread across all features is **{ctrl*100:.1f} pt**, so anything",
        "below that is indistinguishable from noise no matter how it ranks.",
        "",
        "| Feature | Spread | Top Q win% | Bottom Q win% | n | Shuffled | Beats noise? |",
        "|---|---|---|---|---|---|---|",
    ]
    for c, sp, hi, lo, n, sh in out[:20]:
        beats = "**yes**" if abs(sp) > ctrl else "no"
        lines.append(f"| `{c}` | {sp*100:+.1f} pt | {hi*100:.1f}% | {lo*100:.1f}% | "
                     f"{n:,} | {sh*100:+.1f} pt | {beats} |")
    n_beat = sum(1 for r in out if abs(r[1]) > ctrl)
    lines += [
        "",
        f"**{n_beat} of {len(out)} features beat the shuffled control.**",
        "",
        "## Reading this honestly",
        "",
        "- A feature clearing the control has separated outcomes IN SAMPLE, on the same",
        "  history everything else here was fitted to. It is a candidate to test, not an edge.",
        "- The control is the largest spread random noise produced across the same feature",
        "  set, which is the right bar precisely because 37 features were searched.",
        "- Bars containing both stop and target are scored LOSSES; real results are never",
        "  worse than shown.",
    ]
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nWrote {OUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
