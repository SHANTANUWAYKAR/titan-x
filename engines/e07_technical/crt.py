"""
Module: crt.py
Description: Engine 07 -- CRT (Candle Range Theory) detection.

    docs/UPGRADE_ROADMAP.md P1 item 2. Fully specified in
    docs/ICT_SPEC_PHASE5.md section 1, reverse-engineered from
    NadirAliOfficial/STAR-EA-v11.20 (MIT), `DetectCRTSetups`/
    `UpdateCRTSetups` -- every rule below is read from that spec, not from
    ICT prose, and two source bugs the spec identifies are deliberately
    NOT reproduced here (see the two notes below).

    CONCEPT: a single candle whose range is significant relative to
    volatility becomes a reference range. The NEXT candle breaking one
    side of that range defines direction; the range then projects forward
    for entry/stop/targets. A range-expansion setup, not a structure-break
    setup -- non-redundant with BOS/CHoCH/MSS (smart_money.py) or Wyckoff
    springs/upthrusts (wyckoff.py).

    NOT YET ABLATED. Per the spec's own Rule 3/6 requirement ("ablate solo
    first... if solo expectancy is negative, stop") and this platform's
    standing discipline (nothing enters live signals except through
    E24 -> E26 -> explicit promotion), this module is deliberately NOT
    wired into TechnicalAnalysisEngine._generate_advanced_signals or
    _compute_bullish_score -- only exposed on TechnicalSnapshot.crt_setups
    for inspection/research until research/concept_ablation.py measures
    real solo expectancy.

    THE TRANSLATION TRAP (spec 1.4): STAR-EA's MQL5 arrays are series-
    indexed (index 0 = newest bar), so its `high[i-1] > high[i]` means
    "the NEXT bar broke above bar i's high." A naive ascending-index port
    would misread `i-1` as the PREVIOUS bar and implement a different,
    wrong algorithm. The setup is not knowable at bar `i` -- it requires
    bar `i+1` to have closed. This module detects using `i` and `i+1` and
    EMITS AT `i+1` (`signal_index`), never at `i` (`range_bar_index`).
Author: Shantanu Waykar
Version: 1.0.0
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from project_titan_x.engines.e07_technical.smart_money import _average_true_range

MIN_RANGE_ATR = 0.8
MAX_RANGE_ATR = 3.0
MIN_BODY_RATIO = 0.3
MIN_RETRACE = 0.25
PROJECTION_MULT = 1.0
EXTENSION_LEVEL = 1.618


@dataclass
class CRTSetup:
    """One CRT setup. Field names match docs/ICT_SPEC_PHASE5.md section
    1.12's own example JSON exactly."""

    signal_index: int  # k = i+1 -- the bar this setup is EMITTED at, never range_bar_index
    range_bar_index: int  # i -- the reference range bar
    direction: str  # "bullish" / "bearish"
    range_high: float
    range_low: float
    range_atr: float
    # Spec 1.10 bug 2: STAR-EA calls this "wickRatio" but computes
    # bodySize/candleRange -- a BODY ratio. Named correctly here; porting
    # the source's name would invert a future reader's understanding.
    body_ratio: float
    retrace: float
    entry: float
    stop: float
    tp1: float
    tp2: float
    tp3: float
    risk_reward: float
    # A/B/C/D from range_atr alone. Spec 1.9: "not evidence... never been
    # validated against outcomes on this platform. Treat as a label, not
    # a score." Never fed into any confidence/scoring computation.
    quality: str


def _quality_tier(range_atr: float) -> str:
    if range_atr >= 1.5:
        return "A"
    if range_atr >= 1.2:
        return "B"
    if range_atr >= 0.9:
        return "C"
    return "D"


def detect_crt_setups(
    df: pd.DataFrame,
    atr_period: int = 14,
    min_range_atr: float = MIN_RANGE_ATR,
    max_range_atr: float = MAX_RANGE_ATR,
    min_body_ratio: float = MIN_BODY_RATIO,
    require_retrace: bool = True,
    min_retrace: float = MIN_RETRACE,
    projection_mult: float = PROJECTION_MULT,
    extension_level: float = EXTENSION_LEVEL,
) -> list[CRTSetup]:
    """Detect CRT setups per docs/ICT_SPEC_PHASE5.md section 1.2-1.3.

    Args:
        df: OHLC data (volume not used -- spec 1.5).
        atr_period: Wilder-equivalent ATR lookback (same formula as
            e07_technical.engine._add_atr, via smart_money._average_true_range).
        min_range_atr/max_range_atr: bar `i` qualifies as a range bar only
            within this band (defaults 0.8-3.0 -- spec 1.2). The upper
            bound deliberately discards genuine volatility shocks; a
            documented, not accidental, choice (spec 1.9).
        min_body_ratio: minimum |close-open|/range for bar `i` (default
            0.3 -- weaker than this codebase's own `displacement` at 0.6;
            spec 1.9 flags this as a real false-positive source, not fixed
            here since altering the spec's own threshold would no longer
            be testing what the spec defines).
        require_retrace/min_retrace: optional filter (default on, 0.25)
            requiring the breaking bar to close back into a meaningful
            part of the range rather than running away from it.
        projection_mult/extension_level: target-level multipliers (spec
            1.2 defaults 1.0 / 1.618).

    Returns:
        list[CRTSetup], ordered by signal_index ascending. Every level
        (entry/stop/tp1-3) is a specification output, not a validated
        level -- E26 exits on signal flip and does not test stops/targets
        (spec 1.12's own caveat).

    Edge cases (spec 1.8), all reject-not-guess:
        - range_i == 0 (flat bar): rejected, never divides by zero.
        - ATR NaN (warm-up) or ATR <= 0 (flat series): rejected.
        - Last bar of the series: no i+1 exists, loop stops at len-2.
        - Both sides broken (outside bar) or neither: rejected, not a
          coin flip -- exclusive-or is required.
        - Gapped bar (low_k > high_i): counts as broke_high naturally
          (no special-casing needed); retrace will typically then fail,
          the spec's own noted correct-conservative outcome.

    Note (spec 1.10 bug 1): STAR-EA's `CRT_RequireBreak` input flag is
    dead code (the line above it already guarantees at least one side
    broke). No such parameter exists here -- `require_retrace` is the
    only optional gate, and it does real, reachable filtering.
    """
    n = len(df)
    if n < atr_period + 2:
        return []

    o = df["open"].to_numpy(float)
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    atr = _average_true_range(df, atr_period).to_numpy(float)

    setups: list[CRTSetup] = []
    for i in range(n - 1):
        bar_atr = atr[i]
        if not np.isfinite(bar_atr) or bar_atr <= 0:
            continue
        rng = h[i] - l[i]
        if rng <= 0:
            continue
        range_atr = rng / bar_atr
        if not (min_range_atr <= range_atr <= max_range_atr):
            continue
        body_ratio = abs(c[i] - o[i]) / rng
        if body_ratio < min_body_ratio:
            continue

        k = i + 1
        broke_high = h[k] > h[i]
        broke_low = l[k] < l[i]
        if broke_high == broke_low:  # both (outside bar) or neither -- reject
            continue

        direction = "bullish" if broke_high else "bearish"
        retrace = (h[i] - c[k]) / rng if direction == "bullish" else (c[k] - l[i]) / rng
        if require_retrace and retrace < min_retrace:
            continue

        entry = (h[i] + l[i]) / 2
        if direction == "bullish":
            stop = l[i] - 0.2 * bar_atr
            tp1 = h[i] + 0.5 * rng * projection_mult
            tp2 = h[i] + rng * projection_mult
            tp3 = h[i] + rng * extension_level
        else:
            stop = h[i] + 0.2 * bar_atr
            tp1 = l[i] - 0.5 * rng * projection_mult
            tp2 = l[i] - rng * projection_mult
            tp3 = l[i] - rng * extension_level

        risk = abs(entry - stop)
        risk_reward = abs(tp2 - entry) / risk if risk > 0 else 0.0

        setups.append(CRTSetup(
            signal_index=k, range_bar_index=i, direction=direction,
            range_high=float(h[i]), range_low=float(l[i]), range_atr=float(range_atr),
            body_ratio=float(body_ratio), retrace=float(retrace),
            entry=float(entry), stop=float(stop),
            tp1=float(tp1), tp2=float(tp2), tp3=float(tp3),
            risk_reward=float(risk_reward), quality=_quality_tier(range_atr),
        ))
    return setups
