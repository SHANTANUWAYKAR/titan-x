"""
Module: strategy_9_20ema_crossover_confirmed.py
Source document(s): 9 20EMA STRATEGY.txt
Description: Symmetric 9/20 EMA crossover system (kept separate from "9 20 EMA STOCKBURNER
STRATEGY.txt" -- read both fully; this one requires a discrete crossover PLUS slope alignment
PLUS a support/resistance "respect" condition PLUS a confirmation candle on BOTH the long and
short side, unlike Stockburner's asymmetric continuous-regime-long / discrete-crossunder-short
structure). Document specifies 9 EMA / 20 EMA; approximated with ema_8 / ema_21 (documented,
batch-wide convention).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_9_20ema_crossover_confirmed(
    enriched: pd.DataFrame,
    cross_recent_window: int = 5,
    slope_lookback: int = 3,
    respect_atr: float = 0.5,
) -> pd.Series:
    """9/20 EMA crossover + slope + S/R-respect + confirmation candle (9 20EMA STRATEGY.txt).

    Source rule (plain English, symmetric both sides): (1) 9 EMA crosses above/below 20 EMA,
    (2) both EMAs sloping in that same direction, (3) price "respects" the EMA support/
    resistance zone, (4) enter after a same-direction confirmation candle. Fixed 1:3 R:R
    (sizing out of scope per interface-spec rule 7).

    Interpretive assumptions:
      - "9 EMA"/"20 EMA" -> `ema_8`/`ema_21`.
      - The four conditions describe a state that develops over a few bars after the cross, not
        necessarily all at the exact cross bar, so the crossover only needs to have happened
        within the last `cross_recent_window` bars (a plain trailing-window check); slope/
        respect/confirmation are evaluated on the current bar. Because entries only fire while
        the stateful helper's position is flat, a signal staying true for several bars after the
        cross cannot cause repeated re-entries.
      - "Price respects the EMA support/resistance zone" = the bar's low (long case) / high
        (short case) does not violate the slow EMA by more than `respect_atr` ATR.
      - "Candle confirmation" = a same-direction candle body (close vs open) on the entry bar.
      - Exit: the opposite crossover (doc doesn't specify a separate exit rule beyond the R:R
        target, which is out of scope; using the opposite entry trigger is the standard
        mechanical reading).

    Returns:
        pd.Series[int] in {-1, 0, 1}, same index as `enriched`.
    """
    open_ = enriched["open"]; high = enriched["high"]; low = enriched["low"]; close = enriched["close"]
    atr = enriched["atr"].replace(0, np.nan)
    ema_fast = enriched["ema_8"]; ema_slow = enriched["ema_21"]

    cross_up = (ema_fast.shift(1) <= ema_slow.shift(1)) & (ema_fast > ema_slow)
    cross_down = (ema_fast.shift(1) >= ema_slow.shift(1)) & (ema_fast < ema_slow)
    cross_up_recent = cross_up.shift(1).rolling(cross_recent_window, min_periods=1).max().fillna(0).astype(bool) | cross_up
    cross_down_recent = cross_down.shift(1).rolling(cross_recent_window, min_periods=1).max().fillna(0).astype(bool) | cross_down

    slope_up = (ema_fast > ema_fast.shift(slope_lookback)) & (ema_slow > ema_slow.shift(slope_lookback))
    slope_down = (ema_fast < ema_fast.shift(slope_lookback)) & (ema_slow < ema_slow.shift(slope_lookback))

    respects_support = low >= (ema_slow - respect_atr * atr)
    respects_resistance = high <= (ema_slow + respect_atr * atr)

    confirm_bull = close > open_
    confirm_bear = close < open_

    entry_long = (cross_up_recent & slope_up & respects_support & confirm_bull).fillna(False)
    entry_short = (cross_down_recent & slope_down & respects_resistance & confirm_bear).fillna(False)

    exit_long = cross_down.fillna(False)
    exit_short = cross_up.fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
