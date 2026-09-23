"""Scan every asset for the high-profile ORB setup, in the platform's signal shape.

Prints the same fields the main scanner prints -- entry, stop_loss,
take_profit_1/2, risk_percent, expected_value, confidence_score, invalidation --
so a signal from here and a signal from `/api/v1/signals` are read the same way.

`--as-of` points the scan at a past session and is the reason this is testable:
the scanner must produce for 2026-08-14 exactly what it would have produced on
2026-08-14, using nothing that closed later.

    python scripts/scan_high_profile.py
    python scripts/scan_high_profile.py --as-of 2026-08-14 --json
    python scripts/scan_high_profile.py --stop-model orb_opposite --top 10
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from project_titan_x.core.config import list_assets  # noqa: E402
from project_titan_x.core.config.assets import SUPPORTED_ASSETS  # noqa: E402
from project_titan_x.setups.high_profile_setup import HighProfileConfig  # noqa: E402
from project_titan_x.setups.hp_scanner import load_measured, scan_all  # noqa: E402

DATA = ROOT / "project_titan_x" / "data" / "processed"


def _yahoo(s):
    a = SUPPORTED_ASSETS.get(s)
    return getattr(a, "yahoo_symbol", s) if a else s


def _load(sym, tf, tail_bars):
    for c in (_yahoo(sym), sym):
        hits = glob.glob(str(DATA / f"{c}_{tf}.parquet"))
        if hits:
            df = pd.read_parquet(hits[0])
            # Only the recent tail is needed: the scan looks at one session plus
            # the lookback windows behind it. Reading 887k BTC bars to score one
            # day is the difference between a scan that takes seconds and one
            # that takes minutes.
            return df.tail(tail_bars) if tail_bars else df
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeframe", default="5m")
    ap.add_argument("--orb-minutes", type=int, default=5)
    ap.add_argument("--stop-model", default="atr_pct", choices=["atr_pct", "orb_opposite"])
    ap.add_argument("--entry", default="stop_order", choices=["stop_order", "open"])
    ap.add_argument("--rvol-min", type=float, default=1.0)
    ap.add_argument("--rvol-top-n", type=int, default=20)
    ap.add_argument("--as-of", default=None, help="YYYY-MM-DD session to scan")
    ap.add_argument("--tail-bars", type=int, default=6000,
                    help="bars to read per asset; 0 reads the whole file")
    ap.add_argument("--top", type=int, default=0, help="print only the top N")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    cfg = HighProfileConfig(
        orb_minutes=args.orb_minutes, stop_model=args.stop_model,
        entry_trigger=args.entry, rvol_min=args.rvol_min, rvol_top_n=args.rvol_top_n)

    frames = {}
    for a in list_assets():
        df = _load(a.symbol, args.timeframe, args.tail_bars)
        if df is not None and len(df) > 100:
            frames[a.symbol] = df
    if not frames:
        print(f"no {args.timeframe} data found")
        return 1

    as_of = pd.Timestamp(args.as_of) if args.as_of else None
    sigs = scan_all(frames, cfg=cfg, measured=load_measured(), as_of=as_of)
    if args.top:
        sigs = sigs[:args.top]

    if args.json:
        print(json.dumps(sigs, indent=2, default=str))
        return 0

    if not sigs:
        print("no setup fired: every session was a doji, outside the window, "
              "or lacked the lookback to compute a stop.")
        return 0

    print(f"\n{len(sigs)} signal(s) · {args.timeframe} · {cfg.orb_minutes}-min range "
          f"· {cfg.stop_model} stop · entry {cfg.entry_trigger}\n")
    hdr = (f"{'ASSET':<12} {'DIR':<6} {'ENTRY':>12} {'STOP':>12} {'TP1(2R)':>12} "
           f"{'TP2':>12} {'RVOL':>6} {'CONF':>5} {'EV%':>8}  TOP-N")
    print(hdr)
    print("-" * len(hdr))
    for s in sigs:
        print(f"{s['asset']:<12} {s['direction']:<6} {s['entry']:>12.4f} "
              f"{s['stop_loss']:>12.4f} {s['take_profit_1']:>12.4f} "
              f"{s['take_profit_2']:>12.4f} "
              f"{(s['rvol'] if s['rvol'] is not None else float('nan')):>6.2f} "
              f"{s['confidence_score']:>5} {s['expected_value']:>+8.4f}  "
              f"{'yes' if s['checks_passed'].get('rvol_top_n') else 'no'}")

    print("\nFirst signal in full:\n")
    top = sigs[0]
    for line in top["supporting_evidence"]:
        print(f"  - {line}")
    print(f"\n  Invalidation: {top['invalidation']}")
    print(f"  History:      {top['historical_context']}")
    failed = [k for k, v in top["checks_passed"].items() if not v]
    print(f"  Checks failed: {', '.join(failed) if failed else 'none'}")
    print("\nEV% is the MEASURED net expectancy per trade in percent of account, "
          "from this repo's\nown backtest of this setup -- not a forecast. Where it "
          "is negative the setup lost\nmoney on the data it was measured on.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
