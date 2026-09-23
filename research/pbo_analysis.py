"""
Module: pbo_analysis.py
Description: Runs Probability of Backtest Overfitting (PBO, see
    engines/e26_backtesting/pbo.py) against a REAL E24 strategy grid for
    one asset/timeframe -- REPO_REFERENCE.md Tier 1 (purgedcv).

    Reuses `e24_strategy_research.engine._run_one_candidate_worker` with
    `capture_returns=True` directly (the same worker `research()` itself
    calls, and the same one research/synthetic_null.py already uses for
    its own effective-rank calculation) rather than a second, parallel
    grid-search implementation. `research()`'s own public signature does
    not expose `capture_returns` -- it is an internal opt-in only the
    Stage 0 tooling has needed until now.

    REPORT ONLY. Writes a JSON report; does not touch any
    *_strategy_override.json file, promote anything, or gate anything.

    RESEARCH CODE. Imports engines/, never the reverse.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
warnings.filterwarnings("ignore")

from project_titan_x.engines.e02_market_data.engine import MarketDataEngine  # noqa: E402
from project_titan_x.engines.e07_technical import TechnicalAnalysisEngine  # noqa: E402
from project_titan_x.engines.e24_strategy_research.engine import (  # noqa: E402
    DEFAULT_STRATEGY_GRID, _run_one_candidate_worker,
)
from project_titan_x.engines.e26_backtesting.pbo import (  # noqa: E402
    probability_of_backtest_overfitting,
)

OUT = Path(__file__).resolve().parent


def run(symbol: str, timeframe: str, n_splits: int, strategies: str = "") -> dict:
    market = MarketDataEngine()
    market.initialize()
    df_result = market.fetch_ohlcv(symbol, timeframe)
    if not df_result.success:
        raise SystemExit(f"could not fetch {symbol} {timeframe}: {df_result.message}")
    df = df_result.data.reset_index(drop=True)

    ta = TechnicalAnalysisEngine()
    ta.initialize()
    enriched = ta.analyze(df).data["df"]

    grid = DEFAULT_STRATEGY_GRID
    if strategies:
        want = {s.strip() for s in strategies.split(",") if s.strip()}
        grid = {k: v for k, v in grid.items() if k in want}

    candidates = []
    for strat, plist in grid.items():
        for params in plist:
            candidates.append((strat, params))
    print(f"PBO analysis: {symbol} {timeframe} -- {len(candidates)} real candidates, "
          f"n_splits={n_splits}")

    streams, meta = [], []
    for i, (strat, params) in enumerate(candidates):
        r = _run_one_candidate_worker(enriched, strat, params, None, 252.0,
                                       0.0005, 0.0002, capture_returns=True)
        if r is None:
            streams.append(None)
        else:
            streams.append(r.get("bar_returns"))
            meta.append({"strategy": strat, "params": params,
                         "is_sharpe": r["is_sharpe"], "oos_sharpe": r["oos_sharpe"],
                         "passed_validation": r["passed_validation"]})
        if (i + 1) % 20 == 0:
            print(f"  {i + 1}/{len(candidates)} candidates run")

    report = probability_of_backtest_overfitting(streams, n_splits=n_splits)
    n_passed = sum(1 for m in meta if m["passed_validation"])

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol, "timeframe": timeframe,
        "n_candidates": len(candidates), "n_passed_e26_bar": n_passed,
        "pbo_n_configs_used": report.n_configs_used,
        "pbo_n_configs_dropped": report.n_configs_dropped,
        "pbo_n_splits": report.n_splits, "pbo_n_combos": report.n_combos,
        "pbo": report.pbo, "slope": report.slope, "caveats": report.caveats,
    }
    dest = OUT / f"pbo_{symbol.replace('=', '')}_{timeframe}.json"
    dest.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(f"\n{len(candidates)} candidates ({n_passed} passed E26's bar), "
          f"{report.n_configs_used} usable return streams")
    print(f"PBO = {report.pbo:.3f}  (0=no overfit, 0.5=chance, 1=always overfit)")
    print(f"slope = {report.slope:.3f}  (>0 = IS strength carries to OOS, <0 = predicts OOS weakness)")
    print(f"Saved to {dest}")
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbol", default="BTC-USD")
    ap.add_argument("--timeframe", default="1d")
    ap.add_argument("--n-splits", type=int, default=16)
    ap.add_argument("--strategies", default="")
    args = ap.parse_args()
    run(args.symbol, args.timeframe, args.n_splits, args.strategies)


if __name__ == "__main__":
    main()
