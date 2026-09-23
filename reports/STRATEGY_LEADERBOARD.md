# Strategy Leaderboard (PHASE 19)

Generated: 2026-09-23T05:43:34.896172+00:00 · **155,017 candidates** scored from 235 sweep reports

Scored by `engines/e24_strategy_research/strategy_score.py`. Every metric is copied from existing artifacts — nothing is re-backtested, so this table cannot disagree with the evidence it summarises.

**A+ is gated, not earned by score.** A candidate must clear every hard gate (OOS Sharpe, positive expectancy, drawdown, trade count, parameter robustness, and a Stage 0 null percentile ≥ 95) *in addition* to scoring well. A strategy never scored against the synthetic null is capped at B — this project measured pure noise clearing its legacy bar 137 times in 150 at 4h, so backtest metrics alone do not separate edge from noise.

## Distribution

| Grade | Count |  | Status | Count |  | Overfitting risk | Count |
|---|---|---|---|---|---|---|---|
| S | 0 |  | REJECTED | 77076 |  | unknown | 154971 |
| A+ | 0 |  | FRAGILE | 39605 |  | high | 32 |
| A | 5 |  | BACKTESTING | 38290 |  | elevated | 14 |
| B | 3120 |  | OVERFIT | 32 |  |  |  |
| C | 41684 |  | VALIDATION | 14 |  |  |  |
| D | 77899 |  |  |  |  |  |  |
| F | 32309 |  |  |  |  |  |  |

## Top 40 by A+ score

| # | Strategy | Instrument | TF | Trades | Win% | PF | Expectancy | IS SR | OOS SR | MaxDD% | ParamRobust | Null%ile | Overfit risk | Score | Grade | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | strategy_200ema_trend_filter | USDINR | 30m | 9 | 44.4 | 6.06 | 0.233 | 4.75 | 4.36 | 1.7 | 1.0 | — | unknown | 0.9236 | **C** | BACKTESTING |
| 2 | strategy_200ema_trend_filter | USDINR | 30m | 9 | 44.4 | 6.06 | 0.233 | 4.75 | 4.36 | 1.7 | 1.0 | — | unknown | 0.9236 | **C** | BACKTESTING |
| 3 | strategy_200ema_trend_filter | USDINR | 30m | 9 | 44.4 | 6.06 | 0.233 | 4.75 | 4.36 | 1.7 | 1.0 | — | unknown | 0.9236 | **C** | BACKTESTING |
| 4 | strategy_tradewithsunil_orb_5min | SP500 | 30m | 24 | 37.5 | 2.38 | 0.173 | 3.67 | 3.57 | 4.1 | 0.988 | — | unknown | 0.9207 | **C** | BACKTESTING |
| 5 | strategy_tradewithsunil_orb_5min | SP500 | 30m | 24 | 37.5 | 2.36 | 0.172 | 3.64 | 3.48 | 4.1 | 0.9877 | — | unknown | 0.9188 | **C** | BACKTESTING |
| 6 | strategy_tradewithsunil_orb_5min | SP500 | 30m | 23 | 39.1 | 2.59 | 0.191 | 3.93 | 3.57 | 4.1 | 0.988 | — | unknown | 0.9133 | **C** | BACKTESTING |
| 7 | strategy_tg_capital_trident_fvg | USDJPY | 30m | 24 | 29.2 | 2.11 | 0.068 | 2.35 | 3.02 | 3.5 | 0.9855 | — | unknown | 0.9034 | **C** | BACKTESTING |
| 8 | strategy_guardeer_smc_structure_bo | USDJPY | 15m | 15 | 53.3 | 3.76 | 0.126 | 3.06 | 3.1 | 3.9 | 0.9629 | — | unknown | 0.8993 | **C** | BACKTESTING |
| 9 | strategy_guardeer_smc_structure_bo | USDJPY | 15m | 15 | 53.3 | 3.76 | 0.126 | 3.06 | 3.1 | 3.9 | 0.9629 | — | unknown | 0.8993 | **C** | BACKTESTING |
| 10 | strategy_guardeer_smc_structure_bo | USDJPY | 15m | 15 | 53.3 | 3.76 | 0.126 | 3.06 | 3.1 | 3.9 | 0.9629 | — | unknown | 0.8993 | **C** | BACKTESTING |
| 11 | strategy_measured_move_trendline_p | USDJPY | 30m | 100 | 48.0 | 1.82 | 0.038 | 2.99 | 2.77 | 3.5 | 0.6631 | — | unknown | 0.8993 | **B** | BACKTESTING |
| 12 | donchian_breakout | META | 5m | 97 | 46.4 | - | - | 3.8 | 6.47 | 0.1 | 0.7593 | — | unknown | 0.8992 | **B** | BACKTESTING |
| 13 | donchian_breakout_buffer_confirmed | USDJPY | 15m | 88 | 42.0 | 1.7 | 0.043 | 3.27 | 2.92 | 4.1 | 0.9729 | — | unknown | 0.8977 | **B** | BACKTESTING |
| 14 | strategy_mambafx_1m_sr_breakout | GOLD | 4h | 35 | 62.9 | 4.23 | 0.27 | 2.1 | 2.17 | 1.3 | 0.7443 | — | unknown | 0.8961 | **B** | BACKTESTING |
| 15 | ict_fvg_retrace | META | 5m | 139 | 41.0 | - | - | 1.94 | 1.93 | 0.1 | n/a | — | unknown | 0.896 | **B** | BACKTESTING |
| 16 | donchian_breakout | META | 5m | 117 | 46.2 | - | - | 3.46 | 6.12 | 0.1 | 0.7361 | — | unknown | 0.895 | **B** | BACKTESTING |
| 17 | donchian_breakout | USDJPY | 30m | 40 | 40.0 | 2.44 | 0.093 | 3.55 | 3.44 | 3.3 | 0.7946 | — | unknown | 0.8944 | **B** | BACKTESTING |
| 18 | donchian_breakout_buffer_confirmed | USDJPY | 15m | 105 | 40.0 | 1.58 | 0.034 | 2.92 | 3.44 | 4.1 | 0.9729 | — | unknown | 0.8943 | **B** | BACKTESTING |
| 19 | mss_trend_hold | USDJPY | 15m | 74 | 56.8 | 3.27 | 0.063 | 5.77 | 6.76 | 1.3 | 0.8482 | — | unknown | 0.8901 | **B** | BACKTESTING |
| 20 | strategy_9_20ema_stockburner | USDJPY | 30m | 70 | 30.0 | 1.85 | 0.046 | 2.45 | 3.69 | 4.5 | 0.863 | — | unknown | 0.8898 | **B** | BACKTESTING |
| 21 | donchian_breakout | USDJPY | 30m | 99 | 38.4 | 1.61 | 0.035 | 2.65 | 3.75 | 3.3 | 0.733 | — | unknown | 0.8881 | **B** | BACKTESTING |
| 22 | strategy_9_20ema_stockburner | USDJPY | 15m | 181 | 26.5 | 1.49 | 0.02 | 2.36 | 2.77 | 6.0 | 0.9511 | — | unknown | 0.8878 | **B** | BACKTESTING |
| 23 | donchian_breakout_buffer_confirmed | USDJPY | 15m | 81 | 38.3 | 1.69 | 0.045 | 3.11 | 3.81 | 4.3 | 0.9746 | — | unknown | 0.8875 | **B** | BACKTESTING |
| 24 | strategy_guardeer_smc_structure_bo | USDJPY | 15m | 27 | 40.7 | 2.68 | 0.075 | 2.98 | 3.74 | 2.9 | 0.9619 | — | unknown | 0.8867 | **C** | BACKTESTING |
| 25 | strategy_9_20ema_stockburner | USDJPY | 15m | 168 | 25.6 | 1.6 | 0.024 | 2.7 | 2.1 | 5.3 | 0.9448 | — | unknown | 0.8834 | **B** | BACKTESTING |
| 26 | strategy_guardeer_smc_structure_bo | USDJPY | 15m | 28 | 39.3 | 2.57 | 0.07 | 2.89 | 3.74 | 3.1 | 0.9608 | — | unknown | 0.8833 | **C** | BACKTESTING |
| 27 | strategy_guardeer_smc_structure_bo | USDJPY | 15m | 28 | 39.3 | 2.57 | 0.07 | 2.89 | 3.74 | 3.1 | 0.9608 | — | unknown | 0.8833 | **C** | BACKTESTING |
| 28 | donchian_breakout | USDJPY | 30m | 92 | 34.8 | 1.62 | 0.038 | 2.59 | 3.64 | 3.5 | 0.7273 | — | unknown | 0.8831 | **B** | BACKTESTING |
| 29 | strategy_200ema_trend_filter | USDINR | 15m | 27 | 29.6 | 2.85 | 0.07 | 4.01 | 6.71 | 2.5 | 1.0 | — | unknown | 0.8829 | **C** | BACKTESTING |
| 30 | strategy_200ema_trend_filter | USDINR | 15m | 27 | 29.6 | 2.85 | 0.07 | 4.01 | 6.71 | 2.5 | 1.0 | — | unknown | 0.8829 | **C** | BACKTESTING |
| 31 | strategy_200ema_trend_filter | USDINR | 15m | 27 | 29.6 | 2.85 | 0.07 | 4.01 | 6.71 | 2.5 | 1.0 | — | unknown | 0.8829 | **C** | BACKTESTING |
| 32 | rsi_mean_reversion_trend_filtered | GBPUSD | 15m | 34 | 82.3 | 9.11 | 0.055 | 4.8 | 4.98 | 1.4 | 0.8048 | — | unknown | 0.8816 | **B** | BACKTESTING |
| 33 | mss_trend_hold | USDJPY | 15m | 42 | 50.0 | 4.16 | 0.142 | 6.05 | 5.58 | 3.1 | 0.843 | — | unknown | 0.8816 | **B** | BACKTESTING |
| 34 | regime_adaptive | USDJPY | 30m | 111 | 39.6 | 1.5 | 0.029 | 2.25 | 2.09 | 5.1 | n/a | — | unknown | 0.8814 | **B** | BACKTESTING |
| 35 | strategy_guardeer_smc_structure_bo | TCS | 15m | 1 | 100.0 | inf | 8.662 | 4.75 | 5.13 | 2.1 | 0.8169 | — | unknown | 0.8801 | **C** | BACKTESTING |
| 36 | strategy_guardeer_smc_structure_bo | TCS | 15m | 1 | 100.0 | inf | 8.662 | 4.75 | 5.13 | 2.1 | 0.8169 | — | unknown | 0.8801 | **C** | BACKTESTING |
| 37 | strategy_guardeer_smc_structure_bo | TCS | 15m | 1 | 100.0 | inf | 8.662 | 4.75 | 5.13 | 2.1 | 0.8169 | — | unknown | 0.8801 | **C** | BACKTESTING |
| 38 | donchian_breakout | USDJPY | 15m | 118 | 43.2 | 1.68 | 0.034 | 3.43 | 3.54 | 4.1 | 0.7972 | — | unknown | 0.8791 | **B** | BACKTESTING |
| 39 | strategy_trader_mayne_structure_ot | GBPUSD | 30m | 12 | 58.3 | 2.5 | 0.133 | 3.64 | 3.89 | 1.6 | 0.746 | — | unknown | 0.8789 | **C** | BACKTESTING |
| 40 | mss_trend_hold | EURUSD | 30m | 62 | 53.2 | 1.89 | 0.022 | 3.25 | 3.27 | 1.8 | 0.5378 | — | unknown | 0.8779 | **B** | BACKTESTING |

## A+ candidates

**None.** No candidate clears every hard gate. The most common blocker is shown below — this is a real result, not a missing run.

| Blocking gate | Candidates blocked |
|---|---|
| never scored | 154,971 |
| deflated Sharpe | 154,903 |
| OOS Sharpe | 124,137 |
| max drawdown | 57,650 |
| parameter robustness | 46,719 |
| 0 trades | 23,049 |
| expectancy 0.0 | 22,958 |
| expectancy None | 8,298 |

## Known limitations

- **Regime diversification is not scored.** Per-candidate regime attribution is not recorded in any sweep report; PHASE 11's suggested 5% is redistributed rather than awarded on an unmeasured axis.
- **Null percentiles come from live overrides only.** Candidates on instruments with no Stage 0 scoring show `—` and are capped at B by design.
- **The null itself is under-calibrated.** It was built at 167 candidates per path while the current grid is ~830, making the ≥95 gate more lenient than it reads. Re-running the null campaigns at current grid size is the fix.
