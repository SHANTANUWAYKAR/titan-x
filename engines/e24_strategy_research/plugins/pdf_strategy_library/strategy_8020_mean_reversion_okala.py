"""
Module: strategy_8020_mean_reversion_okala.py
Source document(s): 8020-mean-reversion-okala.txt
Description: Okala's "8020" Nasdaq-futures mean-reversion system. Price levels ending in 80 or
20 (e.g. 25,680 / 25,620) act as reaction points; three of the document's four entry patterns
are directly implementable from OHLCV structure (Fork, H-Pattern, Cross-Section) and are
implemented below. The fourth "pattern" (Repair Candles) is explicitly a TARGET/price-magnet
concept in the source document, not an entry trigger ("targets, not entries"), so it produces
no standalone signal and is intentionally not implemented as an entry rule -- consistent with
interface-spec rule 7 (this function's job is entry/exit direction, not target selection).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def _distance_to_8020_grid(price: pd.Series, step: float, low_offset: float, high_offset: float) -> pd.Series:
    """Elementwise distance from `price` to the nearest ...low_offset/high_offset (mod step)
    grid point, e.g. the nearest price ending in 80 or 20 for step=100. Pure pointwise
    arithmetic -- carries no lookahead of its own; safety depends on what `price` the caller
    passes in (current-bar vs `.shift()`-ed)."""
    mod = price.mod(step)
    candidates = [low_offset - step, high_offset - step, low_offset, high_offset, low_offset + step, high_offset + step]
    dists = pd.concat([(mod - c).abs() for c in candidates], axis=1)
    return dists.min(axis=1)


def strategy_8020_mean_reversion_okala(
    enriched: pd.DataFrame,
    level_step: float = 100.0,
    level_low_offset: float = 20.0,
    level_high_offset: float = 80.0,
    level_tolerance: float = 3.0,
    momentum_lookback: int = 3,
    momentum_atr_mult: float = 1.2,
    initiation_body_ratio: float = 0.35,
    initiation_wick_ratio: float = 0.5,
    approach_atr_mult: float = 0.5,
    bounce_lookback: int = 6,
    cross_section_offset: int = 2,
    rejection_wick_ratio: float = 0.4,
    apply_session_filter: bool = True,
    ny_session_start_utc_hour: int = 13,
    ny_session_end_utc_hour: int = 20,
    lunch_start_utc_hour: float = 16.0,
    lunch_end_utc_hour: float = 17.5,
) -> pd.Series:
    """Okala 8020 Nasdaq mean-reversion: Fork / H-Pattern / Cross-Section entries
    (8020-mean-reversion-okala.txt).

    Source rule (plain English): NQ futures reliably react at price levels ending in 80/20.
    This is mean reversion, not trend following. Three entry patterns:
      1. FORK (long): a sharp down move prints an "initiation candle" (small body, long lower
         wick = exhaustion) near an 80/20 level; the next candle dips to test that candle's low,
         FAILS to break it, and turns back up -> enter long.
      2. H-PATTERN (short): a sharp drop, a bounce that FAILS to make a higher high than the
         pre-drop swing high, then a rollover back down near an 80/20 level -> enter short.
      3. CROSS-SECTION (either direction): two adjacent same-direction candles whose ranges
         overlap create a confluence zone; price pulls back into that zone, prints a rejection
         candle, and reverses -> enter in the rejection direction.
    Static 10-point stop / scaled 15-30-60+pt targets are position-sizing detail, out of scope
    for this function (interface-spec rule 7) -- only entry/exit DIRECTION is implemented.

    Interpretive assumptions (all documented per interface-spec rule 3):
      - "Price levels ending in 80/20" is generalized to `price mod level_step` landing within
        `level_tolerance` of `level_low_offset`/`level_high_offset` -- meaningful mainly for
        point-scaled instruments like index futures (the doc's own NQ use case); for very
        differently-scaled instruments this filter will rarely or never engage, which is
        expected/honest rather than a bug.
      - The doc's dual-timeframe design (10-min structure + 200-sec entry) is approximated onto
        the single timeframe this function actually receives per call.
      - No indicators are used (matches the source: "No indicators used -- pure price
        action/structure reading"), only OHLC-derived structure.
      - Exit: the doc's real exits are fixed point-distance scale-outs (position sizing, out of
        scope). As a directional-signal proxy for "reverts toward the middle of the range", the
        session `vwap` is used as the mean-reversion completion level: closing back through vwap
        exits the position.
      - "Session: NY open only, avoid lunch hour" is implemented as an optional UTC-hour filter
        (`apply_session_filter`); the default UTC hours approximate NY late-morning/afternoon
        without DST adjustment (documented limitation -- the platform gives tz-aware UTC
        timestamps but proper US Eastern DST handling was not implemented here).

    Returns:
        pd.Series[int] in {-1, 0, 1}, same index as `enriched`.
    """
    open_ = enriched["open"]; high = enriched["high"]; low = enriched["low"]; close = enriched["close"]
    atr = enriched["atr"].replace(0, np.nan)
    vwap = enriched["vwap"]

    # ---- FORK setup (long): exhaustion candle near an 80/20 level, failed retest, reversal ----
    sharp_down_into_init = (close.shift(momentum_lookback + 1) - close.shift(1)) > (momentum_atr_mult * atr.shift(1))
    init_open = open_.shift(1); init_close = close.shift(1); init_high = high.shift(1); init_low = low.shift(1)
    init_range = (init_high - init_low).replace(0, np.nan)
    init_body = (init_close - init_open).abs()
    init_lower_wick = pd.concat([init_open, init_close], axis=1).min(axis=1) - init_low
    init_is_exhaustion = (init_body <= initiation_body_ratio * init_range) & (init_lower_wick >= initiation_wick_ratio * init_range)
    init_near_level = _distance_to_8020_grid(init_low, level_step, level_low_offset, level_high_offset) <= level_tolerance
    approached_low = low <= (init_low + approach_atr_mult * atr)
    failed_break_low = (low >= init_low) & (close > init_low) & (close > open_)

    entry_long_fork = (
        sharp_down_into_init & init_is_exhaustion & init_near_level & approached_low & failed_break_low
    ).fillna(False)

    # ---- H-PATTERN (short): drop, bounce fails to exceed pre-drop swing high, rollover ----
    pre_bounce_shift = bounce_lookback + 1
    sharp_down_before_bounce = (
        close.shift(pre_bounce_shift + momentum_lookback) - close.shift(pre_bounce_shift)
    ) > (momentum_atr_mult * atr.shift(pre_bounce_shift))
    swing_high_ref = high.shift(pre_bounce_shift).rolling(momentum_lookback, min_periods=1).max()
    bounce_high = high.shift(1).rolling(bounce_lookback, min_periods=1).max()
    failed_to_exceed = bounce_high < swing_high_ref
    rollover_now = (close < close.shift(1)) & (high <= bounce_high)
    failed_high_near_level = _distance_to_8020_grid(bounce_high, level_step, level_low_offset, level_high_offset) <= level_tolerance

    entry_short_h = (
        sharp_down_before_bounce & failed_to_exceed & rollover_now & failed_high_near_level
    ).fillna(False)

    # ---- CROSS-SECTION (either direction): overlap of two adjacent same-direction candles ----
    csA_open = open_.shift(cross_section_offset + 1); csA_close = close.shift(cross_section_offset + 1)
    csA_high = high.shift(cross_section_offset + 1); csA_low = low.shift(cross_section_offset + 1)
    csB_open = open_.shift(cross_section_offset); csB_close = close.shift(cross_section_offset)
    csB_high = high.shift(cross_section_offset); csB_low = low.shift(cross_section_offset)

    both_bearish = (csA_close < csA_open) & (csB_close < csB_open)
    both_bullish = (csA_close > csA_open) & (csB_close > csB_open)
    overlap_low = pd.concat([csA_low, csB_low], axis=1).max(axis=1)
    overlap_high = pd.concat([csA_high, csB_high], axis=1).min(axis=1)
    valid_overlap = overlap_high > overlap_low
    overlap_mid = (overlap_high + overlap_low) / 2.0
    overlap_near_level = _distance_to_8020_grid(overlap_mid, level_step, level_low_offset, level_high_offset) <= level_tolerance

    pulled_into_zone = (low <= overlap_high) & (high >= overlap_low)
    rng = (high - low).replace(0, np.nan)
    bearish_rejection = (close < open_) & ((high - close) >= rejection_wick_ratio * rng) & (close < overlap_low)
    bullish_rejection = (close > open_) & ((close - low) >= rejection_wick_ratio * rng) & (close > overlap_high)

    entry_short_cs = (both_bearish & valid_overlap & overlap_near_level & pulled_into_zone & bearish_rejection).fillna(False)
    entry_long_cs = (both_bullish & valid_overlap & overlap_near_level & pulled_into_zone & bullish_rejection).fillna(False)

    entry_long = (entry_long_fork | entry_long_cs).fillna(False)
    entry_short = (entry_short_h | entry_short_cs).fillna(False)

    if apply_session_filter:
        hour = enriched["timestamp"].dt.hour + enriched["timestamp"].dt.minute / 60.0
        in_session = (hour >= ny_session_start_utc_hour) & (hour <= ny_session_end_utc_hour)
        in_lunch = (hour >= lunch_start_utc_hour) & (hour <= lunch_end_utc_hour)
        session_ok = (in_session & ~in_lunch).fillna(False)
        entry_long = entry_long & session_ok
        entry_short = entry_short & session_ok

    # mean-reversion "back toward the middle" proxy: session VWAP
    exit_long = (close > vwap).fillna(False)
    exit_short = (close < vwap).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
