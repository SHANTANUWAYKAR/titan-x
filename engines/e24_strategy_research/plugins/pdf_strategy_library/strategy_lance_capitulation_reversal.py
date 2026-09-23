"""
Module: strategy_lance_capitulation_reversal.py
Source document(s): Lance PlayBook.txt
Description: Lance Breitstein's "Mean Reversion" playbook: wait for a capitulation move
(large range, high volume, price stretched beyond the Bollinger Bands after a directional
run), then enter on the break of the capitulation bar's high (long) or low (short) as
confirmation the reversal has begun, targeting reversion to equilibrium. The document
explicitly defines "equilibrium" as the 20-period moving average / center of the Bollinger
Bands, which is exactly `bb_middle` on this platform (no approximation needed there).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_lance_capitulation_reversal(
    enriched: pd.DataFrame,
    extreme_multiplier: float = 1.5,
    avg_window: int = 20,
    capitulation_recency: int = 3,
) -> pd.Series:
    """Lance Breitstein mean-reversion capitulation-reversal strategy.

    Source: Lance PlayBook.txt ("Lance Breitstein's Playbook - Mean Reversion Strategy").

    Rule (plain English): markets occasionally overshoot equilibrium via a fast,
    emotional/forced move (big candles, big volume, price far from the mean). The
    strategy does NOT try to pick the exact top/bottom -- it waits for the capitulation
    bar to print, then enters on the break of THAT bar's high (long, after a down-move)
    or low (short, after an up-move), i.e. "trading the right side of the reversal."
    Target is equilibrium, which the document itself defines as the 20-period moving
    average / center of the Bollinger Bands -- this is literally `bb_middle` on this
    platform, used as-is (not an approximation).

    Entry (long): within the last `capitulation_recency` bars there was a "capitulation
    down" bar (close < bb_lower AND range > avg_window-bar avg range * extreme_multiplier
    AND volume > avg_window-bar avg volume * extreme_multiplier), AND the current bar's
    close breaks back above the immediately preceding bar's high (reversal confirmation).
    Entry (short): mirror image using bb_upper / prior bar's low.
    Exit (long): close reaches/exceeds bb_middle (equilibrium reached), or an opposite
    entry fires (handled by the stateful helper). Exit (short): symmetric.

    Interpretive assumptions: "large candle" / "high volume" = range/volume exceeding
    its own trailing `avg_window`-bar average by `extreme_multiplier`x (the document
    gives no exact numeric threshold, only "large compared to normal ranges"/"high
    volume"). "Break of prior bar high/low" = the single bar immediately preceding the
    current one (the document's own worked examples describe bar-by-bar structure, not
    a multi-bar rolling level).

    No lookahead: the capitulation flag and the averages/bands it depends on are
    computed strictly from trailing/`.shift(1)`-ed data before being compared against
    the current bar's own close; `capitulation_..._recent` is shifted by 1 bar again
    before its own rolling window so it never includes the current bar's own flag.
    """
    close = enriched["close"]
    high = enriched["high"]
    low = enriched["low"]
    volume = enriched["volume"]
    rng = high - low

    avg_rng = rng.rolling(avg_window).mean().shift(1)
    avg_vol = volume.rolling(avg_window).mean().shift(1)

    large_move = rng > (avg_rng * extreme_multiplier)
    high_volume = volume > (avg_vol * extreme_multiplier)

    capitulation_down = (close < enriched["bb_lower"]) & large_move & high_volume
    capitulation_up = (close > enriched["bb_upper"]) & large_move & high_volume

    # "recently" capitulated -- excludes the current bar, looks back capitulation_recency bars
    capitulation_down_recent = (
        capitulation_down.shift(1, fill_value=False)
        .rolling(capitulation_recency)
        .max()
        .fillna(0)
        .astype(bool)
    )
    capitulation_up_recent = (
        capitulation_up.shift(1, fill_value=False)
        .rolling(capitulation_recency)
        .max()
        .fillna(0)
        .astype(bool)
    )

    prior_high = high.shift(1)
    prior_low = low.shift(1)

    entry_long = capitulation_down_recent & (close > prior_high)
    entry_short = capitulation_up_recent & (close < prior_low)

    exit_long = close >= enriched["bb_middle"]
    exit_short = close <= enriched["bb_middle"]

    return _stateful_from_entries_exits(
        entry_long.fillna(False),
        exit_long.fillna(False),
        entry_short.fillna(False),
        exit_short.fillna(False),
    )
