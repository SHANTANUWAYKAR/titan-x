"""Net-of-cost edge across trade construction. The only lever that is left.

THE BINDING CONSTRAINT. Measured 2026-09-21 on 101,516 signals: the live rule's
gross edge is +0.0076 R per trade while round-trip cost is 0.0603 R -- it loses
by roughly 8x. No amount of signal work fixes an 8x gap, and every signal lead
tested (price features, cross-asset, relative strength, directional bias) died
under a year-by-year or null check.

So the question stops being "what predicts?" and becomes "is there ANY trade
construction where this rule's edge exceeds its own costs?". That is the
question a desk asks before funding anything.

WHY CONSTRUCTION CAN MOVE THE ANSWER AT ALL. Under risk-based sizing the
notional deployed is `risk_pct / stop_distance`, so a WIDER stop deploys LESS
notional and therefore pays LESS cost in equity terms -- while the same
percentage price move still resolves the trade. Cost per trade falls roughly
linearly in stop width. Win rate falls too, because a distant target is hit less
often. Those two pull opposite ways and the optimum, if one exists, is empirical.

WHAT A POSITIVE CELL WOULD AND WOULD NOT MEAN. A positive net expectancy here is
in-sample over the same decade everything else was fitted to, and this grid is
itself a search -- scanning 30 cells and reporting the best is exactly the
selection bias this project already measured (150/150 noise paths clear its
bar). So the grid reports EVERY cell, not the best one, and a result only counts
if a whole REGION is positive rather than one isolated cell surrounded by
losses.
"""
from __future__ import annotations

import argparse
import glob
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

OUT = ROOT / "project_titan_x" / "reports" / "NET_EDGE_SURFACE.md"

# E26's own assumption: 0.1% commission + 0.05% slippage per side.
COST_ROUND_TRIP = 0.003
RISK_PCT = 0.01


def trades_for(e: pd.DataFrame, *, threshold, rr, atr_mult, horizon):
    """(win, stop_distance_fraction) per resolved signal."""
    comb = combined_score(e).to_numpy(float)
    hi, lo, op = (e["high"].to_numpy(float), e["low"].to_numpy(float),
                  e["open"].to_numpy(float))
    atr = e["atr"].to_numpy(float)
    n = len(e)
    out = []
    for i in range(n - horizon - 1):
        s, A = comb[i], atr[i]
        if not np.isfinite(s) or abs(s) < threshold or not np.isfinite(A) or A <= 0:
            continue
        d = 1 if s > 0 else -1
        en = op[i + 1]
        if not np.isfinite(en) or en <= 0:
            continue
        stop_frac = (atr_mult * A) / en
        if not np.isfinite(stop_frac) or stop_frac <= 0:
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
        out.append((w, stop_frac))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeframe", default="1d")
    ap.add_argument("--threshold", type=float, default=0.2)
    ap.add_argument("--horizon", type=int, default=60)
    ap.add_argument("--max-leverage", type=float, default=3.0)
    args = ap.parse_args()

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
    print(f"{len(frames)} instruments enriched", flush=True)

    ATR_MULTS = [0.5, 1.0, 2.0, 3.0, 5.0, 8.0]
    RRS = [1.0, 1.5, 2.0, 3.0, 5.0]

    grid = {}
    for am in ATR_MULTS:
        for rr in RRS:
            wins, stops = [], []
            for e in frames:
                for w, sf in trades_for(e, threshold=args.threshold, rr=rr,
                                        atr_mult=am, horizon=args.horizon):
                    wins.append(w)
                    stops.append(sf)
            if len(wins) < 500:
                grid[(am, rr)] = None
                continue
            wins = np.array(wins, float)
            stops = np.array(stops, float)
            wr = wins.mean()
            gross_R = wr * rr - (1 - wr) * 1.0
            # Notional actually deployed, capped exactly as E26 caps it.
            notional = np.minimum(RISK_PCT / stops, args.max_leverage)
            cost_eq = (COST_ROUND_TRIP * notional).mean() * 100      # % of equity
            gross_eq = gross_R * RISK_PCT * 100                     # % of equity
            grid[(am, rr)] = {
                "n": len(wins), "wr": wr, "gross_R": gross_R,
                "gross_eq": gross_eq, "cost_eq": cost_eq,
                "net_eq": gross_eq - cost_eq,
                "notional": float(notional.mean()),
            }
        print(f"  atr_mult {am} done", flush=True)

    lines = [
        "# Net-of-Cost Edge Surface",
        "",
        f"Live rule · {args.timeframe} · {len(frames)} instruments · resolve within "
        f"{args.horizon} bars · risk {RISK_PCT*100:.0f}%/trade · "
        f"round-trip cost {COST_ROUND_TRIP*100:.2f}% of notional · leverage cap "
        f"{args.max_leverage}x.",
        "",
        "Each cell is **net % of equity per trade** after costs. Wider stops deploy less",
        "notional (`risk/stop_distance`) and so pay less cost, but hit their target less",
        "often — the grid shows where, if anywhere, that trade is worth making.",
        "",
        "| ATR mult | " + " | ".join(f"RR {r}" for r in RRS) + " |",
        "|---|" + "---|" * len(RRS),
    ]
    for am in ATR_MULTS:
        cells = []
        for rr in RRS:
            g = grid.get((am, rr))
            cells.append("—" if not g else
                         (f"**{g['net_eq']:+.4f}**" if g["net_eq"] > 0 else f"{g['net_eq']:+.4f}"))
        lines.append(f"| {am} | " + " | ".join(cells) + " |")

    pos = [(k, v) for k, v in grid.items() if v and v["net_eq"] > 0]
    lines += ["", f"**{len(pos)} of {len([v for v in grid.values() if v])} cells are net-positive.**", ""]
    if pos:
        pos.sort(key=lambda kv: -kv[1]["net_eq"])
        lines += ["| ATR | RR | trades | win% | gross R | notional | cost %/tr | **net %/tr** |",
                  "|---|---|---|---|---|---|---|---|"]
        for (am, rr), g in pos[:10]:
            lines.append(f"| {am} | {rr} | {g['n']:,} | {g['wr']*100:.1f}% | {g['gross_R']:+.4f} | "
                         f"{g['notional']:.3f}x | {g['cost_eq']:.4f}% | **{g['net_eq']:+.4f}%** |")
    lines += [
        "",
        "## Reading this",
        "",
        "- One positive cell in a field of negatives is selection, not a finding. A result",
        "  counts only if neighbouring cells are positive too — an isolated winner is what",
        "  a 30-cell search produces from noise.",
        "- In-sample, on the decade everything else was fitted to.",
        "- Bars containing both stop and target are scored LOSSES.",
        "- Costs are modelled flat. Real spreads widen exactly when these signals fire.",
    ]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nWrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
