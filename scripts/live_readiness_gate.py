"""Is this system ready for real money? Answered from evidence, not opinion.

WHY THIS EXISTS. Every check below was run manually on 2026-09-21 and every one
failed. Re-deriving that by hand each time invites the most expensive mistake in
trading: remembering the encouraging results and forgetting the disqualifying
ones. This makes the answer reproducible, so "are we ready yet" costs one
command and cannot be argued with.

THE GATES, AND WHY EACH ONE IS A VETO

  1 FORWARD EVIDENCE   Every other number here is measured on the decade the
                       strategies were fitted to. Forward results are the only
                       evidence that cannot be contaminated by that. 30 resolved
                       trades is a floor, not a blessing.

  2 NULL PERCENTILE    This project measured 150 of 150 pure-noise paths
                       producing candidates that clear its selection bar. A
                       strategy that cannot beat its own synthetic null has not
                       been shown to be different from one of those paths.

  3 NET OF COSTS       Measured: +0.0076 R gross per trade against 0.0603 R of
                       cost -- losing by ~8x. A rule must clear its OWN costs at
                       its OWN turnover, not gross.

  4 DEFLATED SHARPE    107,371 candidates were searched. The best of that many
                       draws is high by construction; DSR is what prices that in.

  5 DRAWDOWN REALISM   Until 2026-09-21 every drawdown in this repo was measured
                       on 1%-notional sizing and read ~100x too small, so the 25%
                       limit had never once fired. A strategy graded before that
                       fix has never had its risk measured.

FAILING IS THE EXPECTED RESULT. This gate exists to be honest, not to be passed.
A system that cannot pass it is not broken -- it is a system whose edge has not
been demonstrated yet, which is the normal state of almost every trading idea.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PROJ = ROOT / "project_titan_x"
LB = PROJ / "data" / "models" / "e24_strategy_research" / "strategy_leaderboard.json"
CAL = PROJ / "data" / "models" / "e42_confidence_calibration" / "signal_calibration.json"
STAGE0 = PROJ / "research" / "stage0_override_scores.json"

MIN_RESOLVED_FWD = 30
MIN_NULL_PCT = 95.0
MIN_DSR = 0.95
MAX_DD_PCT = 25.0

# E26's own cost assumption and the notional risk-based sizing actually deploys.
COST_ROUND_TRIP = 0.003
MEDIAN_NOTIONAL = 0.201
RISK_PCT = 0.01


def _load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def gate_forward() -> tuple[bool, str]:
    try:
        from project_titan_x.engines.e24_strategy_research import forward_test as ft
        s = ft.summarise()
        n = int(s.get("total_resolved") or 0)
    except Exception as e:  # noqa: BLE001
        return False, f"forward test unreadable ({e})"
    ok = n >= MIN_RESOLVED_FWD
    return ok, f"{n} resolved forward trade(s); need >= {MIN_RESOLVED_FWD}"


def gate_null() -> tuple[bool, str]:
    d = _load(STAGE0)
    if not d:
        return False, "stage0_override_scores.json unreadable"
    rows = d.get("rows", [])
    passing = [r for r in rows if (r.get("null_percentile") or 0) >= MIN_NULL_PCT]
    if not passing:
        best = max(rows, key=lambda r: r.get("null_percentile") or 0, default=None)
        b = f"best {best['override']} at {best.get('null_percentile')}" if best else "none scored"
        return False, f"0 of {len(rows)} overrides clear null >= {MIN_NULL_PCT} ({b})"
    return True, f"{len(passing)} override(s) clear null >= {MIN_NULL_PCT}"


def gate_net_of_costs() -> tuple[bool, str]:
    d = _load(CAL)
    if not d:
        return False, "signal_calibration.json missing -- run calibrate_signal_confidence.py"
    w, rr = d["overall_win_rate"], d["rr"]
    gross_R = w * rr - (1 - w)
    gross = gross_R * RISK_PCT * 100
    cost = COST_ROUND_TRIP * MEDIAN_NOTIONAL * 100
    net = gross - cost
    return net > 0, (f"live rule net {net:+.4f}% equity/trade "
                     f"(gross {gross:+.4f}%, cost {cost:.4f}%)")


def gate_dsr() -> tuple[bool, str]:
    d = _load(LB)
    if not d:
        return False, "leaderboard missing"
    rows = d.get("rows", [])
    ok_rows = [r for r in rows if (r.get("dsr") or 0) >= MIN_DSR and r.get("grade") in ("S", "A+")]
    if not ok_rows:
        best = max((r for r in rows if r.get("dsr") is not None),
                   key=lambda r: r["dsr"], default=None)
        b = f"best {best['strategy']} {best['symbol']} at {best['dsr']:.3f}" if best else "none"
        return False, f"no A+ candidate with dsr >= {MIN_DSR} ({b})"
    return True, f"{len(ok_rows)} candidate(s) with dsr >= {MIN_DSR}"


def gate_drawdown_realism() -> tuple[bool, str]:
    """Are the book's drawdowns measured on risk-based sizing, or the old fiction?"""
    d = _load(LB)
    if not d:
        return False, "leaderboard missing"
    dds = [r.get("max_drawdown_pct") for r in d.get("rows", [])
           if r.get("max_drawdown_pct") is not None]
    if not dds:
        return False, "no drawdowns recorded"
    dds.sort()
    med = dds[len(dds) // 2]
    # Under 1%-notional sizing the median sat near 0.08%. Anything that low means
    # the book has not been re-swept since the sizing fix.
    ok = med > 1.0
    return ok, f"median book drawdown {med:.2f}% ({'real' if ok else 'still notional-sized fiction'})"


def main() -> int:
    gates = [
        ("Forward evidence", gate_forward),
        ("Beats synthetic null", gate_null),
        ("Net positive after costs", gate_net_of_costs),
        ("Deflated Sharpe", gate_dsr),
        ("Drawdowns are real", gate_drawdown_realism),
    ]
    print("=" * 74)
    print("  LIVE READINESS GATE -- every check must pass before real money")
    print("=" * 74)
    results = []
    for name, fn in gates:
        try:
            ok, detail = fn()
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"check errored: {e}"
        results.append(ok)
        print(f"  [{'PASS' if ok else 'FAIL'}]  {name:<26} {detail}")
    print("=" * 74)
    n_ok = sum(results)
    if all(results):
        print(f"  {n_ok}/{len(results)} gates pass.")
        print("  Every disqualifying condition has cleared. Size small anyway --")
        print("  passing these gates is necessary, never sufficient.")
        return 0
    print(f"  {n_ok}/{len(results)} gates pass -- NOT READY FOR REAL MONEY.")
    print()
    print("  This is the expected result for an edge that has not been")
    print("  demonstrated yet. The two gates that need TIME rather than code:")
    print("    - forward evidence  (~95 days for BTC-USD at its signal rate)")
    print("    - option surface    (~7 months on 1h, 2 instruments only)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
