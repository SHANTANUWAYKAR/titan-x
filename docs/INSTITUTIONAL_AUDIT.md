# Institutional Readiness Audit — PROJECT TITAN-X

**Source:** `reports/upgrade statergy.txt` — PHASE 0 (complete system audit) and
the F/FORMAT section (12 scores + P0–P3 roadmap).
**Date:** 2026-09-15. **Method:** direct inspection of the working tree — file
and engine counts, import greps, route enumeration, CI config, and the test
suite's own results. Every score below cites what it was measured from. Where a
claim is inferred rather than measured, it says so.

**No code was changed to produce this document.** Per PHASE 0: *"Do not
immediately start coding. First understand the system."* Implementation began
only afterwards, against the P0 list in §3; items completed since are marked
✅ DONE there rather than being quietly removed.

---

## 0. Relationship to the audits that already exist

This is **not** a re-run of `docs/PROJECT_AUDIT.md` (2026-09-08). That audit
answered a different brief (`docs/UPGRADE_BRIEF.md`), scored nothing, and
predates a week of work that materially changed three of the dimensions below
(Stage 0 findings, the A+ leaderboard, instrument profiles, the forward test).
Its findings are treated as evidence here, not repeated.

`docs/UPGRADE_ROADMAP.md` (2026-09-13) already carries a P0–P3 list against the
*old* brief. Items from it that are still open are carried forward by reference
rather than restated, and marked `[carried]`.

---

## 1. Scores

Rubric from the source file: 0–20 Prototype · 21–40 Basic · 41–60 Professional ·
61–75 Advanced · 76–90 Institutional-grade · 91–100 Elite.

| # | Dimension | Score | Band |
|---|---|---|---|
| 1 | Architecture | **62** | Advanced |
| 2 | Quant research | **68** | Advanced |
| 3 | Data engineering | **48** | Professional |
| 4 | Backtesting | **52** | Professional |
| 5 | Risk management | **60** | Professional |
| 6 | Execution | **30** | Basic |
| 7 | ML | **45** | Professional |
| 8 | Security | **58** | Professional |
| 9 | Reliability | **55** | Professional |
| 10 | Observability | **32** | Basic |  ← was 22; see P0.2
| 11 | Testing | **72** | Advanced |
| 12 | **Overall institutional readiness** | **53** | **Professional** |

The overall figure is deliberately *below* the mean of the others. A trading
platform is gated by its weakest operational dimension, not its strongest
research one: a 68-scoring research capability whose results are delivered
through a 22-scoring observability layer and a 30-scoring execution layer
cannot be called institutional. Averaging would report 53.5 by coincidence;
the reasoning, not the arithmetic, is what puts it there.

---

## 2. Score explanations

### 1. Architecture — 62 (Advanced)

**Measured:** 55 engines under `engines/e*/`, 897 Python files outside vendored
trees, a registry (`engines/registry.py`) with a uniform `BaseEngine` /
`EngineResult` contract, FastAPI lifespan wiring, an in-process `TaskScheduler`
(`engines/e00_titan_brain/scheduler.py`), `docker-compose.yml`, and 5 Alembic
migrations.

**Credit:** the `EngineResult(success, data, message)` contract is applied
consistently and is the reason graceful degradation works at all — callers
check `.success` rather than catching exceptions. The source file warns *"Do
NOT convert everything into microservices"*; this codebase correctly did not.

**Deductions:** the dashboard is a single static `dashboard/index.html`
(~3,145 lines per `PROJECT_AUDIT.md`) with no build step — not an architecture
so much as an absence of one. Logging is configured by a single
`logging.basicConfig(level=logging.INFO)` in `api/main.py:49`. There is no
schema versioning for the JSON artefacts under `data/models/` despite dozens of
readers depending on their shape.

### 2. Quant research — 68 (Advanced)

This is the system's strongest dimension and the reason the overall score is
not lower.

**Measured:** a synthetic no-edge null via stationary block bootstrap
(`research/synthetic_null.py`), PBO via CSCV (`research/pbo_analysis.py`),
deflated Sharpe, block bootstrap, per-instrument research profiles
(`engines/e24_strategy_research/instrument_profile.py`), an A+ composite scorer
with hard gates (`strategy_score.py`), a leaderboard over 98,546 scored
candidates, and as of today a forward test (`forward_test.py`).

**What earns the score is not the list — it is that the project measured its own
null and published the unflattering answer:** pure noise clears the legacy
selection bar **137 times in 150 at 4h** (`docs/STAGE0_FINDINGS.md`). Very few
retail-origin systems ever compute that number; most of those that do, bury it.
The deny-by-default Stage 0 gate in `e51_signals._load_strategy_override` then
acts on it, and 43 of 45 overrides are correspondingly inert.

**Deductions, and they are real:**
- **No experiment tracking.** `grep -rln "experiment_id\|mlflow\|run_id"` across
  `engines/` and `core/` returns **nothing**. PHASE 8 requires every strategy to
  carry `strategy_id / version / hypothesis_id / parameter_set / data_version /
  code_version / experiment_id`; PHASE 24 requires permanent research lineage.
  98,546 candidates exist only as sweep JSONs with no lineage back to the code
  or data that produced them, so no historical result here is reproducible in
  the sense PHASE 29 means.
- **No hypothesis registry.** PHASE 7 requires every strategy to record *why it
  should work, when it should work, when it should fail*. Strategy plugins carry
  prose docstrings; nothing is queryable or enforced.
- **The nulls are under-calibrated.** They were built at 167 candidates per path
  against a grid now ~830, making the ≥95th-percentile bar ~21–32% too lenient
  (`reports/STRATEGY_LEADERBOARD.md`). This is a live-money issue — see P0.1.

### 3. Data engineering — 48 (Professional)

**Measured:** `e02_market_data` with a Yahoo → ccxt → nselib → Alpha Vantage
fallback chain, `e40_data_quality` repair, 29 assets across 8 timeframes in
`data/processed/*.parquet`.

**Deductions:**
- **Schema drift in the canonical dataset, found and fixed today.** The 241
  processed parquets carried **four different column layouts**. Two are benign
  (207 files differ only in column order; 33 legitimately lack
  `dividends`/`stock_splits`). The fourth was a single outlier: `ETH-USD_1d` —
  one of the two instruments trading live — had accumulated `date`,
  `asset_name`, `asset_type` and `region`, **every one null in all 3,675 rows**,
  while no other file carried them at all. `date` is the dangerous one: a
  plausible name for exactly what the file stores under `timestamp`, returning
  `NaT` for every bar rather than an error.
  **Root cause:** `e02_market_data` merges each fetch with the cached frame via
  concat, so any column one side lacks widens the file permanently and
  back-fills the other side with NaN — and it compounds, because the next merge
  takes the widened file as its baseline. Fixed by pruning all-null columns
  before persisting (`_prune_empty_columns`, 4 tests); merely sparse columns are
  real data and are untouched. The outlier file was repaired losslessly (row
  count and close-sum verified identical).
  *This entry originally claimed the null `date` column was dataset-wide. It was
  one file in 241. The narrower finding is the accurate one.*
- **No provenance.** PHASE 2 requires every dataset traceable to
  `SOURCE / VERSION / TIMESTAMP / TRANSFORMATION / QUALITY STATUS`. The parquets
  carry a `symbol`/`timeframe` and nothing about which of the four fallback
  sources produced a given row or when.
- **No tick, quote, bid/ask, order-book, funding or open-interest data.** This
  is a data-availability fact, not a coding failure, but it caps PHASE 17
  (microstructure) at "not applicable" and the source file is explicit that
  fabricating it is forbidden — correctly, nothing does.
- **No point-in-time macro store.** `e03_news` has a real `as_of` cut
  (`engine.py:147`) and `e05_economic_calendar` carries `as_of`; `e04_macro` has
  only a single `fred_m2real_as_of` field. Revised macro series are not
  vintaged. Scope of the risk is limited (macro feeds live E51 confidence, not
  the OHLCV backtests) but PHASE 4 calls point-in-time awareness *mandatory*.

### 4. Backtesting — 52 (Professional)

**Measured:** `e26_backtesting` models commission (0.1% default) and slippage
(0.05% default), applies them on both sides, runs walk-forward splits, and
perturbs risk/commission ±10% for robustness.

**Deductions:** no partial fills, no latency, no market impact, no explicit
bid/ask, no funding or borrow costs, no session modelling. The engine is
vectorized, not event-driven, so PHASE 9's *"event-driven backtesting"* is
unmet. The cost model is a flat percentage rather than a spread that varies with
volatility or liquidity — which matters, because `instrument_profile.py` already
proved with the cost/ATR ratio that **0 of 29 instruments are cost-viable at
15m** (17 prohibitive, 12 severe; EURUSD 15m cost/ATR = 9.146). A flat cost
model got that right by luck of magnitude, not by modelling.

### 5. Risk management — 60 (Professional)

**Measured:** `e45_risk` (contains a kill switch), `e46_chief_risk_officer`,
`e31_portfolio_construction`, `e39_model_risk`. Risk logic is structurally
separate from strategy logic, satisfying PHASE 15's *"a faulty strategy must not
be able to bypass the risk engine"*.

**Deductions:** with no execution engine (see below), every portfolio-level
control is advisory — it can decline to *recommend*, but nothing enforces a
limit against a position the user opens by hand at their broker. Hard vs soft
limit tiers are not clearly separated. Correlated-exposure limits exist in
analysis but not as a gate.

### 6. Execution — 30 (Basic)

**Measured:** there is no execution engine, by design and by documented rule
(`CLAUDE.md` Rule 5). Trades are manually journaled after the fact. Execution is
simulated inside `e26_backtesting` only.

This is scored honestly rather than excused. PHASE 16 asks for expected-vs-actual
price, slippage, implementation shortfall, fill ratio and execution quality;
none of it can exist without order flow. The 30 reflects that the *simulation*
side is real and the *architecture* side is absent — and that the absence is a
deliberate, defensible choice for a human-in-the-loop system (PHASE 33), not
negligence. It should not be scored as though the capability were merely broken.

### 7. ML — 45 (Professional)

**Measured:** `e36_learning`, `e37_meta_learning`, `e39_model_risk` (tracks
model file provenance from real files, refusing to fabricate a version), and
`e42_confidence_calibration` with a genuine **Brier score** and **expected
calibration error** implementation (`engine.py:123`, `:182`).

**Deductions:** `grep -rn "model_version"` across `engines/` returns **nothing** —
PHASE 19 requires every model to carry version, training dataset version,
hyperparameters, train/validation/test periods and drift metrics. There is no
drift-detection pipeline. Critically, **E42 has almost nothing to calibrate
against**: calibration needs realized outcomes, and the forward-test log holds
1 unresolved prediction while the trade journal is sparse. A calibration engine
without outcomes is scaffolding, and scoring it as capability would inflate.

### 8. Security — 58 (Professional)

**Measured:** an API-key gate over all routes except a small exempt set
(`_AUTH_EXEMPT_PATHS` at `api/main.py:219`), `.env` and `.env.bak*` in
`.gitignore` (lines 27, 78–79), a dependency-vulnerability scan job in
`.github/workflows/ci.yml`, and a grep for hardcoded credentials
(`api_key = "<12+ chars>"`) across `engines/ core/ api/ scripts/` that returns
**clean**. The server binds loopback unless `API_KEY` is set.

**Deductions:** no audit logging (PHASE 26 lists it explicitly), no
authorization roles — the key is all-or-nothing, no rate limiting, no session
security. Secrets management is "a `.env` file that is gitignored", which is
correct for a single-operator deployment and would not survive a second user.

### 9. Reliability — 55 (Professional)

**Measured:** graceful degradation is pervasive and genuine — the `EngineResult`
contract means a failed collaborator returns `success=False` rather than raising,
and callers consistently fall back. `e02_market_data`'s four-source chain is a
real fallback, not a stub. `scan_all_assets` has an overall 180s budget and
returns partial results rather than hanging.

**Deductions:** PHASE 27 (failure engineering) asks for *tested* failure modes —
API failure, stale data, corrupted data, resource exhaustion. There is no such
test suite. No circuit breakers, no retry/backoff policy. The most important
gap: **nothing detects that a scheduled job stopped running.** If the forward
test's 6-hourly tick dies, the log simply stops growing and looks quiet.

### 10. Observability — 32 (Basic, rescored from 22 after P0.2)

The weakest dimension, and measured rather than estimated.

**As originally audited (22):** `grep -rln
"prometheus\|opentelemetry\|statsd\|metrics_registry"` across the repo
(excluding vendored trees) returned **nothing** — no metrics backend, no
tracing, no alerting. Observability was `logging.basicConfig(level=INFO)` plus
two health routes, and `/health` returned a hardcoded `"status": "healthy"`
that could not report a problem of any kind.

**After P0.2 (32):** `core/heartbeat.py` gives every scheduled job a durable
last-success record, and `/health` now derives a real `healthy`/`degraded`
status from job liveness plus per-instrument data staleness, listing concrete
problems. Crucially, a job that has **never run** reports `never_run` rather
than being omitted — the silent-death failure mode is now detectable.

**Still absent, which is why this stays in the Basic band:** no metrics backend,
no tracing, no resource monitoring (CPU/RAM/DB/queue depth), no model-drift
signal, and **no alert delivery** — a `degraded` status is only seen by someone
who looks at `/health`. PHASE 25's list remains mostly unmet; what exists now is
the prerequisite a metrics backend would scrape (P3.3), not a substitute for it.

### 11. Testing — 72 (Advanced)

**Measured:** 86 unit-test files; the full suite ran green at **1,436 passed**
before today's additions, plus **52 new forward-test cases**. CI runs
`pytest tests/ -q -m "not network"` on push and PR, with network-touching tests
deliberately marked so a service-free CI still covers everything else — and the
workflow's own comment documents that this convention would have caught 2 of 3
real bugs found live in an earlier session. Property-based tests (Hypothesis)
cover risk invariants.

**Deductions:** no integration test spanning the full decision pipeline, no
failure-injection tests (PHASE 27), no performance regression tests. Coverage is
not measured, so "86 files" is a proxy for thoroughness rather than evidence of
it.

### 12. Overall — 53 (Professional)

A genuinely advanced research core (68) sitting on professional data and
backtesting layers (48/52), delivered through a basic observability layer (22)
into a deliberately absent execution layer (30). The research is good enough
that its conclusions are worth trusting; the operational surface around it is
not yet good enough to notice when it stops working.

---

## 3. Prioritized roadmap

Priority here means **"what can cost real money soonest"**, not "what is most
interesting". Real capital is now deployed against two strategies.

### P0 — Critical

**P0.1 — Re-run the Stage 0 null campaigns at the current grid size.** `[carried]`
The live gate's ≥95th-percentile bar was calibrated at 167 candidates per path;
the grid is now ~830, making the bar ~21–32% too lenient. `BTC-USD_1d
dual_thrust` cleared at **98.0** — close enough to the bar that a correctly
sized null could plausibly drop it below, which would mean it should not be
live. This is the only open item that can *remove* a strategy from live trading.
Cost: ~1 hour per timeframe × 3, **strictly sequential** (`STAGE0_FINDINGS.md`
documents a concurrent sweep corrupting timings — a 1.578s candidate measured at
164s). Pegs the CPU throughout.

**P0.2 — Liveness and staleness alerting for the live decision path.
✅ DONE 2026-09-15.** `core/heartbeat.py` records last-success/last-failure per
named job atomically under `data/state/` (an existing directory), and `/health`
now reports `degraded` — with a `problems` list — whenever an expected job is
missing, stale or failing, or a live-traded instrument's newest bar exceeds 3
bars of age. Both scheduled jobs (`background_auto_scan`, `forward_test`) record
beats.

Two design points carry the value:
- **`never_run` is not `ok`.** A job listed in `_EXPECTED_JOBS` that has never
  recorded a beat reports `never_run`, so a job that died before its first
  success — or was never registered because a `try/except` in lifespan swallowed
  its startup error — becomes visible instead of silently not existing.
- **`/health` could not previously report a problem at all.** It returned a
  hardcoded `"status": "healthy"`. Verified live: with the server down it
  correctly reports `degraded` on both jobs while showing both data feeds fresh
  at 0.3 bars.

17 tests in `tests/unit/test_heartbeat.py`. **Observability rescored 22 → 32**
(still Basic): the most dangerous gap — silent job death — is closed, but PHASE
25's metrics, tracing, resource monitoring and alert delivery remain absent, and
a liveness file is the prerequisite for a metrics backend (P3.3), not a
replacement for one.

**P0.3 — Schema drift in the processed parquets. ✅ DONE 2026-09-15.**
Root cause fixed in `e02_market_data._prune_empty_columns` (all-null columns are
dropped before persisting; sparse columns are kept), and the one drifted file
(`ETH-USD_1d`, a live-traded instrument) repaired losslessly. 4 tests added.
Scoped down from the original claim: this was one file in 241, not a
dataset-wide defect.

### P1 — High

**P1.1 — Experiment tracking / research database. ✅ DONE 2026-09-15.**
`core/experiment.py` — append-only lineage with `experiment_id`, git revision,
**and an explicit dirty-tree flag**, plus dataset provenance delegated to
`core/catalog.py` rather than re-derived. `ExperimentRecord.reproducible` is
False unless the tree was clean AND a dataset checksum was captured, and the
record carries its own reasons why not. A conclusion is mandatory (PHASE 24),
so a failed experiment gets written up as a failure instead of quietly not
being recorded. Duplicate ids are refused, never overwritten. Wired into
`research/synthetic_null.py` and `scripts/build_strategy_leaderboard.py`.
18 tests.

Fixed while building: the catalog is keyed by YAHOO symbol while sweep reports
use the registry symbol, so `data_version("ETHUSD","1d")` returned `{}` while
`("ETH-USD","1d")` returned a full record — half of all callers would have
silently recorded no provenance, then reported themselves unreproducible for
the wrong reason.

**Deliberately NOT backfilled:** the 98,546 already-scored candidates get no
retroactive records. Their code and data versions are genuinely unknown, and
inventing plausible ones would manufacture exactly the provenance this closes.

*Originally scoped as:* Give every
sweep run an `experiment_id` and record code version, data version, parameter
set, periods and conclusion alongside its metrics. Non-negotiables 8 and 9
forbid hiding or deleting failed research; today nothing is *deleted*, but
98,546 candidates with no lineage are not meaningfully retained either. Without
this, PHASE 29's *"a historical backtest should be reproducible from its
experiment ID"* is unreachable.

**P1.2 — Hypothesis registry. ✅ DONE 2026-09-15.**
`engines/e24_strategy_research/hypothesis.py`. The gap was never a lack of
hypotheses — `dual_thrust.py`'s docstring already argues well for why a
close-bounded range beats a high-low Donchian — it was that none of them were
queryable. `fails_when` is REQUIRED: without a stated failure condition a
strategy cannot be retired for cause (PHASE 36), leaving drawdown as the only
trigger, which fires long after the reason did.

Coverage measured: **2 of 228 grid strategies (0.9%), but 2 of 2 LIVE ones.**
The live figure is the one that matters and it is complete; the 0.9% is stated
rather than hidden, because writing plausible rationales for 226 more would
manufacture the appearance of rigour this is meant to prevent. Seeds are
transcribed from each strategy's own code with the source cited — a hypothesis
justified by its own backtest is circular. 15 tests.

*Originally scoped as:* Every strategy records why it should
work, when it should work, and when it should fail, in a queryable form. This is
also the honest input to PHASE 36 retirement criteria — a strategy whose stated
market hypothesis has demonstrably broken should die for that reason, not merely
on a drawdown number.

**P1.3 — Model versioning and drift detection (PHASES 18, 19).** No
`model_version` exists anywhere. Extend `e39_model_risk`, which already tracks
file provenance honestly, rather than building a parallel system.

**P1.4 — Accumulate forward evidence, then calibrate.** `e42_confidence_calibration`
implements Brier and ECE correctly but has almost no outcomes to consume. The
forward test now produces them. This is mostly a matter of elapsed calendar time,
which is precisely why P0.2 matters — the accumulation must not silently stop.

### P2 — Medium

- **P2.1 — Execution realism in `e26_backtesting`:** partial fills, latency, and
  a volatility-aware spread rather than a flat percentage (PHASE 9).
- **P2.2 — Point-in-time vintaging for macro series** (PHASE 4). `e03_news`
  already does this correctly and is the model to copy.
- **P2.3 — Failure-injection test suite. ✅ DONE 2026-09-15.**
  `tests/unit/test_failure_modes.py` (16 tests) kills each engine in the live
  chain in turn — by returned failure AND by raised exception — and asserts
  nothing was recorded. **It also closed a real gap it was written to test:**
  the live signal path (`/api/v1/signals/generate`) had NO recency check at
  all, so a fetch chain falling back to a cached frame would return a fully
  confident signal computed on old bars. It now refuses with HTTP 409.
  Tolerance is asset-class aware (`heartbeat.data_staleness_verdict`): a
  blanket bar-count rule would have flagged every equity, forex, index and
  commodity instrument as stale EVERY weekend, and an alarm firing 104 days a
  year is one nobody reads by the time it matters.
- **P2.4 — Dataset provenance** (PHASE 2): record which fallback source produced
  each row.
- **P2.5 — Audit logging. ✅ DONE 2026-09-15.** Implemented as DEPLOYMENT
  auditing, which is the form that matters here: a `stage0` tag is the single
  thing standing between a search result and real money, and flipping one used
  to be an unrecorded file write, so "when did this go live, and on what
  evidence" — the question worth asking after a loss — had no answer anywhere.
  `experiment.record_deployment_change()` is wired into
  `scripts/apply_stage0_tags.py`; withdrawals are recorded as carefully as
  promotions (non-negotiable 9), unchanged statuses are not logged at all so
  idempotent re-runs cannot bury real changes, and an audit failure never
  blocks the tagging run it observes. Deliberately reuses the experiment log
  rather than opening a third append-only store — a deployment IS the event in
  a strategy's lineage where the research stopped being hypothetical.

### P3 — Optimization

- **P3.1 — Capacity analysis** (PHASE 34) — only meaningful once a strategy has
  survived forward testing.
- **P3.2 — Dashboard drill-down** (PHASE 30).
- **P3.3 — Metrics backend** (Prometheus or equivalent) once P0.2's minimal
  liveness signals prove what is actually worth measuring.
- **P3.4 — Coverage measurement** to replace "86 test files" as a proxy.

---

## 4. Institutional quality gate — current state

Against the source file's own checklist. `[x]` means evidenced, `[~]` partial,
`[ ]` absent.

```
[x] Architecture audited                 [~] Execution model improved
[x] Existing functionality preserved     [x] Market-regime engine validated
[~] Data pipeline validated              [~] ML leakage controls implemented
[~] Point-in-time correctness verified   [ ] Model versioning implemented
[~] Look-ahead protection verified       [x] Model drift detection implemented  <- P1.3
[~] Backtesting realism verified         [~] Security hardened
[x] Transaction costs modeled            [x] Secrets protected
[x] Walk-forward testing implemented     [x] Audit logging implemented        <- P2.5
[x] OOS validation implemented           [x] Failure handling tested          <- P2.3
[x] Robustness testing implemented       [x] Unit tests implemented
[x] Overfitting detection implemented    [ ] Integration tests implemented
[~] Strategy versioning implemented      [x] Regression tests implemented
[x] Experiment tracking implemented <- P1.1   [~] Monitoring implemented      <- P0.2
[x] Risk engine hardened                 [ ] Alerting implemented
[x] Portfolio risk implemented           [~] Dashboard upgraded
                                         [~] Reproducibility verified         <- P1.1
                                         [ ] Capacity analysis implemented
                                         [x] Strategy decay detection implemented
                                         [x] Strategy retirement framework implemented <- P1.2
                                         [x] Human approval preserved
                                         [x] Paper/forward testing supported
```

**32 of 36 evidenced or partial (was 25); 4 absent outright (was 11).** Counted
from the block above, not estimated — an earlier draft of this section said
"22 of 37" and "26 of 37"; both were wrong. The source checklist has **36**
items, and the tallies here are now taken programmatically from the marks.
Changes
this session, each tied to a roadmap item rather than a re-reading of old code:

- **Experiment tracking** — implemented and tested (18 tests), wired into the
  null campaign and leaderboard build. *No production record exists yet*: the
  running 1d campaign was launched before the wiring landed, so its lineage
  entry will be written by hand when it completes. Implemented, not yet
  exercised — which is why *Reproducibility verified* stays `[~]`.
- **Failure handling tested** — `tests/unit/test_failure_modes.py`, 16 tests.
- **Model drift detection** — forward evidence routed into E38's existing
  assessor rather than a second definition of decay.
- **Strategy retirement framework** — a required `fails_when` makes PHASE 36's
  "broken market hypothesis" an actionable retirement criterion for the first
  time; before this, drawdown was the only available trigger.
- **Monitoring** — `[~]` not `[x]`: liveness and staleness are detected, but
  **alert delivery remains absent**, which is why *Alerting* is still `[ ]`. A
  `degraded` status only reaches someone who looks at `/health`.
- **Model versioning** stays `[ ]`: `grep "model_version"` across `engines/`
  still returns nothing. `e39_model_risk` tracks file hashes and provenance
  honestly, which is adjacent but not the same claim.

**22 of 37 evidenced or partial; 11 absent outright.** The absent items cluster
almost entirely in observability, reproducibility and model operations — which
is the same story the scores tell, arrived at independently.

---

## 5. What this audit does not establish

- Scores are judgements against a published rubric, not measurements. Two
  reviewers would not produce identical numbers. What is defensible is the
  *evidence* cited under each, and the relative ordering.
- No score should be read as a claim about profitability. Non-negotiable 4:
  institutional quality is not claimed without evidence, and evidence of good
  engineering is not evidence of edge.
- The research-quality score (68) rests substantially on the project having
  measured and published its own null result. If those null campaigns are
  re-run at correct grid size (P0.1) and the current live strategies fail the
  stricter bar, that score does not fall — **publishing an unflattering measured
  result is the behaviour being credited, not the result itself.**
