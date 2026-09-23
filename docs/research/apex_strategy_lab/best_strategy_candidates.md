# APEX Best Strategy Candidates

Generated on 2026-06-18 after building the local APEX Strategy Lab and running an initial 10-year EUR/USD daily yfinance test.

This is not financial advice. "Best" means best research candidate so far, not guaranteed profit.

## Initial EUR/USD 1D Ranking

Assumptions:

- Symbol: EURUSD via yfinance.
- Period: 10 years.
- Timeframe: 1 day.
- Capital: 10,000.
- Risk per trade: 0.5%.
- Cost: 1.0 bps.
- Slippage: 0.5 bps.

| Rank | Strategy | CAGR | Max DD | Sharpe | Trades | Profit Factor | Notes |
|---:|---|---:|---:|---:|---:|---:|---|
| 1 | liquidity_sweep_reversal | 9.24% | -30.63% | 0.66 | 73 | 1.53 | Best seed in this test, but drawdown is still large. Needs MT5 broker-data validation. |
| 2 | rsi_bollinger_reversion | 1.87% | -43.98% | 0.23 | 44 | 1.20 | Positive but weak risk-adjusted profile. |
| 3 | ema_macd_momentum | -2.78% | -62.36% | -0.01 | 147 | 0.95 | Not acceptable on this setup. |
| 4 | donchian_trend | -9.13% | -79.89% | -0.39 | 38 | 0.64 | Default parameters failed on EUR/USD daily. |

Report files:

- `reports/EURUSD_1d_ranking_20260618_231452.csv`
- `reports/EURUSD_1d_liquidity_sweep_reversal_yfinance_20260618_231452_report.md`

## Best Candidate Families

1. Liquidity sweep reversal proxy

Use when the market often raids prior highs/lows and then closes back inside the range. It is a measurable translation of SMC/ICT stop-run ideas. Validate with broker spreads and session filters before live use.

2. Trend following / time-series momentum

This has the strongest broad academic and practitioner evidence across futures, currencies, commodities, and indices, but default Donchian settings did not work on the first EUR/USD daily test. Treat it as a cross-market or tuned/walk-forward candidate, not a one-pair default.

3. Mean reversion in confirmed ranges

Use only when volatility is contained and the market is rotating. Avoid during rate shocks, news breaks, and strong directional regimes.

4. EMA/MACD momentum

Better suited for intraday tests and fast trend bursts than this first EUR/USD daily test. Needs session and volatility filters.

5. Macro regime/carry model

Not yet automated in the seed code. This should combine interest-rate differential, central-bank bias, inflation surprises, DXY/yields, and risk sentiment. It is a high-priority next module once macro data sources are selected.

## Next Validation Steps

1. Log in to MT5 and rerun the top candidate with broker data.
2. Add London/New York session filters on intraday MT5 data.
3. Run walk-forward tests instead of optimizing on the full sample.
4. Bootstrap trade results for Monte Carlo drawdown estimates.
5. Test at least EUR/USD, GBP/USD, USD/JPY, GBP/JPY, XAU/USD, NAS100, and BTC/USD separately.

