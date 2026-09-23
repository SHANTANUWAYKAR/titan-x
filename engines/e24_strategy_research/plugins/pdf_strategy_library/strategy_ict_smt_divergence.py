"""
Module: strategy_ict_smt_divergence.py
Source document(s): ict-smt-divergence.txt
Description: "ICT SMT DIVERGENCE -- Smart Money Tool -- Correlated Asset Divergence Strategy"
(BTC/ETH). TWO-ASSET EXCEPTION to the standard one-DataFrame interface (explicitly permitted by
the batch instructions): an SMT (Smart Money Technique) divergence fires when one asset makes a
fresh extreme (Higher High / Lower Low) while the correlated asset FAILS to confirm it (prints
a Lower High / Higher Low instead), signalling the lagging asset -- and by extension the
broader correlated move -- is losing momentum. Requires a `confirm_bars`-candle wait before
entry, matching the document's stated 2-candle confirmation filter.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._shared import (
    _stateful_from_entries_exits,
)


def strategy_ict_smt_divergence(
    enriched_a: pd.DataFrame,
    enriched_b: pd.DataFrame,
    lookback: int = 20,
    confirm_bars: int = 2,
) -> pd.Series:
    """SMT (Smart Money Technique) divergence between two correlated assets (e.g. BTC vs ETH).

    Source document: "ict-smt-divergence.txt". TWO-ASSET EXCEPTION to the standard
    `strategy_fn(enriched) -> pd.Series` interface used everywhere else in this batch: this
    function needs both correlated assets' enriched DataFrames simultaneously and cannot be
    expressed against a single `enriched` frame, so it explicitly takes `enriched_a` and
    `enriched_b`. The returned signal is aligned to `enriched_a`'s index (call it once per
    asset you want signals for, passing that asset as `enriched_a` and its correlated pair as
    `enriched_b`).

    Rule: BEARISH divergence (SHORT) -- asset A makes a fresh N-bar High (breaks its own prior
    rolling high) while asset B fails to break ITS OWN prior rolling high over the same window
    (forms a Lower High instead). Wait `confirm_bars` additional bars (document: "wait TWO
    additional candles to confirm before entering ... filters false/premature triggers"), then
    enter SHORT. BULLISH divergence (LONG) is the mirror: A makes a fresh N-bar Low while B
    fails to make a new low (forms a Higher Low instead).

    Interpretive assumptions:
    - The document's "SMT Divergence (TFO)" TradingView indicator with "Pivot strength = 2" has
      no public formula; approximated mechanically here with rolling N-bar (`lookback`) extremes
      on both assets rather than true swing-pivot detection -- the closest honest approximation
      using only available OHLC columns.
    - If `enriched_b` does not share `enriched_a`'s exact index/timestamps, it is aligned to
      `enriched_a`'s `timestamp` column via an as-of forward-fill, so no future bar of B ever
      informs a decision at a given A timestamp.
    - Exit uses a break of A's own recent opposite extreme as a structural invalidation
      (the document's exit is the 1:2 R:R target / prior swing level, which is external
      position-sizing/exit-level logic per interface spec, not implemented here).
    - "Wait two additional candles" is implemented causally as `.shift(confirm_bars)` on the
      divergence-detected flag (bar `i`'s entry reflects a divergence event that completed
      `confirm_bars` bars ago) -- never `.shift(-confirm_bars)`.
    """
    idx_a = enriched_a.index
    high_a, low_a, close_a = enriched_a["high"], enriched_a["low"], enriched_a["close"]

    same_index = (
        len(enriched_b) == len(enriched_a)
        and enriched_a["timestamp"].to_numpy().tolist() == enriched_b["timestamp"].to_numpy().tolist()
    )
    if same_index:
        high_b = pd.Series(enriched_b["high"].to_numpy(), index=idx_a)
        low_b = pd.Series(enriched_b["low"].to_numpy(), index=idx_a)
    else:
        b_by_time = enriched_b.set_index("timestamp")[["high", "low"]].sort_index()
        aligned_b = b_by_time.reindex(enriched_a["timestamp"].to_numpy(), method="ffill")
        high_b = pd.Series(aligned_b["high"].to_numpy(), index=idx_a)
        low_b = pd.Series(aligned_b["low"].to_numpy(), index=idx_a)

    prior_high_a = high_a.shift(1).rolling(lookback).max()
    prior_low_a = low_a.shift(1).rolling(lookback).min()
    prior_high_b = high_b.shift(1).rolling(lookback).max()
    prior_low_b = low_b.shift(1).rolling(lookback).min()

    a_fresh_high = high_a > prior_high_a
    a_fresh_low = low_a < prior_low_a
    b_fails_new_high = high_b <= prior_high_b
    b_fails_new_low = low_b >= prior_low_b

    bearish_divergence = (a_fresh_high & b_fails_new_high).fillna(False)
    bullish_divergence = (a_fresh_low & b_fails_new_low).fillna(False)

    entry_short = bearish_divergence.shift(confirm_bars).fillna(False)
    entry_long = bullish_divergence.shift(confirm_bars).fillna(False)

    exit_long = (close_a < prior_low_a).fillna(False)
    exit_short = (close_a > prior_high_a).fillna(False)

    return _stateful_from_entries_exits(entry_long, exit_long, entry_short, exit_short)
