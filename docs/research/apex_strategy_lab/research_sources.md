# APEX Research Sources

Collected on 2026-06-18 for the local APEX Strategy Lab.

## Platform And Data

- MetaTrader 5 Python bars: https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesrange_py
  - `copy_rates_range` returns OHLCV-like bars for a date range.
  - MT5 stores bar times in UTC.
  - Available history depends on the terminal chart history and "Max. bars in chart".
- TradingView Pine Script v6: https://www.tradingview.com/pine-script-docs/welcome/
  - Pine Script v6 is the active documented version.
- TradingView strategies: https://www.tradingview.com/pine-script-docs/concepts/strategies/
  - Strategy scripts simulate orders and show results in the Strategy Tester.
- yfinance: https://ranaroussi.github.io/yfinance/
  - Useful for personal research and prototyping.
  - Respect Yahoo terms and do not treat free data as broker-grade execution data.
- YouTube captions API: https://developers.google.com/youtube/v3/docs/captions
  - Use official APIs or user-provided transcripts/notes for YouTube concept mining.
  - Extract rules, not long transcript copies.

## Evidence-Weighted Strategy Seeds

- Trend following / time-series momentum:
  - AQR, "A Century of Evidence on Trend-Following Investing": https://www.aqr.com/Insights/Research/Journal-Article/A-Century-of-Evidence-on-Trend-Following-Investing
  - Moskowitz, Ooi, Pedersen, "Time Series Momentum": https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2089463
  - Use as a first-class seed for FX, futures, commodities, indices, and cross-asset portfolios.
- Technical analysis in FX:
  - St. Louis Fed working paper: https://files.stlouisfed.org/files/htdocs/wp/2011/2011-001.pdf
  - Evidence is mixed and regime dependent, so every rule needs walk-forward and cost testing.
- Retail forex risk:
  - CFTC OTC forex advisory: https://www.cftc.gov/PressRoom/PressReleases/8566-22
  - Broker/dealer risk, leverage, spread, withdrawal, and fraud risks must be considered before live use.

## Practical Rule

APEX should never call a strategy "best" because it sounds institutional. It is only a candidate after:

1. The logic is explicit and non-repainting.
2. It survives spread, slippage, and realistic leverage.
3. It has enough trades for the timeframe.
4. It shows tolerable drawdown.
5. It passes forward testing or walk-forward validation.
6. It fits the trader's psychology and capital constraints.

