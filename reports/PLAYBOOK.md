# Playbook — best strategy per asset, per trading style

Scored from **155,017 candidates**. Style comes from the timeframe using this project's own convention (1m–30m Intraday · 1h–4h Swing · 1d–1wk Positional).

Ranked on **expectancy**, then trade count — deliberately not on Sharpe or `a_plus_score`, both of which reward thin samples.

## The four gates

| Gate | Why it exists |
|---|---|
| expectancy > 0 | without it, the ranking crowns the least-bad loser |
| ≥ 60 trades | below this a 5-trade "A+" is arithmetic noise |
| null percentile ≥ 95 | 150 of 150 pure-noise paths once produced "passing" candidates here |
| DSR ≥ 0.95 | the best of 155,017 draws looks extraordinary by construction |

**0 of 87 (asset × style) cells are tradeable by all four gates.**

> **Nothing qualifies anywhere.** That is a finding, not a gap in the
> testing. Each cell below names the best candidate that exists for that
> asset and style, and the gate it fails. The most common failure is the
> null gate — a candidate that has never been scored against noise is
> *unproven*, not good.

## Intraday

| Asset | TF | Strategy | Grade | Trades | Win% | Expect. | PF | MaxDD% | DSR | Null pct | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| AAPL | 15m | `strategy_mambafx_scalping_breakout` | B | 77 | 49.4% | +0.2610 | 1.84 | 28.4 | 0.015 | **never** | never scored against the null |
| AMZN | 30m | `strategy_tpo_market_profile` | D | 74 | 54.0% | +0.3586 | 2.44 | 6.2 | 0.000 | **never** | never scored against the null |
| BANKNIFTY | 30m | `strategy_traders_paradise_black_box` | D | 67 | 53.7% | +0.1142 | 1.65 | 13.9 | 0.001 | **never** | never scored against the null |
| BHARTIARTL | 15m | `strategy_trendline_based_4h_breakout` | D | 71 | 43.7% | +0.1577 | 1.65 | 10.2 | 0.000 | **never** | never scored against the null |
| BTCUSD | 30m | `dual_thrust` | F | 67 | 47.8% | +0.4690 | 2.96 | 9.3 | 0.000 | **never** | never scored against the null |
| CRUDE | 30m | `strategy_btc_eth_relative_rotation__btc_leg` | F | 62 | 79.0% | +0.5353 | 2.46 | 21.2 | 0.000 | **never** | never scored against the null |
| ETHUSD | 30m | `strategy_gold_silver_ratio_meanrev__gold_leg` | D | 65 | 72.3% | +0.4560 | 2.50 | 13.9 | 0.000 | **never** | never scored against the null |
| EURUSD | 15m | `mss_trend_hold` | B | 63 | 52.4% | +0.0299 | 2.67 | 1.5 | 0.181 | **never** | never scored against the null |
| GBPUSD | 30m | `dual_thrust` | D | 60 | 40.0% | +0.0552 | 1.99 | 2.9 | 0.000 | **never** | never scored against the null |
| GOLD | 30m | `strategy_btc_eth_relative_rotation__btc_leg` | C | 62 | 75.8% | +0.2647 | 2.26 | 13.3 | 0.002 | **never** | never scored against the null |
| GOOGL | 30m | `heikin_ashi_trend` | F | 87 | 37.9% | +0.3656 | 2.63 | 12.2 | 0.000 | **never** | never scored against the null |
| HDFCBANK | 30m | `strategy_traders_paradise_black_box` | D | 69 | 46.4% | +0.1181 | 1.50 | 13.7 | 0.000 | **never** | never scored against the null |
| ICICIBANK | 15m | `liquidity_sweep_reversal` | F | 88 | 58.0% | +0.0767 | 1.46 | 8.7 | 0.000 | **never** | never scored against the null |
| INFY | 30m | `strategy_tradewithsunil_opening_candle_reversal` | D | 60 | 46.7% | +0.2646 | 2.03 | 7.0 | 0.000 | **never** | never scored against the null |
| ITC | 15m | `strategy_usman_noah_fvg_displacement` | F | 90 | 37.8% | +0.0814 | 1.63 | 12.3 | 0.000 | **never** | never scored against the null |
| JPM | 15m | `rsi_mean_reversion` | B | 61 | 65.6% | +0.1189 | 1.69 | 9.4 | 0.005 | **never** | never scored against the null |
| META | 15m | `strategy_mambafx_scalping_breakout` | F | 63 | 44.4% | +0.8338 | 2.63 | 22.2 | 0.000 | **never** | never scored against the null |
| MSFT | 30m | `strategy_usman_noah_fvg_displacement` | F | 62 | 37.1% | +0.2512 | 1.61 | 15.3 | 0.000 | **never** | never scored against the null |
| NIFTY50 | 15m | `vwap_mean_reversion` | D | 72 | 73.6% | +0.0925 | 1.99 | 9.6 | 0.000 | **never** | never scored against the null |
| NVDA | 15m | `strategy_umar_punjabi_orderblock_breakout` | B | 71 | 38.0% | +0.1998 | 1.58 | 18.2 | 0.238 | **never** | never scored against the null |
| RELIANCE | 15m | `strategy_gautam_jha_pdh_pdl_breakout_reversal` | D | 73 | 39.7% | +0.0849 | 1.75 | 7.8 | 0.000 | **never** | never scored against the null |
| SBIN | 15m | `strategy_gautam_jha_pdh_pdl_breakout_reversal` | D | 60 | 48.3% | +0.1368 | 1.85 | 9.5 | 0.000 | **never** | never scored against the null |
| SILVER | 30m | `strategy_btc_eth_relative_rotation__btc_leg` | B | 79 | 65.8% | +0.2390 | 1.60 | 32.1 | 0.016 | **never** | never scored against the null |
| SP500 | 30m | `regime_adaptive` | D | 77 | 40.3% | +0.0714 | 1.86 | 4.9 | 0.000 | **never** | never scored against the null |
| TCS | 15m | `macd_cross` | F | 64 | 46.9% | +0.2558 | 1.65 | 17.6 | 0.000 | **never** | never scored against the null |
| TSLA | 30m | `strategy_big_bar_9ema_retest` | B | 60 | 40.0% | +0.5958 | 2.78 | 8.1 | 0.027 | **never** | never scored against the null |
| US10Y | 15m | `dual_thrust` | F | 73 | 52.0% | +0.0353 | 1.69 | 4.0 | 0.000 | **never** | never scored against the null |
| USDINR | 15m | `strategy_mambafx_scalping_breakout` | F | 65 | 43.1% | +0.0341 | 1.98 | 1.9 | 0.000 | **never** | never scored against the null |
| USDJPY | 15m | `mss_trend_hold` | B | 69 | 52.2% | +0.0813 | 2.62 | 5.2 | 0.702 | **never** | never scored against the null |

## Swing

| Asset | TF | Strategy | Grade | Trades | Win% | Expect. | PF | MaxDD% | DSR | Null pct | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| AAPL | 1h | `strategy_gold_silver_ratio_meanrev__gold_leg` | F | 60 | 68.3% | +1.1918 | 2.75 | 30.5 | 0.000 | **never** | never scored against the null |
| AMZN | 1h | `bollinger_reversion_tuned` | F | 63 | 76.2% | +0.9501 | 2.54 | 15.6 | 0.000 | **never** | never scored against the null |
| BANKNIFTY | 4h | `strategy_tori_trades_trendline` | D | 83 | 51.8% | +0.5337 | 1.98 | 13.9 | 0.000 | **never** | never scored against the null |
| BHARTIARTL | 1h | `strategy_gold_silver_ratio_meanrev__gold_leg` | F | 65 | 67.7% | +0.7365 | 2.78 | 19.2 | 0.000 | **never** | never scored against the null |
| BTCUSD | 1h | `big_candle_continuation` | D | 165 | 37.6% | +1.4987 | 1.56 | 1.0 | — | **never** | never scored against the null |
| CRUDE | 4h | `strategy_jadecap_swing_sweep_trap_breakout` | F | 72 | 55.6% | +1.0651 | 2.23 | 19.6 | 0.000 | **never** | never scored against the null |
| ETHUSD | 4h | `ma_cross_50_200` | C | 68 | 35.3% | +9.2764 | 2.78 | 46.0 | 0.082 | **never** | never scored against the null |
| EURUSD | 4h | `strategy_btc_eth_relative_rotation__eth_leg` | B | 92 | 56.5% | +0.1983 | 1.92 | 12.2 | 0.000 | 9 | null pct 8.7 < 95 |
| GBPUSD | 4h | `strategy_nbb_po3_ote_reversal` | D | 65 | 41.5% | +0.1919 | 1.72 | 11.5 | 0.000 | **never** | never scored against the null |
| GOLD | 4h | `strategy_umar_punjabi_orderblock_breakout` | F | 60 | 45.0% | +0.8810 | 3.11 | 17.0 | 0.002 | **never** | never scored against the null |
| GOOGL | 1h | `strategy_gold_silver_ratio_meanrev__gold_leg` | D | 87 | 66.7% | +0.9146 | 2.63 | 17.6 | 0.000 | **never** | never scored against the null |
| HDFCBANK | 4h | `strategy_mambafx_scalping_breakout` | F | 61 | 50.8% | +0.4759 | 1.59 | 13.7 | 0.001 | **never** | never scored against the null |
| ICICIBANK | 1h | `strategy_9_15_ema_detailed_strategy` | F | 77 | 74.0% | +0.8026 | 2.49 | 29.3 | 0.001 | **never** | never scored against the null |
| INFY | 1h | `mss_trend_filtered` | F | 68 | 51.5% | +0.6851 | 2.43 | 18.6 | 0.000 | **never** | never scored against the null |
| ITC | 1h | `strategy_hurst_regime_switch` | F | 103 | 62.1% | +0.3509 | 1.97 | 12.9 | 0.000 | **never** | never scored against the null |
| JPM | 4h | `strategy_usman_noah_fvg_displacement` | F | 69 | 50.7% | +1.2936 | 3.34 | 12.4 | 0.000 | **never** | never scored against the null |
| META | 1h | `strategy_9_15_ema_detailed_strategy` | F | 99 | 70.7% | +1.2393 | 2.31 | 30.2 | 0.000 | **never** | never scored against the null |
| MSFT | 1h | `strategy_little_rizzy_trend_bos` | B | 77 | 74.0% | +0.6020 | 2.17 | 21.7 | 0.128 | **never** | never scored against the null |
| NIFTY50 | 4h | `strategy_umar_punjabi_gold_fib_sr` | F | 105 | 38.1% | +0.3961 | 2.16 | 18.3 | 0.000 | **never** | never scored against the null |
| NVDA | 1h | `strategy_jadecap_swing_sweep_trap_breakout` | C | 62 | 45.2% | +1.6820 | 2.23 | 21.1 | 0.000 | 79 | null pct 79.3 < 95 |
| RELIANCE | 4h | `strategy_mambafx_scalping_breakout` | D | 63 | 39.7% | +0.5187 | 1.45 | 21.4 | 0.003 | **never** | never scored against the null |
| SBIN | 1h | `ema_crossover_trading_strategy_1` | F | 65 | 72.3% | +0.8812 | 2.05 | 27.6 | 0.000 | **never** | never scored against the null |
| SILVER | 1h | `strategy_nbb_po3_ote_reversal` | F | 81 | 50.6% | +1.0058 | 2.26 | 21.5 | 0.000 | **never** | never scored against the null |
| SP500 | 4h | `strategy_gold_silver_ratio_meanrev__gold_leg` | F | 63 | 58.7% | +0.5698 | 2.25 | 23.3 | 0.000 | **never** | never scored against the null |
| TCS | 4h | `strategy_tori_trades_trendline` | D | 83 | 47.0% | +0.7128 | 1.91 | 14.2 | 0.000 | **never** | never scored against the null |
| TSLA | 1h | `strategy_blackbox_fakeout_reclaim` | F | 99 | 35.4% | +1.5253 | 1.68 | 21.5 | 0.000 | **never** | never scored against the null |
| US10Y | 1h | `strategy_jadecap_swing_sweep_trap_breakout` | D | 189 | 43.9% | +0.0748 | 1.60 | 19.1 | 0.000 | **never** | never scored against the null |
| USDINR | 1h | `strategy_guardeer_ict_smc_sniper_choch_idm` | B | 62 | 37.1% | +0.1091 | 3.17 | 6.8 | 0.347 | **never** | never scored against the null |
| USDJPY | 4h | `trend_pullback_atr_trail` | F | 62 | 32.3% | +0.2046 | 1.65 | 21.1 | 0.000 | **never** | never scored against the null |

## Positional

| Asset | TF | Strategy | Grade | Trades | Win% | Expect. | PF | MaxDD% | DSR | Null pct | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| AAPL | 1d | `strategy_ema_9_21_crossover` | D | 61 | 41.0% | +3.3232 | 2.79 | 18.7 | 0.000 | **never** | never scored against the null |
| AMZN | 1wk | `heikin_ashi_trend` | F | 77 | 40.3% | +1.3648 | 1.56 | 8.0 | 0.000 | **never** | never scored against the null |
| BANKNIFTY | 1d | `strategy_btc_eth_relative_rotation__btc_leg` | F | 66 | 59.1% | +1.7986 | 2.19 | 25.0 | 0.000 | **never** | never scored against the null |
| BHARTIARTL | 1d | `strategy_btc_eth_relative_rotation__btc_leg` | F | 67 | 56.7% | +2.2200 | 2.14 | 17.1 | 0.000 | **never** | never scored against the null |
| BTCUSD | 1d | `trend_pullback_atr_trail` | C | 61 | 37.7% | +13.0431 | 3.42 | 28.4 | 0.162 | **never** | never scored against the null |
| CRUDE | 1d | `strategy_fair_value_gap_reversion` | D | 66 | 36.4% | +4.6683 | 3.19 | 11.5 | 0.000 | **never** | never scored against the null |
| ETHUSD | 1d | `strategy_9_20ema_stockburner` | B | 62 | 38.7% | +11.9747 | 3.29 | 26.9 | 0.674 | **never** | never scored against the null |
| EURUSD | 1d | `trend_pullback_atr_trail` | D | 64 | 48.4% | +0.5169 | 2.11 | 8.0 | 0.000 | **never** | never scored against the null |
| GBPUSD | 1d | `strategy_gold_silver_ratio_meanrev__gold_leg` | F | 60 | 53.3% | +0.4686 | 1.95 | 18.7 | 0.000 | **never** | never scored against the null |
| GOLD | 1d | `strategy_btc_eth_relative_rotation__btc_leg` | D | 64 | 60.9% | +0.6674 | 1.65 | 21.8 | 0.000 | **never** | never scored against the null |
| GOOGL | 1d | `strategy_200ema_trend_filter` | C | 61 | 22.9% | +1.0749 | 1.74 | 24.9 | 0.429 | **never** | never scored against the null |
| HDFCBANK | 1d | `strategy_btc_eth_relative_rotation__btc_leg` | F | 64 | 64.1% | +1.6401 | 2.09 | 22.2 | 0.000 | **never** | never scored against the null |
| ICICIBANK | 1d | `strategy_3_moving_average_trading_setup` | D | 60 | 66.7% | +2.7830 | 2.52 | 17.2 | 0.002 | **never** | never scored against the null |
| INFY | 1d | `donchian_breakout` | D | 60 | 45.0% | +1.1851 | 1.66 | 19.7 | 0.018 | **never** | never scored against the null |
| ITC | 1d | `strategy_measured_move_trendline_projection` | C | 63 | 42.9% | +1.4330 | 2.01 | 14.9 | 0.083 | **never** | never scored against the null |
| JPM | 1d | `strategy_tori_trades_trendline` | D | 105 | 49.5% | +1.1400 | 1.75 | 10.6 | 0.005 | **never** | never scored against the null |
| META | 1d | `regime_adaptive` | D | 85 | 52.9% | +2.8407 | 2.45 | 17.5 | 0.000 | **never** | never scored against the null |
| MSFT | 1d | `strategy_btc_eth_relative_rotation__btc_leg` | D | 62 | 58.1% | +1.6365 | 1.67 | 23.4 | 0.006 | **never** | never scored against the null |
| NIFTY50 | 1d | `strategy_9_20ema_crossover_confirmed` | F | 60 | 33.3% | +1.0559 | 1.80 | 26.5 | 0.000 | **never** | never scored against the null |
| NVDA | 1d | `trend_pullback_atr_trail` | C | 62 | 41.9% | +4.1795 | 2.59 | 19.6 | 0.348 | 92 | null pct 92.0 < 95 |
| RELIANCE | 1d | `strategy_ali_crooks_trendline_pocket` | D | 60 | 30.0% | +1.2497 | 1.60 | 22.4 | 0.000 | **never** | never scored against the null |
| SBIN | 1d | `strategy_tori_trades_trendline` | F | 60 | 51.7% | +3.2324 | 2.28 | 10.0 | 0.000 | **never** | never scored against the null |
| SILVER | 1d | `strategy_blackbox_fakeout_reclaim` | F | 72 | 43.1% | +1.9122 | 1.96 | 21.8 | 0.000 | **never** | never scored against the null |
| SP500 | 1d | `dual_thrust` | F | 69 | 44.9% | +0.7654 | 1.62 | 23.9 | 0.000 | **never** | never scored against the null |
| TCS | 1d | `strategy_tori_trades_trendline` | F | 68 | 57.4% | +1.9031 | 2.38 | 13.5 | 0.001 | **never** | never scored against the null |
| TSLA | 1d | `strategy_9_20ema_crossover_confirmed` | F | 62 | 41.9% | +9.0238 | 3.63 | 29.7 | 0.000 | **never** | never scored against the null |
| US10Y | 1d | `baseline_trend` | D | 62 | 41.9% | +0.4469 | 3.11 | 11.0 | 0.000 | **never** | never scored against the null |
| USDINR | 1d | `strategy_btc_eth_relative_rotation__eth_leg` | D | 60 | 53.3% | +0.3900 | 1.84 | 10.8 | 0.000 | **never** | never scored against the null |
| USDJPY | 1d | `donchian_breakout` | F | 68 | 38.2% | +0.3976 | 1.61 | 28.5 | 0.000 | **never** | never scored against the null |

## Which gate is binding

Out of 87 cells:

| Gate failed | Cells |
|---|---|
| never scored against the null | 87 |
| deflated Sharpe < 0.95 | 87 |

**Every single cell fails "never scored against the null".** That is the one to attack first — it is a measurement that has not been run, not a verdict that has been earned.

## What the deflated Sharpe already settles

Deflated Sharpe is the probability that a candidate's TRUE Sharpe exceeds the noise floor of the search that found it. Across these 86 cells it runs **0.000 to 0.702** (median 0.000).

Every cell here already clears expectancy and sample size — these are real setups on real samples, not flukes. But 155,017 candidates were searched, and the best of that many draws looks extraordinary by construction. A DSR near zero says the observed edge is indistinguishable from the best-of-search luck.

**So the null gate, while genuinely unrun, is not what is holding these back.** Running it would confirm what the deflation already implies. The binding constraint is that the search space was enormous and the surviving edge is not large enough to stand out from it.


## How to use this

- A **TRADEABLE** cell has cleared expectancy, sample size, the synthetic
  null and the multiple-testing correction. Nothing less should get capital.
- A cell failing only the **null** gate is a candidate for null scoring, not
  a trade. Run `research/score_overrides_stage0.py`.
- A cell failing **expectancy** is finished. No amount of sizing or filtering
  turns a negative edge positive — measured directly in
  `reports/ENHANCEMENTS.md`, where volatility targeting improved expectancy in
  only 1 of 4 setups and a regime filter in 4 of 4, neither crossing zero.
- Per-concept decomposition is in `reports/CONCEPT_LAB.md`; the cost
  arithmetic that binds all of it is in `reports/TRADING_ROADMAP.md` §5.1.
