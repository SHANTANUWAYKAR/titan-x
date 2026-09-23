"""Regenerate tests/fixtures/e07_feature_golden_master.json.

Run this ONLY after a deliberate, understood change to one of the
functions tests/unit/test_e07_feature_golden_master.py pins:
detect_structure_events, detect_order_blocks, detect_fair_value_gaps,
displacement, market_structure_shift, compute_cumulative_delta, or
active_killzones (all in engines/e07_technical/). NEVER run this just to
make a failing golden-master test pass -- a failure there means one of
two things, and only one of them justifies running this script:

  1. An accidental regression. Fix the code, do not touch the fixture.
  2. A genuine, intended improvement to the feature logic. Regenerate the
     fixture with this script, AND go re-verify every downstream artifact
     that implicitly assumed the old output -- research/ablation_*.json,
     every strategy override's recorded Sharpe/win-rate, and every
     verdict in docs/STAGE0_FINDINGS.md -- per this project's own
     standing Rule 3 discipline ("every new engine gets trained/
     calibrated before being considered done" applies just as much to
     re-validating existing calibration after a shared-feature change).

The synthetic input series (fixed seed 20260913, 400 hourly bars) is
duplicated inline in the test file rather than imported from here, so the
test has no runtime dependency on this script continuing to exist
unchanged -- this script exists only as the documented, reproducible way
to regenerate the fixture, matching scripts/apply_stage0_tags.py's own
"the script is how you reproduce this, not something the test imports"
convention.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from project_titan_x.engines.e07_technical.killzones import active_killzones
from project_titan_x.engines.e07_technical.order_flow import compute_cumulative_delta
from project_titan_x.engines.e07_technical.smart_money import (
    detect_fair_value_gaps,
    detect_order_blocks,
    detect_structure_events,
    displacement,
    market_structure_shift,
)
from project_titan_x.engines.e07_technical.structure import alternate_swings, find_swing_points

SEED = 20260913
N_BARS = 400
FIXTURE_PATH = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "e07_feature_golden_master.json"


def _build_fixture_df() -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    timestamps = pd.date_range("2026-01-05 00:00:00", periods=N_BARS, freq="1h", tz="UTC")

    price = 100.0
    opens, highs, lows, closes, volumes = [], [], [], [], []
    drift = 0.0
    for i in range(N_BARS):
        if i % 23 == 0:
            drift = rng.normal(0, 0.35)
        step = drift + rng.normal(0, 0.18)
        o = price
        c = max(0.5, o + step)
        hi = max(o, c) + abs(rng.normal(0, 0.12))
        lo = min(o, c) - abs(rng.normal(0, 0.12))
        vol = float(abs(rng.normal(1000, 250)))
        opens.append(o)
        highs.append(hi)
        lows.append(lo)
        closes.append(c)
        volumes.append(vol)
        price = c

    return pd.DataFrame(
        {"timestamp": timestamps, "open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes}
    )


def _round(x, nd=6):
    return round(float(x), nd)


def _compute_all_features(df: pd.DataFrame) -> dict:
    swings = alternate_swings(find_swing_points(df))
    events = detect_structure_events(df, swings=swings)
    order_blocks = detect_order_blocks(df, events)
    fvgs = detect_fair_value_gaps(df)
    disp = displacement(df)
    mss = market_structure_shift(df)
    cvd = compute_cumulative_delta(df)
    kz = active_killzones(df)

    return {
        "n_bars": len(df),
        "structure_events": [
            {"index": e.index, "kind": e.kind.value, "broken_level": _round(e.broken_level)} for e in events
        ],
        "order_blocks": [
            {
                "index": b.index,
                "direction": b.direction,
                "open": _round(b.open),
                "high": _round(b.high),
                "low": _round(b.low),
                "close": _round(b.close),
                "breaker": b.breaker,
                "mitigated_index": b.mitigated_index,
            }
            for b in order_blocks
        ],
        "fair_value_gaps": [
            {
                "index": g.index,
                "direction": g.direction,
                "gap_top": _round(g.gap_top),
                "gap_bottom": _round(g.gap_bottom),
                "filled": g.filled,
            }
            for g in fvgs
        ],
        "displacement_nonzero": {str(i): int(v) for i, v in enumerate(disp) if v != 0},
        "mss_nonzero": {str(i): int(v) for i, v in enumerate(mss) if v != 0},
        "cvd_checkpoints": {str(i): _round(cvd.iloc[i]) for i in range(0, len(cvd), 40)},
        "cvd_final": _round(cvd.iloc[-1]),
        "killzone_true_counts": {col: int(kz[col].sum()) for col in kz.columns},
    }


if __name__ == "__main__":
    result = _compute_all_features(_build_fixture_df())
    FIXTURE_PATH.write_text(json.dumps(result, indent=2) + "\n")
    print(f"wrote {FIXTURE_PATH}")
    print(f"  structure_events={len(result['structure_events'])} "
          f"order_blocks={len(result['order_blocks'])} "
          f"fair_value_gaps={len(result['fair_value_gaps'])} "
          f"displacement_nonzero={len(result['displacement_nonzero'])} "
          f"mss_nonzero={len(result['mss_nonzero'])}")
