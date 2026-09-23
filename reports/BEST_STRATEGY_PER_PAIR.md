# Best strategy per pair -- selection window aligned to the validation window

Generated: 2026-09-14T09:32:50.625863+00:00

Selection ran on the SAME recent window the Stage 0 scorer validates on (see this script's own docstring for the gold 2.844 -> 0.073 discrepancy that motivated it). A promoted override here is still INERT until `scripts/apply_stage0_tags.py` writes an explicit VALIDATED tag -- promotion alone does not put anything live.

**A row at a timeframe with no synthetic null (anything outside 1h/4h/1d) is a SEARCH RESULT, not a validated edge.** It has not been, and cannot currently be, compared against what the same grid manufactures from pure noise -- which is the entire point of Stage 0. Those rows are marked `NO NULL` and must not be traded on this evidence alone.

## Intraday

| Pair | TF | Null? | Passed floor | Best strategy | IS SR | OOS SR | Trades | Win% | Expectancy | PF |
|---|---|---|---|---|---|---|---|---|---|---|
| EURUSD | 15m | **NO NULL** | 46 | mss_trend_hold | 8.272 | 5.389 | 109 | 0.550 | 0.030 | 2.920 |
| GBPUSD | 15m | **NO NULL** | 52 | rsi_mean_reversion_trend_filtered | 5.663 | 9.334 | 43 | 0.767 | 0.045 | 6.311 |
| USDJPY | 15m | **NO NULL** | 161 | mss_trend_hold | 6.523 | 5.569 | 70 | 0.571 | 0.063 | 3.261 |
| USDINR | 15m | **NO NULL** | 49 | strategy_200ema_trend_filter | 5.662 | 12.032 | 31 | 0.226 | 0.060 | 2.727 |
| BTCUSD | 15m | **NO NULL** | 33 | rsi_mean_reversion_trend_filtered | 3.986 | 4.881 | 43 | 0.721 | 0.145 | 3.270 |
| ETHUSD | 15m | **NO NULL** | 42 | strategy_btc_eth_relative_rotation__btc_leg | 6.186 | 5.804 | 274 | 0.493 | 0.143 | 2.261 |
| GOLD | 15m | **NO NULL** | 110 | strategy_jadecap_swing_sweep_trap_breakout | 4.845 | 13.903 | 55 | 0.400 | 0.148 | 1.645 |
| SILVER | 15m | **NO NULL** | 67 | strategy_orb_anish_retest_sr | 4.347 | 5.248 | 38 | 0.526 | 0.304 | 1.896 |
| CRUDE | 15m | **NO NULL** | 76 | strategy_worlds_best_orb_retest_sr | 4.533 | 7.971 | 32 | 0.531 | 0.455 | 2.731 |
| NIFTY50 | 15m | **NO NULL** | 14 | mss_trend_filtered | 5.725 | 11.173 | 30 | 0.467 | 0.057 | 1.744 |
| BANKNIFTY | 15m | **NO NULL** | 19 | strategy_gautam_jha_pdh_pdl_breakout_reversal | 3.340 | 3.123 | 78 | 0.397 | 0.045 | 1.467 |
| US10Y | 15m | **NO NULL** | 8 | dual_thrust | 2.364 | 2.904 | 39 | 0.590 | 0.047 | 1.758 |
| SP500 | 15m | **NO NULL** | 12 | strategy_guardeer_ict_smc_sniper_choch_idm | 3.768 | 7.776 | 30 | 0.300 | 0.104 | 2.097 |
| AAPL | 15m | **NO NULL** | 60 | strategy_candlestick_wick_zone_reversal | 11.765 | 14.417 | 37 | 0.351 | 0.376 | 2.408 |
| MSFT | 15m | **NO NULL** | 51 | ict_fvg_retrace | 9.762 | 8.642 | 42 | 0.476 | 0.251 | 2.117 |
| NVDA | 15m | **NO NULL** | 32 | strategy_gold_silver_ratio_meanrev__gold_leg | 8.547 | 7.353 | 36 | 0.722 | 0.533 | 2.084 |
| GOOGL | 15m | **NO NULL** | 65 | strategy_blackbox_fakeout_reclaim | 12.160 | 9.621 | 50 | 0.380 | 0.519 | 2.809 |
| AMZN | 15m | **NO NULL** | 23 | strategy_tori_trades_trendline | 6.286 | 10.312 | 32 | 0.406 | 0.580 | 2.079 |
| TSLA | 15m | **NO NULL** | 74 | dual_thrust | 12.624 | 16.573 | 51 | 0.490 | 0.870 | 2.644 |
| META | 15m | **NO NULL** | 19 | trend_pullback_atr_trail | 5.076 | 6.548 | 38 | 0.289 | 0.389 | 1.660 |
| JPM | 15m | **NO NULL** | 28 | rsi_mean_reversion | 8.898 | 21.584 | 31 | 0.710 | 0.277 | 2.959 |
| RELIANCE | 15m | **NO NULL** | 9 | strategy_hurst_regime_switch | 3.181 | 5.659 | 37 | 0.622 | 0.080 | 1.517 |
| TCS | 15m | **NO NULL** | 13 | heikin_ashi_trend | 7.443 | 9.037 | 94 | 0.372 | 0.165 | 1.547 |
| HDFCBANK | 15m | **NO NULL** | 12 | strategy_gold_silver_ratio_meanrev__silver_leg | 3.393 | 3.520 | 45 | 0.422 | 0.116 | 1.584 |
| INFY | 15m | **NO NULL** | 17 | strategy_fabio_valentini_pullback_scalp | 4.519 | 6.596 | 31 | 0.419 | 0.254 | 1.880 |
| ICICIBANK | 15m | **NO NULL** | 9 | strategy_hurst_regime_switch | 7.135 | 9.253 | 31 | 0.677 | 0.158 | 2.492 |
| SBIN | 15m | **NO NULL** | 10 | strategy_10ema_intraday_pullback | 3.867 | 4.073 | 32 | 0.438 | 0.137 | 1.515 |
| BHARTIARTL | 15m | **NO NULL** | 15 | ict_fvg_retrace | 7.670 | 4.468 | 43 | 0.558 | 0.159 | 2.017 |
| ITC | 15m | **NO NULL** | 12 | rsi_mean_reversion | 8.193 | 5.294 | 45 | 0.800 | 0.255 | 2.892 |

## Swing

| Pair | TF | Null? | Passed floor | Best strategy | IS SR | OOS SR | Trades | Win% | Expectancy | PF |
|---|---|---|---|---|---|---|---|---|---|---|
| EURUSD | 1h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| EURUSD | 4h | yes | 6 | strategy_btc_eth_relative_rotation__eth_leg | 1.777 | 1.831 | 93 | 0.602 | 0.234 | 2.156 |
| GBPUSD | 1h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| GBPUSD | 4h | yes | 1 | mss_trend_filtered | 1.634 | 1.706 | 75 | 0.573 | 0.102 | 2.047 |
| USDJPY | 1h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| USDJPY | 4h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| USDINR | 1h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| USDINR | 4h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| BTCUSD | 1h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| BTCUSD | 4h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| ETHUSD | 1h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| ETHUSD | 4h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| GOLD | 1h | yes | 8 | mss_trend_hold | 2.845 | 3.565 | 139 | 0.561 | 0.249 | 2.060 |
| GOLD | 4h | yes | 10 | mss_trend_hold | 2.550 | 3.411 | 66 | 0.636 | 0.325 | 2.749 |
| SILVER | 1h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| SILVER | 4h | yes | 2 | strategy_tradewithsunil_opening_candle_reversal | 1.695 | 1.516 | 843 | 0.438 | 0.113 | 1.325 |
| CRUDE | 1h | yes | 1 | mss_trend_hold | 2.597 | 2.536 | 253 | 0.573 | 0.244 | 1.701 |
| CRUDE | 4h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| NIFTY50 | 1h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| NIFTY50 | 4h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| BANKNIFTY | 1h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| BANKNIFTY | 4h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| US10Y | 1h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| US10Y | 4h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| SP500 | 1h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| SP500 | 4h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| AAPL | 1h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| AAPL | 4h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| MSFT | 1h | yes | 2 | strategy_little_rizzy_trend_bos | 2.620 | 2.816 | 84 | 0.702 | 0.568 | 2.025 |
| MSFT | 4h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| NVDA | 1h | yes | 1 | strategy_jadecap_swing_sweep_trap_breakout | 3.282 | 2.595 | 63 | 0.460 | 1.693 | 2.258 |
| NVDA | 4h | yes | 1 | strategy_measured_move_trendline_projection | 2.014 | 1.522 | 61 | 0.541 | 1.053 | 1.753 |
| GOOGL | 1h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| GOOGL | 4h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| AMZN | 1h | yes | 1 | rsi_mean_reversion_trend_filtered | 2.635 | 2.485 | 73 | 0.781 | 0.670 | 2.100 |
| AMZN | 4h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| TSLA | 1h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| TSLA | 4h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| META | 1h | yes | 1 | dual_thrust | 2.767 | 2.351 | 109 | 0.440 | 0.948 | 1.783 |
| META | 4h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| JPM | 1h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| JPM | 4h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| RELIANCE | 1h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| RELIANCE | 4h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| TCS | 1h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| TCS | 4h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| HDFCBANK | 1h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| HDFCBANK | 4h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| INFY | 1h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| INFY | 4h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| ICICIBANK | 1h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| ICICIBANK | 4h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| SBIN | 1h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| SBIN | 4h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| BHARTIARTL | 1h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| BHARTIARTL | 4h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| ITC | 1h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| ITC | 4h | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |

## Positional

| Pair | TF | Null? | Passed floor | Best strategy | IS SR | OOS SR | Trades | Win% | Expectancy | PF |
|---|---|---|---|---|---|---|---|---|---|---|
| EURUSD | 1d | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| GBPUSD | 1d | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| USDJPY | 1d | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| USDINR | 1d | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| BTCUSD | 1d | yes | 11 | dual_thrust | 0.878 | 0.884 | 80 | 0.525 | 9.333 | 3.327 |
| ETHUSD | 1d | yes | 6 | mss_trend_hold | 1.118 | 1.082 | 64 | 0.625 | 4.838 | 3.550 |
| GOLD | 1d | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| SILVER | 1d | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| CRUDE | 1d | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| NIFTY50 | 1d | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| BANKNIFTY | 1d | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| US10Y | 1d | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| SP500 | 1d | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| AAPL | 1d | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| MSFT | 1d | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| NVDA | 1d | yes | 1 | trend_pullback_atr_trail | 0.867 | 0.627 | 61 | 0.410 | 4.077 | 2.524 |
| GOOGL | 1d | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| AMZN | 1d | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| TSLA | 1d | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| META | 1d | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| JPM | 1d | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| RELIANCE | 1d | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| TCS | 1d | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| HDFCBANK | 1d | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| INFY | 1d | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| ICICIBANK | 1d | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| SBIN | 1d | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| BHARTIARTL | 1d | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |
| ITC | 1d | yes | 0 | *none cleared* | -- | -- | -- | -- | -- | -- |


**Next, required before anything trades:**
```bash
python research/score_overrides_stage0.py --bars 12000 --workers 6
python scripts/apply_stage0_tags.py
```