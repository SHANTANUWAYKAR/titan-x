# Stage 0 Findings — Deflated Sharpe, Effective N, and the Synthetic Null

**Status:** complete and enforced (reversibly). **Date:** 2026-09-07.
**Artifacts:** `research/synthetic_null_GCF_{1h,4h,1d}.json`, `research/stage0_override_scores.json`,
`engines/e26_backtesting/deflated_sharpe.py`, `research/synthetic_null.py`,
`research/score_overrides_stage0.py`, `scripts/apply_stage0_tags.py`.

> **Provenance note.** `docs/validation_standards.md` has never existed in this repo — not in the
> tree, never committed, not stashed. This work is built on the standard definitions (Bailey &
> López de Prado for DSR; spectral-entropy effective rank for trial count) plus the parameters
> supplied directly in conversation: effective rank as the primary N estimator, DSR threshold 0.95,
> stationary block bootstrap with three block lengths, K=50 per block length.

---

## 1. Read this first — the caveats that qualify every number below

These are not footnotes. Each one changes how the results should be used.

**1. The 60-trade floor is convention-derived, not measured.** The null campaigns record per-path
pass counts and the winning candidate's Sharpe, but **not the trade count of each passing
candidate**. There is therefore nothing to calibrate a trade floor against. 60 comes from Sharpe
standard-error arithmetic (SE ≈ 0.158 at n=60 for SR=1.0) and convention. Only the
**selection-score floors are measured.** Calibrating the trade floor would need a null variant that
records per-candidate trade counts — not run.

**2. 43 of 45 rows use gold as a cross-asset proxy null.** Campaigns were run on `GC=F` only. Every
override except `GC=F_1h` and `GC=F_4h` is scored against gold's null at its own timeframe. This is
defensible — the null characterises how readily a 167-candidate grid manufactures a winner from a
given number of bars — but volatility structure differs by asset, so it is a **stand-in, not a
measurement of that asset**. Each row's `null source` column says which.

**3. DSR is optimistic.** The derivation assumes near-IID returns. These strategies hold positions
across many bars, so per-bar returns are serially dependent. The skew/kurtosis terms correct for
distribution *shape*, not autocorrelation. Serial dependence overstates the effective number of
independent observations, biasing DSR **upward**. Every DSR in this document is a ceiling, not an
estimate. A borderline pass is not a pass.

**4. The 1h floor is the least trustworthy of the three.** Its p95 varies **1.86×** across block
lengths (1.47 / 2.03 / 2.72 for bl 10 / 50 / 200) against 1.21× for 4h and 1.10× for 1d, and its
bootstrap CI is the widest (0.65 wide). The 1h number is materially dependent on null design in a
way the others are not.

**5. Percentiles are not comparable across timeframes.** Each campaign uses a different bar count
and spans a different era: 12k 4h bars ≈ 8 years, 12k 1h bars ≈ 2 years, 6k 1d bars ≈ 24 years. A
1h percentile and a 1d percentile answer different questions. **Rank within a timeframe only.**

---

## 2. The null distributions

Stationary block bootstrap (Politis–Romano) on whole OHLC bars, so the intrabar geometry the
range-based strategies read (`donchian_breakout`, `opening_range_breakout`, the sweep archetypes)
survives resampling rather than being synthesised. 150 paths per timeframe = 3 block lengths × 50.
Each path runs the full unmodified 167-candidate E24→E26 loop.

Null realism was checked against real gold 4h: volatility clustering 0.18–0.27 synthetic vs 0.23
real, fat tails preserved (kurtosis 8.2–18.0 vs 14.7 real), every bar OHLC-valid.

### Pass-rate distribution — candidates clearing the legacy bar, out of 167

| tf | bars | span | winners | mean | median | max | zero-count |
|---|---|---|---|---|---|---|---|
| 1h | 12,000 | ~2y | 130/150 | 8.9 | 5 | 41 | 20 |
| 4h | 12,000 | ~8y | 137/150 | 11.0 | 4 | 63 | 13 |
| 1d | 6,000 | ~24y | 39/150 | 2.1 | 0 | 31 | 111 |

The distributions are **heavily skewed**: 4h has mean 11.0 but median 4, with one path passing 63
of 167. Most no-edge sweeps look modest; occasionally one looks spectacular.

### Selection-score quantiles, CIs, and block-length spread

| tf | p50 | p90 | **p95** | p99 | bootstrap 95% CI on p95 | bl10 | bl50 | bl200 | spread |
|---|---|---|---|---|---|---|---|---|---|
| 1h | 1.16 | 2.01 | **2.367** | 2.82 | [2.02, 2.67] | 1.47 | 2.03 | 2.72 | **1.86×** |
| 4h | 0.85 | 1.29 | **1.496** | 1.78 | [1.30, 1.67] | 1.26 | 1.52 | 1.53 | 1.21× |
| 1d | 0.46 | 0.64 | **0.663** | 0.74 | [0.60, 0.78] | 0.67 | 0.65 | 0.61 | 1.10× |

Block-length sensitivity was the open methodological worry, and for **4h and 1d it is settled** —
the null design is not driving those results. For **1h it is not settled**; see caveat 4.

### Which p95 — the denominator matters

The adopted floors are **not** the numbers in the table above. The gate is "null percentile ≥ 95",
and that percentile counts **all 150 paths**, including those where noise produced no passing
candidate at all. Those are real outcomes the override beat, so they belong in the denominator.

| tf | p95 over winners only | score at all-paths percentile 95 | adopted floor |
|---|---|---|---|
| 1h | 2.367 (= 95.3rd all-paths) | 2.336 | **2.34** |
| 4h | 1.496 (= 95.3rd all-paths) | 1.486 | **1.49** |
| 1d | 0.663 (= **98.7th** all-paths) | 0.593 | **0.59** |

On 1d the gap is decisive: only 39 of 150 daily paths produced any winner, so the winners-only p95
sits at the 98.7th all-paths percentile. **Gating on 0.663 would have rejected both overrides that
clear "null percentile ≥ 95"** — the bar would have contradicted the audit that set it.

This was also a real bug in the scorer, found and fixed before these results were produced:
`load_null` filtered the null to finite winners, understating every percentile. Measured error at
4h: 0.3–3.5pp. At 1d, where 111 of 150 paths have no winner, it would have discarded most of the
distribution.

---

## 3. The finding that motivated all of this

**The legacy bar (IS Sharpe > 0.5, 30 trades, maxDD < 25%, OOS Sharpe > 0) is cleared by pure noise
137 times out of 150 at 4h — 91%.** The median noise winner has IS Sharpe **0.93**, nearly double
the threshold it is supposed to clear.

A sweep reporting "11 candidates passed validation" is reporting approximately the false-positive
rate, not evidence of edge.

**And the noise pass rate is strongly timeframe-dependent** — 4h averages 11.0 of 167, 1h 8.9, 1d
only 2.1 (median 0). One global bar was therefore **far stricter on 1d than on 4h without anyone
having chosen that**. That asymmetry, not just the absolute level, is why the replacement is
timeframe-aware.

---

## 4. Why DSR is a diagnostic and not a gate

DSR is computed on **IS Sharpe alone**, while the selection score is **min(IS, OOS)**. DSR therefore
cannot see in-sample to out-of-sample decay — which is precisely what the selection score exists to
catch. On the live book the two rank almost inversely:

| override | IS SR | OOS SR | sel | DSR | null %tile | what each says |
|---|---|---|---|---|---|---|
| `ETH-USD_1h` | 3.18 | 0.42 | 0.42 | **0.878** (best in book) | **16.7** | DSR: strong. Null: worse than 83% of noise. |
| `INFY.NS_1d` | 0.64 | 0.77 | 0.64 | **0.009** (near-worst) | **97.3** | DSR: worthless. Null: beats 97% of noise. |

`ETH-USD_1h` collapses 3.18 → 0.42 out of sample. DSR rewards the in-sample number and never sees
the collapse; the percentile does.

**AND-gating two statistics that disagree this violently rejected all 45 overrides.** A bar that
rejects 100% carries no information: it cannot distinguish a bad book from a bad bar. Max DSR
across the entire book is **0.8777**, and **zero** overrides reach 0.90 — so a 0.95 DSR gate is not
a filter, it is a rejection.

DSR is retained as a reported diagnostic on every row and in every override's `stage0` block.

---

## 5. Cost of each threshold set

Evaluated against all 45 live overrides, rescored on 12,000 bars.

| threshold set | definition | 1h | 4h | 1d | total |
|---|---|---|---|---|---|
| legacy | IS SR>0.5, 30 trades | 15/16 | 19/19 | 10/10 | **44/45** |
| "moderate" (rejected) | winners-p90 floor, DSR≥0.90, 60 trades | 0/16 | 0/19 | 0/10 | **0/45** |
| "strict" (rejected) | winners-p95 floor, DSR≥0.95, 100 trades | 0/16 | 0/19 | 0/10 | **0/45** |
| **adopted** | **all-paths p95 floor, 60 trades, DSR reported** | 0/16 | 0/19 | **2/10** | **2/45** |

### Per-criterion attribution for the rejected "strict" set

| tf | n | fail trades ≥100 | fail DSR ≥0.95 | fail score |
|---|---|---|---|---|
| 1h | 16 | 6 | **16** | 16 |
| 4h | 19 | 12 | **19** | 18 |
| 1d | 10 | 6 | **10** | 9 |

DSR is the binding constraint in every timeframe — it eliminates the entire book on its own. That
is what disqualified it as a gate.

### Trade-count distribution (rescored at 12k bars)

min **28**, p25 47, median 87, p75 154, max 356.

| floor | pass/45 | Sharpe SE at n (SR=1.0, IID — a *lower* bound) |
|---|---|---|
| ≥ 30 | 44/45 | 0.224 |
| ≥ 60 | 31/45 | 0.158 |
| ≥ 100 | 21/45 | 0.122 |
| ≥ 150 | 12/45 | 0.100 |

Note one override now falls *below* the legacy 30-trade bar at 28 trades on rescoring.

---

## 6. The adopted bar

Implemented in `engines/e26_backtesting/engine.py` as `STAGE0_TIMEFRAME_THRESHOLDS`:

| timeframe | min selection score = min(IS, OOS) | min trades | DSR |
|---|---|---|---|
| 1h | 2.34 | 60 | reported only |
| 4h | 1.49 | 60 | reported only |
| 1d | 0.59 | 60 | reported only |

Max drawdown < 25% is retained (it gates a different failure mode). The selection-score floor
subsumes the legacy Sharpe conditions: `min(IS, OOS) ≥ floor` forces both above it, and every floor
exceeds the old 0.5/0.0 pair.

`run_backtest(..., timeframe=...)` selects the Stage 0 bar. **Default `None` keeps the legacy bar**,
so the eight existing callers that pass no timeframe are unaffected — and, deliberately, so are
`research/synthetic_null.py` and `research/score_overrides_stage0.py`, whose artifacts characterise
the *old* bar's false-positive rate. That measurement is the evidence justifying the replacement;
silently upgrading it would destroy the baseline it exists to record.

**A note on self-consistency:** the floors are calibrated from a null measured under the legacy bar.
This is sound at the tail — the *best* score a path achieves does not depend on where the pass bar
sits, provided the bar does not exclude the best scorer, and the new floor is by construction the
95th percentile of that best-score distribution. Paths whose best fell below the floor simply have
no winner under the new bar. The upper tail, which is what p95 measures, is unchanged.

---

## 7. The full 45-override table

`sel` = min(IS, OOS) = the selection score the bar is applied to.
`DSR*` = **reported diagnostic, not a gate** (see §4); optimistic, serial dependence uncorrected.
`null source` marks whether the null is that asset's own or a **cross-asset proxy**.
Percentiles are **not comparable between the three blocks below**.

#### 1h overrides (16) - floor 2.34, null GC=F 1h, 150 paths

| override | strategy | IS SR | OOS SR | sel | trades | N_eff | DSR* | null %tile | null source | Stage 0 |
|---|---|---|---|---|---|---|---|---|---|---|
| NVDA_1h | regime_adaptive | 1.48 | 1.55 | 1.48 | 356 | 14.6 | 0.000 | 78.7 | GC=F 1h proxy | UNVALIDATED |
| INFY.NS_1h | donchian_breakout | 1.44 | 0.92 | 0.92 | 82 | 12.3 | 0.218 | 40.0 | GC=F 1h proxy | UNVALIDATED |
| MES=F_1h | freqtrade_rsi_tema_bb | 0.95 | 0.79 | 0.79 | 33 | 13.9 | 0.056 | 32.7 | GC=F 1h proxy | UNVALIDATED |
| ITC.NS_1h | liquidity_sweep_reversal_trend_filtered | 0.69 | 0.96 | 0.69 | 61 | 13.7 | 0.050 | 27.3 | GC=F 1h proxy | UNVALIDATED |
| GC=F_1h | donchian_breakout | 0.44 | 1.74 | 0.44 | 257 | 13.7 | 0.013 | 17.3 | GC=F 1h OWN | UNVALIDATED |
| AAPL_1h | donchian_breakout | 0.33 | 5.93 | 0.33 | 223 | 9.2 | 0.093 | 16.7 | GC=F 1h proxy | UNVALIDATED |
| ETH-USD_1h | dual_thrust | 3.18 | 0.42 | 0.42 | 112 | 12.8 | 0.878 | 16.7 | GC=F 1h proxy | UNVALIDATED |
| BTC-USD_1h | freqtrade_rsi_tema_bb | 0.26 | 1.54 | 0.26 | 32 | 13.4 | 0.077 | 16.0 | GC=F 1h proxy | UNVALIDATED |
| SI=F_1h | freqtrade_rsi_tema_bb | 2.56 | 0.18 | 0.18 | 28 | 12.2 | 0.743 | 16.0 | GC=F 1h proxy | UNVALIDATED |
| AMZN_1h | rsi_mean_reversion | 0.52 | -4.95 | -4.95 | 196 | 5.5 | 0.257 | 13.3 | GC=F 1h proxy | UNVALIDATED |
| EURUSD=X_1h | rsi_mean_reversion_trend_filtered | -2.50 | -2.37 | -2.50 | 88 | 15.5 | 0.000 | 13.3 | GC=F 1h proxy | UNVALIDATED |
| HDFCBANK.NS_1h | donchian_breakout | 1.51 | -0.38 | -0.38 | 128 | 12.6 | 0.363 | 13.3 | GC=F 1h proxy | UNVALIDATED |
| META_1h | rsi_mean_reversion | 0.91 | -7.62 | -7.62 | 134 | 11.8 | 0.199 | 13.3 | GC=F 1h proxy | UNVALIDATED |
| MSFT_1h | liquidity_sweep_reversal_trend_filtered | 0.68 | -0.65 | -0.65 | 181 | 14.2 | 0.152 | 13.3 | GC=F 1h proxy | UNVALIDATED |
| SBIN.NS_1h | donchian_breakout | 0.64 | -0.25 | -0.25 | 110 | 11.8 | 0.268 | 13.3 | GC=F 1h proxy | UNVALIDATED |
| USDJPY=X_1h | dual_thrust | -2.63 | -0.41 | -2.63 | 256 | 15.1 | 0.000 | 13.3 | GC=F 1h proxy | UNVALIDATED |

#### 4h overrides (19) - floor 1.49, null GC=F 4h, 150 paths

| override | strategy | IS SR | OOS SR | sel | trades | N_eff | DSR* | null %tile | null source | Stage 0 |
|---|---|---|---|---|---|---|---|---|---|---|
| GOOGL_4h | liquidity_sweep_reversal_trend_filtered | 1.84 | 1.54 | 1.54 | 44 | 8.7 | 0.626 | 96.0 | GC=F 4h proxy | UNVALIDATED |
| META_4h | donchian_breakout | 1.28 | 2.01 | 1.28 | 47 | 9.5 | 0.429 | 90.7 | GC=F 4h proxy | UNVALIDATED |
| ICICIBANK.NS_4h | liquidity_sweep_reversal | 2.53 | 1.21 | 1.21 | 61 | 13.3 | 0.664 | 84.7 | GC=F 4h proxy | UNVALIDATED |
| ^NSEI_4h | liquidity_sweep_reversal | 2.29 | 1.17 | 1.17 | 83 | 11.0 | 0.670 | 82.7 | GC=F 4h proxy | UNVALIDATED |
| INFY.NS_4h | donchian_breakout | 1.10 | 0.93 | 0.93 | 42 | 12.2 | 0.356 | 68.0 | GC=F 4h proxy | UNVALIDATED |
| HDFCBANK.NS_4h | regime_adaptive | 0.87 | 1.30 | 0.87 | 76 | 13.5 | 0.231 | 60.7 | GC=F 4h proxy | UNVALIDATED |
| RELIANCE.NS_4h | liquidity_sweep_reversal_trend_filtered | 0.79 | 5.10 | 0.79 | 33 | 11.4 | 0.257 | 50.7 | GC=F 4h proxy | UNVALIDATED |
| BHARTIARTL.NS_4h | liquidity_sweep_reversal | 0.76 | 1.25 | 0.76 | 58 | 13.0 | 0.206 | 45.3 | GC=F 4h proxy | UNVALIDATED |
| TSLA_4h | rsi_mean_reversion | 0.76 | 1.15 | 0.76 | 58 | 7.2 | 0.437 | 44.7 | GC=F 4h proxy | UNVALIDATED |
| AMZN_4h | rsi_mean_reversion | 0.73 | 0.82 | 0.73 | 37 | 7.4 | 0.278 | 40.7 | GC=F 4h proxy | UNVALIDATED |
| BTC-USD_4h | dual_thrust | 0.59 | 0.41 | 0.41 | 244 | 12.1 | 0.275 | 15.3 | GC=F 4h proxy | UNVALIDATED |
| ETH-USD_4h | trend_pullback_atr_trail | 0.29 | 1.96 | 0.29 | 199 | 11.3 | 0.141 | 12.7 | GC=F 4h proxy | UNVALIDATED |
| AAPL_4h | rsi_mean_reversion | 0.24 | 1.74 | 0.24 | 69 | 5.6 | 0.234 | 10.7 | GC=F 4h proxy | UNVALIDATED |
| EURUSD=X_4h | rsi_mean_reversion_trend_filtered | -0.73 | -0.27 | -0.73 | 113 | 14.1 | 0.000 | 8.7 | GC=F 4h proxy | UNVALIDATED |
| GBPUSD=X_4h | wyckoff_spring_reversal | -1.43 | 0.19 | -1.43 | 67 | 14.4 | 0.000 | 8.7 | GC=F 4h proxy | UNVALIDATED |
| GC=F_4h | trend_pullback_atr_trail | -0.80 | 0.30 | -0.80 | 282 | 12.2 | 0.000 | 8.7 | GC=F 4h OWN | UNVALIDATED |
| NVDA_4h | donchian_breakout | -0.01 | -0.13 | -0.13 | 114 | 8.8 | 0.259 | 8.7 | GC=F 4h proxy | UNVALIDATED |
| SI=F_4h | donchian_breakout | 0.00 | 0.42 | 0.00 | 321 | 11.2 | 0.025 | 8.7 | GC=F 4h proxy | UNVALIDATED |
| USDJPY=X_4h | rsi_mean_reversion_trend_filtered | -0.49 | 0.08 | -0.49 | 136 | 13.0 | 0.000 | 8.7 | GC=F 4h proxy | UNVALIDATED |

#### 1d overrides (10) - floor 0.59, null GC=F 1d, 150 paths

| override | strategy | IS SR | OOS SR | sel | trades | N_eff | DSR* | null %tile | null source | Stage 0 |
|---|---|---|---|---|---|---|---|---|---|---|
| ETH-USD_1d | dual_thrust | 0.67 | 1.00 | 0.67 | 41 | 7.6 | 0.187 | 98.7 | GC=F 1d proxy | UNVALIDATED |
| BTC-USD_1d | dual_thrust | 0.92 | 0.64 | 0.64 | 87 | 9.6 | 0.564 | 97.3 | GC=F 1d proxy | **VALIDATED** |
| INFY.NS_1d | donchian_breakout | 0.64 | 0.77 | 0.64 | 110 | 13.2 | 0.009 | 97.3 | GC=F 1d proxy | **VALIDATED** |
| TSLA_1d | macd_cross | 0.58 | 0.89 | 0.58 | 136 | 9.5 | 0.249 | 94.0 | GC=F 1d proxy | UNVALIDATED |
| AAPL_1d | donchian_breakout | 0.58 | 0.92 | 0.58 | 154 | 14.1 | 0.211 | 93.3 | GC=F 1d proxy | UNVALIDATED |
| GBPUSD=X_1d | rsi_mean_reversion | 0.52 | 0.69 | 0.52 | 30 | 12.8 | 0.592 | 90.7 | GC=F 1d proxy | UNVALIDATED |
| NVDA_1d | donchian_breakout | 0.68 | 0.30 | 0.30 | 33 | 12.5 | 0.482 | 78.7 | GC=F 1d proxy | UNVALIDATED |
| HDFCBANK.NS_1d | rsi_mean_reversion | 0.62 | 0.25 | 0.25 | 63 | 13.6 | 0.620 | 78.0 | GC=F 1d proxy | UNVALIDATED |
| EURUSD=X_1d | trend_pullback_atr_trail | 0.28 | -0.03 | -0.03 | 40 | 12.7 | 0.230 | 74.0 | GC=F 1d proxy | UNVALIDATED |
| USDJPY=X_1d | donchian_breakout | 0.36 | -0.11 | -0.11 | 259 | 11.4 | 0.229 | 74.0 | GC=F 1d proxy | UNVALIDATED |
---

## 8. Enforcement — reversible by construction

**Nothing was deleted and nothing was auto-demoted.**

1. **Tagging.** `scripts/apply_stage0_tags.py` adds a `stage0` block to each override JSON,
   alongside the existing keys — none reordered, none altered (verified: all 45 files compared
   field-by-field against `HEAD`, zero mismatches). The block records the verdict, the bar, every
   measured input, the DSR diagnostic, the failure reasons, and the caveats.

2. **Skipping.** `engines/e51_signals/engine.py::_load_strategy_override` returns `None` for any
   override tagged `UNVALIDATED`, so the asset falls back to the **baseline composite rule** — the
   same path an asset with no override takes.

3. **Logging.** Every suppressed override emits a `STAGE 0 SKIP` warning naming the symbol,
   timeframe, strategy, measured percentile, trade count, and reason. Deduped per process, not per
   call: every *distinct* override that stopped firing is reported, without a scan loop burying
   that signal under thousands of repeats. `stage0_skipped_overrides()` exposes the registry for
   auditing.

Reversal: delete the `stage0` block, or `git checkout` the override files. The tag is data, not
code.

**Why tag rather than delete:** a tag is reversible and shows up in a diff. A demotion that removed
43 of 45 overrides would be indistinguishable from a bug that ate them.

### What stopped firing

**43 of 45 overrides tagged UNVALIDATED** — 1h 16/16, 4h 19/19, 1d 8/10.

Failure attribution among the 43: 29 fail the percentile only, 2 fail the trade floor only, 12 fail
both.

**The 2 survivors, both 1d:**

| override | strategy | sel | trades | null %tile | DSR* |
|---|---|---|---|---|---|
| `BTC-USD_1d` | dual_thrust | 0.64 | 87 | 97.3 | 0.564 |
| `INFY.NS_1d` | donchian_breakout | 0.64 | 110 | 97.3 | 0.009 |

Both clear the bar on the percentile, and `INFY.NS_1d` does so with a near-zero DSR — the clearest
illustration of why the two statistics could not be AND-gated.

**The practical consequence:** 43 assets revert to the baseline composite rule. That rule found zero
validated configs for 10 of 11 tested assets during its own training, which is why the overrides
were built in the first place. So this is not a quiet improvement — **it removes structural rules
from 43 assets and leaves them on a rule already known to be weak.** The justification is narrow and
should be stated plainly: a rule indistinguishable from noise is worse than a weak rule, because it
carries unearned confidence.

---

## 9. Resume here — what was left undone

**Not done, ordered by how much it would change the conclusions.**

1. **Per-asset nulls.** Campaigns were run on `GC=F` only; 43 of 45 rows use gold as a cross-asset
   proxy. Any override whose verdict sits near the boundary deserves its own null before the verdict
   is trusted. Cost: ~1 hour per (symbol, timeframe) at 6 workers.

2. **Re-measure the null under the new bar.** The recorded campaigns measure the *legacy* bar's
   false-positive rate. The tail argument in §6 says the floors remain valid, but the pass-rate
   distribution under the new bar is unmeasured — and that is the number to quote when asking "how
   often does the new bar admit noise?"

3. **Calibrate the trade floor.** Requires a null variant recording per-candidate trade counts. Until
   then 60 is convention wearing a measured bar's clothing.

4. **A serial-dependence correction for DSR.** Newey-West or a block-bootstrap SE on the Sharpe
   would remove caveat 3. Until then DSR is a ceiling.

5. **1h floor stability.** 1.86× block-length spread. Either more block lengths, or an explicit
   decision to use the most conservative (bl200 → 2.72) rather than the pooled p95.

6. **The 1d null is thin.** Only 39 of 150 paths produced any winner, so the 1d p95 rests on 39
   observations — and both surviving overrides are 1d. This is the weakest evidence supporting the
   only two overrides still firing.

7. **DSR is never surfaced in E26's own gate output** beyond `parameters["selection_score"]` and
   `parameters["gate_applied"]`. Wiring `deflated_sharpe.py` into `run_backtest` as a reported field
   would put the diagnostic where promotions happen rather than only in the offline scorer.

8. **Untouched from earlier work:** the six dashboard bugs (scan timer race, signal click-through,
   funding-account autofill, market-hours filtering, scan speed, progress visibility); the
   forward-test logger for live signal validation; the 10 unresolved YouTube handles
   (`AdamHGrimes`, `hudsonthames`, `ProjectFinance`, `LynAldenInvestment`, `UnchainedPodcast`,
   `RaoulPal`, `AlexKruger`, `ManGroupPlc`, `twosigma`, `algotrading101`); and the YouTube tier-1
   scrape, still blocked by the IP rate limit.

---

## 10. Reproducing this

```bash
# null campaigns (~1h each at 6 workers; run sequentially, never concurrently)
python research/synthetic_null.py --symbol "GC=F" --timeframe 4h --paths 50 --bars 12000 --workers 6
RUN_NULL_CHAIN=1 python scripts/run_null_chain.py          # 1h then 1d

# score every live override against the nulls (report-only, writes nothing to the override dir)
python research/score_overrides_stage0.py --bars 12000 --workers 6

# apply the verdicts (idempotent; --dry-run to preview)
python scripts/apply_stage0_tags.py --dry-run
python scripts/apply_stage0_tags.py
```

**Run campaigns strictly sequentially.** During this work a background sweep left running while
timing paths made a 1.578s candidate measure at 164s — a 100× artifact that nearly triggered a hunt
for an imaginary O(n²) pathology. `scripts/run_null_chain.py` enforces sequential execution and is
opt-in behind `RUN_NULL_CHAIN=1` for that reason.
