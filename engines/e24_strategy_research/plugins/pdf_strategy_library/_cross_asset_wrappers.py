"""
Module: _cross_asset_wrappers.py
Description: single-DataFrame wrapper factory for this package's two-asset strategies
(strategy_ict_smt_divergence, strategy_gold_silver_ratio_meanrev,
strategy_dxy_regime_filtered_trend, strategy_btc_eth_relative_rotation), so they can be
registered in the standard STRATEGIES dict and run through E24's ordinary
`research(symbol, timeframe, ...)` grid-search pipeline, which only ever calls
`strategy_fn(enriched, **params)` with ONE DataFrame (confirmed via direct grep of
_run_one_candidate_worker/research -- every call site passes exactly one `enriched`).

How it works: each wrapper infers `symbol`/`timeframe` from the primary `enriched` frame's own
`symbol`/`timeframe` columns (confirmed populated by TechnicalAnalysisEngine.analyze on every
enriched frame in this codebase), loads the PAIRED asset's OHLCV from the same
`data/processed/<paired_symbol>_<timeframe>.parquet` cache every other research script in this
project already reads from, enriches it through the SAME TechnicalAnalysisEngine, and calls
the real two-asset strategy function with both frames. No lookahead is introduced by this
wrapper: the paired asset's full available history up to the SAME data snapshot is loaded and
enriched exactly the way it would be if it were itself the primary asset being researched
(its own indicators only ever see its own trailing bars); the underlying two-asset function's
own as-of alignment (already no-lookahead-verified) does the rest.

A small in-process cache keyed by (symbol, timeframe) avoids re-loading/re-enriching the paired
asset on every single grid-candidate call within one research() run (which would otherwise
reload the same parquet + recompute the same indicators dozens of times per run).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

import pandas as pd

logger = logging.getLogger(__name__)

# (paired_symbol, timeframe) pairs already warned about -- one line per
# genuinely missing dataset, not one per candidate in a sweep that may
# touch the same missing pair hundreds of times.
_MISSING_PAIR_WARNED: set[tuple[str, str]] = set()

_DATA_DIR = Path(__file__).resolve().parents[4] / "data" / "processed"
_cache: dict[tuple[str, str], pd.DataFrame] = {}


def _load_enriched(symbol: str, timeframe: str) -> pd.DataFrame:
    key = (symbol, timeframe)
    if key in _cache:
        return _cache[key]
    from project_titan_x.engines.e07_technical.engine import TechnicalAnalysisEngine

    pq = _DATA_DIR / f"{symbol}_{timeframe}.parquet"
    df = pd.read_parquet(pq).reset_index(drop=True)
    ta = TechnicalAnalysisEngine()
    ta.initialize()
    enriched = ta.analyze(df, symbol=symbol, timeframe=timeframe).data["df"]
    _cache[key] = enriched
    return enriched


def make_cross_asset_wrapper(
    fn: Callable[..., pd.Series],
    paired_symbol: str,
    fixed_kwargs: dict | None = None,
) -> Callable[..., pd.Series]:
    """Returns a `wrapper(enriched, **params) -> pd.Series` closure that loads
    `paired_symbol`'s data (matching `enriched`'s own timeframe) and calls
    `fn(enriched, paired_enriched, **fixed_kwargs, **params)`.
    """
    fixed_kwargs = fixed_kwargs or {}

    def wrapper(enriched: pd.DataFrame, **params) -> pd.Series:
        timeframe = str(enriched["timeframe"].iloc[0])
        try:
            paired = _load_enriched(paired_symbol, timeframe)
        except FileNotFoundError:
            # Real bug found 2026-09-14 auditing all 231 registered
            # archetypes: `strategy_dxy_regime_filtered_trend__vs_dxy` is
            # in DEFAULT_STRATEGY_GRID, but only DX-Y.NYB_1d.parquet
            # exists -- there is no 1h/4h/15m DXY cache. So on every
            # non-daily sweep this raised FileNotFoundError, E24's
            # candidate worker swallowed it (`except Exception: return
            # None`), and the strategy vanished from the results with no
            # trace. Not a crash, but not a result either: it looked
            # exactly like a strategy that had been fairly evaluated and
            # lost.
            #
            # Logged once per (symbol, timeframe) and degraded to a flat
            # series: a strategy that cannot see its paired asset has no
            # opinion, which scores as zero trades and is correctly
            # excluded -- the difference from the old behaviour is that
            # the reason is now visible instead of inferred from an
            # absence.
            key = (paired_symbol, timeframe)
            if key not in _MISSING_PAIR_WARNED:
                _MISSING_PAIR_WARNED.add(key)
                logger.warning(
                    "%s: no cached data for paired symbol %s at timeframe %s "
                    "(expected %s) -- strategy cannot be evaluated on this timeframe "
                    "and is reported as flat, not failed. Fetch that symbol/timeframe "
                    "into data/processed/ to enable it.",
                    wrapper.__name__, paired_symbol, timeframe,
                    _DATA_DIR / f"{paired_symbol}_{timeframe}.parquet",
                )
            return pd.Series(0, index=enriched.index, dtype="int8")
        return fn(enriched, paired, **fixed_kwargs, **params)

    wrapper.__name__ = f"{fn.__name__}__vs_{paired_symbol.replace('=', '').replace('.', '_').replace('-', '_')}"
    wrapper.__doc__ = (
        f"Auto-generated single-DataFrame wrapper around {fn.__name__}, paired against "
        f"{paired_symbol} (loaded fresh per (symbol, timeframe), cached in-process). "
        f"See {fn.__module__} for the real strategy logic and interpretive assumptions."
    )
    return wrapper
