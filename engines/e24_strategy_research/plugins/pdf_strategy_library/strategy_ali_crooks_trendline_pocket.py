"""
Module: strategy_ali_crooks_trendline_pocket.py
Source document(s): Ali Crooks Playbook.txt
Description: "Trendline Break Pocket" swing strategy. Price extends into a higher-timeframe key
level, a trendline break + break of the prior swing confirm a momentum shift (the "Pocket"),
then price either pulls back to the 21 EMA (primary/Entry Type 1) or breaks out of a tight
post-shift consolidation (Entry Type 2, simplified -- see below) to trigger the trade. Targets
2R with a stop at half the distance to target; those are position-sizing details out of scope
for this function per interface-spec rule 7 -- only entry/exit DIRECTION is implemented.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_ali_crooks_trendline_pocket(
    enriched: pd.DataFrame,
    key_level_lookback: int = 50,
    key_level_atr: float = 1.0,
    structure_lookback: int = 10,
    pocket_window: int = 15,
    consolidation_lookback: int = 6,
    tight_range_atr_mult: float = 2.0,
    invalidation_atr: float = 0.75,
) -> pd.Series:
    """Ali Crooks "Trendline Break Pocket" swing reversal setup (Ali Crooks Playbook.txt).

    Source rule (plain English): a trade is only valid when, in sequence: (1) price has
    extended into a higher-timeframe key support/resistance level, (2) a trendline break and a
    break of the prior swing high/low confirm a genuine momentum shift (together = "the
    Pocket"), then (3) price gives one of two controlled entries -- a pullback into the 21 EMA
    (the playbook's primary entry), or a breakout from a small consolidation that forms on the
    correct side of the broken structure. Base model targets 2R with a stop at half the distance
    to target (~58% documented win rate) -- sizing is out of scope here per interface-spec
    rule 7; only the entry/exit DIRECTION is implemented.

    Interpretive assumptions:
      - "21-period moving average" -> `ema_21` (exact match, no approximation needed).
      - "Higher-timeframe key level" approximated with a rolling `key_level_lookback`-bar
        high/low (shifted so the level is always fixed before the current bar); "price has
        reached" it = close within `key_level_atr` ATR of that rolling extreme.
      - "Trendline break + break of the last swing" (a genuinely discretionary, chart-drawn
        concept) is approximated mechanically as: price closes beyond a shorter
        `structure_lookback`-bar rolling swing high/low -- i.e. a structural break, which is the
        doc's own stated *effect* of a valid trendline break ("this confirms a real momentum
        shift"). The Pocket stays "active" for `pocket_window` bars while waiting for an entry
        trigger.
      - Entry Type 2 ("breakout from consolidation... at least two highs, two lows") is
        approximated as a breakout of a tight (`consolidation_lookback`-bar range <=
        `tight_range_atr_mult` * ATR) post-shift range, rather than exact pivot-counting -- a
        simplification, documented here rather than left unstated.
      - Optional filters the doc lists as NOT increasing win rate (MACD divergence, retail
        sentiment positioning) are intentionally not implemented: no retail-positioning data
        exists in this platform's columns, and the doc itself frames them as optional target-
        extension filters, not entry/exit triggers.
      - Exit: the doc explicitly wants "no micromanagement, no trailing, no early exits" once in
        a 2R trade, so the only mechanical exit implemented is thesis invalidation -- price
        closes back through the 21 EMA pullback zone by more than `invalidation_atr` ATR in the
        wrong direction.

    Returns:
        pd.Series[int] in {-1, 0, 1}, same index as `enriched`.
    """
    open_ = enriched["open"]; high = enriched["high"]; low = enriched["low"]; close = enriched["close"]
    atr = enriched["atr"].replace(0, np.nan)
    ema21 = enriched["ema_21"]

    rolling_high_prior = high.shift(1).rolling(key_level_lookback).max()
    rolling_low_prior = low.shift(1).rolling(key_level_lookback).min()
    at_key_high = close >= (rolling_high_prior - key_level_atr * atr)
    at_key_low = close <= (rolling_low_prior + key_level_atr * atr)

    recent_swing_low = low.shift(1).rolling(structure_lookback).min()
    recent_swing_high = high.shift(1).rolling(structure_lookback).max()
    momentum_shift_down = close < recent_swing_low
    momentum_shift_up = close > recent_swing_high

    pocket_active_short = (
        at_key_high.shift(1).rolling(pocket_window, min_periods=1).max().fillna(0).astype(bool)
        & momentum_shift_down.shift(1).rolling(pocket_window, min_periods=1).max().fillna(0).astype(bool)
    )
    pocket_active_long = (
        at_key_low.shift(1).rolling(pocket_window, min_periods=1).max().fillna(0).astype(bool)
        & momentum_shift_up.shift(1).rolling(pocket_window, min_periods=1).max().fillna(0).astype(bool)
    )

    # Entry Type 1 -- pullback into the 21 EMA (the playbook's primary entry)
    touch_ema = (low <= ema21) & (high >= ema21)
    bearish_at_ema = touch_ema & (close < ema21) & (close < open_)
    bullish_at_ema = touch_ema & (close > ema21) & (close > open_)
    entry_short_type1 = pocket_active_short & bearish_at_ema
    entry_long_type1 = pocket_active_long & bullish_at_ema

    # Entry Type 2 -- breakout from a tight post-shift consolidation (simplified, see docstring)
    consolidation_high = high.shift(1).rolling(consolidation_lookback).max()
    consolidation_low = low.shift(1).rolling(consolidation_lookback).min()
    is_tight = (consolidation_high - consolidation_low) <= (tight_range_atr_mult * atr)
    entry_short_type2 = pocket_active_short & is_tight & (close < consolidation_low)
    entry_long_type2 = pocket_active_long & is_tight & (close > consolidation_high)

    entry_short = (entry_short_type1 | entry_short_type2).fillna(False)
    entry_long = (entry_long_type1 | entry_long_type2).fillna(False)

    exit_long = (close < (ema21 - invalidation_atr * atr)).fillna(False)
    exit_short = (close > (ema21 + invalidation_atr * atr)).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
