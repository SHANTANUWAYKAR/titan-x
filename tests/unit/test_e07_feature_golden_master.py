"""
Module: test_e07_feature_golden_master.py
Description: Golden-master regression test for the shared SMC/ICT feature
    path -- both PDFs in data/PDF/ (the meta-labeling and solo-quant
    validation advisories read 2026-09-13) independently flag
    training/serving feature skew as "the most underrated engineering
    risk" for a platform like this one: research and live code silently
    drifting apart on the SAME concept (BOS/CHoCH, order blocks, FVG,
    CVD, killzones).

    Direct verification before writing this (an Explore agent, then a
    manual read of research/ict_concepts.py's own header) found the risk
    is ALREADY structurally closed on the research/live axis:
    research/ict_concepts.py imports detect_structure_events,
    detect_fair_value_gaps, displacement and market_structure_shift
    directly from engines/e07_technical/smart_money.py rather than
    reimplementing them -- confirmed by grep, zero parallel
    BOS/CHoCH/FVG logic exists in research/. A straight `from ... import`
    cannot silently drift; there is only one function object.

    What was still missing is the OTHER half of "skew": a regression
    net catching an ACCIDENTAL behavior change to that single shared
    implementation itself. Every ablation result in research/ablation_*
    .json, every override's validated Sharpe/win-rate, and every live
    Stage 0 verdict in docs/STAGE0_FINDINGS.md implicitly assumes today's
    detect_structure_events/detect_order_blocks/detect_fair_value_gaps/
    displacement/market_structure_shift/compute_cumulative_delta/
    active_killzones output is the SAME output that produced those
    numbers. Nothing before this file would fail if an edit to
    smart_money.py, order_flow.py, or killzones.py silently changed that
    output -- every existing test in test_smart_money.py etc. checks
    CORRECTNESS on small hand-built cases, not stability of the exact
    values on a larger, realistic series.

    This pins that exact output against a stored fixture
    (tests/fixtures/e07_feature_golden_master.json) computed once against
    a fixed-seed (20260913) synthetic 400-bar hourly series (see
    scripts/regenerate_e07_golden_master.py for how it was produced and
    how to regenerate it deliberately). A failure here means one of two
    things: a real accidental regression (fix the code, do not touch the
    fixture), or a genuine, deliberate improvement to the feature logic
    (regenerate the fixture AND go re-verify every downstream artifact
    that assumed the old behavior -- ablation results, Stage 0 tags,
    override files -- per this project's own standing Rule 3 discipline).
    The fixture is never "just updated" to make a failing test pass.
Author: Shantanu Waykar
Version: 1.0.0
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

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

FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "e07_feature_golden_master.json"
SEED = 20260913
N_BARS = 400


def _build_fixture_df() -> pd.DataFrame:
    """Deterministic synthetic OHLCV: a fixed-seed random walk with
    periodic drift resets (every 23 bars) so the series contains real
    swings, structure breaks, displacement, and FVGs rather than pure
    noise -- same construction as scripts/regenerate_e07_golden_master.py,
    duplicated inline (not imported) so this test has no dependency on
    that script continuing to exist unchanged."""
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


@pytest.fixture(scope="module")
def golden_master() -> dict:
    with open(FIXTURE_PATH) as f:
        return json.load(f)


def test_fixture_file_exists_and_is_nontrivial(golden_master):
    """Sanity check on the fixture itself, so a corrupted/emptied fixture
    file fails loudly here rather than passing every downstream check by
    vacuously matching an equally-empty recomputation."""
    assert golden_master["n_bars"] == N_BARS
    assert len(golden_master["structure_events"]) > 0
    assert len(golden_master["order_blocks"]) > 0
    assert len(golden_master["fair_value_gaps"]) > 0
    assert len(golden_master["displacement_nonzero"]) > 0


def test_structure_events_match_golden_master(golden_master):
    actual = _compute_all_features(_build_fixture_df())
    assert actual["structure_events"] == golden_master["structure_events"]


def test_order_blocks_match_golden_master(golden_master):
    actual = _compute_all_features(_build_fixture_df())
    assert actual["order_blocks"] == golden_master["order_blocks"]


def test_fair_value_gaps_match_golden_master(golden_master):
    actual = _compute_all_features(_build_fixture_df())
    assert actual["fair_value_gaps"] == golden_master["fair_value_gaps"]


def test_displacement_and_mss_match_golden_master(golden_master):
    actual = _compute_all_features(_build_fixture_df())
    assert actual["displacement_nonzero"] == golden_master["displacement_nonzero"]
    assert actual["mss_nonzero"] == golden_master["mss_nonzero"]


def test_cvd_matches_golden_master(golden_master):
    actual = _compute_all_features(_build_fixture_df())
    assert actual["cvd_checkpoints"] == golden_master["cvd_checkpoints"]
    assert actual["cvd_final"] == golden_master["cvd_final"]


def test_killzones_match_golden_master(golden_master):
    actual = _compute_all_features(_build_fixture_df())
    assert actual["killzone_true_counts"] == golden_master["killzone_true_counts"]


def test_input_series_is_itself_deterministic():
    """Guards the guard: confirms the fixed-seed synthetic input is
    reproducible bar-for-bar, so a failure in the tests above can be
    trusted to mean the FEATURE functions changed, not that the input
    generator silently became nondeterministic (e.g. an unseeded RNG call
    creeping in during a future edit to this file)."""
    df1 = _build_fixture_df()
    df2 = _build_fixture_df()
    pd.testing.assert_frame_equal(df1, df2)
