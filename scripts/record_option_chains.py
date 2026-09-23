"""Record one options-surface snapshot per supported currency.

Run on a schedule. Every run that does not happen is a gap that cannot be
backfilled later -- Deribit serves the CURRENT chain, not last Tuesday's.

    python scripts/record_option_chains.py
    python scripts/record_option_chains.py --status    # what's on disk
    python scripts/record_option_chains.py --force     # ignore the dedup window

To accumulate without depending on the API server being up, register it as a
daily Windows task (run this yourself -- it changes system state):

    schtasks /create /tn "TitanX Option Chains" /sc hourly \\
        /tr "<repo>/.venv/Scripts/python.exe <repo>/scripts/record_option_chains.py"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from project_titan_x.engines.e13_derivatives import chain_recorder  # noqa: E402
from project_titan_x.engines.e13_derivatives.engine import (  # noqa: E402
    DerivativesIntelligenceEngine,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true", help="print what is recorded and exit")
    ap.add_argument("--force", action="store_true", help="record even inside the dedup window")
    ap.add_argument("--symbols", default="BTCUSD,ETHUSD")
    args = ap.parse_args()

    if args.status:
        print(json.dumps(chain_recorder.summarise(), indent=2))
        return 0

    engine = DerivativesIntelligenceEngine()
    try:
        engine.initialize()
    except Exception as e:  # noqa: BLE001
        print(f"engine.initialize() raised {e!r} -- continuing", flush=True)

    syms = tuple(s.strip() for s in args.symbols.split(",") if s.strip())
    result = chain_recorder.record_all(engine, syms, force=args.force)

    for r in result["recorded"]:
        lv = "with levels" if r.get("has_levels") else "NO levels (missing IV or expiry)"
        print(f"recorded {r['symbol']} @ {r['timestamp']} -- {lv}")
    for r in result["skipped"]:
        print(f"skipped  {r['symbol']}: {r['reason']}")
    for sym, why in result["failed"].items():
        print(f"FAILED   {sym}: {why}")

    s = chain_recorder.summarise()
    if s.get("exists"):
        print(f"\nhistory: {s['rows']} rows {s.get('by_currency')} · {s.get('first')} -> {s.get('last')}")
    # Failure to reach a data source is not a script error -- the scheduler
    # should keep trying rather than be disabled by one outage.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
