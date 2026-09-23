"""
Module: run_pdf_backtest.py
Description: Grades the 8 archetypes distilled from data/strategy/*.pdf
    against E26's real, unweakened validation bar, per pair.

    A NOTE ON TIMEFRAME THAT BOUNDS EVERY RESULT HERE. The corpus is
    overwhelmingly intraday: counting explicit mentions across the 71
    documents gives 5-minute 33, 15-minute 28, 1-minute 23, against daily
    14. These are, as written, intraday strategies.

    This platform can only fetch 60 days of 5m/15m history and 7 days of
    1m (Yahoo's cap). A 60-day sample is one market regime, and Sharpe on
    fine timeframes is annualised by up to 725x, which is exactly how the
    earlier 8-timeframe sweep produced OOS Sharpes of 40 that turned out
    to be arithmetic rather than edge.

    So each archetype is graded at BOTH:
      - its intended intraday timeframe (15m), flagged as short-history
      - 1h and 4h, where 730 days of real history exist
    and the two are reported separately rather than pooled. A result that
    only appears on 60 days of 15m data is reported as such, not as a
    validated edge.

    RESEARCH CODE. Registers each archetype temporarily and removes it in
    a finally block; the live registry is unchanged. Never promotes.
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

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
warnings.filterwarnings("ignore")

from project_titan_x.engines.e24_strategy_research import strategies as strategies_mod
from project_titan_x.engines.e24_strategy_research.engine import StrategyResearchEngine
from project_titan_x.research.pdf_strategies import PDF_STRATEGIES

SYMBOLS = ("GOLD", "SILVER", "BTCUSD", "ETHUSD", "EURUSD", "GBPUSD", "USDJPY")

# Parameter grids reflecting the ranges the documents actually state:
# EMA pairs 9/15, 9/20, 5/20; R:R 1:2 and 1:3 (47 and 41 mentions).
GRIDS: dict[str, list[dict]] = {
    "ema_cross_pullback": [{"fast": f, "slow": s, "rr": r}
                           for f, s in ((9, 15), (9, 20), (5, 20)) for r in (2.0, 3.0)],
    "ema_retest": [{"period": p, "rr": r} for p in (9, 20) for r in (1.0, 2.0)],
    "ema_stack_trend": [{"fast": 9, "mid": 20, "slow": 50}],
    "session_sweep_bos": [{"session_start": 0, "session_end": 7, "rr": r} for r in (2.0, 3.0)],
    "opening_range_breakout": [{"or_bars": n, "rr": r} for n in (3, 6) for r in (2.0, 3.0)],
    "vwap_reversion": [{"stretch_atr": a, "rr": r} for a in (1.5, 2.0) for r in (2.0, 3.0)],
    "fib_retracement_entry": [{"lookback": n, "rr": r} for n in (30, 50) for r in (2.0, 3.0)],
    "big_candle_continuation": [{"body_atr": a, "rr": r} for a in (1.2, 1.5, 2.0) for r in (2.0, 3.0)],
}
SHORT_HISTORY = {"15m", "5m", "1m"}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--timeframes", default="4h,1h,15m")
    p.add_argument("--symbols", default=",".join(SYMBOLS))
    args = p.parse_args()
    timeframes = [t.strip() for t in args.timeframes.split(",") if t.strip()]
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    engine = StrategyResearchEngine()
    engine.initialize()
    for name, fn in PDF_STRATEGIES.items():
        strategies_mod.STRATEGIES[name] = fn

    out: dict = {}
    try:
        n_cfg = sum(len(v) for v in GRIDS.values())
        print(f"Grading {len(PDF_STRATEGIES)} PDF archetypes ({n_cfg} configs) "
              f"x {len(symbols)} symbols x {len(timeframes)} timeframes\n")
        for tf in timeframes:
            flag = "  [SHORT HISTORY -- 60d sample, treat as a lead only]" if tf in SHORT_HISTORY else ""
            print(f"===== {tf}{flag} =====")
            print(f"{'ASSET':8} {'PASSED':>9} {'EXPECT':>8} {'R:R':>6} {'WIN%':>6} {'OOS':>6} {'TRD':>5}  BEST ARCHETYPE")
            for sym in symbols:
                try:
                    r = engine.research(sym, timeframe=tf, strategy_grid=GRIDS,
                                        years=10, promote_if_validated=False)
                except Exception as e:
                    print(f"{sym:8}   ERROR {type(e).__name__}: {str(e)[:44]}")
                    continue
                if not r.success:
                    print(f"{sym:8}   {r.message[:60]}")
                    continue
                best, n = r.data.best, r.data.n_candidates
                key = f"{sym}_{tf}"
                if not best:
                    print(f"{sym:8} {'0/' + str(n):>9}   -- nothing cleared the bar")
                    out[key] = None
                    continue
                rr = abs(best.avg_win_r / best.avg_loss_r) if best.avg_loss_r else 0.0
                print(f"{sym:8} {str(len(r.data.passed)) + '/' + str(n):>9} {best.expectancy:>8.2f} "
                      f"{rr:>5.2f}R {best.win_rate * 100:>5.1f}% {best.oos_sharpe:>6.2f} "
                      f"{best.is_trades:>5}  {best.strategy} {best.params}")
                out[key] = {**best.to_dict(), "reward_risk": round(rr, 3),
                            "short_history": tf in SHORT_HISTORY,
                            "n_passed": len(r.data.passed)}
            print()
    finally:
        for name in PDF_STRATEGIES:
            strategies_mod.STRATEGIES.pop(name, None)

    reliable = [k for k, v in out.items() if v and not v["short_history"]]
    short = [k for k, v in out.items() if v and v["short_history"]]
    print("=" * 88)
    print(f"validated on RELIABLE history (1h/4h): {len(reliable)}")
    print(f"validated on SHORT history only (15m): {len(short)} -- leads, not edges")

    dest = Path(__file__).resolve().parent / "pdf_backtest_results.json"
    dest.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(),
                                "results": out}, indent=2), encoding="utf-8")
    print(f"\nSaved to {dest}")


if __name__ == "__main__":
    main()
