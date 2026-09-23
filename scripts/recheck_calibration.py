"""Has anything actually changed? Re-runs the signal calibration and compares.

WHY THIS EXISTS. On 2026-09-21 the live signal generator measured 33.59% win
rate against a 33.33% breakeven -- a +0.3 point margin -- with confidence
carrying essentially no information (+0.161 correlation with outcomes, every
bucket sitting at breakeven). Four independent methods agreed there was no
demonstrable edge.

Two things could change that, and both need TIME rather than code: forward-test
evidence accumulating, and the option-surface recorder building the first
non-price input this platform has ever had. Neither is worth checking weekly,
and both are easy to forget entirely.

So this freezes the 2026-09-21 numbers as a baseline and answers one question
on demand: is the generator measurably different from the day it was audited?

A CHANGE IS NOT AN IMPROVEMENT. More signals alone will move these numbers
slightly; that is sampling noise, not progress. The threshold below is
deliberately coarse for that reason -- it is set to flag movement worth
investigating, not to declare victory.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJ = ROOT / "project_titan_x"
LIVE = PROJ / "data" / "models" / "e42_confidence_calibration" / "signal_calibration.json"
BASE = PROJ / "data" / "models" / "e42_confidence_calibration" / "signal_calibration_baseline_20260921.json"
PY = PROJ / ".venv" / "Scripts" / "python.exe"

# Movement smaller than this is sampling noise on a ~100k-signal sample, not a
# change in the generator.
WIN_RATE_EPS = 0.010   # 1.0 percentage point


def main() -> int:
    if not BASE.exists():
        if not LIVE.exists():
            print("No baseline and no live calibration -- run calibrate_signal_confidence.py first.")
            return 1
        BASE.write_text(LIVE.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"Froze current calibration as the baseline -> {BASE.name}")

    base = json.loads(BASE.read_text(encoding="utf-8"))

    print("Re-running calibration (this takes a few minutes)...", flush=True)
    r = subprocess.run(
        [str(PY), str(PROJ / "scripts" / "calibrate_signal_confidence.py"),
         "--timeframes", "1d", "--rr", "2.0"],
        capture_output=True, text=True, cwd=str(PROJ),
    )
    if r.returncode != 0:
        print("calibration failed:\n" + (r.stderr or r.stdout)[-800:])
        return 1

    now = json.loads(LIVE.read_text(encoding="utf-8"))
    b_wr, n_wr = base["overall_win_rate"], now["overall_win_rate"]
    be = now["breakeven"]
    d_wr = n_wr - b_wr

    print()
    print(f"{'':<22}{'baseline':>12}{'now':>12}{'change':>12}")
    print(f"{'signals':<22}{base['n_signals']:>12,}{now['n_signals']:>12,}"
          f"{now['n_signals']-base['n_signals']:>+12,}")
    print(f"{'win rate':<22}{b_wr*100:>11.2f}%{n_wr*100:>11.2f}%{d_wr*100:>+11.2f}pt")
    print(f"{'margin over breakeven':<22}{(b_wr-be)*100:>+11.2f}pt{(n_wr-be)*100:>+11.2f}pt")
    print()

    if abs(d_wr) < WIN_RATE_EPS:
        print(f"UNCHANGED. Win rate moved {d_wr*100:+.2f}pt, inside the {WIN_RATE_EPS*100:.1f}pt "
              "noise band on a sample this size.")
        print("The generator is the same as it was on 2026-09-21. Nothing to act on.")
    elif n_wr > b_wr:
        print(f"IMPROVED by {d_wr*100:+.2f}pt, past the noise band. Worth investigating WHY "
              "before trusting it -- confirm it is not just a different sample period.")
    else:
        print(f"DEGRADED by {d_wr*100:+.2f}pt. Check whether the live rule or its inputs changed.")

    print()
    print("Reminder: calibration is not edge. A generator that reports its own odds "
          "honestly and has no edge is still no edge.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
