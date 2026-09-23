# APEX Strategy Playbook

This playbook distills the user's APEX prompts into a practical strategy-building process.

## Core Operating Law

Capital preservation comes first. Profit is a byproduct of a repeatable edge, survivable sizing, and disciplined execution. Do not guarantee returns, overfit, use dangerous leverage, or present social-media concepts as proven edges without testing.

## Evidence Tiers

Tier 1, prioritize:

- Time-series momentum and trend following across currencies, commodities, indices, bonds, and crypto proxies.
- Breakout systems with volatility-based sizing.
- Macro regime filters that reduce exposure during news shocks, central bank events, and abnormal volatility.

Tier 2, test carefully:

- Moving average, MACD, RSI, Bollinger, VWAP, and channel rules.
- Session filters for London/New York forex and gold.
- Mean reversion in low-volatility ranges.

Tier 3, translate before trusting:

- ICT/SMC concepts, liquidity sweeps, order blocks, fair value gaps, stop hunts, and kill zones.
- YouTube strategies and educator concepts.
- Discretionary chart patterns.

For Tier 3, convert the concept into measurable OHLCV rules before backtesting. Example: a "liquidity sweep" becomes "current low breaks the previous N-bar low and closes back above it."

## Pair DNA Workflow

For a forex pair, gold, index, crypto, or future:

1. Identify the instrument, session, timeframe, broker symbol, and data source.
2. Map long-term history, crisis behavior, central bank cycles, and volatility regimes.
3. Study macro drivers: interest-rate differential, inflation, employment, GDP, yields, DXY, oil, commodities, geopolitical risk, and carry.
4. Study behavior by regime: trend, range, high volatility, low volatility, risk-on, risk-off.
5. Study liquidity: prior highs/lows, session highs/lows, stop pools, sweep frequency, false breakouts, and volatility expansion.
6. Run quant profiles: ATR, return distribution, autocorrelation, trend persistence, seasonality, session volatility, correlation matrix, and Monte Carlo of trade outcomes.
7. Choose strategy families that match the pair's behavior.
8. Define entries, exits, stops, targets, filters, costs, and failure scenarios.
9. Backtest at least 10 years when the data provider supports it; otherwise state the limitation.
10. Rank candidates by CAGR, max drawdown, MAR, Sharpe, profit factor, expectancy, trade count, and psychological fit.

## Strategy Output Framework

Every strategy should include:

- Executive summary.
- Market thesis.
- Best and worst regimes.
- Entry model with exact testable rules.
- Invalidation and stop model.
- Take-profit and trailing model.
- Position sizing formula.
- Risk engine: max daily loss, max weekly loss, max monthly drawdown, correlation cap, volatility kill-switch, news kill-switch.
- Backtesting plan with sample size, out-of-sample, walk-forward, Monte Carlo, spread/slippage, and execution delay.
- Failure scenarios.
- Pine Script v6 or Python implementation when requested.

## Personalized Intake

Before giving a customized live strategy, collect:

- Capital, account currency, broker/platform, margin, leverage, reserve capital.
- Risk per trade, daily/weekly/monthly drawdown limits, max account drawdown.
- Style: scalping, day trading, swing, position.
- Sessions and daily screen time.
- Pairs/markets preferred.
- Manual, semi-auto, or automated execution preference.
- Experience with price action, SMC, volume, macro, and backtesting.
- Psychology: FOMO, revenge trading, fear, early exits, overtrading, hesitation, discipline.

If the user does not provide these, offer a conservative default: 0.25%-0.5% risk per trade, max 2%-3% daily loss, max 6% weekly loss, no revenge trades, no averaging losers, no high-impact-news entries unless specifically tested.

## Stock And Investment Committee Mode

For stock analysis, combine:

- Business quality, moat, pricing power, management, capital allocation, and long-term survivability.
- Financial analysis: growth, margins, ROE/ROIC, debt, cash conversion, dilution/buybacks.
- Valuation: DCF, reverse DCF, multiples, FCF yield, margin of safety.
- Macro: rates, inflation, currency, commodity, geopolitics, liquidity.
- Psychology: market narrative, sentiment, institutional positioning, short interest.
- Technical/quant: trend, relative strength, support/resistance, volatility, beta, correlation.
- Debate: bullish thesis, bearish thesis, biggest risk, buy/hold/sell/avoid, conviction.

End with probabilities, red flags, buy zones, risk matrix, and why the thesis could fail.

## YouTube Knowledge Mining

When the user provides a YouTube video, educator, strategy name, or transcript:

1. Extract claims, rules, filters, and implied market regime.
2. Remove vague claims and guaranteed-profit language.
3. Convert the concept into measurable conditions.
4. Add risk management, stop logic, costs, and invalidation.
5. Compare against known strategy families.
6. Backtest the translated version.
7. Keep source notes short and cite URLs. Do not reproduce long transcripts.

## Local Tools

Use the local strategy lab at:

`C:\Users\Asus\OneDrive\Documents\stategy\apex_strategy_lab`

Common commands:

```powershell
python -m apex_strategy_lab list-strategies
python -m apex_strategy_lab run --symbol EURUSD --provider yfinance --years 10 --timeframe 1d --strategy donchian_trend --capital 10000 --risk 0.5
python -m apex_strategy_lab rank --symbol EURUSD --provider yfinance --years 10 --timeframe 1d --capital 10000 --risk 0.5
python -m apex_strategy_lab pine --strategy donchian_trend
python -m apex_strategy_lab mine-youtube --url "https://www.youtube.com/watch?v=VIDEO_ID"
python -m apex_strategy_lab mt5-check
```
