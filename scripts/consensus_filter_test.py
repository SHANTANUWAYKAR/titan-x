"""Does requiring AGREEMENT beat taking the maximum?

THE PROBLEM THIS ATTACKS. Everything in this platform is selected as "best of
830 candidates", and the synthetic null showed 150 of 150 pure-noise paths
producing candidates that clear the selection bar. Taking the max of many draws
selects whichever one got luckiest, by construction.

The inversion: stop asking "which parameterisation is best" and start asking
"how many parameterisations agree right now". A signal only the luckiest variant
sees is noise; one that most variants see is structure.

WHY THIS IS THE ONLY LEVER LEFT. The binding constraint is measured and blunt:
+0.0076 R gross per trade against 0.0603 R of cost, at 363 trades a year --
losing by ~8x. Everything else tested moves only one side of that ratio and not
far enough (more features: redundant; cross-asset: beta; wider stops: 65%
survivorship bias; perfect execution: still -0.16%/yr). Consensus moves BOTH:
fewer trades cuts the cost bill, and if agreement concentrates signal, per-trade
edge rises at the same time.

WHAT WOULD COUNT AS SUCCESS. Not a higher win rate on its own -- a stricter
filter that keeps the same win rate while trading a tenth as often is already a
large improvement, because cost scales with trade count. The table reports win
rate, trade count and NET of costs together for exactly that reason. What would
count as failure is the win rate staying at ~33.6% while the trade count barely
moves, which is what a filter that is really just noise looks like.

HONEST BIAS WARNING. Scanning agreement thresholds is itself a search over ~8
options, so the best cell is high by construction. The whole column is reported
and a result only counts if it is monotone -- improving steadily with strictness
-- rather than one cell spiking.
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
from calibrate_signal_confidence import _load  # noqa: E402

OUT = ROOT / "project_titan_x" / "reports" / "CONSENSUS_FILTER.md"

COST_ROUND_TRIP = 0.003
RISK_PCT = 0.01
MEDIAN_NOTIONAL = 0.201   # measured on real risk-sized trades

# The live rule's own defaults sit inside this grid, so "1 of M agreeing" is
# close to today's behaviour and the comparison is like for like.
VARIANTS = [
    {"entry_threshold": t, "adx_divisor": a, "momentum_divisor": m}
    for t in (0.15, 0.20, 0.25)
    for a in (20.0, 25.0, 30.0)
    for m in (20.0, 25.0, 30.0)
]


def variant_signal(e: pd.DataFrame, p: dict) -> np.ndarray:
    """One parameterisation's -1/0/+1 view. Same formula as e51 L1010."""
    trend_sign = np.where(e["ema_8"] >= e["ema_21"], 1.0, -1.0)
    macd_sign = np.where(e["macd"].fillna(0) >= e["macd_signal"].fillna(0), 1.0, -1.0)
    adx_ratio = np.clip(e["adx"].fillna(0).to_numpy() / p["adx_divisor"], -1, 1)
    trend = adx_ratio * trend_sign
    trend = np.where(macd_sign != trend_sign, trend * 0.5, trend)
    mom = np.clip((e["rsi"].fillna(50).to_numpy() - 50) / p["momentum_divisor"], -1, 1)
    comb = (trend + mom) / 2
    out = np.zeros(len(e))
    out[comb >= p["entry_threshold"]] = 1
    out[comb <= -p["entry_threshold"]] = -1
    return out


def outcomes(e: pd.DataFrame, votes: np.ndarray, need: int, *, rr, atr_mult, horizon):
    """(win,) for bars where at least `need` variants agree on one direction."""
    longs = (votes == 1).sum(axis=0)
    shorts = (votes == -1).sum(axis=0)
    hi, lo, op = (e["high"].to_numpy(float), e["low"].to_numpy(float),
                  e["open"].to_numpy(float))
    atr = e["atr"].to_numpy(float)
    n = len(e)
    res = []
    for i in range(n - horizon - 1):
        d = 0
        if longs[i] >= need and longs[i] > shorts[i]:
            d = 1
        elif shorts[i] >= need and shorts[i] > longs[i]:
            d = -1
        if d == 0:
            continue
        A = atr[i]
        en = op[i + 1]
        if not np.isfinite(A) or A <= 0 or not np.isfinite(en):
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
        res.append(w)
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeframe", default="1d")
    ap.add_argument("--rr", type=float, default=2.0)
    ap.add_argument("--atr-mult", type=float, default=1.0)
    ap.add_argument("--horizon", type=int, default=20)
    args = ap.parse_args()

    M = len(VARIANTS)
    ta = TechnicalAnalysisEngine()
    ta.initialize()
    frames = []
    for a in list_assets():
        d = _load(a.symbol, args.timeframe)
        if d is None or len(d) < 400:
            continue
        try:
            r = ta.analyze(d, symbol=a.symbol, timeframe=args.timeframe)
            if r.success:
                frames.append(r.data["df"])
        except Exception:  # noqa: BLE001
            continue
    print(f"{len(frames)} instruments · {M} variants", flush=True)

    votes_by_frame = []
    for e in frames:
        votes_by_frame.append(np.vstack([variant_signal(e, p) for p in VARIANTS]))
    print("  votes computed", flush=True)

    needs = [1, int(M * 0.25), int(M * 0.5), int(M * 0.7), int(M * 0.85), M]
    needs = sorted(set(n for n in needs if 1 <= n <= M))
    be = 1.0 / (1.0 + args.rr)

    rows = []
    for need in needs:
        allw = []
        for e, v in zip(frames, votes_by_frame):
            allw.extend(outcomes(e, v, need, rr=args.rr, atr_mult=args.atr_mult,
                                 horizon=args.horizon))
        if len(allw) < 200:
            rows.append((need, len(allw), None, None, None))
            continue
        y = np.array(allw, float)
        wr = y.mean()
        gross_R = wr * args.rr - (1 - wr)
        # Per-trade economics, then annualised at this filter's own trade rate.
        gross_tr = gross_R * RISK_PCT * 100
        cost_tr = COST_ROUND_TRIP * MEDIAN_NOTIONAL * 100
        rows.append((need, len(y), wr, gross_tr - cost_tr, gross_R))
        print(f"  need {need:>2}/{M}: {len(y):>6,} trades  win {wr*100:.2f}%", flush=True)

    base = rows[0]
    lines = [
        "# Consensus Filter Test",
        "",
        f"{len(frames)} instruments · {args.timeframe} · **{M} parameter variants** · "
        f"reward:risk {args.rr}:1 · breakeven {be*100:.1f}%.",
        "",
        "Instead of taking the best parameterisation, require N of M to agree. The",
        "question is not only whether the win rate rises — a filter that holds the win",
        "rate while trading a tenth as often is already a large gain, because cost",
        "scales with trade count.",
        "",
        "| Agreement | Trades | vs base | Win% | Gross R | Net %/trade |",
        "|---|---|---|---|---|---|",
    ]
    for need, n, wr, net, gR in rows:
        if wr is None:
            lines.append(f"| {need}/{M} | {n:,} | — | — | — | too few |")
            continue
        ratio = f"{n/base[1]*100:.0f}%" if base[1] else "—"
        flag = "**" if net and net > 0 else ""
        lines.append(f"| {need}/{M} | {n:,} | {ratio} | {wr*100:.2f}% | {gR:+.4f} | "
                     f"{flag}{net:+.4f}%{flag} |")

    got = [r for r in rows if r[2] is not None]
    if len(got) >= 3:
        wrs = [r[2] for r in got]
        monotone = all(b >= a - 0.002 for a, b in zip(wrs, wrs[1:]))
        lines += ["",
                  f"**Win rate monotone in strictness: {'yes' if monotone else 'NO'}.** "
                  "A real consensus effect improves steadily as agreement tightens; a",
                  "single spiking cell in a scanned grid is selection, not signal."]
    lines += [
        "",
        "## Reading this",
        "",
        "- Net uses the measured median notional (0.201x equity) and E26's 0.30%",
        "  round-trip assumption. Cost per trade is constant here; only the trade",
        "  COUNT changes, which is the entire point.",
        "- In-sample, on the decade everything else was fitted to.",
        "- Bars containing both stop and target are scored LOSSES.",
    ]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nWrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
