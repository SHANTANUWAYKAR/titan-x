"""
NEW_GEN_CONCEPTS — Next-Generation Market Microstructure Trading Strategies
============================================================================

This package contains 7 advanced strategy modules implementing modern
institutional trading concepts that go beyond traditional price-action
and indicator-based approaches.

All strategies:
  - Accept: pd.DataFrame with OHLCV + standard indicators
  - Return: pd.Series of 1 (long) / -1 (short) / 0 (flat)
  - Signal on CLOSED bars only — no repainting
  - Use only pandas + numpy (no external dependencies)

Modules
-------
strategy_volume_profile_poc     : Volume Profile POC/VAH/VAL levels
strategy_footprint_delta        : Footprint Chart — Cumulative Volume Delta
strategy_tpo_market_profile     : TPO / Market Profile — IB + Value Area
strategy_vwap_bands             : VWAP with Standard Deviation Bands
strategy_heatmap_liquidity      : Liquidity Heatmap — Stop Hunt Detection
strategy_gex_gamma_exposure     : GEX Proxy — Gamma Exposure Regime
strategy_cvd_composite          : FLAGSHIP — 5-component composite scoring

Quick Start
-----------
    from NEW_GEN_CONCEPTS.strategy_cvd_composite import generate_signal
    signals = generate_signal(df)

Required DataFrame columns:
    open, high, low, close, volume,
    EMA_9, EMA_20, EMA_50, EMA_200,
    RSI, MACD, MACD_signal,
    ATR, ADX,
    BB_upper, BB_lower, BB_middle

Author: Project Titan-X
"""

from .strategy_volume_profile_poc import generate_signal as volume_profile_poc
from .strategy_footprint_delta import generate_signal as footprint_delta
from .strategy_tpo_market_profile import generate_signal as tpo_market_profile
from .strategy_vwap_bands import generate_signal as vwap_bands
from .strategy_heatmap_liquidity import generate_signal as heatmap_liquidity
from .strategy_gex_gamma_exposure import generate_signal as gex_gamma_exposure
from .strategy_cvd_composite import generate_signal as cvd_composite

__all__ = [
    "volume_profile_poc",
    "footprint_delta",
    "tpo_market_profile",
    "vwap_bands",
    "heatmap_liquidity",
    "gex_gamma_exposure",
    "cvd_composite",
]

# Registry format compatible with E26 backtesting and E24 strategy research
STRATEGY_REGISTRY = {
    "volume_profile_poc"   : volume_profile_poc,
    "footprint_delta"      : footprint_delta,
    "tpo_market_profile"   : tpo_market_profile,
    "vwap_bands"           : vwap_bands,
    "heatmap_liquidity"    : heatmap_liquidity,
    "gex_gamma_exposure"   : gex_gamma_exposure,
    "cvd_composite"        : cvd_composite,
}
