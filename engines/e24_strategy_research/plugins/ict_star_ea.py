"""
Module: ict_star_ea.py
Description: Concept-level port of the FVG-entry core documented in
    STAR-EA-v11.20 (https://github.com/NadirAliOfficial/STAR-EA-v11.20,
    STAR_v11.20.mq5, cloned read-only for reference). The EA is a 51k-line
    MQL5 program whose exact line-by-line logic is not portable, but its
    own extensively documented header states the tradable core this module
    ports: FVG entries gated by killzone windows ("TECH_SB -> allowTC OR
    allowFVG (KZ + FVG confluence)"). The FVG definition itself is the
    standard 3-candle imbalance this platform already detects
    descriptively in e07_technical/smart_money.py (which the same repo
    audit's FVG ATR fix touched -- see CLAUDE.md's 9-repo audit section);
    this is the walk-forward tradable version.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-08-21
"""

import numpy as np
import pandas as pd

from project_titan_x.engines.e07_technical.killzones import is_high_probability_window


def _fvg_retrace_signal(
    enriched: pd.DataFrame, max_age: int, entry_mask: np.ndarray | None
) -> pd.Series:
    """Shared walk-forward core for both variants.

    Bullish FVG at bar g: low[g] > high[g-2] (the standard 3-candle
    imbalance, same definition as smart_money.detect_fair_value_gaps).
    Entry: within `max_age` bars of the gap forming, a bar CLOSES inside
    the still-unfilled gap zone -> enter in the gap's direction (the
    classic ICT retrace-into-imbalance entry). Stop: close beyond the far
    edge of the zone (gap fully traded through -- invalidated). Target:
    close beyond the extreme of the impulse bar that created the gap
    (continuation confirmed). Mirrored for bearish gaps. All fills are
    close-based, the same simplification as every strategy in this
    library. Only the MOST RECENT unfilled gap per direction is tracked --
    the EA likewise trades the freshest zone, not a stack of stale ones.
    """
    n = len(enriched)
    highs = enriched["high"].to_numpy(dtype=float)
    lows = enriched["low"].to_numpy(dtype=float)
    closes = enriched["close"].to_numpy(dtype=float)

    signal = np.zeros(n, dtype=int)
    position = 0
    sl = tp = 0.0
    # (zone_bottom, zone_top, impulse_extreme, born_at) per direction
    bull_gap = bear_gap = None

    for i in range(2, n):
        c = closes[i]
        if position == 1 and (c <= sl or c >= tp):
            position = 0
        elif position == -1 and (c >= sl or c <= tp):
            position = 0

        # Track the freshest unfilled gap in each direction.
        if lows[i] > highs[i - 2]:
            bull_gap = (highs[i - 2], lows[i], highs[i], i)
        if highs[i] < lows[i - 2]:
            bear_gap = (highs[i], lows[i - 2], lows[i], i)
        if bull_gap is not None and (c < bull_gap[0] or i - bull_gap[3] > max_age):
            bull_gap = None
        if bear_gap is not None and (c > bear_gap[1] or i - bear_gap[3] > max_age):
            bear_gap = None

        if position == 0 and (entry_mask is None or entry_mask[i]):
            if bull_gap is not None and bull_gap[3] < i and bull_gap[0] <= c <= bull_gap[1]:
                position, sl, tp = 1, bull_gap[0], bull_gap[2]
                bull_gap = None
            elif bear_gap is not None and bear_gap[3] < i and bear_gap[0] <= c <= bear_gap[1]:
                position, sl, tp = -1, bear_gap[1], bear_gap[2]
                bear_gap = None

        signal[i] = position

    return pd.Series(signal, index=enriched.index)


def ict_fvg_retrace(enriched: pd.DataFrame, max_age: int = 20) -> pd.Series:
    """FVG retrace entry with no session gate -- the EA's core zone logic
    alone, so the sweep can measure what the killzone gate itself adds."""
    return _fvg_retrace_signal(enriched, max_age, None)


def ict_fvg_retrace_killzone(enriched: pd.DataFrame, max_age: int = 20) -> pd.Series:
    """The EA's actual documented confluence: FVG entries only inside an
    ICT killzone (e07_technical/killzones.py, itself added during the same
    repo audit). Entries are gated; an open position may run past the
    window's end (the EA holds through sessions too), unlike
    apply_session_filter's force-flat semantics."""
    mask = is_high_probability_window(enriched).to_numpy(dtype=bool)
    return _fvg_retrace_signal(enriched, max_age, mask)
