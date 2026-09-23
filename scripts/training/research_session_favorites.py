"""
Module: research_session_favorites.py
Description: Session-filtered strategy search across the user's favorite
    assets (GOLD, SILVER, BTCUSD, NIFTY50, EURUSD, GBPUSD, USDJPY, USDINR),
    restricted to their actual trading window: 06:30-09:30 IST, tested
    across every timeframe yfinance can serve intraday (1m, 5m, 15m, 30m,
    1h, 4h).

    Uses e24_strategy_research's new session_window param (strategies.
    session_mask/apply_session_filter, added this session): forces every
    candidate's signal to flat outside the window, so a position can only
    be opened/held during 06:30-09:30 IST and is automatically closed the
    moment the window ends -- never carried overnight/cross-session.

    Honest, known limitations, stated up front rather than discovered
    silently in the results:
      - NIFTY50's regular session starts 09:15 IST -- only the LAST 15
        minutes of the requested window actually overlap real trading
        hours. Expect thin/sparse data for NIFTY50 specifically.
      - yfinance's own intraday history caps (YFINANCE_PERIOD): 1m->7d,
        5m/15m/30m->60d, 1h/4h->730d. 7-60 days of real history, filtered
        down to a 3-hour daily window, is a small sample -- E26's real
        30-trade minimum will likely NOT be reached at 1m/5m/15m for many
        assets. Reported as insufficient_data honestly, not padded.
      - E26's Sharpe is computed from the full bar-by-bar equity curve,
        not per-trade returns -- for a sparse, mostly-flat (session-
        filtered) signal this can produce large/unstable Sharpe values.
        win_rate and trade count are the more directly interpretable
        numbers here; Sharpe is still used for the real pass/fail bar
        (unchanged, never weakened) but read the win_rate/trades columns
        primarily.
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

OUTPUT_PATH = Path(__file__).resolve().parents[2] / "data" / "models" / "e24_strategy_research" / "session_favorites_report.json"

FAVORITE_ASSETS = ["GOLD", "SILVER", "BTCUSD", "NIFTY50", "EURUSD", "GBPUSD", "USDJPY", "USDINR"]
TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h"]
SESSION_WINDOW = ("06:30", "09:30")
SESSION_TZ = "Asia/Kolkata"

# yfinance's own real intraday history caps (YFINANCE_PERIOD in
# e02_market_data/engine.py) -- requesting more `years` than a timeframe
# actually has doesn't error, fetch_ohlcv just returns whatever real
# history exists. `years=1` is enough to not under-ask for any of these.
YEARS = 1

GRID: dict[str, list[dict]] = {
    "rsi_mean_reversion": [
        {"oversold": os, "overbought": ob, "exit_level": ex}
        for os in (20, 25, 30, 35)
        for ob in (65, 70, 75, 80)
        for ex in (45, 50, 55)
        if os < ex < ob
    ],
    "rsi_mean_reversion_trend_filtered": [
        {"oversold": os, "overbought": ob, "exit_level": 50}
        for os in (25, 30, 35)
        for ob in (65, 70, 75)
    ],
    "donchian_breakout": [
        {"entry_n": n, "exit_n": m} for n in (10, 15, 20, 30) for m in (3, 5, 10)
    ],
    "bollinger_reversion_tuned": [
        {"period": p, "std_mult": s} for p in (14, 20) for s in (1.5, 2.0, 2.5)
    ],
    "bollinger_reversion": [{}],
    "regime_adaptive": [{}],
}

WIN_RATE_TARGET = 0.70


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    engine = StrategyResearchEngine()
    engine.initialize()

    n_combos = sum(len(v) for v in GRID.values())
    total = len(FAVORITE_ASSETS) * len(TIMEFRAMES) * n_combos
    logger.info(
        "Searching %d assets x %d timeframes x %d combos = %d backtests, session %s-%s %s...",
        len(FAVORITE_ASSETS), len(TIMEFRAMES), n_combos, total, *SESSION_WINDOW, SESSION_TZ,
    )

    all_results: dict[str, dict] = {}
    for symbol in FAVORITE_ASSETS:
        all_results[symbol] = {}
        for tf in TIMEFRAMES:
            logger.info("--- %s @ %s ---", symbol, tf)
            result = engine.research(
                symbol, timeframe=tf, strategy_grid=GRID, years=YEARS,
                session_window=SESSION_WINDOW, session_tz=SESSION_TZ, promote_if_validated=False,
            )
            if not result.success:
                logger.warning("%s @ %s: %s", symbol, tf, result.message)
                all_results[symbol][tf] = {"error": result.message}
                continue
            report = result.data
            real_hits = [c for c in report.passed if c.win_rate >= WIN_RATE_TARGET]
            best_by_winrate = max(report.candidates, key=lambda c: c.win_rate) if report.candidates else None
            logger.info(
                "%s @ %s: %d candidates, %d passed validation, %d real >=%.0f%% win-rate hits. Best win_rate seen: %s",
                symbol, tf, report.n_candidates, len(report.passed), len(real_hits), WIN_RATE_TARGET * 100,
                f"{best_by_winrate.win_rate*100:.1f}%" if best_by_winrate else "n/a",
            )
            all_results[symbol][tf] = {
                "n_candidates": report.n_candidates,
                "n_passed": len(report.passed),
                "real_hits": [c.to_dict() for c in real_hits],
                "best_by_winrate": best_by_winrate.to_dict() if best_by_winrate else None,
            }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "assets": FAVORITE_ASSETS,
        "timeframes": TIMEFRAMES,
        "session_window": SESSION_WINDOW,
        "session_tz": SESSION_TZ,
        "win_rate_target": WIN_RATE_TARGET,
        "validation_bar": "IS trades>=30, IS Sharpe>0.5, max DD<25%, OOS Sharpe>0 (E26 Backtesting Laboratory) -- never weakened",
        "results": all_results,
    }
    OUTPUT_PATH.write_text(json.dumps(summary, indent=2))

    print(f"\n{'='*120}")
    print(f"Session {SESSION_WINDOW[0]}-{SESSION_WINDOW[1]} {SESSION_TZ} -- real validated {WIN_RATE_TARGET:.0%}+ win-rate hits:")
    print(f"{'='*120}")
    any_hit = False
    for symbol, by_tf in all_results.items():
        for tf, r in by_tf.items():
            if "error" in r:
                continue
            for c in r["real_hits"]:
                any_hit = True
                print(f"{symbol:<10} {tf:<5} {c['strategy']:<28} {c['params']!s:<32} win_rate={c['win_rate']*100:>5.1f}%  IS Sharpe={c['is_sharpe']:>7.2f}  OOS Sharpe={c['oos_sharpe']:>7.2f}  trades={c['is_trades']}")
    if not any_hit:
        print("None. Full per-asset/timeframe breakdown (including near-misses and honest data gaps) below and in the saved report.")

    print(f"\n{'-'*120}\nFull breakdown (best win_rate seen per asset/timeframe, whether validated or not):\n{'-'*120}")
    for symbol, by_tf in all_results.items():
        for tf, r in by_tf.items():
            if "error" in r:
                print(f"{symbol:<10} {tf:<5} DATA GAP: {r['error']}")
                continue
            b = r["best_by_winrate"]
            if b is None:
                print(f"{symbol:<10} {tf:<5} no candidates computed")
                continue
            print(f"{symbol:<10} {tf:<5} best win_rate: {b['strategy']:<28} {b['params']!s:<28} win_rate={b['win_rate']*100:>5.1f}%  trades={b['is_trades']:>4}  passed={b['passed_validation']}")

    print(f"\nFull report saved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
