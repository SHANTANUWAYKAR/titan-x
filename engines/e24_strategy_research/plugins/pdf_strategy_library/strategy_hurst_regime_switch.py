"""
Module: strategy_hurst_regime_switch.py
NEW CONCEPT (2026-09-13): Hurst-exponent regime switching -- a statistical (fractal market
hypothesis) approach, categorically different from every prior strategy in this project's
library (all of which are price-action pattern matching: SMC/ICT structure, candlestick
patterns, moving-average crosses, breakouts, RSI/divergence). Confirmed via repo-wide grep
that "hurst"/"variance ratio" appears nowhere else in this codebase before this file.

Concept: the Hurst exponent H characterises a price series' long-run memory.
- H > 0.5: the series is TRENDING / persistent -- a move in one direction tends to be
  followed by more of the same (momentum edge).
- H < 0.5: the series is MEAN-REVERTING / anti-persistent -- a move tends to be followed by
  a reversal (mean-reversion edge).
- H ~= 0.5: the series is behaving like a random walk -- no directional edge either way.

This strategy estimates a ROLLING Hurst exponent causally (variance-ratio method: Lo &
MacKinnon-style, using only trailing data) and switches which of two simple, well-known
sub-rules is active based on the current regime -- it does not blindly run one fixed rule
across all market conditions, which is the entire point of the concept.

Hurst estimator (variance-ratio method, fully vectorised, no lookahead):
    Var_1 = rolling variance of 1-bar log returns over `window` bars
    Var_k = rolling variance of k-bar (k=`vr_lag`) cumulative log returns over the same window
    H = log(Var_k / Var_1) / (2 * log(k))
This is the standard relationship Var(k-period return) ~ k^(2H) * Var(1-period return) for a
self-similar process, solved for H. Every input to Var_1/Var_k at bar i uses only bars up to
and including i (pandas rolling window), so H at bar i never sees a future bar.

Sub-rules (deliberately simple and well-established -- the NEW part is the regime switch
choosing between them, not novel indicators):
- Trending regime (H >= trend_threshold): momentum -- go long when close > ema_fast > ema_slow
  and RSI is not already overbought (>70), short the mirror image.
- Mean-reverting regime (H <= revert_threshold): fade -- go long when price z-score (vs its
  own rolling mean/std over `window`) is below -entry_z (oversold, expect reversion up), short
  when above +entry_z.
- Ambiguous regime (revert_threshold < H < trend_threshold): flat, no edge either way -- this
  is itself the honest, deliberate design point of the concept (most of the time, most
  markets are in this ambiguous zone, per the fractal market hypothesis literature).

Interpretive assumptions:
- `vr_lag` (k) must be a small integer well below `window` for the variance-ratio estimator
  to be statistically meaningful; defaults (window=100, vr_lag=10) follow common practice
  (k roughly window/10).
- Regime is recomputed every bar (not on a fixed schedule) since the rolling calculation is
  already O(1) amortised via pandas' internal rolling-window algorithm -- no approximation
  needed for performance, unlike volume_profile_breakout's discrete recompute_every.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def strategy_hurst_regime_switch(
    enriched: pd.DataFrame,
    window: int = 100,
    vr_lag: int = 10,
    trend_threshold: float = 0.55,
    revert_threshold: float = 0.45,
    entry_z: float = 1.5,
) -> pd.Series:
    """Hurst-exponent regime switch: momentum sub-rule when trending (H high), mean-reversion
    sub-rule when anti-persistent (H low), flat when ambiguous (H near 0.5).
    """
    close = enriched["close"]
    ema_fast = enriched["ema_8"]
    ema_slow = enriched["ema_21"]
    rsi = enriched["rsi"]

    log_ret = np.log(close / close.shift(1))
    var_1 = log_ret.rolling(window).var()

    k_log_ret = np.log(close / close.shift(vr_lag))
    var_k = k_log_ret.rolling(window).var()

    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = (var_k / var_1).replace([np.inf, -np.inf], np.nan)
    hurst = (np.log(ratio) / (2.0 * np.log(vr_lag))).clip(0.0, 1.0)
    hurst = hurst.fillna(0.5)  # insufficient data / degenerate variance -> assume random walk (flat)

    trending = hurst >= trend_threshold
    reverting = hurst <= revert_threshold

    # Momentum sub-rule (only consulted while trending==True)
    mom_long = (close > ema_fast) & (ema_fast > ema_slow) & (rsi < 70)
    mom_short = (close < ema_fast) & (ema_fast < ema_slow) & (rsi > 30)

    # Mean-reversion sub-rule (only consulted while reverting==True)
    roll_mean = close.rolling(window).mean()
    roll_std = close.rolling(window).std()
    z = ((close - roll_mean) / roll_std.replace(0, np.nan)).fillna(0.0)
    revert_long = z <= -entry_z
    revert_short = z >= entry_z

    entry_long = ((trending & mom_long) | (reverting & revert_long)).fillna(False)
    entry_short = ((trending & mom_short) | (reverting & revert_short)).fillna(False)

    # Exit: regime itself turns ambiguous (edge no longer asserted), or the active sub-rule's
    # own opposite condition fires.
    ambiguous = (~trending & ~reverting).fillna(True)
    exit_long = (ambiguous | mom_short | revert_short).fillna(False)
    exit_short = (ambiguous | mom_long | revert_long).fillna(False)

    from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
        _stateful_from_entries_exits,
    )
    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
