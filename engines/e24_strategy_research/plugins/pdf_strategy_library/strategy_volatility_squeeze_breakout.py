"""
Module: strategy_volatility_squeeze_breakout.py
NEW CONCEPT (2026-09-13): realized-volatility-percentile squeeze/breakout -- confirmed via
repo-wide grep as never implemented anywhere in this codebase before (no "squeeze",
"realized_vol", or "garch" strategy exists; bb_width IS already an available column but has
never been used to drive an entry rule in this project's strategy library -- only ever
computed by e07_technical and left unconsumed by any strategy_fn).

Concept: volatility is mean-reverting and clusters (the single most robust, well-established
stylised fact in quantitative finance -- "volatility clustering", Mandelbrot 1963 / Engle's
ARCH). A market that has been unusually QUIET (realized volatility in a low percentile of its
own recent history) is, empirically, more likely to see an expansion in volatility soon --
this is the standard "squeeze" concept (popularised by Bollinger Band Width / Keltner Channel
squeeze indicators, TTM Squeeze, etc.), but this implementation computes the percentile
directly from REALIZED volatility (rolling std of log returns) rather than from Bollinger
Band width alone, so it is a genuinely distinct calculation from anything bb_width-based
already in this codebase, even though the underlying intuition rhymes with the well-known
indicator family.

This is a DIRECTIONAL breakout strategy (not a pure volatility play): after a confirmed
squeeze (realized vol below `squeeze_percentile` of its own trailing distribution for at
least `squeeze_min_bars` consecutive bars), enter in the direction of the breakout candle
that first closes outside the recent consolidation range (defined by the SAME window's
high/low, established as the "wound-up spring" duration) with an above-average volume
confirmation (volume > its own rolling average) -- volume confirmation on a fresh
volatility-expansion breakout is a real, standard cross-check the platform's own other
volume-aware strategies (volume_profile_breakout, cvd_divergence) already use elsewhere in
this codebase, applied here to a differently-triggered setup.

Interpretive assumptions:
- Realized volatility = rolling std of 1-bar log returns over `vol_window` bars (annualised
  scaling not needed since only the RELATIVE percentile within the same series matters, not
  an absolute cross-asset-comparable number).
- Percentile computed via a rolling rank against the trailing `percentile_window` bars
  (causal: bar i's percentile only ranks bar i's vol against bars stricly before i within the
  window, via a rolling().apply with a strictly-historical comparison array).
- Consolidation range = rolling high/low over the same `vol_window` used for the volatility
  calculation itself, ensuring the "range" and the "quiet" measurement describe the same
  lookback period.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _rolling_percentile_rank_causal(series: pd.Series, window: int) -> pd.Series:
    """Percentile rank (0-100) of the LAST value in each trailing window against the OTHER
    values in that same window (a value's own percentile within its own recent history) --
    causal by construction since pandas rolling windows only ever look backward.
    """
    def _rank_last(arr: np.ndarray) -> float:
        if len(arr) < 2:
            return 50.0
        last = arr[-1]
        return 100.0 * (np.sum(arr <= last) - 1) / (len(arr) - 1)

    return series.rolling(window).apply(_rank_last, raw=True).fillna(50.0)


def strategy_volatility_squeeze_breakout(
    enriched: pd.DataFrame,
    vol_window: int = 20,
    percentile_window: int = 100,
    squeeze_percentile: float = 20.0,
    squeeze_min_bars: int = 5,
    volume_mult: float = 1.2,
) -> pd.Series:
    """Realized-volatility squeeze followed by a directional, volume-confirmed range
    breakout. Flat outside a confirmed squeeze setup.
    """
    close = enriched["close"]
    high = enriched["high"]
    low = enriched["low"]
    volume = enriched["volume"]

    log_ret = np.log(close / close.shift(1))
    realized_vol = log_ret.rolling(vol_window).std()
    vol_percentile = _rolling_percentile_rank_causal(realized_vol, percentile_window)

    is_quiet = vol_percentile <= squeeze_percentile
    squeeze_confirmed = (is_quiet.rolling(squeeze_min_bars).sum() >= squeeze_min_bars).fillna(False)

    # Consolidation range formed DURING the squeeze -- use bars up to and including the
    # previous bar so today's own (potentially breakout) bar is never part of the range it's
    # being compared against.
    range_high = high.shift(1).rolling(vol_window).max()
    range_low = low.shift(1).rolling(vol_window).min()

    avg_volume = volume.rolling(vol_window).mean()
    volume_confirmed = volume > (avg_volume * volume_mult)

    breakout_up = (close > range_high) & volume_confirmed
    breakout_down = (close < range_low) & volume_confirmed

    entry_long = (squeeze_confirmed.shift(1).fillna(False) & breakout_up).fillna(False)
    entry_short = (squeeze_confirmed.shift(1).fillna(False) & breakout_down).fillna(False)

    # Exit: price falls back inside the range that was broken (breakout failure / structural
    # invalidation), or volatility collapses back into a fresh squeeze (the expansion this
    # trade was betting on has already played out or fizzled).
    exit_long = ((close < range_high) | is_quiet).fillna(True)
    exit_short = ((close > range_low) | is_quiet).fillna(True)

    from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
        _stateful_from_entries_exits,
    )
    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
