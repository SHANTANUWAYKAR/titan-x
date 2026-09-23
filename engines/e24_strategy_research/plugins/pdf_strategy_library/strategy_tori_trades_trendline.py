"""
Module: strategy_tori_trades_trendline.py
Source document(s): Tori Trades Playbook.txt, TORI TRADES TRENDLINE STRATEGY.txt
Description: CONSOLIDATED per the interface spec's near-duplicate rule -- both documents are the
same trader's (Tori Trades / Victoria Duke) trendline methodology on the 4H chart: draw a
trendline, trade its bounce or break, and trail/exit using a newly-formed opposing trendline. The
short "TORI TRADES TRENDLINE STRATEGY.txt" describes only the break + opposite-trendline-exit
mechanic; the longer "Tori Trades Playbook.txt" adds the Action Line (entry trigger) / Safety
Line (stop/exit trigger) framing and an explicit "bounce" setup in addition to "break." Both are
implemented here as ONE function with a `variant` parameter ("break" is the default, matching
both documents; "bounce" implements the Playbook-only bounce setup) rather than as two near-
identical files. (NOTE: a differently-named file "TORITRADES TRENDLINE STRATEGY.txt", with no
space, also exists on disk describing a more detailed breakout variant -- that file was NOT in
this batch's assigned 16 documents and is not consolidated here.)
"""
from __future__ import annotations
import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def _rolling_trendline_projection(series: pd.Series, window: int):
    """Fit a straight line (least squares) through `window` PRIOR bars of `series` (the caller
    is expected to have already `.shift(1)`-ed the series so the window ends at bar i-1), and
    project the fitted line one step forward to represent "the trendline's value at bar i."
    Returns (projected_level, slope), both indexed like `series`. Purely backward-looking: at
    row i this only ever uses series[i-window]..series[i-1] (post-shift), matching the spec's
    shift(1)-before-rolling breakout-level idiom generalized from a flat max/min to a sloped
    line.
    """
    x = np.arange(window, dtype=float)

    def _fit_project(arr: np.ndarray) -> float:
        if np.isnan(arr).any():
            return np.nan
        coeffs = np.polyfit(x, arr, 1)
        return float(np.polyval(coeffs, window))

    def _fit_slope(arr: np.ndarray) -> float:
        if np.isnan(arr).any():
            return np.nan
        coeffs = np.polyfit(x, arr, 1)
        return float(coeffs[0])

    projected = series.rolling(window).apply(_fit_project, raw=True)
    slope = series.rolling(window).apply(_fit_slope, raw=True)
    return projected, slope


def strategy_tori_trades_trendline(
    enriched: pd.DataFrame,
    variant: str = "break",
    touch_lookback: int = 42,
    touch_tolerance_atr_mult: float = 0.5,
    min_touches: int = 2,
) -> pd.Series:
    """Tori Trades (Victoria Duke) trendline Bounce/Break with Action-Line/Safety-Line exits.

    Consolidates: Tori Trades Playbook.txt (Trendline Strategy -- Action Line / Safety Line,
    Bounce and 2/3-touchpoint Break setups) and TORI TRADES TRENDLINE STRATEGY.txt (shorter
    break-only description). Both specify the 4H timeframe, hand-drawn trendlines connecting
    swing highs/lows, and holding a break trade until a newly-formed OPPOSING trendline breaks.

    Approximation: hand-drawn trendlines are approximated with a rolling least-squares line
    fit through `touch_lookback` prior bars' highs (down-trendline / resistance candidate) and
    lows (up-trendline / support candidate), each projected one bar forward -- see
    `_rolling_trendline_projection`. `touch_lookback` defaults to 42 (~1 trading week of 4H bars,
    6/day x 7 days), matching the Playbook's own "about one week of price data" requirement. The
    fit always uses `.shift(1)` data (bars strictly before the current one) before fitting, so
    the projected level at bar i is fixed using only bars up to i-1, then compared against bar
    i's own close/low/high (matches the spec's shift-before-rolling breakout-level idiom,
    generalized to a sloped line). "Touchpoints" are approximated by counting, within the
    lookback window, how many bars came within `touch_tolerance_atr_mult` * ATR of the fitted
    line; `min_touches` (default 2, matching the Playbook's minimum "2 Touchpoint Break") gates
    entries to lines that were genuinely respected multiple times, not just any straight-line fit.

    variant="break" (default; matches BOTH source documents' core rule):
      Entry long: close closes above the down-sloping resistance trendline (slope < 0) that has
        >= min_touches touches -- a genuine break of a respected down-trendline.
      Entry short: close closes below the up-sloping support trendline (slope > 0) with
        >= min_touches touches.
      Exit: close closes back through the OPPOSING trendline (the "safety line") -- exit_long
        when close < up-trendline level, exit_short when close > down-trendline level. This is
        the Playbook's "safety line" and the short document's "exit when the new trendline
        breaks in the opposite direction," modeled identically since both describe the same
        trail-and-exit mechanic.

    variant="bounce" (Playbook-only setup):
      Entry long: low touches within tolerance of an up-sloping support trendline (slope > 0)
        and the bar closes bullish (close > open) -- a respected-line bounce, matching "the
        trendline itself is used as the stop-loss level; entry when price reaches or tests the
        trendline."
      Entry short: mirror image off a down-sloping resistance trendline.
      Exit: close closes through that SAME trendline (Action Line == Safety Line for bounce
        setups, per the Playbook).

    No stop-loss/position-sizing values are returned -- only entry/exit direction.
    """
    if variant not in ("break", "bounce"):
        raise ValueError("variant must be 'break' or 'bounce'")

    close = enriched["close"]
    open_ = enriched["open"]
    high = enriched["high"]
    low = enriched["low"]
    atr = enriched["atr"]

    high_prior = high.shift(1)
    low_prior = low.shift(1)

    down_trend_level, down_trend_slope = _rolling_trendline_projection(high_prior, touch_lookback)
    up_trend_level, up_trend_slope = _rolling_trendline_projection(low_prior, touch_lookback)

    tol = atr * touch_tolerance_atr_mult
    down_touches = (high_prior.sub(down_trend_level).abs() <= tol).rolling(touch_lookback).sum()
    up_touches = (low_prior.sub(up_trend_level).abs() <= tol).rolling(touch_lookback).sum()

    down_valid = (down_trend_slope < 0) & (down_touches >= min_touches)
    up_valid = (up_trend_slope > 0) & (up_touches >= min_touches)

    if variant == "break":
        entry_long = down_valid & (close > down_trend_level)
        entry_short = up_valid & (close < up_trend_level)
        exit_long = close < up_trend_level
        exit_short = close > down_trend_level
    else:  # bounce
        near_support = up_valid & (low <= up_trend_level + tol) & (close > open_)
        near_resistance = down_valid & (high >= down_trend_level - tol) & (close < open_)
        entry_long = near_support
        entry_short = near_resistance
        exit_long = close < up_trend_level
        exit_short = close > down_trend_level

    entry_long = entry_long.fillna(False)
    entry_short = entry_short.fillna(False)
    exit_long = exit_long.fillna(False)
    exit_short = exit_short.fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
