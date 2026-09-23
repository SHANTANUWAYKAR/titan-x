"""
Module: strategy_3ema_ribbon_crossover.py
Source document(s): 3 MOVING AVERAGE TRADING SETUP.txt
Description: 9/20/50 EMA ribbon trend-confirmation crossover. Document specifies 9 EMA, 20 EMA
and 50 EMA; approximated with the platform's ema_8, ema_21 and ema_50 respectively (ema_50 is
an exact match, ema_8/ema_21 are the closest available periods to 9/20). Long when the fast EMA
crosses above the mid EMA while both sit above the 50 EMA; the document's explicit exit rule
("exit on an opposite 9/20 crossover") is used for both sides; a short mirror of the entry was
added symmetrically since the doc says "always trade in the direction of the trend" without
restricting to longs only, and this is noted as an interpretive extension.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_3ema_ribbon_crossover(enriched: pd.DataFrame) -> pd.Series:
    """3-EMA ribbon (9/20/50) crossover-above/below-50 trend setup (3 MOVING AVERAGE TRADING
    SETUP.txt).

    Source rule: on the daily chart, wait for the 9 EMA to cross the 20 EMA. The crossover is
    only valid when it happens above the 50 EMA (bullish case) -- confirms a strong trend. Exit
    when an opposite crossover occurs (9 EMA crosses back below 20 EMA).

    Interpretive assumptions:
      - "9 EMA" -> ema_8, "20 EMA" -> ema_21 (closest available periods), "50 EMA" -> ema_50
        (exact).
      - Document only spells out the bullish (long) case explicitly; a symmetric bearish/short
        case (cross-down while both EMAs sit below the 50 EMA) was added by direct mirroring,
        consistent with its own "trade in direction of trend" guidance -- flagged here as an
        interpretive extension, not stated verbatim in the source.

    Returns:
        pd.Series[int] in {-1, 0, 1}, same index as `enriched`.
    """
    ema9 = enriched["ema_8"]; ema20 = enriched["ema_21"]; ema50 = enriched["ema_50"]

    cross_up = (ema9.shift(1) <= ema20.shift(1)) & (ema9 > ema20)
    cross_down = (ema9.shift(1) >= ema20.shift(1)) & (ema9 < ema20)

    entry_long = (cross_up & (ema9 > ema50) & (ema20 > ema50)).fillna(False)
    entry_short = (cross_down & (ema9 < ema50) & (ema20 < ema50)).fillna(False)

    # document's explicit exit rule: exit on the opposite 9/20 crossover
    exit_long = cross_down.fillna(False)
    exit_short = cross_up.fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
