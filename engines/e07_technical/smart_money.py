"""
Module: smart_money.py
Description: ICT / Smart Money Concepts detection for e07_technical --
    Break of Structure (BOS), Change of Character (CHoCH), liquidity
    sweeps, order blocks, and Fair Value Gaps (FVG). Built directly from
    concepts identified in the ICT and Smart Money Concepts topic
    clusters of the ingested book corpus -- the two largest, most
    consistently mechanically-defined methodologies in that corpus after
    general technical analysis (492K+488K+397K+395K+167K+145K tagged
    chunks across Market Profile/Harmonics/ICT/SMC/Wyckoff/Elliott Wave,
    almost none of which the engine covered before this module existed).
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import numpy as np
import pandas as pd

from project_titan_x.engines.e07_technical.structure import SwingKind, SwingPoint, alternate_swings, find_swing_points


class StructureEventKind(str, Enum):
    BOS_BULLISH = "bos_bullish"      # continuation: breaks above prior high, prior break was also bullish
    BOS_BEARISH = "bos_bearish"      # continuation: breaks below prior low, prior break was also bearish
    CHOCH_BULLISH = "choch_bullish"  # reversal: breaks above prior high right after a bearish break
    CHOCH_BEARISH = "choch_bearish"  # reversal: breaks below prior low right after a bullish break


@dataclass
class StructureEvent:
    index: int
    kind: StructureEventKind
    broken_level: float


@dataclass
class LiquiditySweep:
    index: int
    direction: str  # "bullish" (swept sell-side liquidity below a low, closed back above -- reversal up expected) / "bearish" (mirror)
    swept_level: float
    wick_price: float


@dataclass
class OrderBlock:
    index: int
    direction: str  # "bullish" / "bearish"
    open: float
    high: float
    low: float
    close: float
    # Added 2026-08-20: order-block invalidation/polarity-flip tracking --
    # found genuinely missing while reviewing external SMC libraries
    # (joshyattridge/smart-money-concepts's own smc.ob() tracks a
    # `breaker` state; this module's own detect_order_blocks previously
    # treated every block as valid forever, with no way to tell a zone
    # price has since closed clean through from one still genuinely
    # untested). A breaker block is a real, distinct ICT concept: a
    # failed order block whose zone flips polarity (broken support
    # becomes resistance, and vice versa) rather than simply expiring.
    breaker: bool = False
    mitigated_index: Optional[int] = None  # bar index of the first candle whose CLOSE broke clean through the zone, if any


@dataclass
class FairValueGap:
    index: int  # index of the middle (impulse) candle that left the gap behind
    direction: str  # "bullish" / "bearish"
    gap_top: float
    gap_bottom: float
    filled: bool  # whether any later candle has already traded back into the gap


def detect_structure_events(
    df: pd.DataFrame, lookback: int = 5, swings: Optional[list[SwingPoint]] = None
) -> list[StructureEvent]:
    """Walks the price bar-by-bar against the confirmed alternating swing
    sequence (see structure.py). A close beyond the most recent
    not-yet-broken swing high/low is a structural break; whether it's
    labeled BOS (continuation) or CHoCH (reversal) follows the standard
    ICT definition -- it depends on the direction of the PREVIOUS
    structural break, not on the swing sequence's own slope. The very
    first break in a series has no prior break to compare against and is
    reported as a BOS in its own direction (a bootstrap default, not a
    real continuation claim).

    swings: OPTIONAL pre-computed alternate_swings(find_swing_points(df,
    lookback)) result. None (default) computes it here, exactly as
    before. Added 2026-08-02: e07_technical.engine.py's analyze() calls
    this, detect_liquidity_sweeps, AND detect_harmonic_patterns on the
    SAME df with the SAME default lookback in one pass -- each was
    independently recomputing find_swing_points (a rolling centered
    min/max over the whole series) from scratch, 3x total for an
    identical result. Passing a shared, already-computed swings list
    through this optional param lets analyze() compute it once."""
    if swings is None:
        swings = alternate_swings(find_swing_points(df, lookback))
    closes = df["close"].to_numpy()
    n = len(df)

    events: list[StructureEvent] = []
    last_high: SwingPoint | None = None
    last_low: SwingPoint | None = None
    high_broken = False
    low_broken = False
    last_break_bullish: bool | None = None

    swing_iter = iter(swings)
    next_swing = next(swing_iter, None)

    for i in range(n):
        while next_swing is not None and next_swing.index == i:
            if next_swing.kind == SwingKind.HIGH:
                last_high = next_swing
                high_broken = False
            else:
                last_low = next_swing
                low_broken = False
            next_swing = next(swing_iter, None)

        if last_high is not None and not high_broken and closes[i] > last_high.price:
            is_continuation = last_break_bullish is True or last_break_bullish is None
            events.append(StructureEvent(
                index=i,
                kind=StructureEventKind.BOS_BULLISH if is_continuation else StructureEventKind.CHOCH_BULLISH,
                broken_level=last_high.price,
            ))
            high_broken = True
            last_break_bullish = True

        if last_low is not None and not low_broken and closes[i] < last_low.price:
            is_continuation = last_break_bullish is False
            events.append(StructureEvent(
                index=i,
                kind=StructureEventKind.BOS_BEARISH if is_continuation else StructureEventKind.CHOCH_BEARISH,
                broken_level=last_low.price,
            ))
            low_broken = True
            last_break_bullish = False

    return events


def detect_liquidity_sweeps(
    df: pd.DataFrame, lookback: int = 5, swings: Optional[list[SwingPoint]] = None
) -> list[LiquiditySweep]:
    """A liquidity sweep: price wicks beyond a recent swing high/low (the
    resting stop-loss/breakout orders just past it -- the 'liquidity')
    but the candle CLOSES back on the near side -- the signature that
    distinguishes a genuine breakout (closes through) from a stop hunt
    (wicks through, then reverses). Checked against the most recent
    confirmed swing at the time of each candle, not a global extreme, and
    each swing can only register one sweep so a slow grind past a level
    doesn't spam repeated 'sweep' events.

    swings: see detect_structure_events's own docstring -- same optional
    shared-computation param, same reasoning."""
    if swings is None:
        swings = alternate_swings(find_swing_points(df, lookback))
    n = len(df)
    highs, lows, closes = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()

    sweeps: list[LiquiditySweep] = []
    last_high: SwingPoint | None = None
    last_low: SwingPoint | None = None
    high_swept = False
    low_swept = False

    swing_iter = iter(swings)
    next_swing = next(swing_iter, None)

    for i in range(n):
        while next_swing is not None and next_swing.index == i:
            if next_swing.kind == SwingKind.HIGH:
                last_high = next_swing
                high_swept = False
            else:
                last_low = next_swing
                low_swept = False
            next_swing = next(swing_iter, None)

        if last_high is not None and not high_swept and highs[i] > last_high.price and closes[i] < last_high.price:
            sweeps.append(LiquiditySweep(index=i, direction="bearish", swept_level=last_high.price, wick_price=float(highs[i])))
            high_swept = True
        if last_low is not None and not low_swept and lows[i] < last_low.price and closes[i] > last_low.price:
            sweeps.append(LiquiditySweep(index=i, direction="bullish", swept_level=last_low.price, wick_price=float(lows[i])))
            low_swept = True

    return sweeps


def detect_order_blocks(
    df: pd.DataFrame, structure_events: list[StructureEvent], lookback_candles: int = 10
) -> list[OrderBlock]:
    """The order block for a structural break is the LAST opposing-color
    candle before the impulsive move that caused the break -- e.g. for a
    bullish break, the last bearish (close < open) candle before the
    up-move that broke the prior high. Searched backward from the break
    bar, bounded by lookback_candles, since a same-color candle found too
    far before its break is no longer meaningfully tied to that specific
    move."""
    opens, closes = df["open"].to_numpy(), df["close"].to_numpy()
    highs, lows = df["high"].to_numpy(), df["low"].to_numpy()
    n = len(df)
    blocks: list[OrderBlock] = []

    for event in structure_events:
        bullish = event.kind in (StructureEventKind.BOS_BULLISH, StructureEventKind.CHOCH_BULLISH)
        start = max(0, event.index - lookback_candles)
        found_idx = None
        for j in range(event.index - 1, start - 1, -1):
            if bullish and closes[j] < opens[j]:
                found_idx = j
                break
            if not bullish and closes[j] > opens[j]:
                found_idx = j
                break
        if found_idx is not None:
            # Breaker-block check (added 2026-08-20, see OrderBlock's own
            # docstring for provenance): scan FORWARD from the break bar
            # for the first later candle whose CLOSE trades clean through
            # the far side of the block's own [low, high] zone -- for a
            # bullish (support) block that means closing BELOW its low;
            # for a bearish (resistance) block, closing ABOVE its high.
            # A mere wick into the zone is a retest, not a failure -- this
            # deliberately mirrors detect_liquidity_sweeps' own "close,
            # not just wick" precision standard elsewhere in this module.
            breaker = False
            mitigated_index = None
            for k in range(event.index, n):
                if bullish and closes[k] < lows[found_idx]:
                    breaker, mitigated_index = True, k
                    break
                if not bullish and closes[k] > highs[found_idx]:
                    breaker, mitigated_index = True, k
                    break
            blocks.append(OrderBlock(
                index=found_idx,
                direction="bullish" if bullish else "bearish",
                open=float(opens[found_idx]), high=float(highs[found_idx]),
                low=float(lows[found_idx]), close=float(closes[found_idx]),
                breaker=breaker, mitigated_index=mitigated_index,
            ))

    return blocks


def _gap_filled(lows, highs, gap_index: int, gap_top: float, gap_bottom: float) -> bool:
    """True if any candle strictly after the 3-candle pattern that formed
    the gap has traded into [gap_bottom, gap_top] -- a partial fill still
    counts, matching how this is generally treated in practice (an FVG is
    considered 'touched' the moment price revisits any part of it).

    Real bug caught in testing: starting this scan at gap_index + 1 (the
    THIRD candle of the gap-forming triplet, i.e. candle[i+1] where
    gap_index=i) always reported filled=True regardless of real
    subsequent price action -- that candle's own high or low IS one of
    the gap's two boundary values by construction (it's what gap_top or
    gap_bottom was computed from), so it trivially "overlaps" itself.
    Verified directly against real EURUSD data: every single detected gap
    showed filled=True, including ones formed on the second-to-last bar
    of the dataset with almost no future price action to have actually
    filled them -- the tell that this was checking the gap's own
    defining candle, not real subsequent trading. Scanning from
    gap_index + 2 (the first candle strictly outside the pattern) fixes
    it."""
    for j in range(gap_index + 2, len(lows)):
        if lows[j] <= gap_top and highs[j] >= gap_bottom:
            return True
    return False


def _average_true_range(df: pd.DataFrame, period: int) -> pd.Series:
    """Same True Range formula as e07_technical.engine.TechnicalEngine.
    _add_atr -- duplicated here (not imported) since that method is a
    private helper on the indicator engine, not a shared utility, and
    this module already keeps its own small private helpers (_gap_filled)
    rather than reaching into a sibling module for one formula."""
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift()).abs(),
        (df["low"] - df["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def detect_fair_value_gaps(
    df: pd.DataFrame, min_gap_atr_multiple: float = 0.0, atr_period: int = 14,
) -> list[FairValueGap]:
    """A 3-candle imbalance: candle[i-1]'s high sits below candle[i+1]'s
    low (bullish FVG -- an untraded gap left behind by the impulsive
    middle candle) or the mirror image (bearish FVG). Every 3-candle
    window is checked independently -- gaps are not deduplicated or
    merged, since overlapping gaps from consecutive impulsive candles are
    real, distinct zones in ICT usage, not noise.

    Added 2026-08-21 (concept translated from NadirAliOfficial/
    STAR-EA-v11.20, MIT-licensed MQL5, DetectFVG ~L17490 -- code was
    rewritten from scratch in this module's own style, nothing copied):
    an optional ATR-relative minimum gap-size filter, `min_gap_atr_multiple`.
    Off by default (0.0 -- every nonzero 3-candle gap still counts,
    identical to this function's behavior before this change) so this is
    purely additive. STAR-EA's own code comment documents the real bug
    class this guards against: a FIXED minimum gap size tuned for one
    instrument (e.g. a few pips on a forex pair) becomes trivially loose
    on an instrument with a very different price scale (their example:
    XAUUSD, where a "few cents" gap is noise, not a real imbalance) --
    an ATR-relative floor scales correctly across instruments instead of
    needing a hand-tuned fixed threshold per asset. A bar whose ATR isn't
    warmed up yet (the first `atr_period` bars) never passes the filter --
    skipped, not guessed, same "don't fabricate data" convention as the
    rest of this codebase."""
    highs, lows = df["high"].to_numpy(), df["low"].to_numpy()
    n = len(df)
    gaps: list[FairValueGap] = []

    atr = _average_true_range(df, atr_period).to_numpy() if min_gap_atr_multiple > 0 else None

    def _large_enough(gap_size: float, i: int) -> bool:
        if atr is None:
            return True
        bar_atr = atr[i]
        return bar_atr == bar_atr and gap_size >= bar_atr * min_gap_atr_multiple  # bar_atr==bar_atr is a NaN check

    for i in range(1, n - 1):
        if highs[i - 1] < lows[i + 1]:
            gap_bottom, gap_top = highs[i - 1], lows[i + 1]
            if not _large_enough(gap_top - gap_bottom, i):
                continue
            gaps.append(FairValueGap(
                index=i, direction="bullish",
                gap_top=float(gap_top), gap_bottom=float(gap_bottom),
                filled=_gap_filled(lows, highs, i, gap_top, gap_bottom),
            ))
        elif lows[i - 1] > highs[i + 1]:
            gap_top, gap_bottom = lows[i - 1], highs[i + 1]
            if not _large_enough(gap_top - gap_bottom, i):
                continue
            gaps.append(FairValueGap(
                index=i, direction="bearish",
                gap_top=float(gap_top), gap_bottom=float(gap_bottom),
                filled=_gap_filled(lows, highs, i, gap_top, gap_bottom),
            ))

    return gaps


# --------------------------------------------------------------------------
# Displacement and Market Structure Shift
#
# PORTED FROM research/ict_concepts.py 2026-09-08. Promoted on measured
# evidence, not on being available: research/ablation_{BTCUSD,ETHUSD,GOLD}_4h
# scored MSS positive on all three assets (+0.474 / +0.915 / +0.015) over
# 69 / 69 / 46 trades -- the only concept still stranded in research/ that
# was both positive everywhere AND had trade counts above the 60-trade floor
# Stage 0 adopted. See docs/ICT_CONCEPT_DIFF.md for the full triage, and for
# why the other 16 stranded concepts were NOT ported (most measured
# negative; porting them would subtract expectancy).
#
# NOTE ON `displacement`. As a SOLO signal it measured negative on all three
# assets (-0.171 / -0.019 / -0.063), so it is deliberately not surfaced as a
# tradeable concept anywhere -- it exists here only as MSS's confirmation
# filter, which is the role it was measured in. Do not promote it to a
# signal on the strength of it living in engines/ now.
# --------------------------------------------------------------------------
def displacement(
    df: pd.DataFrame, atr_period: int = 14, atr_mult: float = 1.5, body_ratio: float = 0.6
) -> pd.Series:
    """Impulsive one-sided expansion. +1 bullish / -1 bearish / 0 none.

    Displacement is not merely "a big candle": ICT treats it as an
    impulsive, one-sided expansion. Both conditions are required -- range
    must exceed `atr_mult` x ATR AND the body must be at least `body_ratio`
    of that range. Without the body test a huge two-sided indecision bar
    (long wicks, tiny body) would register as displacement, which is the
    opposite of what the concept means.

    Causal by construction: every input is that bar's own OHLC or a
    trailing ATR, so no value depends on a later bar.
    """
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    rng = h - l
    # Reuses this module's existing ATR helper rather than recomputing True
    # Range inline as the research original did. Verified numerically
    # identical -- same TR definition, same rolling mean -- so the ported
    # concept is the one the ablation actually measured.
    atr = _average_true_range(df, atr_period).to_numpy(float)

    body = np.abs(c - o)
    with np.errstate(divide="ignore", invalid="ignore"):
        strong = (rng > atr_mult * atr) & (body / np.where(rng == 0, np.nan, rng) >= body_ratio)
    out = np.zeros(len(df), dtype=np.int8)
    out[strong & (c > o)] = 1
    out[strong & (c < o)] = -1
    return pd.Series(out, index=df.index, dtype=int)


def market_structure_shift(
    df: pd.DataFrame, lookback: int = 5, atr_mult: float = 1.5, confirm_bars: int = 3
) -> pd.Series:
    """MSS: a structure break CONFIRMED by displacement. +1 / -1 / 0.

    This is precisely what distinguishes MSS from a plain CHoCH in ICT
    usage. A CHoCH is any close beyond the prior swing; an MSS additionally
    requires the break to be delivered with force. A structure break that
    drifts across the level on small indecisive candles is exactly the
    break that tends to fail, and this filter is what excludes it.

    The confirmation window looks BACKWARD only -- `disp[e.index -
    confirm_bars : e.index + 1]` -- so a shift is confirmed by displacement
    at or before its own bar, never by a later one. That bound is what
    makes this safe to evaluate bar-by-bar in a live signal, and it is
    asserted directly by the multi-truncation tests in
    tests/unit/test_market_structure_shift.py.
    """
    disp = displacement(df, atr_mult=atr_mult).to_numpy()
    events = detect_structure_events(df, lookback=lookback)
    out = np.zeros(len(df), dtype=np.int8)
    for e in events:
        want = 1 if e.kind in (StructureEventKind.BOS_BULLISH, StructureEventKind.CHOCH_BULLISH) else -1
        lo = max(0, e.index - confirm_bars)
        window = disp[lo:e.index + 1]
        if np.any(window == want):
            out[e.index] = want
    return pd.Series(out, index=df.index, dtype=int)
