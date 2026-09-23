"""Run the remaining synthetic-null campaigns one after another.

Sequential ON PURPOSE. Each campaign already saturates 6 workers, and the
first attempt at measuring per-path cost was wrecked by exactly this
mistake -- a background sweep competing for the same cores made a 1.6s
candidate look like a 164s pathology, and I nearly went hunting for a bug
that did not exist. Overlapping campaigns would corrupt their own timings
the same way.
"""
import subprocess, sys, time
from pathlib import Path

import os

# Opt-in guard. A wrapper process may already be blocked waiting on the 4h
# campaign, and once that finishes it would launch ~3h of further campaigns
# unattended. Killing the wrapper is unreliable (it is mid-WaitForExit and
# the script is already loaded), so the decision is enforced here instead:
# nothing runs unless RUN_NULL_CHAIN=1 is set explicitly.
if os.environ.get("RUN_NULL_CHAIN") != "1":
    print("run_null_chain: not enabled (set RUN_NULL_CHAIN=1 to run 1h/1d campaigns)")
    raise SystemExit(0)

ROOT = Path(__file__).resolve().parents[1]
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")

for tf, bars in (("1h", 12000), ("1d", 6000)):
    out = ROOT / "research" / f"synthetic_null_GCF_{tf}.json"
    if out.exists():
        print(f"{tf}: already done, skipping", flush=True)
        continue
    print(f"=== synthetic null: GC=F {tf} ({bars} bars) ===", flush=True)
    t = time.time()
    rc = subprocess.call([PY, "-u", str(ROOT / "research" / "synthetic_null.py"),
                          "--symbol", "GC=F", "--timeframe", tf,
                          "--paths", "50", "--bars", str(bars), "--workers", "6"],
                         cwd=str(ROOT))
    print(f"=== {tf} finished rc={rc} in {(time.time()-t)/60:.0f}m ===", flush=True)
