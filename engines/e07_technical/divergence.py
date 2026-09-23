"""
Module: divergence.py
Description: RSI divergence detection for e07_technical -- regular and
    hidden bullish/bearish divergence between price swing points and RSI
    at those same points.

    Built from a real gap found while cross-referencing this engine
    against the YouTube Knowledge Import Pipeline's extraction of the
    Mind Math Money channel (97 videos processed): RSI is the single most
    emphasized concept in that corpus (971 mentions) and "divergence"
    the fourth most (196 mentions, almost entirely RSI divergence, incl.
    a dedicated "MASTER The RSI Indicator" video covering it in depth) --
    yet this engine had RSI itself but ZERO divergence detection before
    this module. The four-way taxonomy below (regular vs hidden, bullish
    vs bearish) matches the source material's own stated definitions
    exactly (verified against real extracted transcript quotes, not
    assumed from general TA knowledge alone):
      - regular bullish: "always looking at the lows" -- price and RSI
        disagree at a pair of swing lows, reversal-up read.
      - regular bearish: mirror at swing highs, reversal-down read.
      - hidden bullish/bearish: continuation reads, harder to spot per
        the source material itself.

    Uses the SAME swing-point infrastructure as smart_money.py/
    wyckoff.py/harmonics.py (structure.find_swing_points +
    alternate_swings) so a "swing high/low" means the same thing
    everywhere in this engine, rather than re-deriving a second notion of
    pivot just for this.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd

from project_titan_x.engines.e07_technical.structure import SwingKind, SwingPoint


class DivergenceKind(str, Enum):
    REGULAR_BULLISH = "regular_bullish"  # price lower low, RSI higher low -- reversal up
    REGULAR_BEARISH = "regular_bearish"  # price higher high, RSI lower high -- reversal down
    HIDDEN_BULLISH = "hidden_bullish"    # price higher low, RSI lower low -- uptrend continuation
    HIDDEN_BEARISH = "hidden_bearish"    # price lower high, RSI higher high -- downtrend continuation


@dataclass
class RSIDivergence:
    first_index: int
    second_index: int
    kind: DivergenceKind
    price_first: float
    price_second: float
    rsi_first: float
    rsi_second: float


def detect_rsi_divergences(
    df: pd.DataFrame, swings: list[SwingPoint], rsi_col: str = "rsi",
) -> list[RSIDivergence]:
    """Compares each consecutive same-kind pair of swing points (two
    swing lows, or two swing highs -- via the already-alternating
    `swings` sequence, the same one BOS/CHoCH/harmonics use) against the
    RSI value at those same two bars.

    Only compares ADJACENT swing points of the same kind, not every
    possible pair -- matches how this is actually read on a chart (the
    most recent two swings), and avoids stale, far-apart comparisons.

    Rows where the RSI value is NaN (not enough bars yet for the RSI
    lookback window) are skipped -- an undefined RSI at either point
    makes the comparison meaningless, not just imprecise. Equal
    price/RSI pairs (neither higher nor lower) claim no divergence,
    the conservative default rather than a forced classification.
    """
    if rsi_col not in df.columns:
        return []
    rsi = df[rsi_col].to_numpy()
    divergences: list[RSIDivergence] = []

    for kind in (SwingKind.LOW, SwingKind.HIGH):
        same_kind = [p for p in swings if p.kind == kind]
        for prev, curr in zip(same_kind, same_kind[1:]):
            r_prev, r_curr = rsi[prev.index], rsi[curr.index]
            if pd.isna(r_prev) or pd.isna(r_curr):
                continue

            div_kind: DivergenceKind | None = None
            if kind == SwingKind.LOW:
                if curr.price < prev.price and r_curr > r_prev:
                    div_kind = DivergenceKind.REGULAR_BULLISH
                elif curr.price > prev.price and r_curr < r_prev:
                    div_kind = DivergenceKind.HIDDEN_BULLISH
            else:
                if curr.price > prev.price and r_curr < r_prev:
                    div_kind = DivergenceKind.REGULAR_BEARISH
                elif curr.price < prev.price and r_curr > r_prev:
                    div_kind = DivergenceKind.HIDDEN_BEARISH

            if div_kind is not None:
                divergences.append(RSIDivergence(
                    first_index=prev.index, second_index=curr.index, kind=div_kind,
                    price_first=float(prev.price), price_second=float(curr.price),
                    rsi_first=float(r_prev), rsi_second=float(r_curr),
                ))

    return divergences
