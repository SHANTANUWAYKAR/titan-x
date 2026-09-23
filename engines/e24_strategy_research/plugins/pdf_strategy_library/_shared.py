"""
Module: _shared.py
Description: The one canonical copy of `_stateful_from_entries_exits`, shared by every strategy
    in this package. This is byte-identical to `engines/e24_strategy_research/strategies.py`'s own
    copy (same function, same bug history) -- duplicated here rather than imported directly from
    `strategies.py` to keep this plugin package's internal dependency graph self-contained (it
    only depends on numpy/pandas, matching every other file under `plugins/`), not because the
    logic is meant to diverge. If `strategies.py`'s version is ever changed, mirror the change here.

    History (copied from strategies.py's own docstring for full context):
    Real bug found and fixed 2026-08-21: entries must be assigned AFTER exits, not before, because
    a raw price-condition exit mask has no idea which side is actually open and can silently close
    the wrong side on the same bar a fresh opposite entry fires. SECOND bug found 2026-08-22: even
    with correct ordering, a forward-filled mask still doesn't track which side is open, so an
    exit condition for one side can fire while the other side is genuinely held. Fixed with an
    explicit position-state loop: an exit is only ever consulted for the side that is actually
    open, and a fresh opposite entry flips the position directly.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _stateful_from_entries_exits(
    entry_long: pd.Series, exit_long: pd.Series,
    entry_short: pd.Series, exit_short: pd.Series,
) -> pd.Series:
    el = entry_long.to_numpy(dtype=bool); xl = exit_long.to_numpy(dtype=bool)
    es = entry_short.to_numpy(dtype=bool); xs = exit_short.to_numpy(dtype=bool)

    out = np.zeros(len(el), dtype=np.int8)
    pos = 0
    for i in range(len(el)):
        if pos == 1:
            if es[i]:
                pos = -1
            elif xl[i]:
                pos = 0
        elif pos == -1:
            if el[i]:
                pos = 1
            elif xs[i]:
                pos = 0
        if pos == 0:
            if el[i]:
                pos = 1
            elif es[i]:
                pos = -1
        out[i] = pos
    return pd.Series(out, index=entry_long.index, dtype=int)
