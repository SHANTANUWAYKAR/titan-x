"""
Module: engine.py
Description: Engine 24 -- Strategy Research. Formalizes the ad hoc
    scripts/training/research_signal_strategies*.py (v1 through v5) pattern
    -- five one-off hand-written scripts produced this session alone, each
    re-copy-pasting the same grid-search-against-E26's-validation-bar loop
    for a new question -- into a reusable engine. Every strategy candidate
    is graded by the SAME judge those scripts used and e51_signals' own
    edge-gate uses: E26 Backtesting Laboratory's run_backtest.passed_validation
    (IS trades>=30, IS Sharpe>0.5, max DD<25%, OOS Sharpe>0). This engine
    does not weaken that bar and does not report a "pass" that isn't real.

    Optionally, when a candidate clears the bar AND the caller explicitly
    passes promote_if_validated=True, writes the SAME
    data/models/e51_signals/{symbol}_{timeframe}_strategy_override.json
    file format e51_signals._load_strategy_override already reads -- the
    exact mechanism that already promoted SP500's Donchian breakout, not a
    new parallel one. Off by default: a research call should never silently
    change what's live (CLAUDE.md Rule 5).

    UPDATED 2026-08-21: PROMOTABLE_STRATEGIES now covers every archetype
    in STRATEGIES (previously just "donchian_breakout" and
    "donchian_breakout_volume_confirmed"), since e51_signals.
    _determine_direction_from_override was rewritten to dispatch
    generically through the same STRATEGIES dict this engine validates
    candidates against, instead of a second, hand-maintained, donchian-
    only reimplementation. Found as a real gap by this session's own 1h/
    1d universe sweeps: several assets (TSLA/macd_cross, ETHUSD/
    regime_adaptive, GOOGL/rsi_mean_reversion, NVDA/AAPL's own 1h
    regime_adaptive/macd_cross wins) had a real, E26-validated edge the
    live engine had no way to act on. Any strategy that still can't be
    promoted is genuinely unknown to STRATEGIES, not arbitrarily excluded.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-07-19
"""

import json
import logging
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from project_titan_x.core.config import get_asset
from project_titan_x.engines.base import BaseEngine, EngineResult, EngineStatus
from project_titan_x.engines.e24_strategy_research.plugins.style_library import STYLE_LIBRARY_STRATEGIES
from project_titan_x.engines.e24_strategy_research.strategies import STRATEGIES, apply_session_filter, session_mask
from project_titan_x.engines.e26_backtesting.engine import BacktestingEngine
from project_titan_x.engines.e02_market_data.engine import MarketDataEngine
from project_titan_x.engines.e07_technical.engine import TechnicalAnalysisEngine

logger = logging.getLogger(__name__)

_REPORT_DIR = Path(__file__).resolve().parents[2] / "data" / "models" / "e24_strategy_research"
_OVERRIDE_DIR = Path(__file__).resolve().parents[2] / "data" / "models" / "e51_signals"

# A reasonable general-purpose default grid -- same archetypes/ranges the
# v5 targeted script used, kept as the default so a caller with no
# opinion still gets a real, non-trivial search. Any caller can override
# with its own strategy_grid.
DEFAULT_STRATEGY_GRID: dict[str, list[dict]] = {
    "baseline_trend": [{}],
    "ma_cross_50_200": [{}],
    "macd_cross": [{}],
    "donchian_breakout": [
        {"entry_n": n, "exit_n": m}
        for n in (10, 15, 20, 25, 30, 40)
        for m in (3, 5, 7, 10, 15)
    ],
    "rsi_mean_reversion": [
        {"oversold": o, "overbought": b}
        for o in (20, 25, 30, 35)
        for b in (65, 70, 75, 80)
    ],
    "bollinger_reversion": [{}],
    "wyckoff_spring_reversal": [{}],
    "liquidity_sweep_reversal": [{"lookback": n} for n in (10, 20, 30, 50)],
    "liquidity_sweep_reversal_trend_filtered": [{"lookback": n} for n in (10, 20, 30, 50)],
    "regime_adaptive": [{}],
    # External-repo plugin strategies (see plugins/__init__.py for
    # provenance; each is a real port of the named repo's own logic).
    "smc_bos_ob_confluence": [{"min_score": 3}, {"min_score": 4}],
    "ict_fvg_retrace": [{"max_age": 10}, {"max_age": 20}],
    "ict_fvg_retrace_killzone": [{"max_age": 20}],
    "freqtrade_rsi_tema_bb": [{}],

    # Added 2026-08-22. These six were all registered in STRATEGIES but
    # had NEVER been swept -- present in the library, absent from the
    # grid, so no sweep in this project's history ever evaluated them.
    # Not a cosmetic omission: donchian_atr_trail measured 75.0% win rate
    # at 2.82R (expectancy 5.10) on real AAPL 1d data in the first test
    # that ever ran it, better on that asset than anything currently
    # promoted. The ATR-trail and trend-filtered variants matter
    # especially for a "2-4R winners" profile, since a trailing exit is
    # the mechanism that produces multi-R winners at all.
    "donchian_atr_trail": [
        {"entry_n": n, "atr_mult": m}
        for n in (10, 20, 30, 40) for m in (2.0, 3.0, 4.0)
    ],
    "donchian_breakout_volume_confirmed": [
        {"entry_n": n, "exit_n": x, "volume_mult": v}
        for n in (20, 30) for x in (7, 10) for v in (1.5, 2.0)
    ],
    "donchian_breakout_volatility_confirmed": [
        {"entry_n": n, "exit_n": x} for n in (20, 30) for x in (7, 10)
    ],
    "donchian_breakout_buffer_confirmed": [
        {"entry_n": n, "exit_n": x} for n in (20, 30) for x in (7, 10)
    ],
    "bollinger_reversion_tuned": [
        {"period": p, "std_mult": s} for p in (20, 30) for s in (2.0, 2.5)
    ],
    "rsi_mean_reversion_trend_filtered": [
        {"oversold": o, "overbought": b, "exit_level": e}
        for o in (25, 30, 35) for b in (65, 70, 75) for e in (45, 50, 60)
    ],

    # Ported from research/ 2026-08-23 after beating the live override on
    # BOTH crypto daily markets (see plugins/dual_thrust.py for the
    # evidence and the parameter-plateau check).
    "dual_thrust": [
        {"lookback": n, "k1": k, "k2": k}
        for n in (4, 6, 8, 10) for k in (0.5, 0.6, 0.7)
    ],
    "heikin_ashi_trend": [{"confirm": c} for c in (1, 2, 3)],

    # The purpose-built 2-4R profile strategy (see its docstring): a
    # mean-reversion entry for hit rate, an ATR trailing exit for R.
    "trend_pullback_atr_trail": [
        {"oversold": o, "overbought": b, "atr_mult": m, "adx_min": x}
        for o, b in ((35, 65), (40, 60), (45, 55))
        for m in (2.0, 3.0, 4.0)
        for x in (15.0, 20.0, 25.0)
    ],

    # New concept families added 2026-09-12: MSS (ICT structure shift --
    # already measured positive solo expectancy on BTCUSD/ETHUSD/GOLD 4h in
    # research/concept_ablation.py, see docs/ICT_CONCEPT_DIFF.md section 5 --
    # but never reachable by this grid until now), VWAP bands, CVD (order-
    # flow proxy), and rolling Volume Profile. See strategies.py's own
    # comment block above mss_trend_hold for full provenance and honesty
    # caveats (VWAP/CVD/Volume-Profile carry no prior solo-edge measurement;
    # MSS does).
    "mss_trend_hold": [
        {"hold_bars": h, "atr_mult": m}
        for h in (5, 10, 15, 20) for m in (1.0, 1.5, 2.0)
    ],
    "mss_trend_filtered": [
        {"hold_bars": h, "atr_mult": m}
        for h in (5, 10, 15, 20) for m in (1.0, 1.5, 2.0)
    ],
    "vwap_mean_reversion": [{"band": b} for b in (1, 2)],
    "vwap_breakout": [{"band": b} for b in (1, 2)],
    "cvd_trend_confirmation": [
        {"cvd_fast": f, "cvd_slow": s}
        for f, s in ((5, 13), (8, 21), (13, 34))
    ],
    "cvd_price_divergence_fade": [{"lookback": n} for n in (10, 20, 30, 50)],
    "volume_profile_fade": [
        {"lookback": lb, "recompute_every": r}
        for lb in (100, 200, 300) for r in (10, 20)
    ],
    "volume_profile_breakout": [
        {"lookback": lb, "recompute_every": r}
        for lb in (100, 200, 300) for r in (10, 20)
    ],

    # -------------------------------------------------------------------
    # 90 user-supplied PDF/DOCX strategy documents, converted 2026-09-12.
    # Grids auto-generated: 0 numeric params -> single default candidate;
    # otherwise the top 1-2 lookback/window-style params swept at
    # default*0.6 / default / default*1.5 (rounded), capped at 9 combos.
    # Session-timing params (_hour/_minute) intentionally left untuned --
    # they encode the source document's stated session, not a free knob.
    # See data/strategy_conversion_batch/generate_grid.py for the exact rule.
    # -------------------------------------------------------------------
    "strategy_10ema_intraday_pullback": [{'momentum_lookback': 6, 'arm_window': 5}, {'momentum_lookback': 6, 'arm_window': 8}, {'momentum_lookback': 6, 'arm_window': 12}, {'momentum_lookback': 10, 'arm_window': 5}, {'momentum_lookback': 10, 'arm_window': 8}, {'momentum_lookback': 10, 'arm_window': 12}, {'momentum_lookback': 15, 'arm_window': 5}, {'momentum_lookback': 15, 'arm_window': 8}, {'momentum_lookback': 15, 'arm_window': 12}],
    "strategy_200ema_trend_filter": [{'pullback_atr': 0.15}, {'pullback_atr': 0.25}, {'pullback_atr': 0.375}],
    "strategy_3ema_ribbon_crossover": [{}],
    "strategy_5ema_low_high_break_powerofstocks": [{}],
    "strategy_72min_tbs_gold_journexfx": [{}],
    "strategy_8020_mean_reversion_okala": [{'level_step': 60.0, 'momentum_lookback': 2}, {'level_step': 60.0, 'momentum_lookback': 3}, {'level_step': 60.0, 'momentum_lookback': 4}, {'level_step': 100.0, 'momentum_lookback': 2}, {'level_step': 100.0, 'momentum_lookback': 3}, {'level_step': 100.0, 'momentum_lookback': 4}, {'level_step': 150.0, 'momentum_lookback': 2}, {'level_step': 150.0, 'momentum_lookback': 3}, {'level_step': 150.0, 'momentum_lookback': 4}],
    "strategy_915200_ema_trend_breakout": [{'sync_window': 2, 'momentum_lookback': 2}, {'sync_window': 2, 'momentum_lookback': 3}, {'sync_window': 2, 'momentum_lookback': 4}, {'sync_window': 3, 'momentum_lookback': 2}, {'sync_window': 3, 'momentum_lookback': 3}, {'sync_window': 3, 'momentum_lookback': 4}, {'sync_window': 4, 'momentum_lookback': 2}, {'sync_window': 4, 'momentum_lookback': 3}, {'sync_window': 4, 'momentum_lookback': 4}],
    "strategy_9_15ema_crossover_retest": [{'angle_lookback': 3, 'angle_atr_mult': 0.48}, {'angle_lookback': 3, 'angle_atr_mult': 0.8}, {'angle_lookback': 3, 'angle_atr_mult': 1.2}, {'angle_lookback': 5, 'angle_atr_mult': 0.48}, {'angle_lookback': 5, 'angle_atr_mult': 0.8}, {'angle_lookback': 5, 'angle_atr_mult': 1.2}, {'angle_lookback': 8, 'angle_atr_mult': 0.48}, {'angle_lookback': 8, 'angle_atr_mult': 0.8}, {'angle_lookback': 8, 'angle_atr_mult': 1.2}],
    "strategy_9_15ema_mayankraj_sr_rejection": [{'sr_lookback': 12, 'proximity_atr': 0.3}, {'sr_lookback': 12, 'proximity_atr': 0.5}, {'sr_lookback': 12, 'proximity_atr': 0.75}, {'sr_lookback': 20, 'proximity_atr': 0.3}, {'sr_lookback': 20, 'proximity_atr': 0.5}, {'sr_lookback': 20, 'proximity_atr': 0.75}, {'sr_lookback': 30, 'proximity_atr': 0.3}, {'sr_lookback': 30, 'proximity_atr': 0.5}, {'sr_lookback': 30, 'proximity_atr': 0.75}],
    "strategy_9_20ema_crossover_confirmed": [{'cross_recent_window': 3, 'slope_lookback': 2}, {'cross_recent_window': 3, 'slope_lookback': 3}, {'cross_recent_window': 3, 'slope_lookback': 4}, {'cross_recent_window': 5, 'slope_lookback': 2}, {'cross_recent_window': 5, 'slope_lookback': 3}, {'cross_recent_window': 5, 'slope_lookback': 4}, {'cross_recent_window': 8, 'slope_lookback': 2}, {'cross_recent_window': 8, 'slope_lookback': 3}, {'cross_recent_window': 8, 'slope_lookback': 4}],
    "strategy_9_20ema_stockburner": [{'expand_lookback': 6}, {'expand_lookback': 10}, {'expand_lookback': 15}],
    "strategy_ali_crooks_trendline_pocket": [{'key_level_lookback': 30, 'structure_lookback': 6}, {'key_level_lookback': 30, 'structure_lookback': 10}, {'key_level_lookback': 30, 'structure_lookback': 15}, {'key_level_lookback': 50, 'structure_lookback': 6}, {'key_level_lookback': 50, 'structure_lookback': 10}, {'key_level_lookback': 50, 'structure_lookback': 15}, {'key_level_lookback': 75, 'structure_lookback': 6}, {'key_level_lookback': 75, 'structure_lookback': 10}, {'key_level_lookback': 75, 'structure_lookback': 15}],
    "strategy_anish_singh_vwap_stochrsi_pivot": [{'stoch_bull_level': 30.0}, {'stoch_bull_level': 50.0}, {'stoch_bull_level': 75.0}],
    "strategy_asian_session_bos": [{'sweep_lookback': 7, 'bos_swing_lookback': 3}, {'sweep_lookback': 7, 'bos_swing_lookback': 5}, {'sweep_lookback': 7, 'bos_swing_lookback': 8}, {'sweep_lookback': 12, 'bos_swing_lookback': 3}, {'sweep_lookback': 12, 'bos_swing_lookback': 5}, {'sweep_lookback': 12, 'bos_swing_lookback': 8}, {'sweep_lookback': 18, 'bos_swing_lookback': 3}, {'sweep_lookback': 18, 'bos_swing_lookback': 5}, {'sweep_lookback': 18, 'bos_swing_lookback': 8}],
    "strategy_big_bar_9ema_retest": [{'adx_trend_threshold': 15.0}, {'adx_trend_threshold': 25.0}, {'adx_trend_threshold': 37.5}],
    "strategy_blackbox_fakeout_reclaim": [{'level_lookback': 24, 'sweep_window': 3}, {'level_lookback': 24, 'sweep_window': 5}, {'level_lookback': 24, 'sweep_window': 8}, {'level_lookback': 40, 'sweep_window': 3}, {'level_lookback': 40, 'sweep_window': 5}, {'level_lookback': 40, 'sweep_window': 8}, {'level_lookback': 60, 'sweep_window': 3}, {'level_lookback': 60, 'sweep_window': 5}, {'level_lookback': 60, 'sweep_window': 8}],
    "strategy_box_pdh_pdl_bounce": [{}],
    "strategy_candlestick_wick_zone_reversal": [{'zone_lookback': 18, 'consolidation_adx_threshold': 15.0}, {'zone_lookback': 18, 'consolidation_adx_threshold': 25.0}, {'zone_lookback': 18, 'consolidation_adx_threshold': 37.5}, {'zone_lookback': 30, 'consolidation_adx_threshold': 15.0}, {'zone_lookback': 30, 'consolidation_adx_threshold': 25.0}, {'zone_lookback': 30, 'consolidation_adx_threshold': 37.5}, {'zone_lookback': 45, 'consolidation_adx_threshold': 15.0}, {'zone_lookback': 45, 'consolidation_adx_threshold': 25.0}, {'zone_lookback': 45, 'consolidation_adx_threshold': 37.5}],
    "strategy_ema200_trendline_breakout": [{'trendline_window': 12}, {'trendline_window': 20}, {'trendline_window': 30}],
    "strategy_ema_9_21_crossover": [{}],
    "strategy_ema_fibonacci_pivot_breakout": [{'volume_ma_window': 12, 'body_ratio_threshold': 0.36}, {'volume_ma_window': 12, 'body_ratio_threshold': 0.6}, {'volume_ma_window': 12, 'body_ratio_threshold': 0.9}, {'volume_ma_window': 20, 'body_ratio_threshold': 0.36}, {'volume_ma_window': 20, 'body_ratio_threshold': 0.6}, {'volume_ma_window': 20, 'body_ratio_threshold': 0.9}, {'volume_ma_window': 30, 'body_ratio_threshold': 0.36}, {'volume_ma_window': 30, 'body_ratio_threshold': 0.6}, {'volume_ma_window': 30, 'body_ratio_threshold': 0.9}],
    "strategy_ema_rejection_mtf": [{}],
    "strategy_fabio_valentini_pullback_scalp": [{'volume_ma_window': 12, 'adx_trend_threshold': 15.0}, {'volume_ma_window': 12, 'adx_trend_threshold': 25.0}, {'volume_ma_window': 12, 'adx_trend_threshold': 37.5}, {'volume_ma_window': 20, 'adx_trend_threshold': 15.0}, {'volume_ma_window': 20, 'adx_trend_threshold': 25.0}, {'volume_ma_window': 20, 'adx_trend_threshold': 37.5}, {'volume_ma_window': 30, 'adx_trend_threshold': 15.0}, {'volume_ma_window': 30, 'adx_trend_threshold': 25.0}, {'volume_ma_window': 30, 'adx_trend_threshold': 37.5}],
    "strategy_fair_value_gap_reversion": [{}],
    "strategy_fibonacci_deep_retracement_pullback": [{'swing_lookback': 18, 'fib_zone_low': 0.42}, {'swing_lookback': 18, 'fib_zone_low': 0.7}, {'swing_lookback': 18, 'fib_zone_low': 1.05}, {'swing_lookback': 30, 'fib_zone_low': 0.42}, {'swing_lookback': 30, 'fib_zone_low': 0.7}, {'swing_lookback': 30, 'fib_zone_low': 1.05}, {'swing_lookback': 45, 'fib_zone_low': 0.42}, {'swing_lookback': 45, 'fib_zone_low': 0.7}, {'swing_lookback': 45, 'fib_zone_low': 1.05}],
    "strategy_fxalexg_mtf_swing": [{'zone_lookback': 36, 'stability_bars': 9}, {'zone_lookback': 36, 'stability_bars': 15}, {'zone_lookback': 36, 'stability_bars': 22}, {'zone_lookback': 60, 'stability_bars': 9}, {'zone_lookback': 60, 'stability_bars': 15}, {'zone_lookback': 60, 'stability_bars': 22}, {'zone_lookback': 90, 'stability_bars': 9}, {'zone_lookback': 90, 'stability_bars': 15}, {'zone_lookback': 90, 'stability_bars': 22}],
    "strategy_gautam_jha_pdh_pdl_breakout_reversal": [{'break_lookback': 9}, {'break_lookback': 15}, {'break_lookback': 22}],
    "strategy_mambafx_1m_sr_breakout": [{'sr_lookback': 36, 'stability_bars': 6}, {'sr_lookback': 36, 'stability_bars': 10}, {'sr_lookback': 36, 'stability_bars': 15}, {'sr_lookback': 60, 'stability_bars': 6}, {'sr_lookback': 60, 'stability_bars': 10}, {'sr_lookback': 60, 'stability_bars': 15}, {'sr_lookback': 90, 'stability_bars': 6}, {'sr_lookback': 90, 'stability_bars': 10}, {'sr_lookback': 90, 'stability_bars': 15}],
    "strategy_orb_retest_confirmation": [{'retest_lookback': 12}, {'retest_lookback': 20}, {'retest_lookback': 30}],
    "strategy_timeframe_based_session": [{'major_window': 27, 'minor_window': 9}, {'major_window': 27, 'minor_window': 15}, {'major_window': 27, 'minor_window': 22}, {'major_window': 45, 'minor_window': 9}, {'major_window': 45, 'minor_window': 15}, {'major_window': 45, 'minor_window': 22}, {'major_window': 68, 'minor_window': 9}, {'major_window': 68, 'minor_window': 15}, {'major_window': 68, 'minor_window': 22}],
    "strategy_tom_hougaard_situational_analysis": [{}],
    "strategy_tom_vorwald_pbd_method": [{'adx_trend_threshold': 15.0}, {'adx_trend_threshold': 25.0}, {'adx_trend_threshold': 37.5}],
    "strategy_tori_trades_trendline": [{'touch_lookback': 25, 'touch_tolerance_atr_mult': 0.3}, {'touch_lookback': 25, 'touch_tolerance_atr_mult': 0.5}, {'touch_lookback': 25, 'touch_tolerance_atr_mult': 0.75}, {'touch_lookback': 42, 'touch_tolerance_atr_mult': 0.3}, {'touch_lookback': 42, 'touch_tolerance_atr_mult': 0.5}, {'touch_lookback': 42, 'touch_tolerance_atr_mult': 0.75}, {'touch_lookback': 63, 'touch_tolerance_atr_mult': 0.3}, {'touch_lookback': 63, 'touch_tolerance_atr_mult': 0.5}, {'touch_lookback': 63, 'touch_tolerance_atr_mult': 0.75}],
    "strategy_trader_kane_po3_manipulation": [{'range_window': 12}, {'range_window': 20}, {'range_window': 30}],
    "strategy_trader_mayne_structure_ote": [{'htf_window': 60, 'ltf_window': 6}, {'htf_window': 60, 'ltf_window': 10}, {'htf_window': 60, 'ltf_window': 15}, {'htf_window': 100, 'ltf_window': 6}, {'htf_window': 100, 'ltf_window': 10}, {'htf_window': 100, 'ltf_window': 15}, {'htf_window': 150, 'ltf_window': 6}, {'htf_window': 150, 'ltf_window': 10}, {'htf_window': 150, 'ltf_window': 15}],
    "strategy_traders_paradise_black_box": [{'level_window': 12, 'confirm_window': 3}, {'level_window': 12, 'confirm_window': 5}, {'level_window': 12, 'confirm_window': 8}, {'level_window': 20, 'confirm_window': 3}, {'level_window': 20, 'confirm_window': 5}, {'level_window': 20, 'confirm_window': 8}, {'level_window': 30, 'confirm_window': 3}, {'level_window': 30, 'confirm_window': 5}, {'level_window': 30, 'confirm_window': 8}],
    "strategy_tradewithsunil_orb_5min": [{'retest_tolerance_atr_mult': 0.09}, {'retest_tolerance_atr_mult': 0.15}, {'retest_tolerance_atr_mult': 0.225}],

    # 15 more strategies from the remaining ~53 PDF/DOCX documents, converted 2026-09-13
    # (second sub-batch: Gautam Jha variants, Guardeer ICT/SMC, Inna Rosputnia, JadeCap,
    # Lance, Liquidity Sweep, Little Rizzy, London Breakout, MambaFX NY/scalping).
    # strategy_ict_smt_divergence is INTENTIONALLY EXCLUDED here -- it takes two DataFrames
    # (enriched_a, enriched_b) for cross-asset SMT divergence and cannot run through the
    # single-symbol research() grid search; call it directly, not via this grid.
    "strategy_gautam_jha_reaction_zone_liquidity_grab": [{'zone_lookback': 24, 'body_ratio_threshold': 0.36}, {'zone_lookback': 24, 'body_ratio_threshold': 0.6}, {'zone_lookback': 24, 'body_ratio_threshold': 0.9}, {'zone_lookback': 40, 'body_ratio_threshold': 0.36}, {'zone_lookback': 40, 'body_ratio_threshold': 0.6}, {'zone_lookback': 40, 'body_ratio_threshold': 0.9}, {'zone_lookback': 60, 'body_ratio_threshold': 0.36}, {'zone_lookback': 60, 'body_ratio_threshold': 0.6}, {'zone_lookback': 60, 'body_ratio_threshold': 0.9}],
    "strategy_gautam_trading_breakout": [{'break_lookback': 9}, {'break_lookback': 15}, {'break_lookback': 22}],
    "strategy_gautamjha_trading_breakout": [{'break_lookback': 9}, {'break_lookback': 15}, {'break_lookback': 22}],
    "strategy_guardeer_ict_smc_sniper_choch_idm": [{'choch_window': 9, 'idm_window': 6}, {'choch_window': 9, 'idm_window': 10}, {'choch_window': 9, 'idm_window': 15}, {'choch_window': 15, 'idm_window': 6}, {'choch_window': 15, 'idm_window': 10}, {'choch_window': 15, 'idm_window': 15}, {'choch_window': 22, 'idm_window': 6}, {'choch_window': 22, 'idm_window': 10}, {'choch_window': 22, 'idm_window': 15}],
    "strategy_guardeer_smc_structure_bos_ob": [{'sweep_lookback': 18, 'retrace_lookback': 12}, {'sweep_lookback': 18, 'retrace_lookback': 20}, {'sweep_lookback': 18, 'retrace_lookback': 30}, {'sweep_lookback': 30, 'retrace_lookback': 12}, {'sweep_lookback': 30, 'retrace_lookback': 20}, {'sweep_lookback': 30, 'retrace_lookback': 30}, {'sweep_lookback': 45, 'retrace_lookback': 12}, {'sweep_lookback': 45, 'retrace_lookback': 20}, {'sweep_lookback': 45, 'retrace_lookback': 30}],
    "strategy_inna_rosputnia_sma_trend": [{'volume_lookback': 12}, {'volume_lookback': 20}, {'volume_lookback': 30}],
    "strategy_jadecap_playbook_session_liquidity": [{'raid_confirm_window': 6}, {'raid_confirm_window': 10}, {'raid_confirm_window': 15}],
    "strategy_jadecap_swing_sweep_trap_breakout": [{'level_lookback': 30, 'confirm_window': 6}, {'level_lookback': 30, 'confirm_window': 10}, {'level_lookback': 30, 'confirm_window': 15}, {'level_lookback': 50, 'confirm_window': 6}, {'level_lookback': 50, 'confirm_window': 10}, {'level_lookback': 50, 'confirm_window': 15}, {'level_lookback': 75, 'confirm_window': 6}, {'level_lookback': 75, 'confirm_window': 10}, {'level_lookback': 75, 'confirm_window': 15}],
    "strategy_lance_capitulation_reversal": [{'avg_window': 12, 'extreme_multiplier': 0.9}, {'avg_window': 12, 'extreme_multiplier': 1.5}, {'avg_window': 12, 'extreme_multiplier': 2.25}, {'avg_window': 20, 'extreme_multiplier': 0.9}, {'avg_window': 20, 'extreme_multiplier': 1.5}, {'avg_window': 20, 'extreme_multiplier': 2.25}, {'avg_window': 30, 'extreme_multiplier': 0.9}, {'avg_window': 30, 'extreme_multiplier': 1.5}, {'avg_window': 30, 'extreme_multiplier': 2.25}],
    "strategy_liquidity_sweep_pdh_pdl": [{'wick_ratio': 0.3}, {'wick_ratio': 0.5}, {'wick_ratio': 0.75}],
    "strategy_little_rizzy_trend_bos": [{'swing_lookback': 12, 'confirm_window': 3}, {'swing_lookback': 12, 'confirm_window': 5}, {'swing_lookback': 12, 'confirm_window': 8}, {'swing_lookback': 20, 'confirm_window': 3}, {'swing_lookback': 20, 'confirm_window': 5}, {'swing_lookback': 20, 'confirm_window': 8}, {'swing_lookback': 30, 'confirm_window': 3}, {'swing_lookback': 30, 'confirm_window': 5}, {'swing_lookback': 30, 'confirm_window': 8}],
    "strategy_london_breakout_asian_range": [{}],
    "strategy_mambafx_ny_session_breakout": [{'prep_lookback': 12}, {'prep_lookback': 20}, {'prep_lookback': 30}],
    "strategy_mambafx_scalping_breakout": [{'zone_lookback': 12, 'touch_atr_mult': 0.15}, {'zone_lookback': 12, 'touch_atr_mult': 0.25}, {'zone_lookback': 12, 'touch_atr_mult': 0.375}, {'zone_lookback': 20, 'touch_atr_mult': 0.15}, {'zone_lookback': 20, 'touch_atr_mult': 0.25}, {'zone_lookback': 20, 'touch_atr_mult': 0.375}, {'zone_lookback': 30, 'touch_atr_mult': 0.15}, {'zone_lookback': 30, 'touch_atr_mult': 0.25}, {'zone_lookback': 30, 'touch_atr_mult': 0.375}],

    # 24 more strategies from the final ~24 PDF/DOCX documents, converted 2026-09-13
    # (third and final sub-batch: Marci/Measured-Move, Marco liquidity, Martin Luke swing,
    # NBB PO3, 2 ORB variants, 2 Usman Noah FVG/PDH-PDL, Photon SMC, 2 PowerOfStocks, RSI
    # divergence, Swappy 3C v2, FXAlexG thin-note, TG Capital Trident, Trading Geek, Travelling
    # Trader, First Red Day, TheTradeRoom EMA, TradeWithSunil reversal, Trendline 4H, 2 Umar
    # Punjabi variants, VWAP Devanshraiyt). strategy_umar_punjabi_gold_fib_sr's fib_level is
    # PINNED to the canonical 0.382 (not swept) -- it's a named Fibonacci ratio from the source
    # document, not a free tunable parameter.
    "strategy_first_red_day_short": [{'min_extension_days': 2, 'parabolic_return_atr_mult': 0.9}, {'min_extension_days': 2, 'parabolic_return_atr_mult': 1.5}, {'min_extension_days': 2, 'parabolic_return_atr_mult': 2.25}, {'min_extension_days': 3, 'parabolic_return_atr_mult': 0.9}, {'min_extension_days': 3, 'parabolic_return_atr_mult': 1.5}, {'min_extension_days': 3, 'parabolic_return_atr_mult': 2.25}, {'min_extension_days': 4, 'parabolic_return_atr_mult': 0.9}, {'min_extension_days': 4, 'parabolic_return_atr_mult': 1.5}, {'min_extension_days': 4, 'parabolic_return_atr_mult': 2.25}],
    "strategy_marco_liquidity_trap_reversal": [{'level_lookback': 18, 'respect_bars': 6}, {'level_lookback': 18, 'respect_bars': 10}, {'level_lookback': 18, 'respect_bars': 15}, {'level_lookback': 30, 'respect_bars': 6}, {'level_lookback': 30, 'respect_bars': 10}, {'level_lookback': 30, 'respect_bars': 15}, {'level_lookback': 45, 'respect_bars': 6}, {'level_lookback': 45, 'respect_bars': 10}, {'level_lookback': 45, 'respect_bars': 15}],
    "strategy_martin_luke_momentum_swing": [{'inside_day_window': 2, 'pdh_lookback': 1}, {'inside_day_window': 2, 'pdh_lookback': 2}, {'inside_day_window': 3, 'pdh_lookback': 1}, {'inside_day_window': 3, 'pdh_lookback': 2}, {'inside_day_window': 4, 'pdh_lookback': 1}, {'inside_day_window': 4, 'pdh_lookback': 2}],
    "strategy_measured_move_trendline_projection": [{'pullback_window': 6, 'bb_exhaustion_mult': 0.588}, {'pullback_window': 6, 'bb_exhaustion_mult': 0.98}, {'pullback_window': 6, 'bb_exhaustion_mult': 1.47}, {'pullback_window': 10, 'bb_exhaustion_mult': 0.588}, {'pullback_window': 10, 'bb_exhaustion_mult': 0.98}, {'pullback_window': 10, 'bb_exhaustion_mult': 1.47}, {'pullback_window': 15, 'bb_exhaustion_mult': 0.588}, {'pullback_window': 15, 'bb_exhaustion_mult': 0.98}, {'pullback_window': 15, 'bb_exhaustion_mult': 1.47}],
    "strategy_nbb_po3_ote_reversal": [{'range_window': 12, 'manipulation_window': 3}, {'range_window': 12, 'manipulation_window': 5}, {'range_window': 12, 'manipulation_window': 8}, {'range_window': 20, 'manipulation_window': 3}, {'range_window': 20, 'manipulation_window': 5}, {'range_window': 20, 'manipulation_window': 8}, {'range_window': 30, 'manipulation_window': 3}, {'range_window': 30, 'manipulation_window': 5}, {'range_window': 30, 'manipulation_window': 8}],
    "strategy_orb_anish_retest_sr": [{'body_ratio_threshold': 0.3}, {'body_ratio_threshold': 0.5}, {'body_ratio_threshold': 0.75}],
    "strategy_photon_smc_supply_demand": [{'swing_lookback': 12, 'zone_body_ratio': 0.36}, {'swing_lookback': 12, 'zone_body_ratio': 0.6}, {'swing_lookback': 12, 'zone_body_ratio': 0.9}, {'swing_lookback': 20, 'zone_body_ratio': 0.36}, {'swing_lookback': 20, 'zone_body_ratio': 0.6}, {'swing_lookback': 20, 'zone_body_ratio': 0.9}, {'swing_lookback': 30, 'zone_body_ratio': 0.36}, {'swing_lookback': 30, 'zone_body_ratio': 0.6}, {'swing_lookback': 30, 'zone_body_ratio': 0.9}],
    "strategy_poweofstocks_5min_sr_ema_break": [{'sr_lookback': 18, 'zone_atr_mult': 0.3}, {'sr_lookback': 18, 'zone_atr_mult': 0.5}, {'sr_lookback': 18, 'zone_atr_mult': 0.75}, {'sr_lookback': 30, 'zone_atr_mult': 0.3}, {'sr_lookback': 30, 'zone_atr_mult': 0.5}, {'sr_lookback': 30, 'zone_atr_mult': 0.75}, {'sr_lookback': 45, 'zone_atr_mult': 0.3}, {'sr_lookback': 45, 'zone_atr_mult': 0.5}, {'sr_lookback': 45, 'zone_atr_mult': 0.75}],
    "strategy_power_of_stocks_5ema_break": [{}],
    "strategy_stockburner_rsi_divergence": [{'pivot_lookback': 6, 'confirm_bars': 2}, {'pivot_lookback': 6, 'confirm_bars': 3}, {'pivot_lookback': 6, 'confirm_bars': 4}, {'pivot_lookback': 10, 'confirm_bars': 2}, {'pivot_lookback': 10, 'confirm_bars': 3}, {'pivot_lookback': 10, 'confirm_bars': 4}, {'pivot_lookback': 15, 'confirm_bars': 2}, {'pivot_lookback': 15, 'confirm_bars': 3}, {'pivot_lookback': 15, 'confirm_bars': 4}],
    "strategy_swappy_3c_scalping_v2": [{'body_ratio_threshold': 0.39, 'adx_min': 9.0}, {'body_ratio_threshold': 0.39, 'adx_min': 15.0}, {'body_ratio_threshold': 0.39, 'adx_min': 22.5}, {'body_ratio_threshold': 0.65, 'adx_min': 9.0}, {'body_ratio_threshold': 0.65, 'adx_min': 15.0}, {'body_ratio_threshold': 0.65, 'adx_min': 22.5}, {'body_ratio_threshold': 0.975, 'adx_min': 9.0}, {'body_ratio_threshold': 0.975, 'adx_min': 15.0}, {'body_ratio_threshold': 0.975, 'adx_min': 22.5}],
    "strategy_swing_fxalexg_mtf_confirm": [{'zone_lookback': 36, 'stability_bars': 9}, {'zone_lookback': 36, 'stability_bars': 15}, {'zone_lookback': 36, 'stability_bars': 22}, {'zone_lookback': 60, 'stability_bars': 9}, {'zone_lookback': 60, 'stability_bars': 15}, {'zone_lookback': 60, 'stability_bars': 22}, {'zone_lookback': 90, 'stability_bars': 9}, {'zone_lookback': 90, 'stability_bars': 15}, {'zone_lookback': 90, 'stability_bars': 22}],
    "strategy_tg_capital_trident_fvg": [{'fvg_lookback': 9}, {'fvg_lookback': 15}, {'fvg_lookback': 22}],
    "strategy_thetraderoom_ema_crossover_pullback": [{'slope_lookback': 2, 'slope_atr_mult': 0.3}, {'slope_lookback': 2, 'slope_atr_mult': 0.5}, {'slope_lookback': 2, 'slope_atr_mult': 0.75}, {'slope_lookback': 3, 'slope_atr_mult': 0.3}, {'slope_lookback': 3, 'slope_atr_mult': 0.5}, {'slope_lookback': 3, 'slope_atr_mult': 0.75}, {'slope_lookback': 4, 'slope_atr_mult': 0.3}, {'slope_lookback': 4, 'slope_atr_mult': 0.5}, {'slope_lookback': 4, 'slope_atr_mult': 0.75}],
    "strategy_tradewithsunil_opening_candle_reversal": [{'sustain_bars': 1}, {'sustain_bars': 2}, {'sustain_bars': 3}],
    "strategy_trading_geek_gold_supply_demand": [{'zone_lookback': 24, 'impulse_bars': 2}, {'zone_lookback': 24, 'impulse_bars': 3}, {'zone_lookback': 24, 'impulse_bars': 4}, {'zone_lookback': 40, 'impulse_bars': 2}, {'zone_lookback': 40, 'impulse_bars': 3}, {'zone_lookback': 40, 'impulse_bars': 4}, {'zone_lookback': 60, 'impulse_bars': 2}, {'zone_lookback': 60, 'impulse_bars': 3}, {'zone_lookback': 60, 'impulse_bars': 4}],
    "strategy_travelling_trader_catalyst_retrace": [{'structure_lookback': 12, 'displacement_bars': 2}, {'structure_lookback': 12, 'displacement_bars': 3}, {'structure_lookback': 12, 'displacement_bars': 4}, {'structure_lookback': 20, 'displacement_bars': 2}, {'structure_lookback': 20, 'displacement_bars': 3}, {'structure_lookback': 20, 'displacement_bars': 4}, {'structure_lookback': 30, 'displacement_bars': 2}, {'structure_lookback': 30, 'displacement_bars': 3}, {'structure_lookback': 30, 'displacement_bars': 4}],
    "strategy_trendline_based_4h_breakout": [{'trendline_window': 12}, {'trendline_window': 20}, {'trendline_window': 30}],
    "strategy_umar_punjabi_gold_fib_sr": [{'swing_lookback': 18}, {'swing_lookback': 30}, {'swing_lookback': 45}],
    "strategy_umar_punjabi_orderblock_breakout": [{'impulse_bars': 2, 'impulse_body_ratio': 0.33}, {'impulse_bars': 2, 'impulse_body_ratio': 0.55}, {'impulse_bars': 2, 'impulse_body_ratio': 0.825}, {'impulse_bars': 3, 'impulse_body_ratio': 0.33}, {'impulse_bars': 3, 'impulse_body_ratio': 0.55}, {'impulse_bars': 3, 'impulse_body_ratio': 0.825}, {'impulse_bars': 4, 'impulse_body_ratio': 0.33}, {'impulse_bars': 4, 'impulse_body_ratio': 0.55}, {'impulse_bars': 4, 'impulse_body_ratio': 0.825}],
    "strategy_usman_noah_fvg_displacement": [{'htf_fvg_lookback': 24, 'ltf_fvg_lookback': 5}, {'htf_fvg_lookback': 24, 'ltf_fvg_lookback': 8}, {'htf_fvg_lookback': 24, 'ltf_fvg_lookback': 12}, {'htf_fvg_lookback': 40, 'ltf_fvg_lookback': 5}, {'htf_fvg_lookback': 40, 'ltf_fvg_lookback': 8}, {'htf_fvg_lookback': 40, 'ltf_fvg_lookback': 12}, {'htf_fvg_lookback': 60, 'ltf_fvg_lookback': 5}, {'htf_fvg_lookback': 60, 'ltf_fvg_lookback': 8}, {'htf_fvg_lookback': 60, 'ltf_fvg_lookback': 12}],
    "strategy_usman_noah_pdh_pdl_engulfing": [{'pdh_pdl_window': 14}, {'pdh_pdl_window': 24}, {'pdh_pdl_window': 36}],
    "strategy_vwap_devanshraiyt_cross_retrace": [{'cross_lookback': 6, 'retest_atr_mult': 0.18}, {'cross_lookback': 6, 'retest_atr_mult': 0.3}, {'cross_lookback': 6, 'retest_atr_mult': 0.45}, {'cross_lookback': 10, 'retest_atr_mult': 0.18}, {'cross_lookback': 10, 'retest_atr_mult': 0.3}, {'cross_lookback': 10, 'retest_atr_mult': 0.45}, {'cross_lookback': 15, 'retest_atr_mult': 0.18}, {'cross_lookback': 15, 'retest_atr_mult': 0.3}, {'cross_lookback': 15, 'retest_atr_mult': 0.45}],
    "strategy_worlds_best_orb_retest_sr": [{'sr_lookback': 12, 'touch_atr_mult': 0.3}, {'sr_lookback': 12, 'touch_atr_mult': 0.5}, {'sr_lookback': 12, 'touch_atr_mult': 0.75}, {'sr_lookback': 20, 'touch_atr_mult': 0.3}, {'sr_lookback': 20, 'touch_atr_mult': 0.5}, {'sr_lookback': 20, 'touch_atr_mult': 0.75}, {'sr_lookback': 30, 'touch_atr_mult': 0.3}, {'sr_lookback': 30, 'touch_atr_mult': 0.5}, {'sr_lookback': 30, 'touch_atr_mult': 0.75}],

    # ------------------------------------------------------------------
    # NEW CONCEPTS (2026-09-13): Hurst regime switching, volatility squeeze,
    # and 3 genuine cross-asset strategies -- added in direct response to
    # the user's explicit request for NEW/enhanced concepts, not more
    # single-asset price-action pattern variations. Grids designed
    # deliberately (not auto-generated) around each concept's real degrees
    # of freedom.
    # ------------------------------------------------------------------
    "strategy_hurst_regime_switch": [
        {"window": w, "trend_threshold": tt, "revert_threshold": round(1.0 - tt, 2)}
        for w in (60, 100, 150) for tt in (0.55, 0.60, 0.65)
    ],
    "strategy_volatility_squeeze_breakout": [
        {"vol_window": vw, "squeeze_percentile": sp}
        for vw in (14, 20, 30) for sp in (15.0, 20.0, 25.0)
    ],
    "strategy_gold_silver_ratio_meanrev__gold_leg": [
        {"zscore_window": zw, "entry_z": ez}
        for zw in (40, 60, 90) for ez in (1.25, 1.5, 2.0)
    ],
    "strategy_gold_silver_ratio_meanrev__silver_leg": [
        {"zscore_window": zw, "entry_z": ez}
        for zw in (40, 60, 90) for ez in (1.25, 1.5, 2.0)
    ],
    "strategy_dxy_regime_filtered_trend__vs_dxy": [
        {"rsi_filter": 50.0},
    ],
    "strategy_btc_eth_relative_rotation__eth_leg": [
        {"ema_fast_period": ef, "ema_slow_period": es, "confirm_bars": cb}
        for ef, es in ((8, 21), (12, 26)) for cb in (2, 3, 5)
    ],
    "strategy_btc_eth_relative_rotation__btc_leg": [
        {"ema_fast_period": ef, "ema_slow_period": es, "confirm_bars": cb}
        for ef, es in ((8, 21), (12, 26)) for cb in (2, 3, 5)
    ],
}

# strategies_by_style/ entries, added 2026-09-14 (see plugins/__init__.py's
# own note for why they were previously unreachable). Generated from the
# registry rather than hand-listed: these files hardcode their own
# thresholds -- they were produced per-asset, not as a parameterised
# family -- so each contributes exactly ONE candidate, `{}`, and a
# hand-written list of ~110 no-param entries would be pure duplication
# that drifts the moment a file is added or removed.
#
# COST, stated plainly: this grows the default grid by ~110 candidates.
# The Stage 0 synthetic nulls were calibrated at 167 candidates per path
# (research/synthetic_null_GCF_*.json's own `candidates_per_path` field),
# and the grid was already at 723 before this. A wider search gives noise
# more chances to produce a winner, so the null percentile floor is
# already too LENIENT and this makes it more so. Resampling the existing
# null data put the correction at roughly +21-32% on the floors at 723
# candidates. The real fix is re-running the null campaigns at the current
# grid size, not shrinking the grid -- recorded here so the gap is visible
# at the point where it is caused.
for _style_name in sorted(STYLE_LIBRARY_STRATEGIES):
    DEFAULT_STRATEGY_GRID.setdefault(_style_name, [{}])


def _dedupe_grid_aliases(grid: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Drop grid entries that point at the SAME function object as an
    earlier entry.

    Real defect found 2026-09-14 by comparing registered strategies by
    object identity: `strategy_power_of_stocks_5ema_break` IS
    `strategy_5ema_low_high_break_powerofstocks`, and
    `strategy_swing_fxalexg_mtf_confirm` IS `strategy_fxalexg_mtf_swing` --
    pdf_strategy_library deliberately re-exports some implementations under
    a second, document-specific name so each source PDF has a module named
    after it. That aliasing is intentional and worth keeping; having BOTH
    names in the search grid is not. It meant every sweep backtested those
    two strategies twice -- 20 wasted candidates per run (fxalexg alone
    carries 9 parameter sets, so 18 of them).

    The cost is not only compute. The Stage 0 null percentile is
    calibrated against a candidate COUNT, so duplicated candidates inflate
    the effective number of trials without adding a single new hypothesis,
    making the significance bar more lenient for everything else -- exactly
    the multiple-comparison problem that framework exists to control.

    Keeps the FIRST name encountered (sorted order, so it is stable across
    runs) and logs each drop, since a silently shrinking grid would be its
    own invisible-change problem.
    """
    seen: dict[int, str] = {}
    deduped: dict[str, list[dict]] = {}
    for name in sorted(grid):
        fn = STRATEGIES.get(name)
        key = id(fn) if fn is not None else None
        if key is not None and key in seen:
            logger.info(
                "DEFAULT_STRATEGY_GRID: %r is the same function object as %r -- "
                "dropping the duplicate from the search grid (the alias stays registered "
                "in STRATEGIES and remains usable by name).",
                name, seen[key],
            )
            continue
        if key is not None:
            seen[key] = name
        deduped[name] = grid[name]
    return deduped


DEFAULT_STRATEGY_GRID = _dedupe_grid_aliases(DEFAULT_STRATEGY_GRID)

# Every archetype in STRATEGIES is now promotable -- e51_signals.
# _determine_direction_from_override was rewritten 2026-08-21 to dispatch
# generically through the SAME STRATEGIES dict (calling the exact
# function a candidate was validated against, not a separately hand-
# maintained live-only reimplementation), so there's no longer a smaller
# hardcoded subset of "archetypes the live engine knows how to drive" --
# derived from STRATEGIES itself rather than a second hand-maintained
# set that could silently drift out of sync with it (the real reason
# this used to be a hardcoded {"donchian_breakout",
# "donchian_breakout_volume_confirmed"} pair: those were the only two
# the live driver had hand-written branches for at the time).
PROMOTABLE_STRATEGIES = set(STRATEGIES.keys())

# Real, previously-documented performance pain point this addresses: E24's
# own comment above already measured "~200+ full _simulate passes per
# research() call" for the default grid, each one a bar-by-bar Python-loop
# backtest via E26. Found while researching QuantConnect/Lean's own
# Optimizer module (cloned read-only for reference, 2026-08-20): Lean's
# speed comes from smarter search + PROCESS-level parallelism across
# independent candidate evaluations, not from vectorizing the simulator
# itself -- the same conclusion reached independently after assessing
# vectorbt as a full E26 replacement and rejecting it (would require
# re-deriving every one of E26's bespoke formulas -- fixed-fractional
# sizing, Sharpe/Sortino/CAGR/Calmar, the fill-timing fix from earlier
# today -- in vectorbt's own parameter space, a real risk of silently
# reintroducing the exact subtle-bug class this session already found
# twice in this code path). Parallelizing ACROSS candidates instead
# changes nothing about WHAT gets computed for any single candidate --
# every candidate still runs through E26's real, unchanged run_backtest --
# only WHEN each already-correct, independent computation happens.
# ProcessPoolExecutor (not ThreadPoolExecutor, unlike e51_signals.
# scan_all_assets' own I/O-bound parallelism) because this workload is
# CPU-bound (pure pandas/numpy + Python-loop backtesting, no network
# calls) -- threads wouldn't actually parallelize past the GIL here.


def _selection_score(candidate) -> float:
    """Rank PASSING candidates by their WEAKER of in-sample / out-of-sample
    Sharpe, not by OOS Sharpe alone.

    Accepts either a StrategyCandidateResult or its to_dict() form, since
    research() ranks dataclasses and the merge path ranks dicts.

    Why this replaced `max(passed, key=oos_sharpe)` on 2026-08-21: picking
    the single highest OOS Sharpe out of a 66-candidate grid is the most
    selection-bias-prone rule available -- it structurally rewards the
    LUCKIEST split, and the bias grows with grid size, so simply searching
    harder made the reported "best" worse rather than better. Measured on
    this platform's own real sweeps: RELIANCE 4h came back as the single
    highest OOS Sharpe on the whole platform (4.92) off an IS Sharpe of
    just 0.59 over 33 trades -- an eightfold OOS/IS gap that says "this
    OOS window happened to be kind", not "this edge is strong". MSFT 1h
    (IS 1.02 / OOS 0.84) is the pattern a real edge actually makes.

    min(IS, OOS) is deliberately the plainest rule that fixes this: a
    candidate is only as good as its worse half, so neither an IS
    overfit nor an OOS fluke can win on its own -- consistency across both
    is the only way to score highly. It cannot be gamed by grid size the
    way a pure maximum can. Note this only ever REORDERS candidates that
    already cleared E26's full validation bar (IS trades>=30, IS
    Sharpe>0.5, max DD<25%, OOS Sharpe>0); it never admits anything that
    bar rejected, and never weakens it.

    Deliberately NOT weighted by `robustness`: that field is E26's
    _parameter_sensitivity, which perturbs risk_pct/commission only --
    and, as its own docstring states, "strategy_fn's output depends only
    on df, never on risk_pct/commission/slippage". It measures position-
    sizing/cost sensitivity, not sensitivity to the strategy PARAMETERS
    being searched here, which is why real sweep values cluster in a
    narrow 0.91-0.99 band and cannot discriminate between candidates.
    """
    is_sharpe = candidate["is_sharpe"] if isinstance(candidate, dict) else candidate.is_sharpe
    oos_sharpe = candidate["oos_sharpe"] if isinstance(candidate, dict) else candidate.oos_sharpe
    return min(float(is_sharpe), float(oos_sharpe))


def _run_one_candidate_worker(
    enriched: pd.DataFrame, strat_name: str, params: dict,
    session_mask_series: Optional[pd.Series], periods_per_year: float,
    slippage_pct: float, commission_pct: float,
    capture_returns: bool = False,
    timeframe: Optional[str] = None,
) -> Optional[dict]:
    """Module-level (picklable) worker for the parallel search path -- runs
    in a separate process, so it constructs its OWN BacktestingEngine
    (cheap and stateless per that engine's own health_check: "no external
    dependencies") rather than trying to share one across a process
    boundary. Returns a plain dict (StrategyCandidateResult.to_dict()'s
    shape), not the dataclass itself, to avoid any cross-process
    pickling/import-path fragility with dataclass instances -- the caller
    reconstructs StrategyCandidateResult from the dict."""
    strat_fn_factory = STRATEGIES.get(strat_name)
    if strat_fn_factory is None:
        return None
    try:
        full_signal = strat_fn_factory(enriched, **params)
    except Exception:
        return None
    if session_mask_series is not None:
        full_signal = apply_session_filter(full_signal, session_mask_series)

    def strategy_fn(_df: pd.DataFrame, _signal=full_signal) -> pd.Series:
        return _signal.loc[_df.index]

    backtesting_engine = BacktestingEngine()
    # `timeframe` selects E26's Stage 0 bar (STAGE0_TIMEFRAME_THRESHOLDS).
    # Default None keeps the legacy bar, which is what research/synthetic_null.py
    # and research/score_overrides_stage0.py deliberately continue to measure:
    # those artifacts characterise the OLD bar's false-positive rate, and that
    # measurement is the evidence that justified replacing it. Silently
    # upgrading them would destroy the baseline they exist to record.
    # compute_robustness=False (added 2026-09-11): profiled directly
    # (cProfile, a real 167-candidate grid pass) -- the extra +-10% risk/
    # commission perturbation _parameter_sensitivity runs inside
    # run_backtest cost 52.2% of total grid-search wall-clock time, and
    # nothing anywhere in this codebase reads the `robustness` key this
    # worker's own `out` dict below carries (confirmed via a full-repo
    # grep) -- `_selection_score`'s own docstring already documents why:
    # "real sweep values cluster in a narrow 0.91-0.99 band and cannot
    # discriminate between candidates". Every OTHER run_backtest caller
    # (E30's real adversarial parameter-fragility check in particular)
    # keeps the True default -- this is scoped to the grid-search hot
    # path specifically, where the value was computed 167 times per
    # sweep and used zero times.
    bt_result = backtesting_engine.run_backtest(
        enriched, strategy_fn, periods_per_year=periods_per_year,
        slippage_pct=slippage_pct, commission_pct=commission_pct,
        timeframe=timeframe, compute_robustness=False,
    )
    if not bt_result.success:
        return None
    r = bt_result.data
    m = r.metrics
    out = {
        "strategy": strat_name,
        "params": params,
        "is_trades": int(m.total_trades),
        "is_sharpe": float(m.sharpe_ratio),
        "is_max_dd": float(m.max_drawdown_pct),
        "ppy": float(periods_per_year),
        "n_bars": int(len(enriched)),
        "oos_sharpe": float(r.parameters.get("oos_sharpe", 0.0)),
        "win_rate": float(m.win_rate),
        "robustness": float(r.robustness_score),
        "passed_validation": bool(r.passed_validation),
        "expectancy": float(m.expectancy),
        "avg_win_r": float(m.avg_win_r),
        "avg_loss_r": float(m.avg_loss_r),
        "profit_factor": float(m.profit_factor),
    }
    if capture_returns:
        # Stage 0 (Deflated Sharpe) needs the per-candidate return STREAM to
        # measure how correlated the grid's candidates really are -- 30 of
        # the 167 param-sets are donchian_breakout variants that are near
        # copies, and counting them as 30 independent trials overstates the
        # search. Everything above this line is scalars, and the equity
        # curve was previously discarded here inside the worker, so there
        # was no way to compute that correlation at all.
        #
        # OPT-IN, and a NEW key: every promoted *_strategy_override.json and
        # every sweep report on disk carries this dict's existing shape, so
        # nothing above is renamed or reordered. Off by default, so no
        # existing caller pays the pickling cost of shipping an array back
        # across the process boundary.
        #
        # float32 halves that transfer and is far more precision than a
        # correlation matrix needs.
        try:
            eq = r.equity_curve
            rets = eq.pct_change().to_numpy(dtype="float32")[1:] if len(eq) > 1 else None
            out["bar_returns"] = None if rets is None else np.nan_to_num(
                rets, nan=0.0, posinf=0.0, neginf=0.0)
        except Exception:
            out["bar_returns"] = None      # never fail a candidate over telemetry
    return out


@dataclass
class ParameterSensitivityReport:
    """Extends E26's existing _parameter_sensitivity (which perturbs
    risk_pct/commission only -- see that method's own docstring) to the
    dimension docs/UPGRADE_BRIEF.md Phase 7 item 5 actually asked about:
    the STRATEGY's own numeric parameters. "Knife-edge performance =
    overfitting" is untested for the dimension that actually matters for
    overfitting -- a grid-search winner that only works at entry_n=15 and
    craters at 14 or 16 is exactly that signature, and nothing before this
    checked it.

    Lives here (E24), not E26: rebuilding a strategy_fn from a perturbed
    params dict needs STRATEGIES (the name->factory dict), and E24 already
    imports BacktestingEngine, never the reverse (confirmed directly) --
    the same dependency direction _run_one_candidate_worker already uses.

    ONE PARAMETER AT A TIME, not joint perturbation of every parameter
    simultaneously. This is the standard, interpretable choice: it answers
    "which specific parameter is fragile," which perturbing everything at
    once would conflate. The brief's own wording ("key parameters," plural)
    doesn't disambiguate this, so it's stated here explicitly.
    """

    strategy: str
    base_params: dict
    base_sharpe: float
    perturbed: list[dict] = field(default_factory=list)  # [{param, direction, value, sharpe, delta}]
    most_fragile_param: Optional[str] = None
    stability_score: float = 0.0
    caveats: list[str] = field(default_factory=list)


def strategy_parameter_sensitivity(
    enriched: pd.DataFrame,
    strat_name: str,
    params: dict,
    backtesting_engine: BacktestingEngine,
    *,
    perturbation: float = 0.2,
    periods_per_year: float = 252.0,
    commission_pct: float = 0.0005,
    slippage_pct: float = 0.0002,
    capital: float = 10_000.0,
    risk_pct: float = 1.0,
) -> Optional[ParameterSensitivityReport]:
    """Perturb each of `params`' NUMERIC values by +-`perturbation` (one at a
    time, holding every other param at its base value), rebuild the
    strategy_fn via STRATEGIES[strat_name] for each variant, and report how
    much Sharpe moves. Report only -- promotes nothing, gates nothing,
    changes no existing threshold.

    Returns None (not a fabricated report) when `strat_name` is unknown to
    STRATEGIES, `params` has zero numeric entries, or the base case itself
    produces zero trades (a stability score computed from an untradeable
    base case would be meaningless).
    """
    strat_fn_factory = STRATEGIES.get(strat_name)
    if strat_fn_factory is None:
        return None

    def _run(p: dict) -> Optional[float]:
        try:
            signal = strat_fn_factory(enriched, **p)
        except Exception:
            return None

        def strategy_fn(_df: pd.DataFrame, _signal=signal) -> pd.Series:
            return _signal.loc[_df.index]

        result = backtesting_engine._simulate(
            enriched, strategy_fn, capital, risk_pct, commission_pct, slippage_pct, periods_per_year,
        )
        if result.metrics.total_trades <= 0:
            return None
        return float(result.metrics.sharpe_ratio)

    base_sharpe = _run(params)
    if base_sharpe is None:
        return None

    # bool is a subclass of int in Python -- excluded explicitly so a
    # boolean flag param (e.g. a mode switch) is never "perturbed" into a
    # meaningless 0.8x/1.2x of True/False.
    numeric_params = {
        k: v for k, v in params.items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    }
    if not numeric_params:
        return None

    perturbed: list[dict] = []
    all_sharpes = [base_sharpe]
    for key, base_value in numeric_params.items():
        for direction, mult in (("low", 1 - perturbation), ("high", 1 + perturbation)):
            new_value = base_value * mult
            if isinstance(base_value, int):
                new_value = int(round(new_value))
            if new_value == base_value:
                # Perturbation round-tripped to the base (small int params,
                # e.g. k1=1 at +-20%) -- skip rather than report a fake
                # "no change" data point.
                continue
            variant_params = dict(params, **{key: new_value})
            sharpe = _run(variant_params)
            if sharpe is None:
                continue
            perturbed.append({
                "param": key, "direction": direction, "value": new_value,
                "sharpe": round(sharpe, 4), "delta": round(sharpe - base_sharpe, 4),
            })
            all_sharpes.append(sharpe)

    most_fragile = None
    if perturbed:
        most_fragile = max(perturbed, key=lambda p: abs(p["delta"]))["param"]

    arr = np.asarray(all_sharpes, dtype=float)
    stability = 1.0 - (float(np.std(arr)) / (abs(float(np.mean(arr))) + 1e-9))
    stability_score = max(0.0, min(1.0, stability))

    return ParameterSensitivityReport(
        strategy=strat_name,
        base_params=params,
        base_sharpe=round(base_sharpe, 4),
        perturbed=perturbed,
        most_fragile_param=most_fragile,
        stability_score=round(stability_score, 4),
        caveats=[
            "One parameter perturbed at a time, holding every other "
            "parameter at its base value -- a joint-perturbation reading "
            "would conflate which specific parameter is fragile.",
            "stability_score uses the same 1 - std/mean shape as E26's "
            "existing risk/commission _parameter_sensitivity, for a "
            "consistent reading across the two -- they measure different "
            "things (strategy-parameter fragility vs. sizing/cost "
            "sensitivity) and neither implies the other.",
        ],
    )


# Approximate bars/year per timeframe, for E26's Sharpe/CAGR annualization
# (see BacktestingEngine.run_backtest's own docstring: "otherwise Sharpe/
# CAGR are silently off by whatever factor separates the assumed and
# actual bar frequency"). E24 previously hardcoded periods_per_year=252
# for every timeframe, harmless while E24 only ever tested "1d" data --
# now wrong the moment intraday timeframes are used. Assumes continuous
# (24/7) trading, a reasonable approximation for forex/crypto/commodities;
# exchange-hours-only assets (e.g. NIFTY50) trade materially fewer real
# bars/year than this, so their Sharpe here is a rough approximation, not
# an exact one -- flagged honestly rather than precisely calendar-computed
# per asset, which is out of scope for this grid-search tool.
BARS_PER_YEAR = {
    "1m": 525_600, "5m": 105_120, "15m": 35_040, "30m": 17_520,
    "1h": 8_760, "4h": 2_190, "1d": 252, "1wk": 52, "1mo": 12,
}

# ---------------------------------------------------------------------------
# Trading calendar by asset class.
#
# BARS_PER_YEAR above is a 24/7 calendar: 35,040 15m bars a year is 365 days x
# 96 bars. That is correct for crypto and wrong for everything that closes
# overnight. An NYSE name produces 252 x 26 = 6,552 15m bars a year, so
# annualising an equity strategy against the 24/7 table multiplies its Sharpe
# by sqrt(35_040 / 6_552) = 2.31x.
#
# Measured impact when this was found: the intraday equity rows that dominate
# the PHASE 19 leaderboard (AAPL/AMZN/TSLA/TCS/NIFTY50 at 5m and 15m) were all
# overstated by that factor, which is what ranked them above the 1d candidates
# -- 1d is the one timeframe the old table annualised correctly, so the bug
# systematically favoured intraday noise over daily evidence.
#
# The crypto column of the new calendar reproduces the old table exactly,
# which is the tell that the old constants were crypto-calibrated throughout.
TRADING_HOURS_PER_YEAR = {
    "equity":    6.5 * 252,   # 1,638 -- NYSE/NSE regular session
    "index":     6.5 * 252,   # 1,638 -- cash index follows its cash session
    "forex":    24.0 * 260,   # 6,240 -- 24x5, ~52 weeks
    "crypto":   24.0 * 365,   # 8,760 -- genuinely continuous
    "commodity": 23.0 * 252,  # 5,796 -- CME metals/energy, ~1h daily halt
    "futures":  23.0 * 252,   # 5,796 -- same CME session
    "bond":      6.5 * 252,   # 1,638 -- cash desk hours
}

_BAR_HOURS = {
    "1m": 1 / 60, "5m": 5 / 60, "15m": 15 / 60, "30m": 30 / 60,
    "1h": 1.0, "4h": 4.0,
}

# Session-length bars are counted in sessions, not hours.
_SESSIONS_PER_YEAR = {
    "equity": 252, "index": 252, "forex": 260,
    "crypto": 365, "commodity": 252, "futures": 252, "bond": 252,
}


def bars_per_year(timeframe, asset_class=None):
    # type: (str, Optional[str]) -> float
    """Bars a year for `timeframe` on an instrument of `asset_class`.

    Falls back to the 24/7 BARS_PER_YEAR table when the class is unknown, so
    an unclassified instrument keeps its previous annualisation rather than
    silently acquiring a different one.
    """
    cls = (asset_class or "").lower()
    if cls not in TRADING_HOURS_PER_YEAR:
        return float(BARS_PER_YEAR.get(timeframe, 252))
    if timeframe == "1d":
        return float(_SESSIONS_PER_YEAR[cls])
    if timeframe == "1wk":
        return 52.0
    if timeframe == "1mo":
        return 12.0
    bar_h = _BAR_HOURS.get(timeframe)
    if bar_h is None:
        return float(BARS_PER_YEAR.get(timeframe, 252))
    return TRADING_HOURS_PER_YEAR[cls] / bar_h

# Real bug found and fixed during this engine's own session-filtered
# search: E26.run_backtest's default slippage_pct=0.0005/commission_pct=
# 0.001 (0.05%/0.1% one-way, calibrated for DAILY bars, where a typical
# move is well above that) is far larger than a typical single-bar price
# move on fine intraday timeframes -- e.g. a 1-minute EURUSD bar often
# moves ~0.01-0.03%, so a 0.1% round-trip cost alone guarantees a loss on
# nearly every trade regardless of the strategy's real directional edge.
# Caught live: EURUSD/GBPUSD 1m/5m searches were returning near-0% win
# rates on EVERY one of 77 tested configs (real signal, real entries --
# trades dumped and inspected directly showed entry_price/exit_price
# almost identical, with pnl_pct consistently landing right at the
# round-trip slippage cost, not a real adverse price move). Not "no
# edge" -- a broken cost assumption swamping any edge that might exist.
# These are reasonable, conservative approximations (roughly scaled by
# typical intraday spread/impact for liquid instruments), not a precisely
# calibrated-per-broker figure -- same "static documented convention"
# honesty as e13_derivatives' uncalibrated skew thresholds. 1d values are
# UNCHANGED from E26's own defaults, so every prior daily-timeframe
# result in this project is unaffected by this fix.
# Asset-class cost multipliers (added 2026-08-22). The table below scales
# cost by TIMEFRAME but treated every instrument identically, and its
# figures are calibrated for equities -- which silently made this
# platform's cost assumption wildly wrong for the exact markets it was
# most often asked about. Measured against the 1d row (0.15% round trip):
#
#   EURUSD @1.08     -> 16.2 pips charged vs ~1.0 pip real   = 15x
#   GBPUSD @1.27     -> 19.1 pips charged vs ~1.2 pip real   = 12.5x
#   USDJPY @157      -> 23.6 pips charged vs ~1.0 pip real   = 15x
#   GOLD   @4679     -> $7.02 charged     vs ~$0.40 real     = 15x
#   SILVER @58       -> $0.087 charged    vs ~$0.03 real     = 3x
#   BTCUSD @77000    -> $115 charged      vs ~0.1%/side real = 0.8x  (fair)
#   AAPL   @230      -> $0.35 charged     vs ~0.05% real     = 1.5x  (fair)
#
# So equities and crypto were roughly right while FX and gold were
# overcharged by an order of magnitude. That is not a rounding issue: a
# strategy on EURUSD had to clear ~16 pips of imaginary cost per round
# trip before it could show any edge at all, which is a plausible reason
# no forex pair has EVER validated on any timeframe in this project's
# history. The multipliers below bring each class to a realistic retail
# round-trip; they remain documented approximations, not per-broker
# figures (same honesty convention as the timeframe table itself).
ASSET_CLASS_COST_MULT = {
    "forex": 0.11,      # ~1.5-1.8 pip round trip on majors (deliberately
                        # above the ~1.0-1.3 pip real spread: see below)
    "commodity": 0.10,  # calibrated on gold; see per-symbol override below
    "crypto": 1.45,     # retail taker fees are genuinely ~0.1%/side
    "equity": 1.00,     # the basis these figures were calibrated on
    "index": 0.60,
    "futures": 0.40,
    "bond": 0.50,
}

# Per-symbol overrides, applied instead of the class multiplier where a
# single class contains instruments whose spread-to-price ratios differ
# by an order of magnitude. Caught while verifying the class fix above:
# "commodity" holds both gold and silver, but their RELATIVE costs are
# nothing alike --
#     GOLD   ~$0.40 spread on ~$4679  = 0.0085%
#     SILVER ~$0.025 spread on ~$58   = 0.043%   (5x wider, relatively)
# so a single multiplier tuned for gold charged silver about a third of
# its real cost. UNDERCHARGING is the dangerous direction of this error:
# it manufactures edges that cannot survive live execution, which is
# exactly the failure this whole cost model exists to prevent. Erring
# slightly high per instrument is the safe side of the trade.
SYMBOL_COST_MULT = {
    "SILVER": 0.30,   # ~0.045% round trip, matching a real XAGUSD spread
}

TRANSACTION_COSTS = {
    "1m": {"slippage_pct": 0.00003, "commission_pct": 0.0001},
    "5m": {"slippage_pct": 0.00005, "commission_pct": 0.0001},
    "15m": {"slippage_pct": 0.00007, "commission_pct": 0.00015},
    "30m": {"slippage_pct": 0.0001, "commission_pct": 0.0002},
    "1h": {"slippage_pct": 0.0002, "commission_pct": 0.0005},
    "4h": {"slippage_pct": 0.0003, "commission_pct": 0.0007},
    "1d": {"slippage_pct": 0.0005, "commission_pct": 0.001},  # E26's own defaults, unchanged
    "1wk": {"slippage_pct": 0.0005, "commission_pct": 0.001},
    "1mo": {"slippage_pct": 0.0005, "commission_pct": 0.001},
}


@dataclass
class StrategyCandidateResult:
    strategy: str
    params: dict
    is_trades: int
    is_sharpe: float
    is_max_dd: float
    oos_sharpe: float
    win_rate: float
    robustness: float
    passed_validation: bool
    # Added 2026-08-22. E26 has always COMPUTED these -- they sat in
    # BacktestMetrics and were thrown away here, so every sweep report
    # this project ever produced could only be ranked by win rate and
    # Sharpe. Neither answers "does this actually make money per trade,
    # and how big are the winners relative to the losers", which is the
    # question that decides whether a rule is tradeable: a 65% win rate
    # can carry a NEGATIVE expectancy (measured on real ETHUSD 1d data:
    # 65.1% win rate, avg win +7.16 vs avg loss -33.99, expectancy
    # -7.195), and no amount of win-rate ranking exposes that.
    expectancy: float = 0.0
    avg_win_r: float = 0.0
    avg_loss_r: float = 0.0
    profit_factor: float = 0.0
    # Annualisation actually used for is_sharpe/oos_sharpe. Recorded because
    # store_report merges rather than overwrites: after the asset-class
    # calendar fix a report can hold rows scored both ways, and Sharpe scales
    # by sqrt(ppy_new/ppy_old), so the row is only correctable if it says what
    # it was scored with. 0.0 means "written before this was recorded" -- treat
    # as the old 24/7 BARS_PER_YEAR table.
    ppy: float = 0.0
    # Bars the backtest actually saw. Needed for the expected-max-Sharpe
    # test (Bailey/Lopez de Prado): the Sharpe that the BEST of N random
    # strategies reaches by luck scales as 1/sqrt(n_bars), so without the
    # real bar count the noise floor can only be guessed from `years`,
    # and an asset with less history than requested (BTCUSD since ~2014)
    # would have its floor UNDERSTATED -- the dangerous direction.
    n_bars: int = 0

    @property
    def reward_risk(self) -> float:
        """Average winner divided by average loser, in R. The '2-4R
        winners' half of a trend profile -- and the number that decides
        what win rate a strategy actually NEEDS to break even
        (breakeven_win_rate = 1 / (1 + reward_risk))."""
        return abs(self.avg_win_r / self.avg_loss_r) if self.avg_loss_r else 0.0

    @property
    def breakeven_win_rate(self) -> float:
        """The win rate below which this strategy loses money, given its
        own reward:risk. Makes 'is 40% good?' answerable instead of a
        matter of taste: at 2.5R, breakeven is 28.6%, so 40% is healthy."""
        rr = self.reward_risk
        return 1.0 / (1.0 + rr) if rr > 0 else 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "params": self.params,
            "is_trades": self.is_trades,
            "is_sharpe": round(self.is_sharpe, 4),
            "is_max_dd": round(self.is_max_dd, 2),
            "oos_sharpe": round(self.oos_sharpe, 4),
            "win_rate": round(self.win_rate, 4),
            "robustness": round(self.robustness, 4),
            "passed_validation": self.passed_validation,
            "expectancy": round(self.expectancy, 4),
            "avg_win_r": round(self.avg_win_r, 4),
            "avg_loss_r": round(self.avg_loss_r, 4),
            "profit_factor": round(self.profit_factor, 4),
            "reward_risk": round(self.reward_risk, 4),
            "breakeven_win_rate": round(self.breakeven_win_rate, 4),
            "ppy": round(float(self.ppy), 2),
            "n_bars": int(self.n_bars),
        }


@dataclass
class StrategyResearchReport:
    symbol: str
    timeframe: str
    generated_at: datetime
    n_candidates: int
    candidates: list[StrategyCandidateResult] = field(default_factory=list)
    passed: list[StrategyCandidateResult] = field(default_factory=list)
    best: Optional[StrategyCandidateResult] = None
    promoted: bool = False
    promotion_note: Optional[str] = None


class StrategyResearchEngine(BaseEngine):
    """
    Strategy Research Engine (#24) -- runs a strategy/parameter grid
    against E26's real validation bar for one symbol, replacing the
    one-off-script research pattern with a reusable, re-runnable call.
    """

    engine_id = "e24_strategy_research"
    engine_name = "Strategy Research Engine"
    version = "1.0.0"

    def __init__(
        self,
        market_data_engine: Optional[MarketDataEngine] = None,
        technical_engine: Optional[TechnicalAnalysisEngine] = None,
        backtesting_engine: Optional[BacktestingEngine] = None,
    ) -> None:
        super().__init__()
        self._market_data_engine = market_data_engine if market_data_engine is not None else MarketDataEngine()
        self._technical_engine = technical_engine if technical_engine is not None else TechnicalAnalysisEngine()
        self._backtesting_engine = backtesting_engine if backtesting_engine is not None else BacktestingEngine()

    def initialize(self) -> EngineResult:
        self._set_status(EngineStatus.IDLE)
        return EngineResult(success=True, message="Strategy Research Engine initialized")

    def health_check(self) -> EngineResult:
        return EngineResult(success=True, message="Healthy")

    def list_reports(self) -> EngineResult:
        """Summary of every already-computed research report on disk
        (docs/UPGRADE_BRIEF.md Phase 12 -- Strategy Laboratory / Backtesting
        dashboard surfaces). Deliberately excludes each report's full
        `all_candidates` array (up to ~800+ entries, ~400KB per report,
        244 report files total) -- this is a listing, not a data dump; use
        get_report(symbol, timeframe) for the full candidate grid of one
        report. Read-only, real data already written by the research
        scripts -- never triggers a new research run."""
        if not _REPORT_DIR.exists():
            return EngineResult(success=True, data=[], message="No reports found")
        summaries = []
        for path in sorted(_REPORT_DIR.glob("*_report.json")):
            try:
                report = json.loads(path.read_text())
            except Exception as e:
                logger.warning("Skipping unreadable report %s: %s", path.name, e)
                continue
            summaries.append({
                "symbol": report.get("symbol"),
                "timeframe": report.get("timeframe"),
                "generated_at": report.get("generated_at"),
                "n_candidates": report.get("n_candidates"),
                "n_passed": len(report.get("passed") or []),
                "promoted": bool(report.get("promoted")),
                "promotion_note": report.get("promotion_note"),
                "best": report.get("best"),
            })
        return EngineResult(success=True, data=summaries, message=f"{len(summaries)} report(s)")

    def get_report(self, symbol: str, timeframe: str) -> EngineResult:
        """Full research report (including every candidate) for one
        symbol+timeframe, exactly as written by research()/_save_report --
        read-only, never triggers a new research run."""
        path = _REPORT_DIR / f"{symbol}_{timeframe}_report.json"
        if not path.exists():
            return EngineResult(success=False, message=f"No report found for {symbol} {timeframe}")
        try:
            report = json.loads(path.read_text())
        except Exception as e:
            return EngineResult(success=False, message=f"Report unreadable: {e}", errors=[str(e)])
        return EngineResult(success=True, data=report, message="Report loaded")

    def research(
        self,
        symbol: str,
        timeframe: str = "1d",
        strategy_grid: Optional[dict[str, list[dict]]] = None,
        # 10, matching the master prompt's own "10+ years data where
        # possible" backtesting requirement -- 5 was found (during this
        # engine's own build) to understate a real, already-validated
        # edge for a lower-frequency strategy (SP500's Donchian override
        # needs ~8 years of real history to reach E26's 30-trade minimum;
        # a shorter window doesn't mean "no edge," it means "not enough
        # trades yet to tell"). Assets with less real history than
        # requested (e.g. BTCUSD since ~2014, MES=F since ~2019) simply
        # get whatever real history actually exists -- fetch_ohlcv bounds
        # to real availability, never fabricates the rest.
        years: int = 10,
        promote_if_validated: bool = False,
        # Optional (start, end) local-time strings, e.g. ("06:30", "09:30"),
        # for a trader who only wants to be in a position during a specific
        # session window (see strategies.session_mask/apply_session_filter).
        # None (default) -- no session restriction, unchanged behavior for
        # every existing caller. Only meaningful for intraday `timeframe`s;
        # applying it to daily+ bars would zero out almost everything.
        session_window: Optional[tuple[str, str]] = None,
        session_tz: str = "Asia/Kolkata",
        parallel: bool = False,
        max_workers: Optional[int] = None,
        executor: Optional[ProcessPoolExecutor] = None,
    ) -> EngineResult:
        """Grid-search `strategy_grid` (defaults to DEFAULT_STRATEGY_GRID)
        for `symbol`, grading every candidate against E26's real IS/OOS
        validation bar. Never fabricates a pass -- an empty `passed` list
        is a legitimate, reportable outcome (see the many honest zero-pass
        research runs already on record in data/models/e51_signals/).

        parallel: added 2026-08-20, default False (every existing caller's
            behavior is completely unchanged unless explicitly opted in).
            When True, runs the grid across a ProcessPoolExecutor instead
            of sequentially -- same candidates, same E26 run_backtest call
            per candidate, same results; only wall-clock time changes. See
            _run_one_candidate_worker's own docstring for why this is a
            safe optimization (parallelism across independent, unchanged
            computations) rather than a risky one (no simulator internals
            touched).

            MEASURED honestly on this machine (real BTC-USD 1d data, real
            E26 backtests, not a theoretical estimate): a single
            research() call only sees ~1.15-1.3x wall-clock speedup for a
            46-52 candidate grid -- Windows spawns each worker process
            fresh (no fork like Unix), and every worker re-imports this
            project's full dependency tree (pandas/scipy/sklearn/etc.),
            which dominates the actual per-candidate backtest cost for a
            grid this size. That fixed per-process import cost is paid
            ONCE per worker for the LIFE of the pool, though -- so a
            caller researching MANY assets in a loop (e.g.
            research_best_strategy_universe.py's real 29-asset sweep)
            should build ONE ProcessPoolExecutor and pass it via
            `executor` below, reusing the same already-warmed-up worker
            processes across every symbol instead of paying the import
            cost 29 times over. That is where this feature's real payoff
            is, not a single isolated call.
        max_workers: None (default) uses os.cpu_count(); only meaningful
            when parallel=True and `executor` is None (a caller-supplied
            executor already fixed its own worker count at construction).
        executor: None (default) -- research() creates and tears down its
            own short-lived executor for this one call (the modest 1.15-
            1.3x case above). Pass a real, already-constructed
            ProcessPoolExecutor to reuse it across multiple research()
            calls instead (e.g. one per asset in a batch sweep) -- this
            method never shuts down a caller-supplied executor; that
            stays the caller's own responsibility."""
        try:
            self._set_status(EngineStatus.RUNNING)
            asset = get_asset(symbol)
            if asset is None:
                return EngineResult(success=False, message=f"Unknown asset: {symbol}")

            fetch = self._market_data_engine.fetch_ohlcv(asset.yahoo_symbol, timeframe, years=years)
            if not fetch.success or fetch.data is None or len(fetch.data) < 260:
                return EngineResult(
                    success=False,
                    message=f"Insufficient OHLCV history for {symbol} ({timeframe}) -- need >=260 bars for a meaningful OOS split",
                )
            df = fetch.data

            ta_result = self._technical_engine.analyze(df, symbol=asset.symbol, timeframe=timeframe)
            if not ta_result.success:
                return EngineResult(success=False, message=f"Technical analysis failed: {ta_result.message}")
            enriched = ta_result.data["df"]

            mask = None
            if session_window is not None:
                mask = session_mask(enriched, session_window[0], session_window[1], tz=session_tz)
                if not bool(mask.any()):
                    return EngineResult(
                        success=False,
                        message=(
                            f"No bars for {symbol} ({timeframe}) fall inside {session_window[0]}-{session_window[1]} "
                            f"{session_tz} -- this asset's real trading hours don't overlap that window"
                        ),
                    )

            grid = strategy_grid if strategy_grid is not None else DEFAULT_STRATEGY_GRID
            costs = TRANSACTION_COSTS.get(timeframe, TRANSACTION_COSTS["1d"])
            # Scale the timeframe baseline by asset class -- see
            # ASSET_CLASS_COST_MULT for the measured per-class error this
            # corrects. Unknown class falls back to 1.0, i.e. exactly the
            # previous equity-calibrated behaviour.
            cls_mult = SYMBOL_COST_MULT.get(
                asset.symbol,
                ASSET_CLASS_COST_MULT.get(
                    asset.asset_class.value if getattr(asset, "asset_class", None) else "", 1.0
                ),
            )
            costs = {
                "slippage_pct": costs["slippage_pct"] * cls_mult,
                "commission_pct": costs["commission_pct"] * cls_mult,
            }
            periods_per_year = bars_per_year(
                timeframe,
                asset.asset_class.value
                if getattr(asset, "asset_class", None) else None,
            )

            # Flat (strat_name, params) job list -- shared by both the
            # sequential and parallel paths below, so "what gets evaluated"
            # is defined in exactly one place regardless of how it's run.
            jobs: list[tuple[str, dict]] = []
            for strat_name, param_sets in grid.items():
                if STRATEGIES.get(strat_name) is None:
                    logger.warning("Unknown strategy %s in grid -- skipping", strat_name)
                    continue
                for params in param_sets:
                    jobs.append((strat_name, params))

            candidates: list[StrategyCandidateResult] = []
            if parallel and len(jobs) > 1:
                owns_executor = executor is None
                pool = executor or ProcessPoolExecutor(max_workers=min(max_workers or os.cpu_count() or 4, len(jobs)))
                try:
                    futures = {
                        pool.submit(
                            _run_one_candidate_worker, enriched, strat_name, params,
                            mask, periods_per_year, costs["slippage_pct"], costs["commission_pct"],
                            False, timeframe,
                        ): (strat_name, params)
                        for strat_name, params in jobs
                    }
                    for future in as_completed(futures):
                        strat_name, params = futures[future]
                        try:
                            result_dict = future.result()
                        except Exception as e:
                            logger.warning("%s%s: parallel worker failed: %s", strat_name, params, e)
                            continue
                        if result_dict is not None:
                            candidates.append(StrategyCandidateResult(**result_dict))
                finally:
                    # Only tear down a pool THIS call created -- a
                    # caller-supplied executor (reused across many
                    # research() calls) is never this method's to close.
                    # Explicit shutdown(wait=False), same documented
                    # reasoning as e51_signals.scan_all_assets' own
                    # ThreadPoolExecutor usage (CLAUDE.md Performance
                    # notes): never let one hung/slow candidate block the
                    # whole call from returning whatever already completed.
                    if owns_executor:
                        pool.shutdown(wait=False)
            else:
                for strat_name, params in jobs:
                    strat_fn_factory = STRATEGIES[strat_name]
                    candidate = self._run_one(
                        enriched, strat_name, strat_fn_factory, params,
                        session_mask_series=mask, periods_per_year=periods_per_year,
                        slippage_pct=costs["slippage_pct"], commission_pct=costs["commission_pct"],
                        timeframe=timeframe,
                    )
                    if candidate is not None:
                        candidates.append(candidate)

            passed = [c for c in candidates if c.passed_validation]
            best = max(passed, key=_selection_score) if passed else None

            report = StrategyResearchReport(
                symbol=asset.symbol,
                timeframe=timeframe,
                generated_at=datetime.now(timezone.utc),
                n_candidates=len(candidates),
                candidates=candidates,
                passed=passed,
                best=best,
            )

            if promote_if_validated and best is not None:
                report.promoted, report.promotion_note = self._promote(asset, timeframe, best)
            elif promote_if_validated and best is None:
                report.promotion_note = "No candidate cleared the validation bar -- nothing to promote"

            self._save_report(report)
            self._set_status(EngineStatus.IDLE)
            n_passed = len(passed)
            return EngineResult(
                success=True,
                data=report,
                message=(
                    f"{n_passed}/{len(candidates)} candidate(s) passed full validation for {asset.symbol} "
                    f"({'promoted ' + best.strategy if report.promoted else 'not promoted'})"
                ),
            )
        except Exception as e:
            self._set_status(EngineStatus.ERROR)
            logger.error("Strategy research failed for %s: %s", symbol, e)
            return EngineResult(success=False, message=str(e), errors=[str(e)])

    def _run_one(
        self, enriched: pd.DataFrame, strat_name: str, strat_fn_factory, params: dict,
        session_mask_series: Optional[pd.Series] = None, periods_per_year: float = 252,
        slippage_pct: float = 0.0005, commission_pct: float = 0.001,
        timeframe: Optional[str] = None,
    ) -> Optional[StrategyCandidateResult]:
        try:
            full_signal = strat_fn_factory(enriched, **params)
        except Exception as e:
            logger.warning("%s%s: strategy computation failed: %s", strat_name, params, e)
            return None

        if session_mask_series is not None:
            full_signal = apply_session_filter(full_signal, session_mask_series)

        def strategy_fn(_df: pd.DataFrame, _signal=full_signal) -> pd.Series:
            return _signal.loc[_df.index]

        bt_result = self._backtesting_engine.run_backtest(
            enriched, strategy_fn, periods_per_year=periods_per_year,
            slippage_pct=slippage_pct, commission_pct=commission_pct,
            timeframe=timeframe,
        )
        if not bt_result.success:
            logger.warning("%s%s: backtest failed: %s", strat_name, params, bt_result.message)
            return None
        r = bt_result.data
        m = r.metrics
        return StrategyCandidateResult(
            strategy=strat_name,
            params=params,
            is_trades=int(m.total_trades),
            is_sharpe=float(m.sharpe_ratio),
            is_max_dd=float(m.max_drawdown_pct),
            ppy=float(periods_per_year),
            n_bars=int(len(enriched)),
            oos_sharpe=float(r.parameters.get("oos_sharpe", 0.0)),
            win_rate=float(m.win_rate),
            robustness=float(r.robustness_score),
            passed_validation=bool(r.passed_validation),
            expectancy=float(m.expectancy),
            avg_win_r=float(m.avg_win_r),
            avg_loss_r=float(m.avg_loss_r),
            profit_factor=float(m.profit_factor),
        )

    def _promote(self, asset, timeframe: str, best: StrategyCandidateResult) -> tuple[bool, str]:
        """Write a strategy_override.json e51_signals can pick up, in the
        SAME format/location the manual research scripts already used --
        only for archetypes e51_signals._determine_direction_from_override
        actually knows how to drive live (see PROMOTABLE_STRATEGIES)."""
        if best.strategy not in PROMOTABLE_STRATEGIES:
            return False, (
                f"{best.strategy} cleared validation but is not yet a promotable archetype -- "
                f"e51_signals only knows how to drive a live signal from {sorted(PROMOTABLE_STRATEGIES)}"
            )
        path = _OVERRIDE_DIR / f"{asset.yahoo_symbol}_{timeframe}_strategy_override.json"
        override = {
            "strategy": best.strategy,
            "params": best.params,
            "win_rate": round(best.win_rate, 3),
            "is_sharpe": round(best.is_sharpe, 2),
            "oos_sharpe": round(best.oos_sharpe, 2),
            "max_drawdown_pct": round(best.is_max_dd, 1),
            "total_trades": best.is_trades,
            "min_confidence": round(best.win_rate * 100),
            "validated_at": datetime.now(timezone.utc).isoformat(),
            "source": "engines/e24_strategy_research (research() promote_if_validated=True)",
            "note": (
                f"Promoted by e24_strategy_research: {best.strategy}{best.params} cleared E26's full "
                f"walk-forward validation bar for {asset.symbol} {timeframe} (IS Sharpe={best.is_sharpe:.2f}, "
                f"OOS Sharpe={best.oos_sharpe:.2f}, {best.is_trades} trades, {best.win_rate:.1%} win rate)."
            ),
        }
        _OVERRIDE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(override, indent=2))
        return True, f"Promoted to {path}"

    @staticmethod
    def _save_report(report: StrategyResearchReport) -> None:
        """Merge this run's candidates into any existing report for the
        same symbol+timeframe, keyed by (strategy, params) -- multiple
        callers target this SAME file with deliberately different grids
        (e.g. research_best_strategy_universe.py's full DEFAULT_STRATEGY_
        GRID vs. research_high_winrate_favorites.py's narrower targeted
        grid, both at timeframe="1d" for overlapping symbols). A plain
        overwrite here silently destroys the other run's previously
        recorded candidates -- confirmed on disk: BTCUSD_1d_report.json
        and GBPUSD_1d_report.json were reduced from a full multi-
        archetype sweep down to a handful of candidates by a later,
        narrower-grid run. Same keyed-merge discipline as
        e22_alpha_research.store_result's alpha database."""
        _REPORT_DIR.mkdir(parents=True, exist_ok=True)
        path = _REPORT_DIR / f"{report.symbol}_{report.timeframe}_report.json"

        merged: dict[tuple, dict] = {}
        if path.exists():
            try:
                prev = json.loads(path.read_text())
                for c in prev.get("all_candidates", []):
                    key = (c["strategy"], tuple(sorted(c.get("params", {}).items())))
                    merged[key] = c
            except Exception as e:
                logger.warning("Existing strategy report unreadable (%s) -- starting fresh", e)

        for c in report.candidates:
            key = (c.strategy, tuple(sorted(c.params.items())))
            merged[key] = c.to_dict()

        all_candidates = list(merged.values())
        passed = [c for c in all_candidates if c["passed_validation"]]
        best = max(passed, key=_selection_score) if passed else None

        payload = {
            "symbol": report.symbol,
            "timeframe": report.timeframe,
            "generated_at": report.generated_at.isoformat(),
            "n_candidates": len(all_candidates),
            "validation_bar": "IS trades>=30, IS Sharpe>0.5, max DD<25%, OOS Sharpe>0 (E26 Backtesting Laboratory)",
            "passed": passed,
            "best": best,
            "promoted": report.promoted,
            "promotion_note": report.promotion_note,
            "all_candidates": all_candidates,
        }
        path.write_text(json.dumps(payload, indent=2))
