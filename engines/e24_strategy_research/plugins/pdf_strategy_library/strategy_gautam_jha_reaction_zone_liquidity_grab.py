"""
Module: strategy_gautam_jha_reaction_zone_liquidity_grab.py
Source document(s): GAUTAM JHA TRADING STRATEGY.txt
Description: "StockLearner (Gautam Jha) - Precise Entry Trading Strategy". In an uptrend, mark
the low/high of a red (bearish) candle that prints between green candles as a reaction zone.
When price later returns to that zone and takes liquidity (wicks through the zone low and
closes back above it), a strong green confirmation candle closing back above the zone's high
triggers a BUY. This is a genuinely different mechanic from the previous-day-high/low breakout
rule already covered elsewhere in this project (GAUTAM JHA STRATEGY.txt / batch2) -- this
document never mentions PDH/PDL at all; the trigger zone is an arbitrary red candle inside an
active uptrend, not a fixed daily level.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_gautam_jha_reaction_zone_liquidity_grab(
    enriched: pd.DataFrame,
    body_ratio_threshold: float = 0.60,
    zone_lookback: int = 40,
) -> pd.Series:
    """Uptrend red-candle reaction zone -> liquidity grab -> strong green confirmation.

    Source document: "GAUTAM JHA TRADING STRATEGY.txt" (StockLearner / Gautam Jha "Precise
    Entry Trading"). Rule: in an uptrend, find a red candle printed between green candles and
    mark its [low, high] as a reaction zone. Wait for price to come back to that zone. If price
    wicks below the zone low (liquidity grab) and then closes back above the zone with a strong
    green candle (body >= body_ratio_threshold of range), enter LONG. Stop loss is implied
    below the reaction zone (left to the platform's own R:R engine, per interface spec -- not
    implemented here).

    Interpretive assumptions:
    - "Uptrend" (document: "consecutive green candles moving upward") is proxied as
      close > ema_21 and ema_21 > ema_50, the same EMA-stack convention already used for this
      trader's style elsewhere in this project (there is no literal "consecutive green candle
      count" column available).
    - "Important level of the red candle" = the candle's full [low, high] range.
    - "Liquidity grab" = a later bar's low trades below the zone low (sweeping resting stops)
      and closes back above it in the same bar, while still inside `zone_lookback` bars of the
      zone being marked (bounds how long a stale zone stays "live").
    - "Strong green candle" = body >= body_ratio_threshold of the candle's high-low range (the
      0.60 convention already used for "strong candle" elsewhere in this project).
    - The document explicitly only describes a BUY workflow ("Plan Your Buy Entry"). The SELL
      side implemented here (downtrend + green-candle zone + liquidity grab above + strong red
      confirmation) is an interpretive, symmetric mirror added so the function produces a
      genuinely two-sided signal; it is NOT stated in the source text -- flagged explicitly.
    - Exit uses a break back beyond the zone that sourced the active trade as a structural
      invalidation (a document-implied stop, distinct from R:R sizing which is external).
    """
    o = enriched["open"].to_numpy(dtype=float)
    h = enriched["high"].to_numpy(dtype=float)
    l = enriched["low"].to_numpy(dtype=float)
    c = enriched["close"].to_numpy(dtype=float)
    ema21 = enriched["ema_21"].to_numpy(dtype=float)
    ema50 = enriched["ema_50"].to_numpy(dtype=float)
    n = len(enriched)

    rng = h - l
    body = np.abs(c - o)
    with np.errstate(divide="ignore", invalid="ignore"):
        body_ratio = np.where(rng > 0, body / rng, 0.0)
    body_ratio = np.nan_to_num(body_ratio, nan=0.0)
    is_green = c > o
    is_red = c < o
    uptrend = (c > ema21) & (ema21 > ema50)
    downtrend = (c < ema21) & (ema21 < ema50)

    entry_long = np.zeros(n, dtype=bool)
    entry_short = np.zeros(n, dtype=bool)
    exit_long = np.zeros(n, dtype=bool)
    exit_short = np.zeros(n, dtype=bool)

    # long-side state machine: 0=seeking zone, 1=zone marked (awaiting sweep), 2=swept (awaiting confirm)
    long_state = 0
    zl_low = zl_high = np.nan
    zl_bar = -1
    active_long_ref = np.nan

    # short-side mirror
    short_state = 0
    zs_low = zs_high = np.nan
    zs_bar = -1
    active_short_ref = np.nan

    for i in range(2, n):
        # ---------------- LONG side ----------------
        if long_state == 0:
            if uptrend[i] and is_red[i]:
                zl_low, zl_high, zl_bar = l[i], h[i], i
                long_state = 1
        elif long_state == 1:
            if (i - zl_bar) > zone_lookback or not uptrend[i]:
                long_state = 0
            elif l[i] < zl_low and c[i] > zl_low:
                long_state = 2
        elif long_state == 2:
            if (i - zl_bar) > zone_lookback:
                long_state = 0
            elif is_green[i] and body_ratio[i] >= body_ratio_threshold and c[i] > zl_high:
                entry_long[i] = True
                active_long_ref = zl_low
                long_state = 0

        if not np.isnan(active_long_ref) and c[i] < active_long_ref:
            exit_long[i] = True
            active_long_ref = np.nan

        # ---------------- SHORT side (mirror) ----------------
        if short_state == 0:
            if downtrend[i] and is_green[i]:
                zs_low, zs_high, zs_bar = l[i], h[i], i
                short_state = 1
        elif short_state == 1:
            if (i - zs_bar) > zone_lookback or not downtrend[i]:
                short_state = 0
            elif h[i] > zs_high and c[i] < zs_high:
                short_state = 2
        elif short_state == 2:
            if (i - zs_bar) > zone_lookback:
                short_state = 0
            elif is_red[i] and body_ratio[i] >= body_ratio_threshold and c[i] < zs_low:
                entry_short[i] = True
                active_short_ref = zs_high
                short_state = 0

        if not np.isnan(active_short_ref) and c[i] > active_short_ref:
            exit_short[i] = True
            active_short_ref = np.nan

    idx = enriched.index
    entry_long_s = pd.Series(entry_long, index=idx)
    exit_long_s = pd.Series(exit_long, index=idx)
    entry_short_s = pd.Series(entry_short, index=idx)
    exit_short_s = pd.Series(exit_short, index=idx)

    return _stateful_from_entries_exits(entry_long_s, exit_long_s, entry_short_s, exit_short_s)
