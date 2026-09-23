"""
Module: best_signals.py
Description: "Best signal right now, across every pair" -- the repeatable
    version of a full-universe live scan.

    Scans ONLY (asset, timeframe) pairs that carry a validated strategy
    override, i.e. a rule that cleared E26's full walk-forward bar (IS
    trades>=30, IS Sharpe>0.5, max DD<25%, OOS Sharpe>0). Assets with no
    proven edge are skipped rather than shown with a heuristic score, so
    the list never mixes "tested" with "merely computed" -- forex, gold,
    crude and bonds validate on NO timeframe and correctly never appear.

    Every row carries the win rate that actually governs it. That pairing
    is the point of this script, not decoration: several of this
    platform's best-expectancy rules win FEWER than half their trades and
    make their money from outlier winners (ETHUSD 1d regime_adaptive:
    39.2% win rate over 102 real trades, with 6+ losing streaks expected
    about twice per 102). A signal read without its win rate invites
    position sizing that the strategy's own loss pattern will punish.

    Ranks by OOS Sharpe -- realised out-of-sample expectancy -- NOT by the
    confidence score, which is a per-signal conviction read rather than a
    tested edge. Rule 5 still holds: this reports, it never executes.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
if hasattr(sys.stdout, "buffer"):   # real symbols (₹, ·) on a cp1252 console
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from project_titan_x.core.config.assets import list_assets
from project_titan_x.engines.e02_market_data.engine import MarketDataEngine
from project_titan_x.engines.e07_technical import TechnicalAnalysisEngine
from project_titan_x.engines.e08_regime import MarketRegimeEngine
from project_titan_x.engines.e51_signals import SignalIntelligenceEngine

logger = logging.getLogger(__name__)
_OVERRIDE_DIR = Path(__file__).resolve().parents[1] / "data" / "models" / "e51_signals"
_OUT = Path(__file__).resolve().parents[1] / "data" / "models" / "e51_signals" / "live_best_signals.json"
TIMEFRAMES = ("1h", "4h", "1d")


def _validated_jobs(timeframes):
    """Every (asset, timeframe, override) with a real promoted override."""
    jobs = []
    for asset in list_assets():
        for tf in timeframes:
            path = _OVERRIDE_DIR / f"{asset.yahoo_symbol}_{tf}_strategy_override.json"
            if path.exists():
                jobs.append((asset, tf, json.loads(path.read_text(encoding="utf-8"))))
    return jobs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeframe", action="append", choices=TIMEFRAMES,
                        help="Restrict to one timeframe (repeatable). Default: all three.")
    parser.add_argument("--min-win-rate", type=float, default=0.0,
                        help="Only show setups whose validated win rate is at least this (e.g. 0.5).")
    parser.add_argument("--directional-only", action="store_true",
                        help="Hide assets that are currently flat.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(message)s")

    timeframes = tuple(args.timeframe) if args.timeframe else TIMEFRAMES

    md = MarketDataEngine(); md.initialize()
    ta = TechnicalAnalysisEngine(); ta.initialize()
    rg = MarketRegimeEngine(); rg.initialize()
    sig = SignalIntelligenceEngine(technical_engine=ta); sig.initialize()

    jobs = [j for j in _validated_jobs(timeframes) if j[2].get("win_rate", 0) >= args.min_win_rate]
    print(f"Scanning {len(jobs)} validated asset/timeframe setup(s)...\n")

    rows, flat = [], []
    for asset, tf, ovr in jobs:
        try:
            fetch = md.fetch_ohlcv(asset.yahoo_symbol, timeframe=tf, years=3)
            if not fetch.success:
                print(f"  {asset.symbol:11} {tf:3}  data unavailable"); continue
            df = fetch.data
            ta_res = ta.analyze(df, symbol=asset.symbol, timeframe=tf)
            if not ta_res.success:
                print(f"  {asset.symbol:11} {tf:3}  technical analysis failed"); continue
            snapshot, enriched = ta_res.data["snapshot"], ta_res.data["df"]
            regime = rg.classify(df, snapshot, None)
            result = sig.generate_signal(
                asset.symbol, df, snapshot, regime.data, 0.0, enriched_df=enriched
            )
            if result.success and result.data is not None:
                d = result.data
                rows.append({
                    "symbol": asset.symbol, "timeframe": tf, "direction": d.direction,
                    "confidence": d.confidence_score, "strategy": ovr["strategy"],
                    "params": ovr.get("params", {}), "win_rate": ovr["win_rate"],
                    "oos_sharpe": ovr.get("oos_sharpe"), "validated_trades": ovr.get("total_trades"),
                    "regime": getattr(d, "regime", None),
                    "expected_value_r": getattr(d, "expected_value", None),
                })
                print(f"  {asset.symbol:11} {tf:3}  {d.direction:5} conf={d.confidence_score:3}")
            else:
                flat.append(f"{asset.symbol} {tf}")
        except Exception as e:   # one bad asset must never end the scan
            print(f"  {asset.symbol:11} {tf:3}  ERROR {type(e).__name__}: {e}")

    rows.sort(key=lambda r: -(r["oos_sharpe"] or 0))

    print("\n" + "=" * 100)
    print("LIVE SIGNALS - validated setups only, ranked by proven out-of-sample expectancy")
    print("=" * 100)
    if rows:
        print(f"{'ASSET':11} {'TF':4} {'DIR':6} {'CONF':>5} {'WIN%':>6} {'OOS':>6} {'TRD':>5}  STRATEGY")
        for r in rows:
            print(f"{r['symbol']:11} {r['timeframe']:4} {r['direction']:6} {r['confidence']:>5} "
                  f"{r['win_rate']*100:>5.1f}% {r['oos_sharpe']:>6.2f} {r['validated_trades']:>5}  {r['strategy']}")
        low = [r for r in rows if r["win_rate"] < 0.5]
        if low:
            print(f"\n{len(low)} of these win FEWER than half their trades "
                  f"({', '.join(r['symbol'] + ' ' + r['timeframe'] for r in low)}).")
            print("That is normal for trend/breakout rules -- the edge is in outlier winners, "
                  "not hit rate. Size for the losing streaks, not the winners.")
    else:
        print("No validated setup is firing right now. That is a real answer, not a failure.")
    if flat and not args.directional_only:
        print(f"\nFlat (validated, but no directional bias right now): {', '.join(flat)}")

    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "signals": rows, "flat": flat,
    }, indent=2), encoding="utf-8")
    print(f"\nSaved to {_OUT}")


if __name__ == "__main__":
    main()
