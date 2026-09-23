# PHASE 1 Research Audit — existing system vs. `reports/statergy.txt`

**Date:** 2026-09-14 · **Method:** direct inspection of the working tree, plus live
execution of every registered strategy against real `data/processed/` bars. Where a
claim below is measured, the measurement is stated. Where it is inferred, it says so.

`statergy.txt` PHASE 1 requires inspecting the whole project and deciding what to
**reuse** before building anything, and its opening constraint is explicit: *"Do NOT
create new folders/files unnecessarily. Use and upgrade the existing project
architecture whenever possible."* This audit exists to make that decision on evidence
rather than assumption — the headline finding is that **most of what the prompt asks
for already exists**, and the genuinely missing pieces are narrower than expected.

---

## 1. What exists (measured, not assumed)

| Component | Where | State |
|---|---|---|
| Data pipeline | E02 + E40 | 29 instruments × 8 timeframes, 241 parquet files, fallback chain, quality repair |
| Indicators | E07 | EMA/RSI/MACD/ADX/ATR/Bollinger/VWAP/Stoch/CCI/OBV/MFI/Supertrend/Ichimoku |
| Strategy factory | E24 | **236 archetypes, 830 grid candidates** |
| Backtester | E26 | Real costs: 0.1% commission + 0.05% slippage per side, applied entry and exit |
| IS/OOS + walk-forward | E26, E27 | Present |
| Robustness | E26 | `block_bootstrap.py`, Monte Carlo sequencing, MC ruin, parameter sensitivity, 2× cost stress |
| Overfitting detection | E26 | **`pbo.py` — Probability of Backtest Overfitting via CSCV** (Bailey, Borwein, López de Prado & Zhu 2017); `deflated_sharpe.py`; `research/synthetic_null.py` |
| Metrics | E35, `tearsheet.py` | Sharpe/Sortino/Calmar/PF/expectancy/DD/recovery/CVaR |
| Regime engine | E08 | Rule-based ADX/ATR/VIX + 2-state Gaussian HMM + ruptures changepoint |
| Cross-asset | E10 | 10 pairs, calibrated baselines, IC-tested |
| ML | E26 `meta_labeling.py`, E09, E12 | Triple-barrier labeling + secondary meta-model |
| Portfolio / capital | E31, E32, E79 | Construction, allocation, simulation |
| Risk | E45 | Veto authority, kill switch, trailing-drawdown zones, risk-of-ruin, Kelly |
| Governance | E47, E48 | Rule-5 enforcement, tested |
| Tests | `tests/unit` | **1,411 passing** |

**Assessment:** PHASES 2, 5, 6, 7, 8, 9, 10, 13, 14, 15, 16, 17, 18 are substantially
built. `statergy.txt` PHASE 9 asks for overfitting detection "using appropriate
statistical validation" — this project already has three independent layers of it
(PBO/CSCV, deflated Sharpe, and a synthetic no-edge null), which is more than the
prompt asks for.

---

## 2. What is genuinely missing

| Phase | Missing | Evidence |
|---|---|---|
| **3** | **Per-instrument research profiles** | No profile module and no profile artifacts exist. Grep for `instrument_profile`/`asset_profile`/`research_profile` returns nothing; `data/models/e24_strategy_research/` holds no profile files. |
| **11** | **A+ composite score + S/A+/A/B/C/D/F grades** | No grading module. |
| **19** | **Research leaderboard** | Grep for `leaderboard` across `engines/`, `research/`, `scripts/` returns nothing. |
| **20** | **Continuous research engine / backlog** | No backlog artifact, no "what has not been tested" mechanism. |
| NON-NEG #14 | **Forward / paper-trade record** | No forward-test log, no populated trades table. Nothing has ever been validated in real time. |
| 7.3 | **CPCV with purge + embargo** | `pbo.py` implements CSCV (related but a different question); no purge/embargo splitter. `docs/PROJECT_AUDIT.md` records this as still open. |

PHASE 3 is the most consequential absence. `statergy.txt` is emphatic — *"Do NOT use
one universal strategy for every market"* and *"Do NOT force a strategy onto an
instrument simply because it performs well elsewhere"* — yet the platform currently
searches one shared 830-candidate grid across all 29 instruments with no per-asset
characterisation of volatility, trend persistence, mean-reversion tendency, session
behaviour or cost structure to inform which families are even appropriate.

---

## 3. A measured problem the prompt names directly

PHASE 9 lists **"multiple-comparison problems"** as an overfitting symptom to detect.
This platform has a live, quantified instance:

- Stage 0's synthetic nulls were calibrated at **167 candidates per path**
  (`research/synthetic_null_GCF_*.json` → `candidates_per_path`).
- The default grid is now **830 candidates**.

The null answers "what is the best score a *167*-candidate grid manufactures from pure
noise". Judging an 830-candidate search against it makes the bar **systematically too
lenient** — more draws, higher expected maximum, same threshold. Resampling the
existing null data put the correction at roughly **+21–32%** on the floors.

Two of the strategies currently tagged VALIDATED and driving live signals
(`BTC-USD_1d`, `ETH-USD_1d`) were passed by that under-calibrated bar. `ETH-USD_1d`
clears comfortably either way (null percentile 100.0, DSR 0.961); `BTC-USD_1d` does
not survive the corrected floor (selection score 0.654 vs ~0.782 required) and its own
scorer verdict is `LIKELY NOISE`.

**This is the single highest-value fix available**, because it changes the verdict on
what is already live. The correct remedy is re-running the null campaigns at the
current grid size — not adjusting thresholds by hand.

---

## 4. Reuse decisions (PHASE 1 items 3–5)

**Reuse, do not rebuild:** E26's backtester, cost model, PBO, deflated Sharpe,
block bootstrap; E24's parallel search; E07's indicators (its RSI is Cutler's, and its
own docstring warns every validated parameter was fitted against that definition —
recomputing with a different convention would silently invalidate the book); E08
regime; E45 risk; the Stage 0 tagging pipeline.

**Extend, do not duplicate:** the A+ score and leaderboard should read E26/E35 metrics
that already exist rather than recomputing them; instrument profiles should be built
from `data/processed/` parquet already on disk.

**Do not build:** a second backtester, a second metrics layer, a second regime engine,
or any new top-level folder.

---

## 5. Proposed next cycle, in priority order

1. **Re-run the null campaigns at 830 candidates** (~1 hr per timeframe × 3). Directly
   determines whether the two live strategies deserve to be live. Nothing else changes
   a live decision.
2. **PHASE 3 — instrument profiles.** Build one profile per instrument from existing
   parquet: realised volatility, ATR percentile, trend persistence (Hurst / ADX
   distribution), mean-reversion tendency (variance ratio), session/time-of-day
   behaviour, gap behaviour, cost-to-ATR ratio. Feeds strategy-family selection.
3. **PHASE 11 + 19 — A+ score and leaderboard.** Composite score over metrics already
   computed, with strict grades, surfaced as one ranked table. Makes every existing
   validation layer legible in one place.
4. **Forward-test logger** (NON-NEGOTIABLE #14). Log every live signal with entry/stop/
   target and timestamp, score against realised outcome. Converts "97th percentile
   against a proxy null" into an actual track record.
5. **CPCV with purge/embargo** — genuine gap, but statistically subtle and lower value
   than items 1–4 given PBO already covers adjacent ground.

---

## 6. Facts vs. assumptions

Per `statergy.txt`'s closing requirement to distinguish evidence classes:

- **FACT (measured):** 236 archetypes, 830 candidates, 1,411 tests passing; nulls
  calibrated at 167 candidates; `BTC-USD_1d` selection score 0.654, `ETH-USD_1d` 1.096.
- **FACT (measured):** 29/29 INTRADAY strategies produce trades after the indicator
  adapter fix; 0/29 did before.
- **STATISTICAL EVIDENCE:** 43 of 45 overrides score `LIKELY NOISE` against the
  synthetic null; gold at the 10th–64th percentile against *its own* null.
- **ASSUMPTION (not yet tested):** that the +21–32% floor correction estimated by
  resampling the existing null generalises to a true 830-candidate campaign. Item 1
  above replaces this assumption with a measurement.
- **UNCERTAINTY:** no forward-test data exists, so no out-of-sample-in-time evidence
  supports any strategy currently live.
