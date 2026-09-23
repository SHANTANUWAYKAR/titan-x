"""
Module: block_bootstrap_analysis.py
Description: Runs the block-bootstrap OOS Sharpe distribution (see
    engines/e26_backtesting/block_bootstrap.py) against ONE real,
    already-chosen live override's strategy+params -- docs/UPGRADE_BRIEF.md
    Phase 7 item 3, reconciled per docs/PROJECT_AUDIT.md section 11.

    Distinct from pbo_analysis.py: PBO asks whether the ENTIRE grid-search
    process tends to overfit; this asks whether ONE already-selected
    strategy shows a genuinely positive, consistent OOS Sharpe DISTRIBUTION
    across many resamplings of its own independent historical blocks, rather
    than the single 80/20 split run_backtest's own validation used to select
    it. Originally scoped as literal CPCV (see block_bootstrap.py's own
    docstring for why that was tried on real data and abandoned -- every
    reconstructed path came back identical, since nothing here gets re-fit).

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
from project_titan_x.engines.e24_strategy_research.strategies import STRATEGIES  # noqa: E402
from project_titan_x.engines.e26_backtesting.block_bootstrap import (  # noqa: E402
    block_bootstrap_validation,
)
from project_titan_x.engines.e26_backtesting.engine import BacktestingEngine  # noqa: E402

OUT = Path(__file__).resolve().parent
OVERRIDES = ROOT / "project_titan_x" / "data" / "models" / "e51_signals"


def run(symbol: str, timeframe: str, n_blocks: int, n_bootstrap: int,
        strategy: str = "", params_json: str = "") -> dict:
    if strategy:
        strat_name, params = strategy, json.loads(params_json) if params_json else {}
    else:
        override_path = OVERRIDES / f"{symbol}_{timeframe}_strategy_override.json"
        if not override_path.exists():
            raise SystemExit(f"no override at {override_path} -- pass --strategy/--params explicitly")
        ov = json.loads(override_path.read_text(encoding="utf-8"))
        strat_name, params = ov["strategy"], ov.get("params", ov.get("parameters", {}))

    strat_fn_factory = STRATEGIES.get(strat_name)
    if strat_fn_factory is None:
        raise SystemExit(f"unknown strategy {strat_name!r}; known: {sorted(STRATEGIES)}")

    market = MarketDataEngine()
    market.initialize()
    df_result = market.fetch_ohlcv(symbol, timeframe)
    if not df_result.success:
        raise SystemExit(f"could not fetch {symbol} {timeframe}: {df_result.message}")
    df = df_result.data.reset_index(drop=True)

    ta = TechnicalAnalysisEngine()
    ta.initialize()
    enriched = ta.analyze(df).data["df"]

    full_signal = strat_fn_factory(enriched, **params)

    def strategy_fn(_df, _signal=full_signal):
        return _signal.loc[_df.index]

    backtesting_engine = BacktestingEngine()
    backtesting_engine.initialize()

    print(f"Block-bootstrap analysis: {symbol} {timeframe} -- {strat_name}{params} on "
          f"{len(enriched)} bars, n_blocks={n_blocks}, n_bootstrap={n_bootstrap}")

    report = block_bootstrap_validation(
        enriched, strategy_fn, backtesting_engine,
        n_blocks=n_blocks, n_bootstrap=n_bootstrap, seed=0,
    )

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol, "timeframe": timeframe,
        "strategy": strat_name, "params": params,
        "n_bars": report.n_bars, "n_blocks": report.n_blocks, "n_bootstrap": report.n_bootstrap,
        "error": report.error,
        "block_sharpes": report.block_sharpes,
        "mean_sharpe": report.mean_sharpe, "median_sharpe": report.median_sharpe,
        "std_sharpe": report.std_sharpe, "pct_draws_positive": report.pct_draws_positive,
        "p05_sharpe": report.p05_sharpe, "p95_sharpe": report.p95_sharpe,
        "caveats": report.caveats,
    }
    dest = OUT / f"block_bootstrap_{symbol.replace('=', '')}_{timeframe}.json"
    dest.write_text(json.dumps(result, indent=2), encoding="utf-8")

    if report.error:
        print(f"ERROR: {report.error}")
    else:
        print(f"\n{report.n_blocks} independent blocks: {report.block_sharpes}")
        print(f"{report.n_bootstrap} bootstrap draws:")
        print(f"mean Sharpe = {report.mean_sharpe}  median = {report.median_sharpe}  "
              f"std = {report.std_sharpe}")
        print(f"{report.pct_draws_positive}% of draws positive  "
              f"[p05={report.p05_sharpe}, p95={report.p95_sharpe}]")
    print(f"Saved to {dest}")
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbol", default="BTC-USD")
    ap.add_argument("--timeframe", default="1d")
    ap.add_argument("--n-blocks", type=int, default=6)
    ap.add_argument("--n-bootstrap", type=int, default=1000)
    ap.add_argument("--strategy", default="", help="override the on-disk *_strategy_override.json lookup")
    ap.add_argument("--params", default="", help="JSON dict, required if --strategy is set")
    args = ap.parse_args()
    run(args.symbol, args.timeframe, args.n_blocks, args.n_bootstrap, args.strategy, args.params)


if __name__ == "__main__":
    main()
