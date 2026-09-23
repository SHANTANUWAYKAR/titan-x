"""What the live signal generator's confidence number actually means.

THE PROBLEM. e51's `_determine_direction` says so itself: "Confidence is
honestly |combined_score|*100 -- a heuristic conviction score, NOT a calibrated
win-probability." So a signal reading 64 is not 64% odds; it is an arbitrary
conviction figure with no measured relationship to outcomes. For a generator
someone actually trades, that is the defect that matters most -- more than any
individual strategy's Sharpe, because it is what turns a number into a
decision.

WHAT THIS DOES. Replays the EXACT live rule over history, records what happened
after each signal, and reports the realised win rate per confidence bucket. The
output answers one question: when this generator says 60-70, how often is it
right?

WHY REPLAYING IS LEGITIMATE HERE. `_vectorized_signal_series` is kept in sync
with `_determine_direction` deliberately -- e51's own docstring says the
edge-gate backtest grades the SAME rule that runs live. The formula is
reimplemented here rather than imported because the engine's version returns
only -1/0/+1 and discards the score that becomes confidence.

OUTCOME DEFINITION. A signal is a WIN when price reaches +`rr` x ATR before
-1 x ATR, measured bar by bar with the stop checked FIRST on any bar that could
have hit both. OHLC cannot order two touches inside one bar, so the ambiguous
case is scored as a loss -- the same convention forward_test uses. The true
result is never worse than reported, and may be better.

This is calibration, not validation. A well-calibrated generator with no edge
is still no edge; it just stops lying about its own conviction.
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

DATA = ROOT / "project_titan_x" / "data" / "processed"
OUT_MD = ROOT / "project_titan_x" / "reports" / "SIGNAL_CALIBRATION.md"
OUT_JSON = ROOT / "project_titan_x" / "data" / "models" / "e42_confidence_calibration" / "signal_calibration.json"


def _yahoo(sym: str) -> str:
    a = SUPPORTED_ASSETS.get(sym)
    return getattr(a, "yahoo_symbol", sym) if a else sym


def _load(sym: str, tf: str):
    for cand in (_yahoo(sym), sym):
        hits = glob.glob(str(DATA / f"{cand}_{tf}.parquet"))
        if hits:
            df = pd.read_parquet(hits[0])
            df.columns = [c.lower() for c in df.columns]
            return df
    return None


def combined_score(enriched: pd.DataFrame, params: dict | None = None) -> pd.Series:
    """The live rule's combined score, reproduced exactly (e51 L1010)."""
    p = params or {}
    adx_div = p.get("adx_divisor", 25.0)
    mom_div = p.get("momentum_divisor", 25.0)
    damp = p.get("disagreement_dampening", 0.5)

    trend_sign = pd.Series(
        np.where(enriched["ema_8"] >= enriched["ema_21"], 1.0, -1.0), index=enriched.index)
    macd_sign = pd.Series(
        np.where(enriched["macd"].fillna(0) >= enriched["macd_signal"].fillna(0), 1.0, -1.0),
        index=enriched.index)
    adx_ratio = (enriched["adx"].fillna(0) / adx_div).clip(-1, 1)
    trend = adx_ratio * trend_sign
    disagree = macd_sign != trend_sign
    trend = trend.where(~disagree, trend * damp)
    momentum = ((enriched["rsi"].fillna(50) - 50) / mom_div).clip(-1, 1)
    return (trend + momentum) / 2


def outcomes(df: pd.DataFrame, comb: pd.Series, *, threshold: float, rr: float,
             atr_mult: float, horizon: int) -> list[tuple[float, int]]:
    """(confidence, win) for every bar whose signal fires.

    Entry is the NEXT bar's open -- the score is only knowable once the bar
    closes, so entering at that same close would be a fill nobody could get.
    """
    high = df["high"].to_numpy(float)
    low = df["low"].to_numpy(float)
    open_ = df["open"].to_numpy(float)
    atr = df["atr"].to_numpy(float) if "atr" in df.columns else None
    if atr is None:
        tr = pd.concat([df["high"] - df["low"],
                        (df["high"] - df["close"].shift()).abs(),
                        (df["low"] - df["close"].shift()).abs()], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().to_numpy(float)
    c = comb.to_numpy(float)
    n = len(df)
    out: list[tuple[float, int]] = []

    for i in range(n - horizon - 1):
        score = c[i]
        if not np.isfinite(score) or abs(score) < threshold:
            continue
        a = atr[i]
        if not np.isfinite(a) or a <= 0:
            continue
        direction = 1 if score > 0 else -1
        entry = open_[i + 1]
        if not np.isfinite(entry):
            continue
        stop = entry - direction * atr_mult * a
        target = entry + direction * rr * atr_mult * a
        win = 0
        for j in range(i + 1, min(i + 1 + horizon, n)):
            hi, lo = high[j], low[j]
            # Stop checked first: a bar containing both levels is scored a
            # loss, because OHLC cannot say which came first.
            if (direction == 1 and lo <= stop) or (direction == -1 and hi >= stop):
                win = 0
                break
            if (direction == 1 and hi >= target) or (direction == -1 and lo <= target):
                win = 1
                break
        out.append((abs(score) * 100.0, win))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeframes", default="1d,4h")
    ap.add_argument("--threshold", type=float, default=0.2)
    ap.add_argument("--rr", type=float, default=2.0, help="reward:risk in ATR units")
    ap.add_argument("--atr-mult", type=float, default=1.0)
    ap.add_argument("--horizon", type=int, default=20, help="bars allowed to resolve")
    args = ap.parse_args()

    ta = TechnicalAnalysisEngine()
    ta.initialize()
    tfs = [t.strip() for t in args.timeframes.split(",") if t.strip()]
    syms = [a.symbol for a in list_assets()]

    rows: list[tuple[float, int]] = []
    per_tf: dict[str, list[tuple[float, int]]] = {}
    covered = 0
    for tf in tfs:
        for sym in syms:
            df = _load(sym, tf)
            if df is None or len(df) < 300:
                continue
            try:
                res = ta.analyze(df, symbol=sym, timeframe=tf)
                if not res.success:
                    continue
                e = res.data["df"]
                o = outcomes(e, combined_score(e), threshold=args.threshold,
                             rr=args.rr, atr_mult=args.atr_mult, horizon=args.horizon)
            except Exception:  # noqa: BLE001
                continue
            if o:
                rows.extend(o)
                per_tf.setdefault(tf, []).extend(o)
                covered += 1
        print(f"  {tf}: {len(per_tf.get(tf, []))} signals from {covered} series", flush=True)

    if not rows:
        print("No signals produced -- nothing to calibrate.")
        return 1

    conf = np.array([r[0] for r in rows])
    win = np.array([r[1] for r in rows])
    breakeven = 1.0 / (1.0 + args.rr)

    edges = [20, 30, 40, 50, 60, 70, 80, 100]
    lines = [
        "# Signal Confidence Calibration",
        "",
        f"**{len(rows):,} signals** · reward:risk {args.rr}:1 (ATR x{args.atr_mult}) · "
        f"resolve within {args.horizon} bars · entry at next bar's open.",
        "",
        f"Breakeven win rate at {args.rr}:1 is **{breakeven*100:.1f}%**. A bucket below that "
        "loses money no matter how confident it sounds.",
        "",
        "| Confidence | Signals | Realised win% | vs breakeven | Verdict |",
        "|---|---|---|---|---|",
    ]
    buckets = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (conf >= lo) & (conf < hi)
        k = int(m.sum())
        if k == 0:
            continue
        wr = float(win[m].mean())
        diff = (wr - breakeven) * 100
        verdict = "profitable" if wr > breakeven else "loses money"
        buckets.append({"lo": lo, "hi": hi, "n": k, "win_rate": round(wr, 4)})
        lines.append(f"| {lo}–{hi} | {k:,} | {wr*100:.1f}% | {diff:+.1f} pt | {verdict} |")

    # Does confidence order outcomes at all? That is the whole claim.
    if len(buckets) >= 2:
        xs = np.array([(b["lo"] + b["hi"]) / 2 for b in buckets])
        ys = np.array([b["win_rate"] for b in buckets])
        ns = np.array([b["n"] for b in buckets], dtype=float)
        corr = float(np.corrcoef(xs, ys)[0, 1]) if len(xs) > 2 else float("nan")
        overall = float(win.mean())
        lines += [
            "",
            f"**Overall win rate {overall*100:.1f}%** against a {breakeven*100:.1f}% breakeven "
            f"({(overall-breakeven)*100:+.1f} pt).",
            "",
            f"**Confidence-to-outcome correlation: {corr:+.3f}.** This is the number that decides",
            "whether the confidence score is informative at all. Near zero means a signal reading",
            "80 is no better than one reading 30, and the number should not be shown to a trader",
            "as though it were.",
        ]
    lines += [
        "",
        "## What this does not establish",
        "",
        "- Calibration is not edge. A perfectly calibrated generator with no edge is still no",
        "  edge -- it has merely stopped overstating its own conviction.",
        "- Bars containing both stop and target are scored as LOSSES, because OHLC cannot order",
        "  two touches inside one bar. Real results are never worse than this, and may be better.",
        "- This replays history. It is not forward evidence, and cannot become forward evidence.",
    ]
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps({
        "n_signals": len(rows), "rr": args.rr, "breakeven": breakeven,
        "overall_win_rate": float(win.mean()), "buckets": buckets,
    }, indent=2), encoding="utf-8")
    print(f"\nWrote {OUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
