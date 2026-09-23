"""
Module: _adapter.py
Description: Bridges the 150 strategy files in strategies_by_style/ into
    this engine's real STRATEGIES registry, so E26 validation, the Stage 0
    bar, sweep reporting and E51 live driving treat them exactly like every
    other archetype -- same unweakened bar.

    THE BUG THIS FIXES (found 2026-09-14, and it is why the user reported
    "I don't see any trades in intraday for any pair"). Every file in
    strategies_by_style/ opens with a guard like:

        required = ['EMA_9','EMA_20','EMA_50','RSI','MACD','MACD_signal','ADX','ATR']
        if not all(col in df.columns for col in required):
            return signals          # <- all zeros

    E24 DOES hand strategies an E07-enriched frame, but E07 names its
    columns in lower case (`ema_21`, `rsi`, `macd_signal`, `adx`, `atr`)
    and computes EMA periods [8, 21, 50, 200]. The style files ask for
    UPPER case and for periods E07 never computes (3, 9, 15, 19, 20, 100).
    So the guard failed on every call, every file returned an all-zero
    series, and the failure was SILENT -- no exception, no warning, just a
    strategy that never trades. Measured directly on real BTC-USD 15m
    data: 0 positions before this adapter, 225 position changes after.

    WHY AN ALIAS RATHER THAN RECOMPUTING. E07's indicator math is the
    real, already-validated implementation this whole platform is fitted
    against -- including a deliberate convention its own docstring calls
    out ("Uses a SIMPLE rolling mean of gains/losses (Cutler's RSI), not
    Wilder's... Every validated strategy parameter in this project was
    fitted against this definition, so changing it would invalidate all of
    them"). Recomputing RSI here with pandas_ta (Wilder's) would silently
    give these strategies a DIFFERENT RSI from every other archetype they
    are ranked against in the same sweep. So: reuse E07's columns
    verbatim, alias the names, and add only the missing EMA periods using
    E07's own identical formula.
Author: Shantanu Waykar
Version: 1.0.0
"""

from __future__ import annotations

from typing import Callable

import pandas as pd

# E07 lower-case column -> the upper-case name the style files expect.
# Only aliases; no value is recomputed or altered.
_ALIASES: dict[str, str] = {
    "rsi": "RSI",
    "macd": "MACD",
    "macd_signal": "MACD_signal",
    "macd_hist": "MACD_hist",
    "adx": "ADX",
    "atr": "ATR",
    "bb_upper": "BB_upper",
    "bb_middle": "BB_middle",
    "bb_lower": "BB_lower",
    "vwap": "VWAP",
    "ema_8": "EMA_8",
    "ema_21": "EMA_21",
    "ema_50": "EMA_50",
    "ema_200": "EMA_200",
    # E07 computes stoch_k/stoch_d via pandas-ta; one style file asks for
    # a bare "Stochastic" and reads it as the %K line.
    "stoch_k": "Stochastic",
    "stoch_d": "Stochastic_D",
}

# Periods the style files reference that E07's EMA_PERIODS ([8,21,50,200])
# does not produce. Computed with E07's own formula --
# `close.ewm(span=period, adjust=False).mean()` -- so an EMA_50 added here
# would be bit-identical to E07's, not a second convention.
#
# Deliberately NOT including EMA_215 / EMA_29 / EMA_3200, which
# strategy_915200_ema_trading_strategy.py asks for: those are a generator
# defect, not real parameters -- its source document is "9/15/200 EMA
# TRADING STRATEGY" and the converter mangled the three periods 9, 15 and
# 200 into 29, 215 and 3200. An EMA with a 3200-bar span cannot even warm
# up inside a 3000-bar test window. Computing them would manufacture
# plausible-looking columns for a strategy whose stated rules are
# corrupted, so that file correctly stays inert instead.
_EXTRA_EMA_PERIODS = (3, 5, 9, 10, 15, 19, 20, 100)


def adapt_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Return `df` plus the upper-case indicator columns the
    strategies_by_style files require. Never mutates the caller's frame.

    Safe to call on an already-adapted frame (idempotent) and on a frame
    that was never E07-enriched -- a missing source column simply means
    that alias is not added, and the strategy's own `required` guard then
    correctly reports it cannot run, which is the honest outcome rather
    than a fabricated zero-filled column.
    """
    out = df.copy()
    for src, dst in _ALIASES.items():
        if src in out.columns and dst not in out.columns:
            out[dst] = out[src]
    if "close" in out.columns:
        for period in _EXTRA_EMA_PERIODS:
            name = f"EMA_{period}"
            if name not in out.columns:
                out[name] = out["close"].ewm(span=period, adjust=False).mean()
    return out


def wrap(fn: Callable[..., pd.Series], registered_name: str | None = None) -> Callable[..., pd.Series]:
    """Adapt a strategies_by_style function into this engine's archetype
    interface: `f(enriched_df) -> position Series`.

    The style files take (df) or (df, params) and return a Series of
    1/-1/0 positions -- the same contract `_stateful_from_entries_exits`
    produces for the pdf_strategy_library archetypes, so no position-model
    translation is needed, only the column adaptation above.

    Takes and ignores **params: these files hardcode their own thresholds
    (they were generated per-asset, not as a parameterised grid), so there
    is nothing to sweep. Accepting **params keeps them callable through the
    exact same `strat_fn_factory(enriched, **params)` path E24 uses for
    every other archetype rather than needing a special case there.
    """

    def _adapted(enriched: pd.DataFrame, **_params) -> pd.Series:
        return fn(adapt_frame(enriched))

    # Name it after the REGISTERED key, not the wrapped function. Every
    # NEW_GEN_CONCEPTS module names its entry point `generate_signal`, so
    # taking fn.__name__ gave all seven of them (CVD, VWAP bands, TPO
    # profile, GEX, footprint, heatmap, volume profile) the identical
    # __name__ -- which made them indistinguishable in logs, sweep
    # reports, and any duplicate-detection pass that groups by function
    # name. Falls back to the wrapped name when no key is supplied.
    _adapted.__name__ = registered_name or getattr(fn, "__name__", "style_strategy")
    _adapted.__doc__ = getattr(fn, "__doc__", None)
    return _adapted
