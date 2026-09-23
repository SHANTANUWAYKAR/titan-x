"""
Module: strategy_ema_9_21_crossover.py
Source document(s): EMA Crossover Trading Strategy (1).txt
Description: Classic fast/slow EMA crossover. Document names ema_8 ("9 EMA") as the fast line
and ema_21 as the slow line. NOTE: the source document's own worded buy-signal ("When 21 EMA
crosses above 9 EMA -> BUY") is the literal mirror-image of its own worded sell-signal ("When 9
EMA crosses below 21 EMA -> SELL") -- both describe the SAME crossover event with opposite
labels, an internal inconsistency in the source text. Implemented the standard, universally
consistent convention instead (fast EMA above slow EMA = bullish = buy; fast below slow =
bearish = sell), which matches the document's own correctly-worded sell rule.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_ema_9_21_crossover(enriched: pd.DataFrame) -> pd.Series:
    """Simple 9/21 EMA crossover, always in the market (flips on the opposite cross).

    Source document: "EMA Crossover Trading Strategy (1).txt". Rule: fast EMA (9, approximated
    with `ema_8`) crossing the slow EMA (21, `ema_21`) generates the signal; see the module
    docstring for the source document's internal buy/sell wording inconsistency and how it was
    resolved (standard fast-over-slow=bullish convention used).
    """
    fast, slow = enriched["ema_8"], enriched["ema_21"]

    cross_up = ((fast > slow) & (fast.shift(1) <= slow.shift(1))).fillna(False)
    cross_down = ((fast < slow) & (fast.shift(1) >= slow.shift(1))).fillna(False)

    entry_long = cross_up
    entry_short = cross_down
    exit_long = cross_down
    exit_short = cross_up

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
