# Intraday diagnosis — why a timeframe returns no signals

Every row is the FIRST stage that stopped that asset. `scan_all_assets`
collapses all of these into the same silent `return None`, so a plumbing
failure and an honest 'no setup today' are indistinguishable from outside.
**`NO_DIRECTION` is the only stage that is a real market answer.**

| Asset | 1d | 4h | 1h | 15m | 5m |
|---|---|---|---|---|---|
| EURUSD | SIGNAL | FETCH_FAIL | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative |
| GBPUSD | SIGNAL | FETCH_FAIL | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative |
| USDJPY | SIGNAL | FETCH_FAIL | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative |
| USDINR | SIGNAL | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative |
| BTCUSD | SIGNAL | FETCH_FAIL | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative |
| ETHUSD | SIGNAL | SIGNAL | NO_DIRECTION | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative |
| GOLD | SIGNAL | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative |
| SILVER | SIGNAL | NO_DIRECTION | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative |
| CRUDE | NO_DIRECTION | FETCH_FAIL | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative |
| NIFTY50 | SIGNAL | FETCH_FAIL | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative |
| BANKNIFTY | SIGNAL | NO_DIRECTION | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative | NO_DIRECTION |
| US10Y | SIGNAL | FETCH_FAIL | NO_DIRECTION | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative |
| SP500 | SIGNAL | FETCH_FAIL | NO_DIRECTION | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative |
| AAPL | SIGNAL | SIGNAL | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative |
| MSFT | NO_DIRECTION | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative |
| NVDA | VETOED:edge_not_proven_negative | SIGNAL | SIGNAL | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative |
| GOOGL | SIGNAL | FETCH_FAIL | VETOED:edge_not_proven_negative | SIGNAL | VETOED:edge_not_proven_negative |
| AMZN | NO_DIRECTION | FETCH_FAIL | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative |
| TSLA | SIGNAL | SIGNAL | VETOED:edge_not_proven_negative | SIGNAL | VETOED:edge_not_proven_negative |
| META | SIGNAL | SIGNAL | VETOED:edge_not_proven_negative | SIGNAL | NO_DIRECTION |
| JPM | SIGNAL | SIGNAL | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative |
| RELIANCE | SIGNAL | VETOED:edge_not_proven_negative | NO_DIRECTION | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative |
| TCS | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative |
| HDFCBANK | SIGNAL | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative |
| INFY | SIGNAL | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative | NO_DIRECTION | VETOED:edge_not_proven_negative |
| ICICIBANK | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative | NO_DIRECTION | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative |
| SBIN | SIGNAL | NO_DIRECTION | VETOED:edge_not_proven_negative | NO_DIRECTION | VETOED:edge_not_proven_negative |
| BHARTIARTL | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative |
| ITC | NO_DIRECTION | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative | VETOED:edge_not_proven_negative | NO_DIRECTION |

## Stage counts by timeframe

| Timeframe | SIGNAL | NO_DIRECTION | FETCH_FAIL | VETOED:edge_not_proven_negative |
|---|---|---|---|---|
| 1d | 21 | 4 | 0 | 4 |
| 4h | 6 | 3 | 10 | 10 |
| 1h | 1 | 5 | 0 | 23 |
| 15m | 3 | 2 | 0 | 24 |
| 5m | 0 | 3 | 0 | 26 |

## Reading this

| Timeframe | signals | vetoed share |
|---|---|---|
| 1d | 21 | 14% |
| 4h | 6 | 34% |
| 1h | 1 | 79% |
| 15m | 3 | 83% |
| 5m | 0 | 90% |

**The vetoed share rises monotonically as the timeframe shortens (14% -> 34% -> 79% -> 83% -> 90%).**

`edge_not_proven_negative` means this platform backtested THIS EXACT
signal rule on THIS EXACT symbol and timeframe and measured a negative
Sharpe. The signal is withheld on purpose. An empty intraday screen is
therefore the edge gate working, not a pipeline failure -- and tuning
the intraday rules harder does not address it, because the rules were
already tested and already lost money.

The pattern is what the cost arithmetic predicts: a shorter timeframe
means more trades, more cost per unit of edge, and a worse Sharpe. See
`reports/TRADING_ROADMAP.md` section 5.1 for the equation.

## Detail for everything that was not a signal

| Asset | TF | Stage | Detail |
|---|---|---|---|
| AAPL | 15m | VETOED:edge_not_proven_negative | conf=89 failed=[edge_not_proven_negative] |
| AAPL | 1h | VETOED:edge_not_proven_negative | conf=90 failed=[edge_not_proven_negative] |
| AAPL | 5m | VETOED:edge_not_proven_negative | conf=100 failed=[edge_not_proven_negative] |
| AMZN | 15m | VETOED:edge_not_proven_negative | conf=100 failed=[edge_not_proven_negative] |
| AMZN | 1d | NO_DIRECTION | conf=0 |
| AMZN | 1h | VETOED:edge_not_proven_negative | conf=29 failed=[edge_not_proven_negative] |
| AMZN | 4h | FETCH_FAIL | No data returned for AMZN (tried yahoo_finance, ccxt, nselib, alpha_va |
| AMZN | 5m | VETOED:edge_not_proven_negative | conf=100 failed=[edge_not_proven_negative] |
| BANKNIFTY | 15m | VETOED:edge_not_proven_negative | conf=24 failed=[edge_not_proven_negative] |
| BANKNIFTY | 1h | VETOED:edge_not_proven_negative | conf=43 failed=[edge_not_proven_negative] |
| BANKNIFTY | 4h | NO_DIRECTION | conf=0 |
| BANKNIFTY | 5m | NO_DIRECTION | conf=0 |
| BHARTIARTL | 15m | VETOED:edge_not_proven_negative | conf=67 failed=[edge_not_proven_negative] |
| BHARTIARTL | 1d | VETOED:edge_not_proven_negative | conf=45 failed=[edge_not_proven_negative] |
| BHARTIARTL | 1h | VETOED:edge_not_proven_negative | conf=94 failed=[edge_not_proven_negative] |
| BHARTIARTL | 4h | VETOED:edge_not_proven_negative | conf=58 failed=[edge_not_proven_negative] |
| BHARTIARTL | 5m | VETOED:edge_not_proven_negative | conf=68 failed=[edge_not_proven_negative] |
| BTCUSD | 15m | VETOED:edge_not_proven_negative | conf=62 failed=[edge_not_proven_negative] |
| BTCUSD | 1h | VETOED:edge_not_proven_negative | conf=50 failed=[edge_not_proven_negative] |
| BTCUSD | 4h | FETCH_FAIL | No data returned for BTC-USD (tried yahoo_finance, ccxt, nselib, alpha |
| BTCUSD | 5m | VETOED:edge_not_proven_negative | conf=76 failed=[edge_not_proven_negative] |
| CRUDE | 15m | VETOED:edge_not_proven_negative | conf=56 failed=[edge_not_proven_negative] |
| CRUDE | 1d | NO_DIRECTION | conf=0 |
| CRUDE | 1h | VETOED:edge_not_proven_negative | conf=54 failed=[edge_not_proven_negative] |
| CRUDE | 4h | FETCH_FAIL | No data returned for CL=F (tried yahoo_finance, ccxt, nselib, alpha_va |
| CRUDE | 5m | VETOED:edge_not_proven_negative | conf=75 failed=[edge_not_proven_negative] |
| ETHUSD | 15m | VETOED:edge_not_proven_negative | conf=24 failed=[edge_not_proven_negative] |
| ETHUSD | 1h | NO_DIRECTION | conf=0 |
| ETHUSD | 5m | VETOED:edge_not_proven_negative | conf=99 failed=[edge_not_proven_negative] |
| EURUSD | 15m | VETOED:edge_not_proven_negative | conf=100 failed=[edge_not_proven_negative] |
| EURUSD | 1h | VETOED:edge_not_proven_negative | conf=86 failed=[edge_not_proven_negative] |
| EURUSD | 4h | FETCH_FAIL | No data returned for EURUSD=X (tried yahoo_finance, ccxt, nselib, alph |
| EURUSD | 5m | VETOED:edge_not_proven_negative | conf=100 failed=[edge_not_proven_negative] |
| GBPUSD | 15m | VETOED:edge_not_proven_negative | conf=89 failed=[edge_not_proven_negative] |
| GBPUSD | 1h | VETOED:edge_not_proven_negative | conf=78 failed=[edge_not_proven_negative] |
| GBPUSD | 4h | FETCH_FAIL | No data returned for GBPUSD=X (tried yahoo_finance, ccxt, nselib, alph |
| GBPUSD | 5m | VETOED:edge_not_proven_negative | conf=93 failed=[edge_not_proven_negative] |
| GOLD | 15m | VETOED:edge_not_proven_negative | conf=22 failed=[edge_not_proven_negative] |
| GOLD | 1h | VETOED:edge_not_proven_negative | conf=45 failed=[edge_not_proven_negative] |
| GOLD | 4h | VETOED:edge_not_proven_negative | conf=78 failed=[edge_not_proven_negative] |
| GOLD | 5m | VETOED:edge_not_proven_negative | conf=22 failed=[edge_not_proven_negative] |
| GOOGL | 1h | VETOED:edge_not_proven_negative | conf=66 failed=[edge_not_proven_negative] |
| GOOGL | 4h | FETCH_FAIL | No data returned for GOOGL (tried yahoo_finance, ccxt, nselib, alpha_v |
| GOOGL | 5m | VETOED:edge_not_proven_negative | conf=100 failed=[edge_not_proven_negative] |
| HDFCBANK | 15m | VETOED:edge_not_proven_negative | conf=92 failed=[edge_not_proven_negative] |
| HDFCBANK | 1h | VETOED:edge_not_proven_negative | conf=44 failed=[edge_not_proven_negative] |
| HDFCBANK | 4h | VETOED:edge_not_proven_negative | conf=87 failed=[edge_not_proven_negative] |
| HDFCBANK | 5m | VETOED:edge_not_proven_negative | conf=50 failed=[edge_not_proven_negative] |
| ICICIBANK | 15m | VETOED:edge_not_proven_negative | conf=70 failed=[edge_not_proven_negative] |
| ICICIBANK | 1d | VETOED:edge_not_proven_negative | conf=100 failed=[edge_not_proven_negative] |
| ICICIBANK | 1h | NO_DIRECTION | conf=0 |
| ICICIBANK | 4h | VETOED:edge_not_proven_negative | conf=51 failed=[edge_not_proven_negative] |
| ICICIBANK | 5m | VETOED:edge_not_proven_negative | conf=35 failed=[edge_not_proven_negative] |
| INFY | 15m | NO_DIRECTION | conf=0 |
| INFY | 1h | VETOED:edge_not_proven_negative | conf=85 failed=[edge_not_proven_negative] |
| INFY | 4h | VETOED:edge_not_proven_negative | conf=100 failed=[edge_not_proven_negative] |
| INFY | 5m | VETOED:edge_not_proven_negative | conf=81 failed=[edge_not_proven_negative] |
| ITC | 15m | VETOED:edge_not_proven_negative | conf=50 failed=[edge_not_proven_negative] |
| ITC | 1d | NO_DIRECTION | conf=0 |
| ITC | 1h | VETOED:edge_not_proven_negative | conf=35 failed=[edge_not_proven_negative] |
| ITC | 4h | VETOED:edge_not_proven_negative | conf=62 failed=[edge_not_proven_negative] |
| ITC | 5m | NO_DIRECTION | conf=0 |
| JPM | 15m | VETOED:edge_not_proven_negative | conf=100 failed=[edge_not_proven_negative] |
| JPM | 1h | VETOED:edge_not_proven_negative | conf=53 failed=[edge_not_proven_negative] |
| JPM | 5m | VETOED:edge_not_proven_negative | conf=39 failed=[edge_not_proven_negative] |
| META | 1h | VETOED:edge_not_proven_negative | conf=100 failed=[edge_not_proven_negative] |
| META | 5m | NO_DIRECTION | conf=0 |
| MSFT | 15m | VETOED:edge_not_proven_negative | conf=68 failed=[edge_not_proven_negative] |
| MSFT | 1d | NO_DIRECTION | conf=0 |
| MSFT | 1h | VETOED:edge_not_proven_negative | conf=57 failed=[edge_not_proven_negative] |
| MSFT | 4h | VETOED:edge_not_proven_negative | conf=27 failed=[edge_not_proven_negative] |
| MSFT | 5m | VETOED:edge_not_proven_negative | conf=83 failed=[edge_not_proven_negative] |
| NIFTY50 | 15m | VETOED:edge_not_proven_negative | conf=47 failed=[edge_not_proven_negative] |
| NIFTY50 | 1h | VETOED:edge_not_proven_negative | conf=25 failed=[edge_not_proven_negative] |
| NIFTY50 | 4h | FETCH_FAIL | No data returned for ^NSEI (tried yahoo_finance, ccxt, nselib, alpha_v |
| NIFTY50 | 5m | VETOED:edge_not_proven_negative | conf=72 failed=[edge_not_proven_negative] |
| NVDA | 15m | VETOED:edge_not_proven_negative | conf=36 failed=[edge_not_proven_negative] |
| NVDA | 1d | VETOED:edge_not_proven_negative | conf=40 failed=[edge_not_proven_negative] |
| NVDA | 5m | VETOED:edge_not_proven_negative | conf=28 failed=[edge_not_proven_negative] |
| RELIANCE | 15m | VETOED:edge_not_proven_negative | conf=66 failed=[edge_not_proven_negative] |
| RELIANCE | 1h | NO_DIRECTION | conf=0 |
| RELIANCE | 4h | VETOED:edge_not_proven_negative | conf=39 failed=[edge_not_proven_negative] |
| RELIANCE | 5m | VETOED:edge_not_proven_negative | conf=32 failed=[edge_not_proven_negative] |
| SBIN | 15m | NO_DIRECTION | conf=0 |
| SBIN | 1h | VETOED:edge_not_proven_negative | conf=74 failed=[edge_not_proven_negative] |
| SBIN | 4h | NO_DIRECTION | conf=0 |
| SBIN | 5m | VETOED:edge_not_proven_negative | conf=78 failed=[edge_not_proven_negative] |
| SILVER | 15m | VETOED:edge_not_proven_negative | conf=64 failed=[edge_not_proven_negative] |
| SILVER | 1h | VETOED:edge_not_proven_negative | conf=44 failed=[edge_not_proven_negative] |
| SILVER | 4h | NO_DIRECTION | conf=0 |
| SILVER | 5m | VETOED:edge_not_proven_negative | conf=28 failed=[edge_not_proven_negative] |
| SP500 | 15m | VETOED:edge_not_proven_negative | conf=41 failed=[edge_not_proven_negative] |
| SP500 | 1h | NO_DIRECTION | conf=0 |
| SP500 | 4h | FETCH_FAIL | No data returned for MES=F (tried yahoo_finance, ccxt, nselib, alpha_v |
| SP500 | 5m | VETOED:edge_not_proven_negative | conf=46 failed=[edge_not_proven_negative] |
| TCS | 15m | VETOED:edge_not_proven_negative | conf=25 failed=[edge_not_proven_negative] |
| TCS | 1d | VETOED:edge_not_proven_negative | conf=91 failed=[edge_not_proven_negative] |
| TCS | 1h | VETOED:edge_not_proven_negative | conf=24 failed=[edge_not_proven_negative] |
| TCS | 4h | VETOED:edge_not_proven_negative | conf=91 failed=[edge_not_proven_negative] |
| TCS | 5m | VETOED:edge_not_proven_negative | conf=36 failed=[edge_not_proven_negative] |
| TSLA | 1h | VETOED:edge_not_proven_negative | conf=90 failed=[edge_not_proven_negative] |
| TSLA | 5m | VETOED:edge_not_proven_negative | conf=78 failed=[edge_not_proven_negative] |
| US10Y | 15m | VETOED:edge_not_proven_negative | conf=84 failed=[edge_not_proven_negative] |
| US10Y | 1h | NO_DIRECTION | conf=0 |
| US10Y | 4h | FETCH_FAIL | No data returned for ZN=F (tried yahoo_finance, ccxt, nselib, alpha_va |
| US10Y | 5m | VETOED:edge_not_proven_negative | conf=67 failed=[edge_not_proven_negative] |
| USDINR | 15m | VETOED:edge_not_proven_negative | conf=85 failed=[edge_not_proven_negative] |
| USDINR | 1h | VETOED:edge_not_proven_negative | conf=85 failed=[edge_not_proven_negative] |
| USDINR | 4h | VETOED:edge_not_proven_negative | conf=81 failed=[edge_not_proven_negative] |
| USDINR | 5m | VETOED:edge_not_proven_negative | conf=85 failed=[edge_not_proven_negative] |
| USDJPY | 15m | VETOED:edge_not_proven_negative | conf=64 failed=[edge_not_proven_negative] |
| USDJPY | 1h | VETOED:edge_not_proven_negative | conf=39 failed=[edge_not_proven_negative] |
| USDJPY | 4h | FETCH_FAIL | No data returned for USDJPY=X (tried yahoo_finance, ccxt, nselib, alph |
| USDJPY | 5m | VETOED:edge_not_proven_negative | conf=99 failed=[edge_not_proven_negative] |
