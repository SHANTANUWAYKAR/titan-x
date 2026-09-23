"""
Module: promote_survey_winners.py
Description: Write strategy_override.json files from an already-completed
    set_best_strategy_per_pair.py survey, without re-running the search.

    WHY THIS EXISTS. set_best_strategy_per_pair.py was run with
    --no-promote (deliberately: a 116-job sweep writing ~70 live-candidate
    override files unreviewed is not something to do by default). Getting
    those winners in front of the Stage 0 scorer would otherwise mean
    re-running the entire hour-long sweep purely to flip one flag, since
    research/score_overrides_stage0.py scores override FILES, not search
    results. This reads the survey JSON the sweep already wrote and emits
    the same override format e24's own _promote() writes -- identical
    fields, same directory -- so the scorer and tagger can then run
    unchanged.

    ONLY writes timeframes that have a real synthetic null (1h/4h/1d).
    A 15m "winner" cannot be scored against noise at all (no
    synthetic_null_GCF_15m.json exists), and the survey found one on 29 of
    29 pairs at 15m -- a 100% hit rate on the one timeframe that can't be
    checked is the signature of a 723-candidate grid fitting randomness,
    not 29 real edges. Promoting those would put unvalidatable rules in
    the same directory as validated ones, which is exactly the "unearned
    confidence" the Stage 0 gate exists to prevent.

    Writing an override here does NOT put anything live.
    e51_signals._load_strategy_override is deny-by-default: a file with no
    explicit `"stage0": {"status": "VALIDATED"}` tag is inert. The real
    sequence is:

        python scripts/promote_survey_winners.py
        python research/score_overrides_stage0.py --bars 12000 --workers 6
        python scripts/apply_stage0_tags.py

    Step 1 (this script) only makes the candidates visible to step 2.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from project_titan_x.core.config import get_asset  # noqa: E402
from project_titan_x.engines.e24_strategy_research.engine import PROMOTABLE_STRATEGIES  # noqa: E402

SURVEY_PATH = (
    Path(__file__).resolve().parents[1]
    / "data" / "models" / "e24_strategy_research" / "best_strategy_per_pair.json"
)
OVERRIDE_DIR = Path(__file__).resolve().parents[1] / "data" / "models" / "e51_signals"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Show what would be written, write nothing.")
    args = ap.parse_args()

    survey = json.loads(SURVEY_PATH.read_text(encoding="utf-8"))
    winners = [
        r for r in survey["results"]
        if r.get("best") and r.get("null_available")
    ]

    written, skipped = [], []
    for r in winners:
        b = r["best"]
        if b["strategy"] not in PROMOTABLE_STRATEGIES:
            skipped.append((r["pair"], r["timeframe"], b["strategy"], "not a promotable archetype"))
            continue
        asset = get_asset(r["pair"])
        if asset is None:
            skipped.append((r["pair"], r["timeframe"], b["strategy"], "unknown asset"))
            continue

        path = OVERRIDE_DIR / f"{asset.yahoo_symbol}_{r['timeframe']}_strategy_override.json"
        # Same field set e24's own _promote() writes -- deliberately
        # identical so the scorer, the tagger, and e51_signals all read
        # this exactly as they read a normally-promoted file.
        override = {
            "strategy": b["strategy"],
            "params": b["params"],
            "win_rate": round(b["win_rate"], 3),
            "is_sharpe": round(b["is_sharpe"], 2),
            "oos_sharpe": round(b["oos_sharpe"], 2),
            "max_drawdown_pct": round(b["is_max_dd"], 1),
            "total_trades": b["is_trades"],
            "min_confidence": round(b["win_rate"] * 100),
            "validated_at": datetime.now(timezone.utc).isoformat(),
            "source": "scripts/promote_survey_winners.py (from set_best_strategy_per_pair.py survey)",
            "note": (
                f"{b['strategy']}{b['params']} was the best candidate for {r['pair']} "
                f"{r['timeframe']} in the style survey (IS Sharpe={b['is_sharpe']:.2f}, "
                f"OOS Sharpe={b['oos_sharpe']:.2f}, {b['is_trades']} trades, "
                f"{b['win_rate']:.1%} win rate, expectancy={b['expectancy']:.3f}). "
                "SEARCH RESULT ONLY -- not yet scored against the synthetic no-edge null. "
                "Inert until scripts/apply_stage0_tags.py writes a VALIDATED tag."
            ),
        }
        if args.dry_run:
            written.append((r["pair"], r["timeframe"], b["strategy"], "would write"))
        else:
            OVERRIDE_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(override, indent=2), encoding="utf-8")
            written.append((r["pair"], r["timeframe"], b["strategy"], path.name))

    mode = "DRY RUN -- nothing written" if args.dry_run else "WRITTEN"
    print(f"Promote survey winners ({mode})")
    print(f"  survey winners on null-backed timeframes: {len(winners)}")
    print(f"  written: {len(written)} | skipped: {len(skipped)}")
    for pair, tf, strat, note in written:
        print(f"    {pair:10} {tf:3} {strat[:40]:42} {note}")
    for pair, tf, strat, why in skipped:
        print(f"    SKIP {pair:10} {tf:3} {strat[:40]:42} {why}")
    print()
    print("  These are INERT. Next:")
    print("    python research/score_overrides_stage0.py --bars 12000 --workers 6")
    print("    python scripts/apply_stage0_tags.py")


if __name__ == "__main__":
    main()
