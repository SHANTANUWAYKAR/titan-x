"""
Module: strategy_btc_eth_relative_rotation.py
NEW CONCEPT (2026-09-13): BTC/ETH relative-strength rotation -- the "altcoin season" rotation
concept from crypto markets, confirmed via repo-wide grep as never implemented anywhere in
this codebase before (no "rotation"/"dominance"/"relative_strength" strategy exists).

Distinct from strategy_ict_smt_divergence (which looks for DIVERGENCE/failure-to-confirm
between BTC and ETH as a reversal signal) and strategy_gold_silver_ratio_meanrev (mean
reversion on a ratio): this is a MOMENTUM concept on the ETH/BTC ratio itself, not a
divergence or mean-reversion read. Real, well-known crypto market structure this project's
own e17_crypto engine's BTC-dominance framing already gestures at conceptually but never
operationalises into a tradeable rule: capital rotates between BTC and large-cap alts
(ETH being the largest and most liquid) in cycles -- when the ETH/BTC ratio is trending up,
ETH is outperforming BTC on a relative basis and that relative momentum has historically
persisted for multiple bars/days rather than reverting immediately (the opposite regime from
the mean-reverting Gold/Silver ratio, which is why these two ratio strategies use opposite
sub-rules: momentum here vs. mean-reversion there -- a real difference in the two ratios'
own established behavior, not an arbitrary choice).

Rule: compute the ETH/BTC ratio's own trend (EMA-fast vs EMA-slow of the RATIO series
itself, not of either asset's own price -- the ratio is the traded object here). When the
ratio trend is up (ETH outperforming, "alt season" tailwind), go LONG the asset selected by
`asset_role="eth"` and SHORT (or flat, if `allow_short=False`) the asset selected by
`asset_role="btc"` -- and the mirror image when the ratio trend is down ("BTC season").

TWO-ASSET EXCEPTION to the standard one-DataFrame interface (same documented pattern as the
other two-asset strategies in this package). `enriched_a` = ETH, `enriched_b` = BTC (fixed
roles, unlike the Gold/Silver strategy, since "ETH/BTC ratio" is the market's own standard
convention -- there is no equivalent "BTC/ETH" convention quoted anywhere).

Interpretive assumptions:
- Ratio trend uses the SAME ema_8/ema_21 fast/slow convention already used everywhere else
  in this codebase for consistency, computed fresh on the ratio series (not reused from
  either asset's own ema columns, which describe each asset's OWN price trend, a different
  quantity from the ratio's trend).
- A minimum ratio-trend persistence filter (`confirm_bars`) requires the ratio trend
  direction to have held for at least that many consecutive bars before entering, filtering
  single-bar EMA crossover noise -- a real, standard momentum-confirmation technique (not
  novel to this file).
- If `enriched_b` doesn't share `enriched_a`'s exact timestamps, aligned via the same as-of
  forward-fill convention as the other two-asset strategies in this package.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def strategy_btc_eth_relative_rotation(
    enriched_a: pd.DataFrame,
    enriched_b: pd.DataFrame,
    ema_fast_period: int = 8,
    ema_slow_period: int = 21,
    confirm_bars: int = 3,
    asset_role: str = "eth",
    allow_short: bool = True,
) -> pd.Series:
    """ETH/BTC relative-strength rotation. `enriched_a` = ETH's enriched df, `enriched_b` =
    BTC's enriched df (fixed roles). `asset_role` picks which leg's signal is returned.
    """
    idx_a = enriched_a.index
    close_eth = enriched_a["close"]

    same_index = (
        len(enriched_b) == len(enriched_a)
        and enriched_a["timestamp"].to_numpy().tolist() == enriched_b["timestamp"].to_numpy().tolist()
    )
    if same_index:
        close_btc = pd.Series(enriched_b["close"].to_numpy(), index=idx_a)
    else:
        b_by_time = enriched_b.set_index("timestamp")[["close"]].sort_index()
        aligned_b = b_by_time.reindex(enriched_a["timestamp"].to_numpy(), method="ffill")
        close_btc = pd.Series(aligned_b["close"].to_numpy(), index=idx_a)

    ratio = close_eth / close_btc.replace(0, np.nan)
    ratio_ema_fast = ratio.ewm(span=ema_fast_period, adjust=False).mean()
    ratio_ema_slow = ratio.ewm(span=ema_slow_period, adjust=False).mean()

    ratio_trend_up = (ratio_ema_fast > ratio_ema_slow).fillna(False)
    ratio_trend_down = (ratio_ema_fast < ratio_ema_slow).fillna(False)

    # Persistence filter: trend direction must have held for `confirm_bars` consecutive bars.
    eth_season = (ratio_trend_up.rolling(confirm_bars).sum() >= confirm_bars).fillna(False)
    btc_season = (ratio_trend_down.rolling(confirm_bars).sum() >= confirm_bars).fillna(False)

    if asset_role == "eth":
        entry_long = eth_season
        entry_short = btc_season if allow_short else pd.Series(False, index=idx_a)
        exit_long = ~eth_season
        exit_short = ~btc_season
    else:  # asset_role == "btc": mirror image
        entry_long = btc_season
        entry_short = eth_season if allow_short else pd.Series(False, index=idx_a)
        exit_long = ~btc_season
        exit_short = ~eth_season

    from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
        _stateful_from_entries_exits,
    )
    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
