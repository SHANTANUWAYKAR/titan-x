# Strategy Dossiers

Generated: 2026-09-15T13:16:14.271437+00:00

One institutional research report per LIVE strategy (2 currently carrying an explicit `stage0.status == "VALIDATED"` tag). PHASE 37 of `reports/upgrade statergy.txt`.

Every number is copied from an artifact that already exists — nothing is recomputed here, so this cannot disagree with the evidence it summarises. Sections follow PHASE 37's required separation: **observation**, **hypothesis**, **evidence**, **conclusion**. Missing inputs are stated as missing rather than omitted.

---

# BTCUSD 1d — `dual_thrust`

**Deployment status: LIVE.** Driving real signals via a `stage0.status == "VALIDATED"` tag on `data/models/e51_signals/BTC-USD_1d_strategy_override.json`.

---

## 1. Observation

What the instrument measurably does, independent of any strategy (`engines/e24_strategy_research/instrument_profile.py`).

| Measure | Value | Reading |
|---|---|---|
| Hurst exponent | 0.5907 | trend-persistent |
| Cost / ATR ratio | 0.08 | **workable** — the share of a typical bar's range consumed by one round trip |
| Bars analysed | 4381 | |

Highest-prior family for this instrument: **volatility_breakout** (prior 0.613) — volatility clusters (|return| lag-1 autocorr 0.2128) -- quiet periods precede expansion

---

## 2. Hypothesis

Why an edge should exist here. **This is a claim, not evidence.**

**Family:** breakout

**Why it should work.** Builds its trigger range from highs against CLOSES rather than highs against lows: range = max(HH(n) - LC(n), HC(n) - LL(n)). A single spike wick inflates a high-low range and widens a Donchian channel for the whole lookback; mixing highs against closes bounds that, so the threshold reflects where price actually settled rather than where it was briefly printed. k1 and k2 are separate, letting the long and short triggers sit at different distances from the open, which is the strategy's own idea rather than a symmetry assumption.

**When it should work.** Markets that trend after leaving a settled range, on timeframes where a bar's typical movement comfortably exceeds round-trip cost. Crypto daily qualifies on the cost test; 15m does not for any instrument in this platform (instrument_profile.py measured 0 of 29 cost-viable there).

**When it should fail.** Choppy ranges that repeatedly cross the threshold without following through -- each crossing pays the full round trip. Also when volatility collapses so the computed range shrinks below the cost hurdle, making every breakout trigger unprofitable regardless of direction accuracy.

**Expected edge.** Asymmetric payoff from occasional sustained moves, not hit rate. The live BTC-USD 1d configuration plans roughly 2:1 reward:risk, where breakeven is a 33.3% win rate -- its 52.5% backtest claim is significant against THAT baseline (p=0.0003) and indistinguishable from a coin flip against 50% (p=0.37).

**Regime.** Trending / expansion; degrades in compression.

**Cost assumptions.** E26 defaults: 0.1% commission + 0.05% slippage per side, 0.30% round trip.

**Risk model.** ATR-derived stop with a fixed reward:risk target; sized by e45_risk.

*Transcribed from: engines/e24_strategy_research/plugins/dual_thrust.py module docstring and implementation.*

Notes:

- Ported from je-suis-tm/quant-trading (Apache-2.0), logic rewritten not copied.
- Parameter PLATEAU was checked, not a single point: all 16 combinations of lookback 4-10 x k 0.5-0.8 gave positive expectancy on ETHUSD 1d.
- LIVE on BTC-USD 1d with {'lookback': 10, 'k1': 0.5, 'k2': 0.5}.

---

## 3. Evidence

### 3a. Backtest (in-sample search)

| Metric | Value |
|---|---|
| Win rate | 52.5% over 80 trades |
| IS Sharpe | 0.88 |
| OOS Sharpe | 0.88 |
| Max drawdown | 1.6% |
| Validated at | 2026-09-14T09:37:41.977568+00:00 |

Against a fair coin the same claim reads **p=0.37**; against 33.3% (breakeven at the planned 2.00:1) it reads **p=0.00032**. Quoting either without its baseline invites the wrong conclusion — a 2:1 strategy does not need a 50% hit rate to make money.

### 3b. Stage 0 — scored against a synthetic no-edge null

| Metric | Value |
|---|---|
| Null percentile | **98.0** (bar: 95.0) |
| Selection score | 0.65 |
| Trades | 87 |
| Null source | `synthetic_null_GCF_1d.json` |
| Cross-asset proxy | True |

- The 60-trade floor is convention-derived, not measured: the null campaigns do not record per-candidate trade counts.
- Null is gold (GC=F) at this timeframe -- a CROSS-ASSET PROXY for every symbol except GC=F itself.
- Percentiles are not comparable across timeframes.

> **The bar itself is under-calibrated.** These nulls were built at 167 candidates per path while the live grid is ~830 (4.97x). The best-of-N score climbs with N, so the >=95th-percentile bar they define is more lenient than it reads. A re-calibrated 1d campaign is the outstanding item; until it lands, a percentile near the bar should be read as *not yet established* rather than as a pass.

### 3c. Forward test — evidence written before the outcome was knowable

| Metric | Value |
|---|---|
| Predictions recorded | 1 |
| Resolved | 0 |
| Forward win rate | — |
| Forward expectancy | — R |
| Verdict | **no_forward_evidence** |
| Trades needed to detect decay to breakeven | 19 |

- No resolved forward trades yet. Nothing here supports or contradicts the backtest; the strategy is running on historical evidence alone.
- Backtest claim read against its own breakeven (33.3%): p=0.00032. Against a 50% baseline the same claim reads p=0.37 -- quoting either number without its baseline invites the wrong conclusion. Both describe the BACKTEST, not forward evidence.

---

## 4. Conclusion

**Deployed, but not established.** Outstanding:

- no resolved forward trades
- a null percentile of 98.0 against an under-calibrated bar, close enough that a correctly sized null could move it below

None of this says the strategy is bad. It says the evidence currently supporting it is the kind this project has already measured to be unreliable on its own, and the forward test is the only thing that can change that — one bar at a time.


---

# ETHUSD 1d — `mss_trend_hold`

**Deployment status: LIVE.** Driving real signals via a `stage0.status == "VALIDATED"` tag on `data/models/e51_signals/ETH-USD_1d_strategy_override.json`.

---

## 1. Observation

What the instrument measurably does, independent of any strategy (`engines/e24_strategy_research/instrument_profile.py`).

| Measure | Value | Reading |
|---|---|---|
| Hurst exponent | 0.6009 | trend-persistent |
| Cost / ATR ratio | 0.058 | **workable** — the share of a typical bar's range consumed by one round trip |
| Bars analysed | 3674 | |

Highest-prior family for this instrument: **volatility_breakout** (prior 0.607) — volatility clusters (|return| lag-1 autocorr 0.2071) -- quiet periods precede expansion

> **Note the mismatch.** This strategy is registered as `trend_following` while the instrument's highest prior is `volatility_breakout`. That is not disqualifying — the priors are hypotheses for a search to test, not verdicts — but it means the instrument's measured character is not the reason this strategy was selected.

---

## 2. Hypothesis

Why an edge should exist here. **This is a claim, not evidence.**

**Family:** trend_following

**Why it should work.** Trades e07_technical.smart_money.market_structure_shift's +1/-1/0 event series. A market structure shift marks the point where price stops making lows in one direction and starts making them in the other; the claim is that such a shift is followed by directional continuation more often than chance. The event is sparse, so it is held for `hold_bars` bars to be tradeable at all, and an opposite-direction event overrides the hold immediately rather than waiting for it to expire.

**When it should work.** Instruments and timeframes where structure is legible -- enough bars per swing for a shift to be distinguishable from noise. Daily crypto has this; the same logic intraday mostly detects microstructure noise.

**When it should fail.** Ranging markets, where structure shifts fire repeatedly in both directions and each is reversed within the hold window. Also whenever hold_bars is longer than the continuation it is trying to capture, which converts a winning signal into a round trip through a reversal.

**Expected edge.** Directional continuation after a structural break. Backtest claim on ETH-USD 1d is a 62.5% win rate over 64 trades (p=0.030 against a fair coin) -- the stronger of the two live claims on hit rate, though with roughly half the per-trade expectancy of dual_thrust.

**Regime.** Trending; explicitly not range-bound.

**Cost assumptions.** E26 defaults: 0.1% commission + 0.05% slippage per side, 0.30% round trip.

**Risk model.** ATR-based stop (atr_mult), fixed hold window; sized by e45_risk.

*Transcribed from: engines/e24_strategy_research/strategies.py::mss_trend_hold docstring and implementation.*

Notes:

- Causality is established rather than assumed: forward-fill-with-limit only propagates into LATER bars, and market_structure_shift is separately proven causal.
- hold_bars is a free grid parameter, so it is re-searched against current data rather than inherited from the ablation's fixed HOLD=10.
- LIVE on ETH-USD 1d with {'hold_bars': 5, 'atr_mult': 1.0}.

---

## 3. Evidence

### 3a. Backtest (in-sample search)

| Metric | Value |
|---|---|
| Win rate | 62.5% over 64 trades |
| IS Sharpe | 1.12 |
| OOS Sharpe | 1.08 |
| Max drawdown | 30.0% |
| Validated at | 2026-09-14T09:37:41.977568+00:00 |

Against a fair coin the same claim reads **p=0.03**; against 50% it reads **p=0.03**. Quoting either without its baseline invites the wrong conclusion — a 2:1 strategy does not need a 50% hit rate to make money.

### 3b. Stage 0 — scored against a synthetic no-edge null

| Metric | Value |
|---|---|
| Null percentile | **100.0** (bar: 95.0) |
| Selection score | 1.1 |
| Trades | 71 |
| Null source | `synthetic_null_GCF_1d.json` |
| Cross-asset proxy | True |

- The 60-trade floor is convention-derived, not measured: the null campaigns do not record per-candidate trade counts.
- Null is gold (GC=F) at this timeframe -- a CROSS-ASSET PROXY for every symbol except GC=F itself.
- Percentiles are not comparable across timeframes.

> **The bar itself is under-calibrated.** These nulls were built at 167 candidates per path while the live grid is ~830 (4.97x). The best-of-N score climbs with N, so the >=95th-percentile bar they define is more lenient than it reads. A re-calibrated 1d campaign is the outstanding item; until it lands, a percentile near the bar should be read as *not yet established* rather than as a pass.

### 3c. Forward test — evidence written before the outcome was knowable

**No forward predictions recorded yet for this pair.** This strategy is running on historical evidence alone — an in-sample sweep, a walk-forward split and a null percentile, every one computed over bars that already existed when the search ran.

---

## 4. Conclusion

**Deployed, but not established.** Outstanding:

- no resolved forward trades

None of this says the strategy is bad. It says the evidence currently supporting it is the kind this project has already measured to be unreliable on its own, and the forward test is the only thing that can change that — one bar at a time.


---
