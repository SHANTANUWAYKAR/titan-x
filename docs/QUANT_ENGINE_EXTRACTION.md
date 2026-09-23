# Quant Engine Extraction — Phase 6

**Date:** 2026-09-10. **Sources inspected:** `je-suis-tm/quant-trading` (Apache-2.0, all 12 files),
`freqtrade/freqtrade` (GPL-3.0, sparse), `mementum/backtrader` (GPL-3.0). `QuantConnect/Lean` not
cloned — see §6.

**Headline: four strategies ported, zero validate.** Every archetype this phase produced was run
through E26 on the unweakened bar. None cleared it. That is the result, not a gap in the work.

---

## 1. What was already covered

`je-suis-tm/quant-trading` has 12 files. Mapping them against E24's archetypes before porting
anything:

| Source file | E24 equivalent | Status |
|---|---|---|
| Dual Thrust | `dual_thrust` | already live |
| Heikin-Ashi | `heikin_ashi_trend` | already live |
| MACD Oscillator | `macd_cross` | already live |
| RSI Pattern Recognition | `rsi_mean_reversion` (+ trend-filtered) | covered |
| Bollinger Bands Pattern Recognition | `bollinger_reversion` (+ tuned) | covered |
| London Breakout | **ported** (`3cc66a4`) | fails validation |
| Awesome Oscillator | — | **ported**, fails |
| Parabolic SAR | — | **ported**, fails |
| Shooting Star | — | **ported**, unmeasurable |
| Pair trading | E12 has cointegration | §5 — architectural mismatch |
| Options Straddle | E13 | different domain |
| VIX Calculator | E12/E13 | utility, not a strategy |

E24 went from 25 archetypes to 28.

---

## 2. Results — all four ports, measured

**Awesome Oscillator and Parabolic SAR**, tested against both the legacy bar and the Stage 0
timeframe floors:

| asset | tf | strategy | IS | OOS | sel | trades | legacy | Stage 0 |
|---|---|---|---|---|---|---|---|---|
| GC=F | 4h | awesome_oscillator | −1.09 | 0.35 | −1.09 | 356 | fail | fail (1.49) |
| GC=F | 4h | parabolic_sar | −2.67 | −1.15 | −2.67 | 692 | fail | fail |
| GC=F | 1d | awesome_oscillator | −0.20 | 0.22 | −0.20 | 195 | fail | fail (0.59) |
| BTC-USD | 4h | awesome_oscillator | −0.32 | −1.54 | −1.54 | 365 | fail | fail |
| **BTC-USD** | **1d** | **awesome_oscillator** | **0.69** | **0.25** | **0.25** | **110** | **PASS** | **fail** |
| BTC-USD | 1d | parabolic_sar | 0.30 | −0.21 | −0.21 | 215 | fail | fail |
| AAPL | 4h | awesome_oscillator | −0.56 | −2.38 | −2.38 | 76 | fail | fail |
| AAPL | 1d | awesome_oscillator | 0.17 | 0.17 | 0.17 | 344 | fail | fail |

**The BTC-USD 1d row is the most useful thing in this document.** It passes the legacy bar and fails
Stage 0. Its selection score is 0.25, against a 1d floor of 0.59 — and the 1d null's *median* winner
scored 0.464. So the legacy bar would have promoted a candidate scoring **below the median of pure
noise**. This is Stage 0 doing exactly the job it was built for, on a candidate that arrived after
it was built.

**London Breakout** (committed separately) fails on both FX pairs and both variants: EURUSD IS
−14.38 / OOS −17.53, GBPUSD IS −13.80 / OOS −15.85.

**Shooting Star is unmeasurable, not wrong.** Across ~480,000 bars and 15 asset-timeframe
combinations it produces **46 entries total** — best single case EURUSD 1h with 17. That is below
the legacy 30-trade minimum, let alone the 60-trade Stage 0 floor. It can never accumulate enough
trades to be judged. The condition funnel on GC=F 4h shows why, and shows every condition doing real
work rather than one being broken:

```
8,000 bars → 3,900 (red) → 778 (no lower wick) → 77 (small body)
           → 21 (long upper wick) → 2 (uptrend into it) → 0 after next-bar confirmation
```

---

## 3. Three lookaheads found in the source, all fixed

`Shooting Star backtest.py` would have produced a strategy with fabricated performance if ported
verbatim. Three separate defects:

| # | Source code | Problem |
|---|---|---|
| 1 | `condition7 = df['High'].shift(-1) <= df['High']` | reads the **next** bar's high |
| 2 | `condition8 = df['Close'].shift(-1) <= df['Close']` | reads the **next** bar's close |
| 3 | `condition3` compares each body to `np.mean(df['Open'] - df['Close'])` | a **whole-dataframe** mean, future bars included, used as a per-bar threshold |

Conditions 7 and 8 are part of the pattern's genuine definition — the star must be followed by a
lower candle — so they were kept and **the signal is emitted one bar later**, at the confirming bar,
which is the first moment the pattern is knowable. Condition 3 became a trailing rolling mean.

This is the same defect class as the order-block bug that once reported a 94.8% win rate here, and
the same class as the CRT translation trap documented in `ICT_SPEC_PHASE5.md` §1.4. It is now the
third independent instance in this codebase's history. **Any ported strategy should be grepped for
`shift(-` and for whole-series statistics before it is trusted.**

Awesome Oscillator and Parabolic SAR were checked the same way and are clean — zero negative shifts,
no whole-series statistics.

---

## 4. The standardised strategy interface

Phase 6 asks for `Data → Features → Signal → Risk → Position → Analytics`. **Titan X already
implements this**, distributed across engines rather than as one class. Documenting the mapping
rather than building a second abstraction over it:

| Stage | Where it lives | Contract |
|---|---|---|
| **Data** | E02 `fetch_ohlcv` (+ `core/data_providers/yahoo.py` for ad-hoc tickers) | OHLCV frame, fallback chain, catalog + audit per fetch |
| **Features** | E07 `analyze()` → enriched frame; E21 assembles the feature vector | indicator columns added to the frame |
| **Signal** | `STRATEGIES[name](enriched, **params) -> pd.Series` of −1/0/+1 | **this is the actual interface** |
| **Risk** | E45 `evaluate_trade()` — absolute veto | may reject anything; nothing may bypass it |
| **Position** | E45 sizing, capped by `max_position_leverage`; E12 Kelly | fraction of equity |
| **Analytics** | E26 metrics, E34/E35 attribution, E42 calibration | Sharpe, PF, expectancy, R-multiples |
| *(Execution)* | **absent by design** — Rule 5, enforced by E47/E48 | — |

**The signal contract in one line:** a strategy is a pure function from an enriched OHLCV frame to a
ternary Series aligned on the same index, with no lookahead. Everything else — sizing, risk,
attribution — is somebody else's job, which is what keeps `STRATEGIES` uniform enough that E26,
E24's sweep, promotion and E51's live driver all consume it identically.

**No new abstraction was introduced.** freqtrade's `IStrategy` splits
`populate_indicators` / `populate_entry_trend` / `populate_exit_trend`, which is a cleaner separation
on paper. Adopting it would mean rewriting 28 working archetypes and every caller for a structural
tidiness gain with no measurable benefit — and freqtrade is GPL, so it could only ever be a concept.
Recorded as a genuine design option, deliberately declined.

---

## 5. Pair trading — an architectural mismatch, not a port

The only quant-trading strategy with real conceptual value left unported. It is a **two-asset**
strategy: it trades the spread between a cointegrated pair.

The `STRATEGIES` contract is single-series (`df -> Series`), and E26 simulates one instrument. A pair
strategy needs two aligned price series, a hedge ratio, and a spread — none of which fit the
contract without changing it for all 28 archetypes.

Titan X already has the *statistics*: E12 implements cointegration and correlation clustering. What
is missing is a **spread instrument** — a synthetic series E26 could backtest like any other. That is
the honest shape of the work: construct the spread as a derived series, then a pair strategy becomes
an ordinary single-series strategy over it. **Not attempted here**; it is a data-model change, not a
strategy port.

---

## 6. Not inspected

**`QuantConnect/Lean`** — Apache-2.0 but C#, 573 MB. Its stated relevance is architectural (data
abstraction, parallel search, portfolio construction). E24 already has a measured 2.46× parallel
sweep with a `_PoolManager` rebuild path; reading someone else's C# would not improve a Python design
this project has already benchmarked. Declined on cost/benefit, not availability.

**`backtrader`** — cloned, GPL-3.0. Its analyzer pattern (pluggable metric collectors over a
backtest) is genuinely clean, and E26 computes its metrics inline. Same verdict as freqtrade's
interface: a real structural option, no measurable gain, copyleft. `INSPIRE ONLY`.

---

## 7. What this phase actually established

1. **Four new archetypes exist and are registered**, so any future sweep grades them automatically. None is promoted.
2. **Zero validate.** Combined with earlier sweeps, the pattern across this platform is consistent: forex has no validated edge on any timeframe, and generic indicator archetypes do not clear a bar calibrated against noise.
3. **Stage 0 caught a live case** — BTC-USD 1d AO, which the legacy bar would have promoted at a score below the median noise winner.
4. **A third instance of the same lookahead class** was found and fixed, and the two mechanical tells (`shift(-`, whole-series statistics) are now written down.
5. **The strategy interface already exists**; the useful output is the documented contract, not a new abstraction.

**Caveat on all of it:** these were tested on a handful of assets and timeframes, with default
parameters, and not swept across a parameter grid. A grid sweep could surface a parameterisation that
validates — but per Rule 6, searching harder until something passes is precisely what the Stage 0
work exists to discount. The negative results here should be read as "not promising at defaults",
not "impossible".
