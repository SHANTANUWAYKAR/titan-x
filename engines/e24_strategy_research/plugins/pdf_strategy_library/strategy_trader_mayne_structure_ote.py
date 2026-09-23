"""
Module: strategy_trader_mayne_structure_ote.py
Source document(s): Trader Mayne Playbook.txt
Description: "Structure & OTE" -- higher-timeframe (HTF) break-of-structure defines trend and a
Point-of-Interest (POI)/discount-premium zone; price pulling back into that POI on a lower
timeframe (LTF), sweeping local liquidity and reclaiming structure, is the entry. Approximated on
a single-resolution DataFrame by treating "HTF" as a long rolling lookback (trend + range/50%
line) and "LTF" as a short rolling lookback (the local liquidity sweep + reclaim), using ema_50
vs ema_200 as the HTF bias filter (a standard, available proxy for "a clear market structure
trend").
"""
from __future__ import annotations
import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_trader_mayne_structure_ote(
    enriched: pd.DataFrame,
    htf_window: int = 100,
    ltf_window: int = 10,
) -> pd.Series:
    """HTF trend + discount/premium POI + LTF liquidity-sweep reclaim (Trader Mayne Playbook.txt,
    "Structure & OTE").

    Source document rule: on the higher timeframe, confirm trend via a market structure break,
    mark the swing range and its 50% line (discount = lower half, premium = upper half), and mark
    a Point of Interest (Order Block / Breaker / FVG) where price should pull back to. On the
    lower timeframe, wait for price to reach that POI, sweep local liquidity, and reclaim
    structure -- that reclaim is the entry. Target = the next HTF external liquidity (opposite
    swing extreme).

    Approximation (single-resolution `enriched`): "HTF" = a long `htf_window`-bar rolling
    lookback; "LTF" = a short `ltf_window`-bar rolling lookback on the SAME series (both windows
    always `.shift(1)`-ed before use, so all levels are fixed using bars strictly before the
    current one). HTF trend/bias uses ema_50 vs ema_200 (the closest available proxy for "a clear
    higher-timeframe structure trend") rather than a hand-identified structure break. The POI /
    discount-premium zone is the HTF range's 50% line. The LTF "engineered liquidity sweep +
    reclaim" is a short-lookback rolling extreme that gets pierced intrabar then closed back
    beyond, in the direction of the HTF trend, while price is inside the discount (uptrend) or
    premium (downtrend) half of the HTF range.

    Entry (long): ema_50 > ema_200 (bullish HTF bias) AND close is in the discount half of the
    HTF range (below the HTF midpoint) AND the LTF low swept below the prior `ltf_window`-bar low
    but closed back above it (local liquidity sweep + reclaim). Entry (short): mirror image
    (bearish HTF bias, premium half, LTF high sweep + reclaim down).
    Exit: HTF bias flips (ema_50/ema_200 cross), or price reaches the opposite HTF range extreme
    (the "next external liquidity" target).
    """
    close = enriched["close"]
    high = enriched["high"]
    low = enriched["low"]
    ema_50 = enriched["ema_50"]
    ema_200 = enriched["ema_200"]

    htf_high = high.shift(1).rolling(htf_window).max()
    htf_low = low.shift(1).rolling(htf_window).min()
    htf_mid = (htf_high + htf_low) / 2.0

    bullish_bias = ema_50 > ema_200
    bearish_bias = ema_50 < ema_200

    in_discount = close < htf_mid
    in_premium = close > htf_mid

    ltf_low_level = low.shift(1).rolling(ltf_window).min()
    ltf_high_level = high.shift(1).rolling(ltf_window).max()

    ltf_sweep_reclaim_up = (low < ltf_low_level) & (close > ltf_low_level)
    ltf_sweep_reclaim_down = (high > ltf_high_level) & (close < ltf_high_level)

    entry_long = bullish_bias & in_discount & ltf_sweep_reclaim_up
    entry_short = bearish_bias & in_premium & ltf_sweep_reclaim_down

    exit_long = bearish_bias | (close >= htf_high)
    exit_short = bullish_bias | (close <= htf_low)

    entry_long = entry_long.fillna(False)
    entry_short = entry_short.fillna(False)
    exit_long = exit_long.fillna(False)
    exit_short = exit_short.fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
