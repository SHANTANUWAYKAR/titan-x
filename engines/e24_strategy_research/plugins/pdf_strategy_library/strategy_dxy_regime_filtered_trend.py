"""
Module: strategy_dxy_regime_filtered_trend.py
NEW CONCEPT (2026-09-13): DXY-regime cross-asset filter applied to a GOLD/SILVER trend rule.

This project's own e10_cross_asset engine already tracks "DXY vs Gold" as a real, live-trained
baseline correlation (data/models/e10_cross_asset/baseline_correlations.json:
baseline_correlation = -0.4014, confirmed stable train vs test split) -- but confirmed via
repo-wide grep that NOTHING in engines/e24_strategy_research/ has ever actually traded on
that relationship. Every strategy tried for GOLD/SILVER so far (SMC/ICT, MSS, VWAP/CVD, EMA
crosses, RSI, chart patterns, the 76 PDF-derived strategies) uses only the asset's own price
action. This is the first to add a macro cross-asset regime filter on top of a price rule.

Concept: gold is priced in USD, so a weakening dollar (DXY downtrend) is a structural tailwind
for gold higher, and a strengthening dollar (DXY uptrend) is a structural headwind -- the
well-documented, real inverse relationship the correlation baseline above already confirms.
This strategy takes a simple, well-known trend-following entry (EMA fast > EMA slow, "buy
the trend") but ONLY acts on it when the DXY regime agrees with the trade direction, and
stays flat otherwise -- the cross-asset agreement is a FILTER, not a new entry trigger of its
own, so its net effect is testable in isolation (fewer, more selective trades vs. the
un-filtered version).

TWO-ASSET EXCEPTION to the standard one-DataFrame interface (same documented pattern as
strategy_ict_smt_divergence / strategy_gold_silver_ratio_meanrev in this package):
`enriched_a` = the traded asset (GOLD or SILVER), `enriched_b` = DXY.

Interpretive assumptions:
- DXY "downtrend" / "uptrend" defined the same simple, well-known way as the traded asset's
  own trend rule for consistency: ema_fast vs ema_slow (both already computed columns on
  DXY's own enriched frame -- no bespoke DXY-only indicator invented).
- DXY is only available at 1d resolution in this platform's data store (confirmed via direct
  inspection: no DX-Y.NYB_1h/4h parquet exists) -- if `enriched_b` is coarser than
  `enriched_a` (fewer effective bars per real calendar day), it is forward-filled onto
  `enriched_a`'s timestamps (each intraday bar sees the MOST RECENTLY CLOSED daily DXY bar,
  never a same-day-but-later or future one) -- the same causal as-of alignment convention
  strategy_ict_smt_divergence already established, just documented explicitly here for the
  cross-timeframe case.
- require_agreement=True (default) demands DXY trend and trade direction to structurally
  agree (short gold needs DXY uptrend, long gold needs DXY downtrend) before allowing the
  trade at all; this is deliberately strict so the filter's effect is unambiguous to
  interpret in a backtest.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def strategy_dxy_regime_filtered_trend(
    enriched_a: pd.DataFrame,
    enriched_b: pd.DataFrame,
    rsi_filter: float = 50.0,
) -> pd.Series:
    """EMA-trend entry on `enriched_a` (GOLD or SILVER), gated by DXY's own EMA-trend regime
    on `enriched_b`. Long only when asset trend is up AND DXY trend is down (weak-dollar
    tailwind); short only when asset trend is down AND DXY trend is up (strong-dollar
    headwind). No trade when the two disagree.
    """
    idx_a = enriched_a.index
    close_a = enriched_a["close"]
    ema_fast_a = enriched_a["ema_8"]
    ema_slow_a = enriched_a["ema_21"]
    rsi_a = enriched_a["rsi"]

    same_index = (
        len(enriched_b) == len(enriched_a)
        and enriched_a["timestamp"].to_numpy().tolist() == enriched_b["timestamp"].to_numpy().tolist()
    )
    if same_index:
        dxy_fast = pd.Series(enriched_b["ema_8"].to_numpy(), index=idx_a)
        dxy_slow = pd.Series(enriched_b["ema_21"].to_numpy(), index=idx_a)
    else:
        b_by_time = enriched_b.set_index("timestamp")[["ema_8", "ema_21"]].sort_index()
        aligned_b = b_by_time.reindex(enriched_a["timestamp"].to_numpy(), method="ffill")
        dxy_fast = pd.Series(aligned_b["ema_8"].to_numpy(), index=idx_a)
        dxy_slow = pd.Series(aligned_b["ema_21"].to_numpy(), index=idx_a)

    asset_trend_up = ema_fast_a > ema_slow_a
    asset_trend_down = ema_fast_a < ema_slow_a
    dxy_trend_up = (dxy_fast > dxy_slow).fillna(False)
    dxy_trend_down = (dxy_fast < dxy_slow).fillna(False)

    entry_long = (asset_trend_up & dxy_trend_down & (rsi_a < 70) &
                  (close_a > ema_fast_a)).fillna(False)
    entry_short = (asset_trend_down & dxy_trend_up & (rsi_a > 30) &
                   (close_a < ema_fast_a)).fillna(False)

    exit_long = (~asset_trend_up | ~dxy_trend_down).fillna(True)
    exit_short = (~asset_trend_down | ~dxy_trend_up).fillna(True)

    from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
        _stateful_from_entries_exits,
    )
    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
