"""
Module: structure_sweep.py
Description: Follow-up to concept_ablation.py's two findings, tested across
    the full focus-market x timeframe matrix rather than one market.

    Finding 1 to test: market structure (BOS/CHoCH, order block, MSS) was
    the only family with consistent solo edge at 4h. Is 4h actually where
    it is strongest, or was that just the timeframe that happened to be
    measured?

    Finding 2 to test: of 23 filter tests across three markets, exactly ONE
    improved expectancy -- buying in DISCOUNT on BTCUSD. One hit in 23 is
    what noise looks like, so it is re-tested everywhere before being
    believed.

    Deliberately narrow: only the concepts that already earned a look get
    re-run, over 7 symbols x 3 timeframes, so the result is a genuine
    out-of-sample check on the earlier conclusion rather than a fresh
    fishing expedition over 20 concepts.

    Every concept is lookahead-checked at five truncation points before it
    is graded, the same guard that caught the order-block bug.

    RESEARCH CODE -- outside engines/, nothing live imports it. Reports
    only; never promotes.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import warnings
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
warnings.filterwarnings("ignore")

from project_titan_x.core.config.assets import get_asset
from project_titan_x.engines.e02_market_data.engine import MarketDataEngine
from project_titan_x.engines.e07_technical import TechnicalAnalysisEngine
from project_titan_x.engines.e26_backtesting.engine import BacktestingEngine
from project_titan_x.research import ict_concepts as ic
from project_titan_x.research.concept_ablation import (
    CONCEPTS, _grade, _no_lookahead,
)

STRUCTURE = ("bos_choch", "choch_only", "order_block", "mss")
SYMBOLS = ("GOLD", "SILVER", "BTCUSD", "ETHUSD", "EURUSD", "GBPUSD", "USDJPY")
TIMEFRAMES = ("1h", "4h", "1d")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--symbols", default=",".join(SYMBOLS))
    p.add_argument("--timeframes", default=",".join(TIMEFRAMES))
    args = p.parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    timeframes = [t.strip() for t in args.timeframes.split(",") if t.strip()]

    md, ta, bt = MarketDataEngine(), TechnicalAnalysisEngine(), BacktestingEngine()
    for e in (md, ta, bt):
        e.initialize()

    results: dict = {}
    by_tf: dict[str, list[float]] = defaultdict(list)
    by_concept: dict[str, list[float]] = defaultdict(list)
    discount_deltas: list[tuple[str, str, float]] = []

    print(f"{'ASSET':8} {'TF':4} {'CONCEPT':12} {'TRD':>5} {'WIN%':>6} {'R:R':>6} {'EXPECT':>8} "
          f"{'+DISCOUNT':>10} {'DELTA':>8}")
    for sym in symbols:
        asset = get_asset(sym)
        ysym = asset.yahoo_symbol if asset else sym
        for tf in timeframes:
            fetch = md.fetch_ohlcv(ysym, timeframe=tf, years=10)
            if not fetch.success:
                print(f"{sym:8} {tf:4}   no data")
                continue
            enriched = ta.analyze(fetch.data).data["df"].reset_index(drop=True)
            if len(enriched) < 300:
                print(f"{sym:8} {tf:4}   only {len(enriched)} bars -- skipped")
                continue

            for cname in STRUCTURE:
                fn = CONCEPTS[cname]
                if not _no_lookahead(fn, enriched):
                    print(f"{sym:8} {tf:4} {cname:12}   DISQUALIFIED -- lookahead")
                    continue
                base = _grade(bt, enriched, fn)
                if not base:
                    continue

                # The one filter that helped anywhere: buy only in discount.
                def with_discount(d, _b=fn):
                    return (_b(d).astype(int) * (ic.premium_discount(d) <= 0).astype(int)).astype(int)

                filt = _grade(bt, enriched, with_discount) if _no_lookahead(with_discount, enriched) else None
                delta = (filt["expectancy"] - base["expectancy"]) if filt else float("nan")

                key = f"{sym}_{tf}_{cname}"
                results[key] = {"base": base, "with_discount": filt,
                                "delta_expectancy": None if filt is None else round(delta, 4)}
                by_tf[tf].append(base["expectancy"])
                by_concept[cname].append(base["expectancy"])
                if filt:
                    discount_deltas.append((sym, tf, delta))

                print(f"{sym:8} {tf:4} {cname:12} {base['trades']:>5} {base['win_rate']*100:>5.1f}% "
                      f"{base['reward_risk']:>5.2f}R {base['expectancy']:>8.3f} "
                      f"{(filt['expectancy'] if filt else float('nan')):>10.3f} {delta:>+8.3f}")

    print("\n" + "=" * 92)
    print("FINDING 1 -- is 4h really where structure works best?")
    print("=" * 92)
    print(f"{'TIMEFRAME':10} {'N':>4} {'MEAN EXPECT':>13} {'MEDIAN':>9} {'POSITIVE':>10}")
    for tf in timeframes:
        v = by_tf.get(tf, [])
        if not v:
            continue
        pos = sum(1 for x in v if x > 0)
        print(f"{tf:10} {len(v):>4} {np.mean(v):>13.3f} {np.median(v):>9.3f} {pos:>6}/{len(v)}")
    print(f"\n{'CONCEPT':14} {'N':>4} {'MEAN EXPECT':>13} {'POSITIVE':>10}")
    for c in STRUCTURE:
        v = by_concept.get(c, [])
        if not v:
            continue
        pos = sum(1 for x in v if x > 0)
        print(f"{c:14} {len(v):>4} {np.mean(v):>13.3f} {pos:>6}/{len(v)}")

    print("\n" + "=" * 92)
    print("FINDING 2 -- does the DISCOUNT filter hold up, or was 1-in-23 noise?")
    print("=" * 92)
    if discount_deltas:
        deltas = [d for _, _, d in discount_deltas]
        helped = sum(1 for d in deltas if d > 0)
        print(f"tested on {len(deltas)} asset/timeframe/concept combinations")
        print(f"  improved expectancy : {helped}/{len(deltas)} ({helped/len(deltas)*100:.0f}%)")
        print(f"  mean delta          : {np.mean(deltas):+.4f}")
        print(f"  median delta        : {np.median(deltas):+.4f}")
        best = sorted(discount_deltas, key=lambda x: -x[2])[:3]
        print("  best cases          :", ", ".join(f"{s} {t} {d:+.3f}" for s, t, d in best))
        verdict = ("HOLDS UP -- helps in the majority of cases"
                   if helped > len(deltas) * 0.5 and np.mean(deltas) > 0
                   else "DOES NOT HOLD UP -- the single BTCUSD hit was noise")
        print(f"\n  VERDICT: {verdict}")
    else:
        print("  no gradeable combinations")

    dest = Path(__file__).resolve().parent / "structure_sweep_results.json"
    dest.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(),
                                "results": results}, indent=2), encoding="utf-8")
    print(f"\nSaved to {dest}")


if __name__ == "__main__":
    main()
