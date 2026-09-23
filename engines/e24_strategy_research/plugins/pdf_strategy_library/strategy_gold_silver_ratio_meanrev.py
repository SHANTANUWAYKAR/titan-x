"""
Module: strategy_gold_silver_ratio_meanrev.py
NEW CONCEPT (2026-09-13): cross-asset statistical-arbitrage mean reversion on the
Gold/Silver ratio.

Genuinely different from every prior GOLD/SILVER strategy tried this project (all of which
were single-asset price action: SMC, MSS, VWAP/CVD, EMA crosses, RSI divergence, retail PDF
strategies). This is a classic commodities stat-arb concept: Gold/Silver ratio = gold_close /
silver_close. The ratio has a long-run mean (see data/models/e16_commodity's own
GoldSilverRatioResult -- this project already tracks this ratio's percentile for context, but
has never traded it directly). When the ratio is statistically extreme relative to its own
trailing distribution, historically it has reverted -- extreme-high ratio = gold rich vs
silver (fade gold / favor silver); extreme-low ratio = silver rich vs gold (fade silver /
favor gold).

TWO-ASSET EXCEPTION to the standard one-DataFrame interface (same documented, explicitly
permitted pattern as strategy_ict_smt_divergence in this same package): needs both GOLD and
SILVER simultaneously.

Interpretive assumptions:
- Ratio z-score computed on a trailing `zscore_window`-bar rolling mean/std (causal, no
  lookahead: today's z-score never uses today's own bar in the rolling stats' window end --
  the rolling window naturally only includes bars up to and including the current one, which
  is standard and fine since the CURRENT ratio being scored is allowed to see itself; no
  FUTURE bar is used).
- Entry: |z| >= entry_z triggers a fade position (mean-reversion, not momentum). Exit: z
  reverts to within exit_z of zero (the mean), OR the position has been held longer than
  max_hold_bars (a stat-arb position that hasn't reverted within a reasonable window is
  more likely a genuine regime shift than "still waiting" -- cap the holding period).
- `asset_role` selects which side of the pair this call represents: "gold" returns gold's
  leg of the trade (SHORT gold when ratio extreme-high, LONG gold when ratio extreme-low);
  "silver" returns silver's leg (the mirror image). Call this function once per asset,
  exactly like strategy_ict_smt_divergence's own calling convention.
- If `enriched_b` doesn't share `enriched_a`'s exact timestamps, it's aligned via an as-of
  forward-fill on the timestamp column (never a future bar of B informs a decision at A's
  timestamp) -- identical alignment approach to strategy_ict_smt_divergence.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def strategy_gold_silver_ratio_meanrev(
    enriched_a: pd.DataFrame,
    enriched_b: pd.DataFrame,
    zscore_window: int = 60,
    entry_z: float = 1.5,
    exit_z: float = 0.5,
    max_hold_bars: int = 40,
    asset_role: str = "gold",
) -> pd.Series:
    """Gold/Silver ratio mean-reversion. `enriched_a` = GOLD's enriched df, `enriched_b` =
    SILVER's enriched df, regardless of `asset_role` (the role only picks which leg's signal
    is returned -- both dataframes are always required to compute the ratio itself).
    """
    idx_a = enriched_a.index
    close_a = enriched_a["close"]

    same_index = (
        len(enriched_b) == len(enriched_a)
        and enriched_a["timestamp"].to_numpy().tolist() == enriched_b["timestamp"].to_numpy().tolist()
    )
    if same_index:
        close_b = pd.Series(enriched_b["close"].to_numpy(), index=idx_a)
    else:
        b_by_time = enriched_b.set_index("timestamp")[["close"]].sort_index()
        aligned_b = b_by_time.reindex(enriched_a["timestamp"].to_numpy(), method="ffill")
        close_b = pd.Series(aligned_b["close"].to_numpy(), index=idx_a)

    ratio = close_a / close_b.replace(0, np.nan)
    roll_mean = ratio.rolling(zscore_window).mean()
    roll_std = ratio.rolling(zscore_window).std()
    z = ((ratio - roll_mean) / roll_std.replace(0, np.nan)).fillna(0.0)

    ratio_extreme_high = z >= entry_z   # gold rich vs silver
    ratio_extreme_low = z <= -entry_z   # silver rich vs gold
    reverted = z.abs() <= exit_z

    n = len(enriched_a)
    signal = np.zeros(n, dtype=int)
    position = 0
    bars_held = 0
    eh = ratio_extreme_high.to_numpy()
    el = ratio_extreme_low.to_numpy()
    rv = reverted.to_numpy()

    for i in range(n):
        if position != 0:
            bars_held += 1
            if rv[i] or bars_held >= max_hold_bars:
                position = 0
                bars_held = 0
        if position == 0:
            if eh[i]:
                # gold rich vs silver -> fade: short gold, long silver
                position = -1 if asset_role == "gold" else 1
                bars_held = 0
            elif el[i]:
                # silver rich vs gold -> fade: long gold, short silver
                position = 1 if asset_role == "gold" else -1
                bars_held = 0
        signal[i] = position

    return pd.Series(signal, index=idx_a)
