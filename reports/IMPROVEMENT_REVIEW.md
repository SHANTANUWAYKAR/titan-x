# Improvement Review

Generated: 2026-09-19T15:40:56.649823+00:00

PHASE 23 of `reports/upgrade statergy.txt`: diagnose, hypothesise, modify ONE variable, test out of sample, accept or reject — run against the strategies that are currently live.

**Nothing here is deployed.** These are proposals for a human to approve or ignore. Going live still requires a deliberate Stage 0 tag, which this loop cannot write (PHASE 33; non-negotiable 20).

**Read the trial count before the result.** This loop is itself a search: best-of-N climbs on noise alone, so a variant that wins after 30 trials is a much weaker claim than one that wins after 3. That is the failure mode that makes most self-tuning trading agents lose money — they improve their way into fitting noise, and report only the winner.

## BTC-USD 1d — `dual_thrust`

**Diagnosis.** below the Stage 0 bar: selection 0.5887 < 0.59 (short by 0.0013)

Incumbent selection score **0.5887** against a bar of 0.59 (margin -0.0013).

**Trials consumed: 3** · accepted 0 · rejected 3

### No proposal

No single-variable change improved the selection score without costing out-of-sample performance. **This is a real result, not a failed run** — it says the incumbent parameterisation is already the best of those tested, and that the strategy's problem is not its parameters.

### Rejected (kept — non-negotiables 8 and 9)

| Change | Selection | OOS Sharpe | Why rejected |
|---|---|---|---|
| `lookback: 10 -> 4` | -0.0505 | -0.050 | REJECTED: out-of-sample Sharpe fell 0.589 -> -0.050. An in-sample improvement bought with an out-of-sample loss is overfitting, not progress |
| `lookback: 10 -> 6` | 0.4175 | 0.418 | REJECTED: out-of-sample Sharpe fell 0.589 -> 0.418. An in-sample improvement bought with an out-of-sample loss is overfitting, not progress |
| `lookback: 10 -> 8` | 0.5438 | 0.544 | REJECTED: out-of-sample Sharpe fell 0.589 -> 0.544. An in-sample improvement bought with an out-of-sample loss is overfitting, not progress |

### Caveats

- 3 variant(s) were tried. Best-of-3 on noise alone climbs with the trial count, so this proposal is only as strong as that number is small.
- Accepting a proposal here changes NOTHING that trades. Going live requires a separate, deliberate Stage 0 tag; this loop cannot write one.

Recorded as experiment `robustness-20260919T154054-3d27da`.

---

## ETH-USD 1d — `mss_trend_hold`

**Diagnosis.** no failure identified

Incumbent selection score **1.0457** against a bar of 0.59 (margin +0.4557).

**Trials consumed: 5** · accepted 0 · rejected 5

### No proposal

No single-variable change improved the selection score without costing out-of-sample performance. **This is a real result, not a failed run** — it says the incumbent parameterisation is already the best of those tested, and that the strategy's problem is not its parameters.

### Rejected (kept — non-negotiables 8 and 9)

| Change | Selection | OOS Sharpe | Why rejected |
|---|---|---|---|
| `atr_mult: 1.0 -> 1.5` | 0.8286 | 0.829 | REJECTED: out-of-sample Sharpe fell 1.046 -> 0.829. An in-sample improvement bought with an out-of-sample loss is overfitting, not progress |
| `atr_mult: 1.0 -> 2.0` | 0.9533 | 0.998 | REJECTED: out-of-sample Sharpe fell 1.046 -> 0.998. An in-sample improvement bought with an out-of-sample loss is overfitting, not progress |
| `hold_bars: 5 -> 10` | 0.5701 | 0.570 | REJECTED: out-of-sample Sharpe fell 1.046 -> 0.570. An in-sample improvement bought with an out-of-sample loss is overfitting, not progress |
| `hold_bars: 5 -> 15` | 0.7130 | 0.713 | REJECTED: out-of-sample Sharpe fell 1.046 -> 0.713. An in-sample improvement bought with an out-of-sample loss is overfitting, not progress |
| `hold_bars: 5 -> 20` | 1.0387 | 1.039 | REJECTED: out-of-sample Sharpe fell 1.046 -> 1.039. An in-sample improvement bought with an out-of-sample loss is overfitting, not progress |

### Caveats

- 5 variant(s) were tried. Best-of-5 on noise alone climbs with the trial count, so this proposal is only as strong as that number is small.
- Accepting a proposal here changes NOTHING that trades. Going live requires a separate, deliberate Stage 0 tag; this loop cannot write one.

Recorded as experiment `robustness-20260919T154055-646a75`.

---
