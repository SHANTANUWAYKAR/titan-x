"""
Module: apply_stage0_tags.py
Description: Tag every live e51_signals strategy override with its Stage 0
    verdict -- VALIDATED or UNVALIDATED -- against the timeframe-aware bar
    measured in docs/STAGE0_FINDINGS.md.

    TAGGING, NOT DELETING. Nothing is removed and no file is rewritten from
    scratch: a `stage0` block is added alongside the existing keys, which are
    neither reordered nor altered. A tag is reversible with `git checkout` and
    auditable in a diff; a deletion is neither, and a demotion that silently
    removed 43 of 45 overrides would be indistinguishable from a bug that ate
    them.

    THE BAR (see engines/e26_backtesting/engine.py STAGE0_TIMEFRAME_THRESHOLDS):
      null percentile >= 95 at the override's own timeframe, AND >= 60 trades.
    The percentile is computed against ALL 150 null paths, counting paths where
    noise produced no passing candidate at all as paths the override beat.

    IDEMPOTENT. Re-running overwrites the `stage0` block with the same verdict
    from the same scores file. Use --dry-run to see the diff first.

Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

OVERRIDES = ROOT / "data" / "models" / "e51_signals"
SCORES = ROOT / "research" / "stage0_override_scores.json"

MIN_NULL_PCT = 95.0
MIN_TRADES = 60


def _audit_deployment(**kw) -> None:
    """Best-effort deployment audit. Never raises: a missing audit line is bad,
    but a tagging run dying halfway -- leaving some overrides tagged and others
    not -- is worse."""
    try:
        from project_titan_x.core import experiment as _ex
        _ex.record_deployment_change(**kw)
    except Exception as e:  # noqa: BLE001
        print(f"  (warning: could not audit deployment change: {e})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="report, write nothing")
    args = ap.parse_args()

    if not SCORES.exists():
        raise SystemExit(f"missing {SCORES} -- run research/score_overrides_stage0.py first")
    rows = json.loads(SCORES.read_text(encoding="utf-8"))["rows"]
    by_stem = {r["override"]: r for r in rows}

    files = sorted(OVERRIDES.glob("*_strategy_override.json"))
    if not files:
        raise SystemExit(f"no override files under {OVERRIDES}")

    validated, unvalidated, skipped = [], [], []
    for f in files:
        stem = f.name.replace("_strategy_override.json", "")
        r = by_stem.get(stem)
        if r is None or "dsr" not in r:
            skipped.append(stem)
            continue

        pct = r.get("null_percentile")
        trades = r.get("trades")
        passes = (pct is not None and pct >= MIN_NULL_PCT and trades >= MIN_TRADES)
        reasons = []
        if pct is None:
            reasons.append("no null available for this timeframe")
        elif pct < MIN_NULL_PCT:
            reasons.append(f"null percentile {pct:.1f} < {MIN_NULL_PCT}")
        if trades < MIN_TRADES:
            reasons.append(f"{trades} trades < {MIN_TRADES}")

        block = {
            "status": "VALIDATED" if passes else "UNVALIDATED",
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "bar": {"min_null_percentile": MIN_NULL_PCT, "min_trades": MIN_TRADES},
            "measured": {
                "timeframe": r.get("timeframe"),
                "selection_score": round(min(r["raw_sharpe"], r["oos_sharpe"]), 4),
                "is_sharpe": r["raw_sharpe"],
                "oos_sharpe": r["oos_sharpe"],
                "trades": trades,
                "null_percentile": pct,
                "null_source": r.get("null_source"),
                "null_is_proxy": r.get("null_is_proxy"),
                "n_effective": r.get("n_effective"),
            },
            # Reported, never gated. DSR is computed on IS Sharpe alone and so
            # cannot see IS->OOS decay; on this book it ranks almost inversely
            # to the null percentile. Kept for diagnosis, not for decisions.
            "dsr_diagnostic": r.get("dsr"),
            "reasons": reasons or None,
            "caveats": [
                "The 60-trade floor is convention-derived, not measured: the null "
                "campaigns do not record per-candidate trade counts.",
                "Null is gold (GC=F) at this timeframe -- a CROSS-ASSET PROXY for "
                "every symbol except GC=F itself.",
                "Percentiles are not comparable across timeframes.",
            ],
            "reversible": "Remove this block or run git checkout to restore prior behaviour.",
        }

        doc = json.loads(f.read_text(encoding="utf-8"))
        previous_status = (doc.get("stage0") or {}).get("status")
        doc["stage0"] = block
        (validated if passes else unvalidated).append(stem)
        if not args.dry_run:
            f.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")

            # Audit the DEPLOYMENT change (PHASE 26), not just the file write.
            # A stage0 tag is the single thing standing between a search result
            # and real money; flipping one used to leave no record at all, so
            # "when did this go live, and on what evidence" -- the question
            # worth asking after a loss -- had no answer anywhere.
            symbol, _, tf = stem.rpartition("_")
            _audit_deployment(
                symbol=symbol, timeframe=tf, strategy=doc.get("strategy") or "unknown",
                previous_status=previous_status, new_status=block["status"],
                reason=(", ".join(reasons) if reasons else
                        f"null percentile {r.get('null_percentile')} vs bar {MIN_NULL_PCT}"),
                evidence=block.get("measured") or {},
            )

    mode = "DRY RUN -- nothing written" if args.dry_run else "WRITTEN"
    print(f"Stage 0 tagging ({mode})")
    print(f"  bar: null percentile >= {MIN_NULL_PCT} AND trades >= {MIN_TRADES}\n")
    print(f"  VALIDATED   {len(validated)}")
    for s in validated:
        print(f"    {s}")
    print(f"  UNVALIDATED {len(unvalidated)}")
    for s in unvalidated:
        print(f"    {s}")
    if skipped:
        print(f"  SKIPPED (no score row) {len(skipped)}")
        for s in skipped:
            print(f"    {s}")


if __name__ == "__main__":
    main()
