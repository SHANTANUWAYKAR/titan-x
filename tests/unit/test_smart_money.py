"""
Module: test_smart_money.py
Description: Unit tests for engines/e07_technical/smart_money.py -- added
    2026-08-20 alongside the new breaker-block (order-block invalidation/
    polarity-flip) tracking; see OrderBlock's own docstring for
    provenance. No dedicated test file existed for this module before;
    these tests cover the new breaker-block behavior specifically, not a
    retroactive full backfill of BOS/CHoCH/liquidity-sweep/FVG detection
    (those already have real, live verification on record per this
    module's own docstring -- 99-book-corpus-informed, checked against
    real EURUSD data during the module's original build).
Author: Shantanu Waykar
Version: 1.0.0
"""

import pandas as pd

from project_titan_x.engines.e07_technical.smart_money import (
    StructureEvent,
    StructureEventKind,
    detect_fair_value_gaps,
    detect_order_blocks,
)


def _ohlc(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    """rows: list of (open, high, low, close)."""
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"])


def test_bullish_order_block_becomes_breaker_when_later_close_breaks_below_its_low():
    # Bar 0: the bearish order-block candle (close < open) -- low=95, high=99.
    # Bar 1: the impulsive break bar (index 1, matches the StructureEvent below).
    # Bar 5: a LATER candle whose CLOSE trades clean below bar 0's low (95) -- must flip to breaker.
    rows = [
        (99.0, 99.0, 95.0, 96.0),   # 0: order-block candle (bearish body)
        (96.0, 110.0, 96.0, 108.0),  # 1: impulsive bullish break bar
        (108.0, 109.0, 105.0, 106.0),
        (106.0, 107.0, 100.0, 101.0),
        (101.0, 102.0, 97.0, 98.0),
        (98.0, 99.0, 90.0, 92.0),    # 5: closes (92) clean below bar 0's low (95) -> breaker
    ]
    df = _ohlc(rows)
    events = [StructureEvent(index=1, kind=StructureEventKind.BOS_BULLISH, broken_level=99.0)]
    blocks = detect_order_blocks(df, events, lookback_candles=10)
    assert len(blocks) == 1
    ob = blocks[0]
    assert ob.index == 0
    assert ob.direction == "bullish"
    assert ob.breaker is True
    assert ob.mitigated_index == 5


def test_bullish_order_block_not_a_breaker_on_mere_wick_retest():
    """A wick INTO the zone (low dips below the block's low) without the
    CANDLE'S CLOSE breaking through is a retest, not a failure -- must
    stay breaker=False, mirroring detect_liquidity_sweeps' own
    close-vs-wick precision standard elsewhere in this module."""
    rows = [
        (99.0, 99.0, 95.0, 96.0),    # 0: order-block candle, low=95
        (96.0, 110.0, 96.0, 108.0),   # 1: impulsive break bar
        (108.0, 109.0, 105.0, 106.0),
        (106.0, 107.0, 93.0, 105.0),  # 3: wicks to 93 (below 95) but CLOSES at 105 -- not a breaker
    ]
    df = _ohlc(rows)
    events = [StructureEvent(index=1, kind=StructureEventKind.BOS_BULLISH, broken_level=99.0)]
    blocks = detect_order_blocks(df, events, lookback_candles=10)
    assert len(blocks) == 1
    assert blocks[0].breaker is False
    assert blocks[0].mitigated_index is None


def test_bearish_order_block_becomes_breaker_when_later_close_breaks_above_its_high():
    rows = [
        (95.0, 99.0, 95.0, 98.0),     # 0: order-block candle (bullish body), high=99
        (98.0, 98.0, 85.0, 87.0),      # 1: impulsive bearish break bar
        (87.0, 90.0, 86.0, 89.0),
        (89.0, 105.0, 89.0, 102.0),    # 3: closes (102) clean above bar 0's high (99) -> breaker
    ]
    df = _ohlc(rows)
    events = [StructureEvent(index=1, kind=StructureEventKind.BOS_BEARISH, broken_level=85.0)]
    blocks = detect_order_blocks(df, events, lookback_candles=10)
    assert len(blocks) == 1
    ob = blocks[0]
    assert ob.direction == "bearish"
    assert ob.breaker is True
    assert ob.mitigated_index == 3


def test_order_block_stays_valid_with_no_later_violation():
    rows = [
        (99.0, 99.0, 95.0, 96.0),
        (96.0, 110.0, 96.0, 108.0),
        (108.0, 112.0, 106.0, 110.0),
        (110.0, 115.0, 108.0, 113.0),
    ]
    df = _ohlc(rows)
    events = [StructureEvent(index=1, kind=StructureEventKind.BOS_BULLISH, broken_level=99.0)]
    blocks = detect_order_blocks(df, events, lookback_candles=10)
    assert len(blocks) == 1
    assert blocks[0].breaker is False
    assert blocks[0].mitigated_index is None


def _ohlc_with_close(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"])


def test_min_gap_atr_multiple_default_zero_keeps_every_prior_behavior():
    """min_gap_atr_multiple=0.0 is the default and must reproduce the
    exact set of gaps detect_fair_value_gaps found before this parameter
    was added -- including a trivially tiny one, which a real ATR filter
    would reject."""
    rows = [
        (100.0, 100.5, 99.5, 100.0),
        (100.0, 102.0, 101.9, 101.95),   # tiny impulsive candle
        (101.95, 102.5, 101.91, 102.3),  # gap: bar0 high (100.5) < bar2 low (101.91) -- huge gap, not the tiny one
    ]
    df = _ohlc_with_close(rows)
    gaps_default = detect_fair_value_gaps(df)
    gaps_explicit_zero = detect_fair_value_gaps(df, min_gap_atr_multiple=0.0)
    assert gaps_default == gaps_explicit_zero
    assert len(gaps_default) == 1


def test_min_gap_atr_multiple_filters_out_a_gap_smaller_than_the_atr_floor():
    """A real, non-noise-sized gap should survive a modest ATR filter;
    an artificially tiny gap on the same data should not."""
    # 20 warm-up bars with ~2.0 true range each so ATR(14) has a real,
    # stable value by the time the FVG-forming triplet arrives.
    rows = [(100.0 + i * 0.1, 100.0 + i * 0.1 + 1.0, 100.0 + i * 0.1 - 1.0, 100.0 + i * 0.1) for i in range(20)]
    base = rows[-1][3]
    # Triplet forming a bullish FVG only ~0.05 wide -- far smaller than
    # the ~2.0 ATR established by the warm-up bars above.
    rows += [
        (base, base + 0.2, base - 0.2, base + 0.1),
        (base + 0.1, base + 0.3, base + 0.25, base + 0.28),
        (base + 0.28, base + 0.5, base + 0.30, base + 0.45),  # bar[-3] high=base+0.2 < bar[-1] low=base+0.30
    ]
    df = _ohlc_with_close(rows)

    gaps_unfiltered = detect_fair_value_gaps(df)
    assert len(gaps_unfiltered) == 1  # the tiny gap is detected with no filter

    gaps_filtered = detect_fair_value_gaps(df, min_gap_atr_multiple=0.5, atr_period=14)
    assert gaps_filtered == []  # same tiny gap is rejected once it must clear 0.5x the real ~2.0 ATR


def test_min_gap_atr_multiple_skips_bars_before_atr_warms_up():
    """A gap inside the first atr_period bars has no real ATR reading yet
    (NaN) -- must be skipped (not fabricated as passing), never raise."""
    rows = [
        (100.0, 100.5, 99.5, 100.0),
        (100.0, 102.0, 101.9, 101.95),
        (101.95, 110.0, 101.91, 108.0),  # would be a large, real gap...
    ]
    df = _ohlc_with_close(rows)
    # ...but with only 3 bars total, ATR(14) is NaN everywhere -- must be filtered out, not crash.
    gaps = detect_fair_value_gaps(df, min_gap_atr_multiple=0.1, atr_period=14)
    assert gaps == []
