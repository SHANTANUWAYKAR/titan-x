"""
Package: e24_strategy_research.plugins.pdf_strategy_library
Description: Strategies converted from the 90 user-supplied trading-strategy PDF/DOCX
    documents in data/strategy/. Each module cites its exact source document(s) in its
    own docstring, states any indicator-substitution/interpretive assumption made, and
    follows the same _stateful_from_entries_exits position-tracking discipline as the
    rest of this platform (see ._shared for the canonical copy). Registered into e24's
    STRATEGIES dict via plugins/__init__.py's PLUGIN_STRATEGIES merge -- same unweakened
    E26/Stage-0 validation bar as every built-in archetype.
Author: Shantanu Waykar
Version: 1.0.0
"""

from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_10ema_intraday_pullback import strategy_10ema_intraday_pullback
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_200ema_trend_filter import strategy_200ema_trend_filter
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_3ema_ribbon_crossover import strategy_3ema_ribbon_crossover
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_5ema_low_high_break_powerofstocks import strategy_5ema_low_high_break_powerofstocks
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_72min_tbs_gold_journexfx import strategy_72min_tbs_gold_journexfx
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_8020_mean_reversion_okala import strategy_8020_mean_reversion_okala
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_915200_ema_trend_breakout import strategy_915200_ema_trend_breakout
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_9_15ema_crossover_retest import strategy_9_15ema_crossover_retest
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_9_15ema_mayankraj_sr_rejection import strategy_9_15ema_mayankraj_sr_rejection
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_9_20ema_crossover_confirmed import strategy_9_20ema_crossover_confirmed
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_9_20ema_stockburner import strategy_9_20ema_stockburner
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_ali_crooks_trendline_pocket import strategy_ali_crooks_trendline_pocket
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_anish_singh_vwap_stochrsi_pivot import strategy_anish_singh_vwap_stochrsi_pivot
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_asian_session_bos import strategy_asian_session_bos
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_big_bar_9ema_retest import strategy_big_bar_9ema_retest
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_blackbox_fakeout_reclaim import strategy_blackbox_fakeout_reclaim
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_box_pdh_pdl_bounce import strategy_box_pdh_pdl_bounce
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_candlestick_wick_zone_reversal import strategy_candlestick_wick_zone_reversal
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_ema200_trendline_breakout import strategy_ema200_trendline_breakout
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_ema_9_21_crossover import strategy_ema_9_21_crossover
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_ema_fibonacci_pivot_breakout import strategy_ema_fibonacci_pivot_breakout
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_ema_rejection_mtf import strategy_ema_rejection_mtf
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_fabio_valentini_pullback_scalp import strategy_fabio_valentini_pullback_scalp
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_fair_value_gap_reversion import strategy_fair_value_gap_reversion
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_fibonacci_deep_retracement_pullback import strategy_fibonacci_deep_retracement_pullback
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_fxalexg_mtf_swing import strategy_fxalexg_mtf_swing
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_gautam_jha_pdh_pdl_breakout_reversal import strategy_gautam_jha_pdh_pdl_breakout_reversal
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_mambafx_1m_sr_breakout import strategy_mambafx_1m_sr_breakout
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_orb_retest_confirmation import strategy_orb_retest_confirmation
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_timeframe_based_session import strategy_timeframe_based_session
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_tom_hougaard_situational_analysis import strategy_tom_hougaard_situational_analysis
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_tom_vorwald_pbd_method import strategy_tom_vorwald_pbd_method
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_tori_trades_trendline import strategy_tori_trades_trendline
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_trader_kane_po3_manipulation import strategy_trader_kane_po3_manipulation
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_trader_mayne_structure_ote import strategy_trader_mayne_structure_ote
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_traders_paradise_black_box import strategy_traders_paradise_black_box
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_tradewithsunil_orb_5min import strategy_tradewithsunil_orb_5min
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_gautam_intraday_breakout_variants_thin import strategy_gautam_trading_breakout, strategy_gautamjha_trading_breakout
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_gautam_jha_reaction_zone_liquidity_grab import strategy_gautam_jha_reaction_zone_liquidity_grab
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_guardeer_ict_smc_sniper_choch_idm import strategy_guardeer_ict_smc_sniper_choch_idm
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_guardeer_smc_structure_bos_ob import strategy_guardeer_smc_structure_bos_ob
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_ict_smt_divergence import strategy_ict_smt_divergence
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_inna_rosputnia_sma_trend import strategy_inna_rosputnia_sma_trend
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_jadecap_playbook_session_liquidity import strategy_jadecap_playbook_session_liquidity
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_jadecap_swing_sweep_trap_breakout import strategy_jadecap_swing_sweep_trap_breakout
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_lance_capitulation_reversal import strategy_lance_capitulation_reversal
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_liquidity_sweep_pdh_pdl import strategy_liquidity_sweep_pdh_pdl
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_little_rizzy_trend_bos import strategy_little_rizzy_trend_bos
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_london_breakout_asian_range import strategy_london_breakout_asian_range
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_mambafx_ny_session_breakout import strategy_mambafx_ny_session_breakout
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_mambafx_scalping_breakout import strategy_mambafx_scalping_breakout
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_measured_move_trendline_projection import strategy_measured_move_trendline_projection
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_marco_liquidity_trap_reversal import strategy_marco_liquidity_trap_reversal
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_martin_luke_momentum_swing import strategy_martin_luke_momentum_swing
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_nbb_po3_ote_reversal import strategy_nbb_po3_ote_reversal
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_orb_anish_retest_sr import strategy_orb_anish_retest_sr
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_worlds_best_orb_retest_sr import strategy_worlds_best_orb_retest_sr
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_usman_noah_fvg_displacement import strategy_usman_noah_fvg_displacement
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_usman_noah_pdh_pdl_engulfing import strategy_usman_noah_pdh_pdl_engulfing
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_photon_smc_supply_demand import strategy_photon_smc_supply_demand
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_power_of_stocks_5ema_break import strategy_power_of_stocks_5ema_break
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_poweofstocks_5min_sr_ema_break import strategy_poweofstocks_5min_sr_ema_break
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_stockburner_rsi_divergence import strategy_stockburner_rsi_divergence
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_swappy_3c_scalping_v2 import strategy_swappy_3c_scalping_v2
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_swing_fxalexg_mtf_confirm import strategy_swing_fxalexg_mtf_confirm
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_tg_capital_trident_fvg import strategy_tg_capital_trident_fvg
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_trading_geek_gold_supply_demand import strategy_trading_geek_gold_supply_demand
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_travelling_trader_catalyst_retrace import strategy_travelling_trader_catalyst_retrace
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_first_red_day_short import strategy_first_red_day_short
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_thetraderoom_ema_crossover_pullback import strategy_thetraderoom_ema_crossover_pullback
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_tradewithsunil_opening_candle_reversal import strategy_tradewithsunil_opening_candle_reversal
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_trendline_based_4h_breakout import strategy_trendline_based_4h_breakout
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_umar_punjabi_gold_fib_sr import strategy_umar_punjabi_gold_fib_sr
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_umar_punjabi_orderblock_breakout import strategy_umar_punjabi_orderblock_breakout
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_vwap_devanshraiyt_cross_retrace import strategy_vwap_devanshraiyt_cross_retrace

PDF_LIBRARY_STRATEGIES = {
    "strategy_10ema_intraday_pullback": strategy_10ema_intraday_pullback,
    "strategy_200ema_trend_filter": strategy_200ema_trend_filter,
    "strategy_3ema_ribbon_crossover": strategy_3ema_ribbon_crossover,
    "strategy_5ema_low_high_break_powerofstocks": strategy_5ema_low_high_break_powerofstocks,
    "strategy_72min_tbs_gold_journexfx": strategy_72min_tbs_gold_journexfx,
    "strategy_8020_mean_reversion_okala": strategy_8020_mean_reversion_okala,
    "strategy_915200_ema_trend_breakout": strategy_915200_ema_trend_breakout,
    "strategy_9_15ema_crossover_retest": strategy_9_15ema_crossover_retest,
    "strategy_9_15ema_mayankraj_sr_rejection": strategy_9_15ema_mayankraj_sr_rejection,
    "strategy_9_20ema_crossover_confirmed": strategy_9_20ema_crossover_confirmed,
    "strategy_9_20ema_stockburner": strategy_9_20ema_stockburner,
    "strategy_ali_crooks_trendline_pocket": strategy_ali_crooks_trendline_pocket,
    "strategy_anish_singh_vwap_stochrsi_pivot": strategy_anish_singh_vwap_stochrsi_pivot,
    "strategy_asian_session_bos": strategy_asian_session_bos,
    "strategy_big_bar_9ema_retest": strategy_big_bar_9ema_retest,
    "strategy_blackbox_fakeout_reclaim": strategy_blackbox_fakeout_reclaim,
    "strategy_box_pdh_pdl_bounce": strategy_box_pdh_pdl_bounce,
    "strategy_candlestick_wick_zone_reversal": strategy_candlestick_wick_zone_reversal,
    "strategy_ema200_trendline_breakout": strategy_ema200_trendline_breakout,
    "strategy_ema_9_21_crossover": strategy_ema_9_21_crossover,
    "strategy_ema_fibonacci_pivot_breakout": strategy_ema_fibonacci_pivot_breakout,
    "strategy_ema_rejection_mtf": strategy_ema_rejection_mtf,
    "strategy_fabio_valentini_pullback_scalp": strategy_fabio_valentini_pullback_scalp,
    "strategy_fair_value_gap_reversion": strategy_fair_value_gap_reversion,
    "strategy_fibonacci_deep_retracement_pullback": strategy_fibonacci_deep_retracement_pullback,
    "strategy_fxalexg_mtf_swing": strategy_fxalexg_mtf_swing,
    "strategy_gautam_jha_pdh_pdl_breakout_reversal": strategy_gautam_jha_pdh_pdl_breakout_reversal,
    "strategy_mambafx_1m_sr_breakout": strategy_mambafx_1m_sr_breakout,
    "strategy_orb_retest_confirmation": strategy_orb_retest_confirmation,
    "strategy_timeframe_based_session": strategy_timeframe_based_session,
    "strategy_tom_hougaard_situational_analysis": strategy_tom_hougaard_situational_analysis,
    "strategy_tom_vorwald_pbd_method": strategy_tom_vorwald_pbd_method,
    "strategy_tori_trades_trendline": strategy_tori_trades_trendline,
    "strategy_trader_kane_po3_manipulation": strategy_trader_kane_po3_manipulation,
    "strategy_trader_mayne_structure_ote": strategy_trader_mayne_structure_ote,
    "strategy_traders_paradise_black_box": strategy_traders_paradise_black_box,
    "strategy_tradewithsunil_orb_5min": strategy_tradewithsunil_orb_5min,
    "strategy_gautam_trading_breakout": strategy_gautam_trading_breakout,
    "strategy_gautamjha_trading_breakout": strategy_gautamjha_trading_breakout,
    "strategy_gautam_jha_reaction_zone_liquidity_grab": strategy_gautam_jha_reaction_zone_liquidity_grab,
    "strategy_guardeer_ict_smc_sniper_choch_idm": strategy_guardeer_ict_smc_sniper_choch_idm,
    "strategy_guardeer_smc_structure_bos_ob": strategy_guardeer_smc_structure_bos_ob,
    "strategy_ict_smt_divergence": strategy_ict_smt_divergence,
    "strategy_inna_rosputnia_sma_trend": strategy_inna_rosputnia_sma_trend,
    "strategy_jadecap_playbook_session_liquidity": strategy_jadecap_playbook_session_liquidity,
    "strategy_jadecap_swing_sweep_trap_breakout": strategy_jadecap_swing_sweep_trap_breakout,
    "strategy_lance_capitulation_reversal": strategy_lance_capitulation_reversal,
    "strategy_liquidity_sweep_pdh_pdl": strategy_liquidity_sweep_pdh_pdl,
    "strategy_little_rizzy_trend_bos": strategy_little_rizzy_trend_bos,
    "strategy_london_breakout_asian_range": strategy_london_breakout_asian_range,
    "strategy_mambafx_ny_session_breakout": strategy_mambafx_ny_session_breakout,
    "strategy_mambafx_scalping_breakout": strategy_mambafx_scalping_breakout,
    "strategy_measured_move_trendline_projection": strategy_measured_move_trendline_projection,
    "strategy_marco_liquidity_trap_reversal": strategy_marco_liquidity_trap_reversal,
    "strategy_martin_luke_momentum_swing": strategy_martin_luke_momentum_swing,
    "strategy_nbb_po3_ote_reversal": strategy_nbb_po3_ote_reversal,
    "strategy_orb_anish_retest_sr": strategy_orb_anish_retest_sr,
    "strategy_worlds_best_orb_retest_sr": strategy_worlds_best_orb_retest_sr,
    "strategy_usman_noah_fvg_displacement": strategy_usman_noah_fvg_displacement,
    "strategy_usman_noah_pdh_pdl_engulfing": strategy_usman_noah_pdh_pdl_engulfing,
    "strategy_photon_smc_supply_demand": strategy_photon_smc_supply_demand,
    "strategy_power_of_stocks_5ema_break": strategy_power_of_stocks_5ema_break,
    "strategy_poweofstocks_5min_sr_ema_break": strategy_poweofstocks_5min_sr_ema_break,
    "strategy_stockburner_rsi_divergence": strategy_stockburner_rsi_divergence,
    "strategy_swappy_3c_scalping_v2": strategy_swappy_3c_scalping_v2,
    "strategy_swing_fxalexg_mtf_confirm": strategy_swing_fxalexg_mtf_confirm,
    "strategy_tg_capital_trident_fvg": strategy_tg_capital_trident_fvg,
    "strategy_trading_geek_gold_supply_demand": strategy_trading_geek_gold_supply_demand,
    "strategy_travelling_trader_catalyst_retrace": strategy_travelling_trader_catalyst_retrace,
    "strategy_first_red_day_short": strategy_first_red_day_short,
    "strategy_thetraderoom_ema_crossover_pullback": strategy_thetraderoom_ema_crossover_pullback,
    "strategy_tradewithsunil_opening_candle_reversal": strategy_tradewithsunil_opening_candle_reversal,
    "strategy_trendline_based_4h_breakout": strategy_trendline_based_4h_breakout,
    "strategy_umar_punjabi_gold_fib_sr": strategy_umar_punjabi_gold_fib_sr,
    "strategy_umar_punjabi_orderblock_breakout": strategy_umar_punjabi_orderblock_breakout,
    "strategy_vwap_devanshraiyt_cross_retrace": strategy_vwap_devanshraiyt_cross_retrace,
}

# ---------------------------------------------------------------------------
# NEW CONCEPTS (2026-09-13) -- added in direct response to the user's explicit
# request for genuinely NEW/enhanced concepts for GOLD/SILVER/BTCUSD/ETHUSD,
# not more retail price-action pattern variations of what had already been
# tried (SMC/ICT, MSS, VWAP/CVD, EMA crosses, RSI, chart patterns, 76
# PDF-derived strategies -- all single-asset price action). These 5 are
# statistically/structurally distinct: 2 single-asset statistical concepts
# (Hurst regime switching, realized-volatility squeeze) never before
# implemented anywhere in this codebase (confirmed via repo-wide grep before
# writing), and 3 genuine CROSS-ASSET strategies (Gold/Silver ratio mean
# reversion, DXY-regime-filtered Gold/Silver trend, BTC/ETH relative
# rotation) -- the first strategies in this project's entire strategy
# library to trade a relationship BETWEEN assets rather than one asset's own
# price action in isolation.
# ---------------------------------------------------------------------------
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_hurst_regime_switch import strategy_hurst_regime_switch
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_volatility_squeeze_breakout import strategy_volatility_squeeze_breakout
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_gold_silver_ratio_meanrev import strategy_gold_silver_ratio_meanrev
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_dxy_regime_filtered_trend import strategy_dxy_regime_filtered_trend
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library.strategy_btc_eth_relative_rotation import strategy_btc_eth_relative_rotation
from project_titan_x.engines.e24_strategy_research.plugins.pdf_strategy_library._cross_asset_wrappers import make_cross_asset_wrapper

# Cross-asset wrappers, one per (strategy, paired-asset, asset_role) combination actually
# needed for this platform's GOLD/SILVER/BTCUSD/ETHUSD watchlist. Each is registered under
# its own unique STRATEGIES key so E24's standard single-DataFrame research(symbol=...) path
# can grid-search it exactly like any other strategy -- `symbol` picks up the PRIMARY leg
# automatically via research()'s own OHLCV fetch; the wrapper internally loads the PAIRED
# asset via _cross_asset_wrappers._load_enriched.
strategy_gold_silver_ratio_meanrev__gold_leg = make_cross_asset_wrapper(
    strategy_gold_silver_ratio_meanrev, paired_symbol="SI=F", fixed_kwargs={"asset_role": "gold"})
strategy_gold_silver_ratio_meanrev__silver_leg = make_cross_asset_wrapper(
    strategy_gold_silver_ratio_meanrev, paired_symbol="GC=F", fixed_kwargs={"asset_role": "silver"})
strategy_dxy_regime_filtered_trend__vs_dxy = make_cross_asset_wrapper(
    strategy_dxy_regime_filtered_trend, paired_symbol="DX-Y.NYB")
strategy_btc_eth_relative_rotation__eth_leg = make_cross_asset_wrapper(
    strategy_btc_eth_relative_rotation, paired_symbol="BTC-USD", fixed_kwargs={"asset_role": "eth"})
strategy_btc_eth_relative_rotation__btc_leg = make_cross_asset_wrapper(
    strategy_btc_eth_relative_rotation, paired_symbol="ETH-USD", fixed_kwargs={"asset_role": "btc"})

PDF_LIBRARY_STRATEGIES.update({
    "strategy_hurst_regime_switch": strategy_hurst_regime_switch,
    "strategy_volatility_squeeze_breakout": strategy_volatility_squeeze_breakout,
    "strategy_gold_silver_ratio_meanrev__gold_leg": strategy_gold_silver_ratio_meanrev__gold_leg,
    "strategy_gold_silver_ratio_meanrev__silver_leg": strategy_gold_silver_ratio_meanrev__silver_leg,
    "strategy_dxy_regime_filtered_trend__vs_dxy": strategy_dxy_regime_filtered_trend__vs_dxy,
    "strategy_btc_eth_relative_rotation__eth_leg": strategy_btc_eth_relative_rotation__eth_leg,
    "strategy_btc_eth_relative_rotation__btc_leg": strategy_btc_eth_relative_rotation__btc_leg,
})

