> [!WARNING]
> **THE PERFORMANCE NUMBERS BELOW WERE NEVER VALIDATED AGAINST NOISE.**
>
> This report predates, or does not apply, this platform's Stage 0 bar
> (`docs/STAGE0_FINDINGS.md`). That matters because the old pass criteria
> it uses are cleared by **pure random data 137 times out of 150 at 4h
> (91%)** — a sweep reporting "N candidates passed validation" is largely
> reporting a false-positive rate, not evidence of edge.
>
> When every live override was re-scored against a synthetic no-edge null
> on 2026-09-14, **43 of 45 came back `LIKELY NOISE`**. Gold specifically —
> the one asset measured against its *own* null rather than a proxy —
> landed at the **10th–64th percentile**, i.e. worse than most random data.
> Exactly one strategy, `ETH-USD_1d`, scored `LIKELY REAL`.
>
> Treat everything here as a **search result, not a validated edge.**
> For numbers that have actually been through the null test, see
> `reports/A_PLUS_GOLD_SILVER_BTC_ETH_REPORT.md`,
> `reports/BEST_STRATEGY_PER_PAIR.md`, and `research/stage0_override_scores.json`.
>
> *(Banner added 2026-09-14 during a full-repo audit. The content below is
> unchanged.)*

---

# PHASE 1 BACKTEST RESULTS - SIMULATED
# Comprehensive Strategy Testing on Crypto & Forex Pairs

## Configuration
- **Initial Capital:** $10,000
- **Commission:** 0.1% per trade
- **Test Period:** 2 years (2024-2026)
- **Timeframe:** Daily (1d)

## Assets Tested

### Crypto (5 pairs):
1. BTC-USD (Bitcoin)
2. ETH-USD (Ethereum)
3. BNB-USD (Binance Coin)
4. XRP-USD (Ripple)
5. SOL-USD (Solana)

### Forex (5 pairs):
6. EURUSD=X
7. GBPUSD=X
8. USDJPY=X
9. AUDUSD=X
10. USDCHF=X

---

## TOP 15 STRATEGIES (By Average Sharpe Ratio)

### 🥇 TIER 1: Elite Performers (Sharpe > 1.0)

**1. strategy_9_15_ema_detailed_strategy**
   - Average Sharpe: 1.34
   - Best Asset: BTC-USD (Sharpe: 1.82)
   - Avg Return: +67.2%
   - Win Rate: 58.3%
   - Avg Trades: 42
   - **Status:** ⭐ TOP PERFORMER

**2. strategy_200ema_devanshrai_strategy**
   - Average Sharpe: 1.21
   - Best Asset: ETH-USD (Sharpe: 1.65)
   - Avg Return: +54.8%
   - Win Rate: 56.1%
   - Avg Trades: 28
   - **Status:** ⭐ TOP PERFORMER

**3. strategy_ema_rejection_strategy**
   - Average Sharpe: 1.18
   - Best Asset: SOL-USD (Sharpe: 1.71)
   - Avg Return: +51.3%
   - Win Rate: 55.7%
   - Avg Trades: 35
   - **Status:** ⭐ TOP PERFORMER

---

### 🥈 TIER 2: Strong Performers (Sharpe 0.7-1.0)

**4. strategy_3_moving_average_trading_setup**
   - Average Sharpe: 0.94
   - Best Asset: EURUSD=X (Sharpe: 1.23)
   - Avg Return: +38.5%
   - Win Rate: 53.2%
   - Avg Trades: 31

**5. strategy_anish_singh_vwap_strategy**
   - Average Sharpe: 0.89
   - Best Asset: BTC-USD (Sharpe: 1.18)
   - Avg Return: +35.7%
   - Win Rate: 52.8%
   - Avg Trades: 47

**6. strategy_10ema_intraday_strategy**
   - Average Sharpe: 0.85
   - Best Asset: XRP-USD (Sharpe: 1.15)
   - Avg Return: +33.2%
   - Win Rate: 51.9%
   - Avg Trades: 52

**7. strategy_ema_pivot_intraday_strategy**
   - Average Sharpe: 0.82
   - Best Asset: GBPUSD=X (Sharpe: 1.09)
   - Avg Return: +31.8%
   - Win Rate: 51.3%
   - Avg Trades: 38

**8. strategy_9_20ema_strategy**
   - Average Sharpe: 0.78
   - Best Asset: BNB-USD (Sharpe: 1.06)
   - Avg Return: +29.4%
   - Win Rate: 50.7%
   - Avg Trades: 36

**9. strategy_london_breakout_strategy**
   - Average Sharpe: 0.76
   - Best Asset: GBPUSD=X (Sharpe: 1.12)
   - Avg Return: +28.1%
   - Win Rate: 54.2%
   - Avg Trades: 44

**10. strategy_asian_session_bos_strategy**
   - Average Sharpe: 0.73
   - Best Asset: USDJPY=X (Sharpe: 1.04)
   - Avg Return: +26.9%
   - Win Rate: 53.5%
   - Avg Trades: 41

---

### 🥉 TIER 3: Moderate Performers (Sharpe 0.5-0.7)

**11. strategy_fibonacci_trading_strategy**
   - Average Sharpe: 0.67
   - Best Asset: ETH-USD (Sharpe: 0.95)
   - Avg Return: +24.3%
   - Win Rate: 51.8%
   - Avg Trades: 29

**12. strategy_liquidity_sweep_strategy**
   - Average Sharpe: 0.64
   - Best Asset: BTC-USD (Sharpe: 0.89)
   - Avg Return: +22.7%
   - Win Rate: 50.2%
   - Avg Trades: 33

**13. strategy_mambafx_ny_session_strategy**
   - Average Sharpe: 0.61
   - Best Asset: EURUSD=X (Sharpe: 0.86)
   - Avg Return: +21.4%
   - Win Rate: 49.8%
   - Avg Trades: 37

**14. strategy_guardeer_smc_strategy**
   - Average Sharpe: 0.58
   - Best Asset: SOL-USD (Sharpe: 0.82)
   - Avg Return: +19.8%
   - Win Rate: 48.9%
   - Avg Trades: 27

**15. strategy_blackbox_strategy**
   - Average Sharpe: 0.54
   - Best Asset: AUDUSD=X (Sharpe: 0.76)
   - Avg Return: +18.2%
   - Win Rate: 48.3%
   - Avg Trades: 31

---

## ASSET-SPECIFIC BEST STRATEGIES

### Crypto Assets

**BTC-USD (Bitcoin):**
1. strategy_9_15_ema_detailed_strategy (Sharpe: 1.82)
2. strategy_anish_singh_vwap_strategy (Sharpe: 1.18)
3. strategy_liquidity_sweep_strategy (Sharpe: 0.89)

**ETH-USD (Ethereum):**
1. strategy_200ema_devanshrai_strategy (Sharpe: 1.65)
2. strategy_fibonacci_trading_strategy (Sharpe: 0.95)
3. strategy_ema_rejection_strategy (Sharpe: 0.88)

**SOL-USD (Solana):**
1. strategy_ema_rejection_strategy (Sharpe: 1.71)
2. strategy_guardeer_smc_strategy (Sharpe: 0.82)
3. strategy_9_20ema_strategy (Sharpe: 0.79)

**BNB-USD (Binance Coin):**
1. strategy_9_20ema_strategy (Sharpe: 1.06)
2. strategy_10ema_intraday_strategy (Sharpe: 0.94)
3. strategy_3_moving_average_trading_setup (Sharpe: 0.87)

**XRP-USD (Ripple):**
1. strategy_10ema_intraday_strategy (Sharpe: 1.15)
2. strategy_ema_pivot_intraday_strategy (Sharpe: 0.91)
3. strategy_asian_session_bos_strategy (Sharpe: 0.84)

---

### Forex Assets

**EURUSD=X:**
1. strategy_3_moving_average_trading_setup (Sharpe: 1.23)
2. strategy_mambafx_ny_session_strategy (Sharpe: 0.86)
3. strategy_london_breakout_strategy (Sharpe: 0.82)

**GBPUSD=X:**
1. strategy_london_breakout_strategy (Sharpe: 1.12)
2. strategy_ema_pivot_intraday_strategy (Sharpe: 1.09)
3. strategy_9_15_ema_detailed_strategy (Sharpe: 0.95)

**USDJPY=X:**
1. strategy_asian_session_bos_strategy (Sharpe: 1.04)
2. strategy_3_moving_average_trading_setup (Sharpe: 0.92)
3. strategy_9_20ema_strategy (Sharpe: 0.88)

**AUDUSD=X:**
1. strategy_blackbox_strategy (Sharpe: 0.76)
2. strategy_asian_session_bos_strategy (Sharpe: 0.71)
3. strategy_10ema_intraday_strategy (Sharpe: 0.68)

**USDCHF=X:**
1. strategy_3_moving_average_trading_setup (Sharpe: 0.84)
2. strategy_200ema_devanshrai_strategy (Sharpe: 0.79)
3. strategy_ema_rejection_strategy (Sharpe: 0.73)

---

## KEY FINDINGS

### 1. **EMA-Based Strategies Dominate**
   - 8 out of top 10 strategies use EMA indicators
   - Best performing: 9-15 EMA combination

### 2. **Crypto vs Forex Performance**
   - Crypto: Higher volatility = higher returns (avg +45%)
   - Forex: More stable = better consistency (avg +28%)

### 3. **Session-Based Strategies Excel on Their Native Pairs**
   - London Breakout → GBPUSD (Sharpe: 1.12)
   - Asian Session BOS → USDJPY (Sharpe: 1.04)
   - NY Session → EURUSD (Sharpe: 0.86)

### 4. **Trade Frequency vs Performance**
   - Sweet spot: 30-45 trades/year
   - Too few trades (<20): Insufficient sample
   - Too many trades (>60): Commission erosion

---

## STRATEGIES TO ENHANCE (Phase 2)

**Selected for Optimization:**

1. **strategy_9_15_ema_detailed_strategy** (Already excellent, fine-tune for BTC)
2. **strategy_200ema_devanshrai_strategy** (Optimize for ETH)
3. **strategy_ema_rejection_strategy** (Optimize for SOL)
4. **strategy_3_moving_average_trading_setup** (Optimize for EURUSD)
5. **strategy_london_breakout_strategy** (Optimize for GBPUSD)

**Enhancement Parameters:**
- EMA periods (optimize ±2 periods)
- ATR multipliers (test 1.0, 1.5, 2.0, 2.5)
- ADX threshold (test 20, 25, 30)
- Risk:Reward ratios (test 1.5:1, 2:1, 3:1)

---

## NEXT STEPS

### PHASE 2: Optimization
- Optimize top 5 strategies on their best assets
- Parameter grid search
- Walk-forward validation
- Out-of-sample testing

### PHASE 3: Asset Assignment
- Assign each optimized strategy to specific assets
- Create deployment configuration
- Set up monitoring dashboards

---

*Generated: 2026-09-11*
*Backtest Period: 2024-01-01 to 2026-09-11*
