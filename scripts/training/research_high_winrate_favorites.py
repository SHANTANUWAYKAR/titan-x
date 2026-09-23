"""
Module: research_high_winrate_favorites.py
Description: Targeted search for a high-win-rate strategy across the
    user's stated favorite assets: GOLD, SILVER, BTCUSD, NIFTY50, and
    every USD-forex pair this platform supports (EURUSD, GBPUSD, USDJPY,
    USDINR).

    Round 2 (target lowered 80%->75%, two new archetypes added to
    e24_strategy_research/strategies.py specifically for this search):
      - bollinger_reversion_tuned: independently tunable band (period,
        std_mult) instead of e07_technical's fixed 20/2.0 columns.
      - rsi_mean_reversion_trend_filtered: classic "buy the dip in an
        uptrend / sell the rip in a downtrend" -- only takes RSI-oversold
        longs above the 200-day EMA and RSI-overbought shorts below it,
        a well-established way to raise a mean-reversion system's win
        rate by not fighting the dominant trend.

    Round 1 (previous run, see high_winrate_favorites_report.json) found
    NOTHING at 80%+ with real statistical backing across these 8 assets --
    every 80%+ hit had <30 trades and weak/negative Sharpe (noise, not
    edge). This round searches harder and asks for less (75%), but keeps
    E26's real validation bar completely intact -- never weakened, same
    discipline as every prior research run this project has done.
Author: Shantanu Waykar
Version: 1.0.0
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))

from project_titan_x.engines.e24_strategy_research.engine import StrategyResearchEngine

logger = logging.getLogger(__name__)

OUTPUT_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "e24_strategy_research" / "high_winrate_favorites_report_v2.json"

FAVORITE_ASSETS = ["GOLD", "SILVER", "BTCUSD", "NIFTY50", "EURUSD", "GBPUSD", "USDJPY", "USDINR"]

HIGH_WINRATE_GRID: dict[str, list[dict]] = {
    "rsi_mean_reversion": [
        {"oversold": os, "overbought": ob, "exit_level": ex}
        for os in (15, 20, 25, 30, 35, 40)
        for ob in (60, 65, 70, 75, 80, 85)
        for ex in (40, 45, 50, 55, 60)
        if os < ex < ob
    ],
    "rsi_mean_reversion_trend_filtered": [
        {"oversold": os, "overbought": ob, "exit_level": ex}
        for os in (20, 25, 30, 35, 40)
        for ob in (60, 65, 70, 75, 80)
        for ex in (45, 50, 55)
        if os < ex < ob
    ],
    "bollinger_reversion": [{}],
    "bollinger_reversion_tuned": [
        {"period": p, "std_mult": s} for p in (10, 14, 20, 30) for s in (1.0, 1.5, 2.0, 2.5, 3.0)
    ],
    "regime_adaptive": [{}],
    "donchian_breakout": [
        {"entry_n": n, "exit_n": m} for n in (10, 15, 20, 25, 30, 40) for m in (3, 5, 7, 10, 15)
    ],
}

WIN_RATE_TARGET = 0.75
WIN_RATE_REPORT_FLOOR = 0.65
MIN_TRADES_FOR_TARGET = 30  # E26's own real bar -- never weakened


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    engine = StrategyResearchEngine()
    engine.initialize()

    n_combos = sum(len(v) for v in HIGH_WINRATE_GRID.values())
    logger.info("Searching %d assets x %d combos = %d backtests...", len(FAVORITE_ASSETS), n_combos, len(FAVORITE_ASSETS) * n_combos)

    all_results: dict[str, dict] = {}
    for symbol in FAVORITE_ASSETS:
        logger.info("--- %s ---", symbol)
        result = engine.research(symbol, timeframe="1d", strategy_grid=HIGH_WINRATE_GRID, years=10, promote_if_validated=False)
        if not result.success:
            logger.warning("%s: %s", symbol, result.message)
            all_results[symbol] = {"error": result.message}
            continue
        report = result.data
        high_wr = sorted(
            [c for c in report.candidates if c.win_rate >= WIN_RATE_REPORT_FLOOR],
            key=lambda c: (-c.passed_validation, -c.win_rate),
        )
        real_hits = [c for c in high_wr if c.win_rate >= WIN_RATE_TARGET and c.passed_validation]
        logger.info(
            "%s: %d/%d passed full validation. %d candidate(s) with win_rate>=%.0f%%. REAL 75%%+ hits: %d",
            symbol, len(report.passed), report.n_candidates, len(high_wr), WIN_RATE_REPORT_FLOOR * 100, len(real_hits),
        )
        all_results[symbol] = {
            "n_candidates": report.n_candidates,
            "n_passed_full_validation": len(report.passed),
            "high_winrate_candidates": [c.to_dict() for c in high_wr],
            "real_75pct_hits": [c.to_dict() for c in real_hits],
        }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "assets": FAVORITE_ASSETS,
        "win_rate_target": WIN_RATE_TARGET,
        "validation_bar": "IS trades>=30, IS Sharpe>0.5, max DD<25%, OOS Sharpe>0 (E26 Backtesting Laboratory) -- never weakened",
        "results": all_results,
    }
    OUTPUT_PATH.write_text(json.dumps(summary, indent=2))

    print(f"\n{'='*115}")
    print(f"Target: win_rate >= {WIN_RATE_TARGET:.0%} AND real validated edge (>=30 trades, Sharpe/DD bar), across {FAVORITE_ASSETS}")
    print(f"{'='*115}")
    any_real_hit = False
    for symbol, r in all_results.items():
        if "error" in r:
            print(f"{symbol}: ERROR -- {r['error']}")
            continue
        real_hits = r["real_75pct_hits"]
        if real_hits:
            any_real_hit = True
            print(f"\n{symbol}: REAL VALIDATED 75%+ HIT(S):")
            for c in real_hits:
                print(f"   {c['strategy']:<28} {c['params']!s:<36} win_rate={c['win_rate']*100:>5.1f}%  IS Sharpe={c['is_sharpe']:>6.2f}  OOS Sharpe={c['oos_sharpe']:>6.2f}  trades={c['is_trades']}")
        else:
            top = r["high_winrate_candidates"][:2]
            if top:
                print(f"\n{symbol}: no real 75%+ hit. Closest (unvalidated) candidates:")
                for c in top:
                    print(f"   {c['strategy']:<28} {c['params']!s:<36} win_rate={c['win_rate']*100:>5.1f}%  IS Sharpe={c['is_sharpe']:>6.2f}  OOS Sharpe={c['oos_sharpe']:>6.2f}  trades={c['is_trades']}  NOT VALIDATED")
            else:
                print(f"\n{symbol}: nothing reached even {WIN_RATE_REPORT_FLOOR:.0%} win rate out of {r['n_candidates']} tested.")

    print(f"\n{'='*115}")
    if not any_real_hit:
        print(f"Honest result: no candidate across these 8 assets reached {WIN_RATE_TARGET:.0%} win rate AND cleared full validation.")
    print(f"Full report saved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
