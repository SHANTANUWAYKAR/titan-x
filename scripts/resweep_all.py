"""Re-run every sweep on the corrected asset-class trading calendar.

WHY THIS EXISTS. BARS_PER_YEAR was a single 24/7 table, so every instrument
that closes overnight was annualised against far too many bars -- an NYSE name
got 35,040 15m bars a year instead of 6,552, inflating its Sharpe by 2.31x.
`bars_per_year(timeframe, asset_class)` fixes it for new runs; this re-scores
the stored book so the leaderboard stops ranking on the old numbers.

The leaderboard ALREADY corrects stored rows in closed form (Sharpe scales by
sqrt(ppy_new/ppy_old) exactly), so this run is not what makes the ranking
honest -- that is already true. What a real re-sweep adds is everything the
algebra cannot reach: candidates are re-backtested against current data, so
trade counts, expectancy, drawdown and OOS splits are all recomputed rather
than inherited.

SAFETY. `promote_if_validated` is left at its default False, so nothing here
can tag a strategy live. Going live still needs a deliberate Stage 0 tag.

Sequential on purpose: a parallel run of this engine exhausted this machine's
memory (6 workers, 16GB) and left orphaned processes behind.

Resumable: progress is written after every sweep, and --resume skips whatever
already completed.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from project_titan_x.core.config import list_assets  # noqa: E402
from project_titan_x.engines.e24_strategy_research.engine import (  # noqa: E402
    StrategyResearchEngine,
)

PROGRESS = (
    ROOT / "project_titan_x" / "data" / "models"
    / "e24_strategy_research" / "_resweep_progress.json"
)
# Ordered by VALUE PER MINUTE OF COMPUTE, not by duration, because this run is
# long enough to be interrupted and whatever finished first should be the part
# worth having. 1d/4h/1h carry this platform's validated edges and every live
# override; they are also cheap, because a daily series is thousands of bars
# while a 5m forex series is millions (EURUSD 5m is 1,741,474 rows against
# 2,629 for its 1d). Sweeping 5m first -- as the original symbol-major ordering
# did -- spends hours before producing anything the leaderboard ranks on.
TIMEFRAMES = ["1d", "4h", "1h", "1wk", "30m", "15m", "5m", "1m"]


def load_progress():
    if PROGRESS.exists():
        try:
            return json.loads(PROGRESS.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"done": [], "failed": {}, "started": None}


def save(state):
    PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS.write_text(json.dumps(state, indent=2), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--resume", action="store_true", help="skip already-completed pairs")
    ap.add_argument("--years", type=int, default=10)
    ap.add_argument("--timeframes", default=",".join(TIMEFRAMES))
    ap.add_argument("--symbols", default="", help="optional comma-separated subset")
    args = ap.parse_args()

    logging.disable(logging.INFO)

    tfs = [t.strip() for t in args.timeframes.split(",") if t.strip()]
    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    else:
        symbols = [a.symbol for a in list_assets()]

    state = load_progress()
    if not args.resume:
        state = {"done": [], "failed": {}, "started": None}
    state["started"] = state.get("started") or datetime.now(timezone.utc).isoformat()
    done = set(tuple(x) for x in state["done"])

    engine = StrategyResearchEngine()
    try:
        engine.initialize()
    except Exception as e:
        print(f"engine.initialize() raised {e!r} -- continuing", flush=True)

    # Timeframe-major, not symbol-major: finish 1d across ALL assets before
    # starting 4h, so an interruption leaves complete timeframes rather than a
    # few fully-swept assets and nothing else.
    jobs = [(s, tf) for tf in tfs for s in symbols]
    todo = [j for j in jobs if tuple(j) not in done]
    print(
        f"re-sweep: {len(jobs)} pairs ({len(symbols)} assets x {len(tfs)} timeframes), "
        f"{len(todo)} to run, {len(jobs) - len(todo)} already done",
        flush=True,
    )

    t0 = time.time()
    for i, (sym, tf) in enumerate(todo, 1):
        started = time.time()
        try:
            r = engine.research(sym, tf, years=args.years)
            ok = bool(getattr(r, "success", False))
            n = len(getattr(getattr(r, "data", None), "candidates", []) or [])
            msg = f"{n} candidates" if ok else f"FAILED: {getattr(r, 'message', '?')}"
            if ok:
                state["done"].append([sym, tf])
                state["failed"].pop(f"{sym}_{tf}", None)
            else:
                state["failed"][f"{sym}_{tf}"] = str(getattr(r, "message", "?"))
        except Exception as e:  # noqa: BLE001 - one pair must not sink the run
            msg = f"RAISED: {e}"
            state["failed"][f"{sym}_{tf}"] = str(e)
        el = time.time() - started
        rate = (time.time() - t0) / i
        eta = rate * (len(todo) - i)
        print(
            f"[{i}/{len(todo)}] {sym} {tf}: {msg} ({el:.0f}s) "
            f"| elapsed {(time.time()-t0)/60:.0f}m eta {eta/60:.0f}m",
            flush=True,
        )
        save(state)

    save(state)
    print(
        f"\nre-sweep finished in {(time.time()-t0)/60:.1f} min · "
        f"{len(state['done'])} ok · {len(state['failed'])} failed",
        flush=True,
    )
    if state["failed"]:
        for k, v in list(state["failed"].items())[:10]:
            print(f"  failed {k}: {v}", flush=True)
    print("\nNow rebuild the leaderboard:", flush=True)
    print("  .venv/Scripts/python.exe scripts/build_strategy_leaderboard.py", flush=True)


if __name__ == "__main__":
    main()
