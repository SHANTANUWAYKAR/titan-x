# PROJECT_AUDIT.md — Phase 1

**Scope:** audit only. No project code was modified. **Date:** 2026-09-08.
**Method:** direct inspection of the working tree at `a3dad71` — file counts, import graphs, route
enumeration, config resolution, and test-reference mapping. Where a claim is inferred rather than
measured, it says so.

---

## 0. Corrections to the brief's own premises

Three statements in `UPGRADE_BRIEF.md` do not match the repository. Flagging them first because
later phases are scoped against them.

| Brief says | Actual | Impact |
|---|---|---|
| "FastAPI + React" | FastAPI + **a single 3,145-line static `dashboard/index.html`**. No `package.json`, no `src/`, no build step, no React. | **Phase 12 is mis-scoped.** "Do not install a second component library" is moot — there is no first one. shadcn tokens are used as hand-written CSS, not components. |
| "854 tests" (§C, Phase 1, Phase 17, Constraint 10) | **935 collected**: 854 deterministic + 81 marked `network`. | The 854 figure is right *for the deterministic subset*, which is the correct gate. Constraint 10 should read "854 non-network tests must pass" — the 81 network tests fail in bulk whenever an external API rate-limits, independent of code. |
| "45 live strategy overrides" | 45 files exist, but as of `a3dad71` **43 are tagged `UNVALIDATED` and no longer drive signals**. | §C's pipeline diagram is stale. Only `BTC-USD_1d` and `INFY.NS_1d` still take the override branch. |

**Also:** the brief's header says to save it to `docs/UPGRADE_BRIEF.md`; it was living at
`TIS/data/UPGRADE_BRIEF.md` (outside the package). Copied to `docs/` verbatim.

---

## 1. Existing capabilities

**55 engines**, 143 Python files, 29,470 LOC under `engines/`.

| Capability | Engine(s) | State |
|---|---|---|
| Market data + fallback chain | E02 (yfinance → ccxt → nselib → Alpha Vantage) | Live; 241 parquet files, 725 MB |
| Data quality / gap repair | E40 | Live |
| Technical indicators | E07 (EMA, RSI, ATR, MACD, ADX, Bollinger) | Live |
| ICT/SMC | E07 `smart_money` (BOS, CHoCH, sweeps, order blocks, FVG), `killzones`, `order_flow` (CVD), `wyckoff`, `volume_profile` | Live |
| Regime classification | E08 | Live |
| Signal generation | E51 (override branch + baseline composite, confluence adjustment, edge gate) | Live |
| Risk | E45 (confidence floor, R:R, daily/weekly/monthly loss, drawdown, portfolio heat, risk-of-ruin, correlation, consecutive-loss breaker, funded-account rules, position sizing) | Live |
| Strategy research | E24 (23 strategies, 167-candidate grid) | Live |
| Backtesting | E26 (IS/OOS walk-forward, cost model, parameter sensitivity, MC sequencing, MC ruin) | Live |
| Walk-forward | E27 | Live |
| Validation (Stage 0) | E26 `deflated_sharpe.py` + `research/synthetic_null.py` | **New at `a3dad71`** |
| Options | E13 derivatives, Kite option chain provider | Live |
| News / sentiment / macro | E03, E09, E04, E05 | Live |
| Cross-asset, commodity, crypto, fixed income, credit, liquidity | E10, E16, E17, E14, E15, E19 | Live |
| Portfolio / capital allocation | E31, E32 | Live |
| Governance | E47 — **actively scans engines for `place_order`/`execute_trade`/`submit_order`/`send_order`** | Live |
| Execution readiness | E48 — verifies no execution method exists | Live |
| API | FastAPI, **78 routes** in a single 2,172-line `api/main.py` | Live |
| Persistence | PostgreSQL (SQLAlchemy 2.0 + Alembic), Redis cache w/ circuit breaker, Qdrant vectors | Live |
| CI | `.github/workflows/ci.yml` | Present |

**Rule 5 and the research-isolation rule both hold.** `grep` for order placement in `engines/` and
`api/` returns only E47/E48's own enforcement code. No `engines/` module imports `research/` — the
four matches are comments describing the rule.

---

## 2. Missing capabilities

Relative to the brief's target set:

- **CPCV** (Phase 7.3) — not present. E26 uses a single IS/OOS split; E27 does walk-forward windows. No purge, no embargo, no path distribution.
- **Trailing equity drawdown** (Phase 8) — E45 has drawdown limits; a *trailing* high-water-mark model and the green/yellow/red size-reduction zones are not implemented.
- **Kill switch** (Phase 8) — no single global halt mechanism found.
- **Unified journal** (Phase 9) — no module capturing MAE/MFE, skipped signals, or rule-based mistake tagging.
- **Portfolio VaR / CVaR at the risk gate** — CVaR exists in E31 optimisation; not enforced as a risk limit.
- **Property-based tests (Hypothesis)** — not present anywhere.
- **MT5 integration** — not present (correctly, per Rule 5; would be report-only).
- **API authentication** — none. See §7.

---

## 3. Architectural weaknesses

**W1 — Vendor coupling bypasses E02.** Seven engines import `yfinance` directly: E02, E04, E06,
E10, E13, E14, E15. Only E02 has the documented fallback chain, so the other six inherit none of
it: a yfinance outage degrades them silently and differently. This directly contradicts the brief's
constraint 20 ("prefer adapters over vendor-specific implementations"). **The single highest-value
structural fix in this audit.**

**W2 — `api/main.py` is a 2,172-line monolith** holding all 78 routes. No routers, no per-domain
modules. Every API change touches one file.

**W3 — `engines/e51_signals/engine.py` is 2,010 lines** and carries override loading, baseline
composite direction, confluence adjustment, the edge gate, and signal assembly. It is the widest
blast radius in the system and has the most conditional branching.

**W4 — Three independent Sharpe implementations** (E26 `deflated_sharpe.py`, E31, E35
`sharpe_per_trade`). E35's is explicitly per-trade; the others are per-period annualised. Nothing
enforces that they agree, and a Sharpe quoted in the UI may not be the Sharpe that gated a
promotion. Not yet shown to disagree — flagged as risk, not defect.

**W5 — No service layer between engines and API.** Routes call engines directly, so HTTP concerns
and domain logic are interleaved.

---

## 4. Duplicate systems

| Duplicate | Locations | Verdict |
|---|---|---|
| Monte Carlo | E26 `monte_carlo_sequencing_test` (Sharpe p-value) and E26 `monte_carlo` (ruin risk, consumed by E30) | **Not a duplicate** — different questions, documented at the call site. Keep both. |
| Sharpe | E26 / E31 / E35 | **Real duplication.** Consolidate to one utility (W4). |
| Drawdown | E45 limits, E26 metrics, E35 analytics | Three computations of max DD. Likely consistent; unverified. |
| ICT/SMC | E07 `smart_money` vs Group A repos (Phase 2) | **Pre-emptive `CONFLICT`** — BOS/CHoCH/order blocks/FVG already exist. Phase 4 must diff, not import. |

---

## 5. Technical debt

- **19 of 55 engines have zero test references** (§9).
- **Static dashboard at 3,145 lines** in one file, with a "do not touch" constraint — so all new UI work must live in parallel files, which will fragment the surface.
- **`logging.basicConfig(level=INFO)`** is the only logging configuration. No structured logging, no per-module levels, no rotation — the brief's Phase 16 asks for structured logging.
- **One Alembic migration** for a 2.0-style model set; schema evolution is effectively untracked.
- **`.env.example` declares 41 keys**; settings resolve through `core/config/settings.py`, so drift between the two is invisible until runtime.
- **`data/raw` is 520 MB and `data/processed` 725 MB**, both in-repo. Git operations carry that weight.

---

## 6. Performance bottlenecks

- **Full 167-candidate sweep ≈ 258 s at 12,000 bars** (measured). A 150-path null campaign is ~1 hour on 6 workers. This is the dominant research cost.
- **Pool capped at 6 workers** after a 16-worker pool lost a run when a child died. Correct trade-off, but it means research scales with cores only to 6.
- **`wyckoff_spring_reversal` is a ~12× outlier** — 6–8 s for a single parameter set against ~0.5 s typical. Unprofiled.
- **Test suite: 124 s deterministic, but 20m43s including network tests** under API rate limiting. The network tests are an unbounded-latency dependency in CI.
- **Redis cache has a circuit breaker** (`core/cache.py`) — good; failure mode is degraded, not broken.

---

## 7. Security risks

**S1 — The API is unauthenticated and bound to all interfaces.** `api_host = "0.0.0.0"`,
`CORSMiddleware(allow_origins=["*"])`, and no `Depends`-based auth on any of the 78 routes. Any host
that can reach the port can call every endpoint, including `POST /api/v1/market-data/fetch` and the
brain workflow runner. On a laptop behind NAT this is low-severity; on any shared or bridged network
it is not. **Highest-severity finding in this audit.**

**S2 — No secrets found in source.** Grep for assigned key/secret/password/token literals returns
nothing; everything resolves through settings. `.env.example` carries names only. Good.

**S3 — Broker credentials in scope.** `KITE_API_KEY` / `KITE_ACCESS_TOKEN` exist in config. Per Rule
5 they must remain read-only; E47/E48 enforce the absence of order placement, which is the right
control. No action needed, but Phase 10 must not weaken it.

**S4 — Phase 2 will clone 21 third-party repositories.** Two brief-listed red flags (broker
credential requests, Selenium broker automation) are exactly the categories that would introduce
credential exfiltration. Cloning must be to `./external/` and must never be added to the import path.

---

## 8. Data-quality risks

- **Yahoo outages surface as "insufficient history," not as errors.** Documented previously: two matrix runs were corrupted this way, indistinguishable from a genuine finding. Mitigation exists (offline parquet runner) but the ambiguity is unfixed at the source.
- **Six engines with no fallback chain** (W1) inherit this failure mode without E02's mitigations.
- **241 parquet files, no checksum manifest** in `data/processed`. The brief's constraint 26 asks for a data checksum per promotion; `data/catalog/registry.json` records checksums for fetched raw data, but the processed layer is not covered.
- **Timestamp handling** — `timestamp` columns are present in parquet; UTC-internal discipline (constraint 25) not verified in this phase.

---

## 9. Testing gaps

**Current: 935 collected — 854 deterministic (all passing, 124 s) + 81 `network`-marked.**

**19 of 55 engines are never referenced by any test:**

```
e22_alpha_research      e23_forecasting        e25_strategy_lifecycle
e29_scenario_analysis   e30_adversarial_testing e32_capital_allocation
e36_learning            e37_meta_learning      e39_model_risk
e44_chief_investment_officer                   e46_chief_risk_officer
e47_governance          e48_execution_readiness e63_market_memory
e64_causal_intelligence e65_world_model        e74_conflict_resolution
e79_portfolio_simulation e84_counterfactual
```

Three of these matter disproportionately:

- **E47 governance** and **E48 execution readiness** are the engines that *enforce Rule 5*. The mechanism guaranteeing "no execution engine" is itself untested.
- **E46 chief risk officer** and **E39 model risk** are risk-authority engines, untested.
- **E30 adversarial testing** consumes E26's `monte_carlo` — a contract with no test on either side.

Other gaps: no Hypothesis property tests; no adversarial-input tests of the kind Phase 17 lists
(NaN, duplicate candles, zero volume, API failure); the 81 network tests make CI dependent on
third-party uptime.

---

## 10. Scalability problems

- **Research throughput is the binding constraint**, not serving. 6-worker cap × ~258 s/sweep sets the ceiling on how much validation can be done — and Stage 0 raised the amount of validation needed per promotion substantially.
- **Per-symbol nulls do not exist.** 43 of 45 Stage 0 verdicts rest on a gold proxy. Doing it properly is ~1 hour per (symbol, timeframe); at 23 symbols × 3 timeframes that is ~69 hours of compute.
- **Single-process API.** No worker model, no queue; long research calls would block HTTP.
- **In-repo data growth** (1.2 GB) will not scale with more symbols/timeframes.

---

## 11. `CONFLICT` — Phase 7 vs. work already committed

**Phase 7's "institutional validation upgrades" are substantially already implemented**, at commits
`023819b` and `a3dad71`, and **two of its six requirements conflict with measurements taken from
this system.** Raising this now because Phase 7 as written would require undoing committed,
evidence-backed work.

| Phase 7 item | Status | Conflict |
|---|---|---|
| 1. DSR with effective N, **require DSR > 0.95** | DSR + spectral-entropy effective rank implemented (`deflated_sharpe.py`) | **CONFLICT.** DSR > 0.95 rejects **all 45** overrides; max observed DSR is 0.8777 and none reach 0.90. DSR is computed on IS Sharpe alone and cannot see IS→OOS decay — on this book it ranks almost inversely to the null percentile (`ETH-USD_1h`: DSR 0.878 / percentile 16.7 vs `INFY.NS_1d`: DSR 0.009 / percentile 97.3). It was adopted as a **reported diagnostic, not a gate**. |
| 2. Synthetic-null baseline | **Done.** 3 timeframes × 150 paths × 167 candidates. Found the legacy bar cleared by noise on 137/150 4h paths (91%). | None — this is the item that drove everything else. |
| 3. CPCV, 21-day purge/embargo | **Not done.** | None; genuine gap. |
| 4. **Raise minimum trades 30 → 100 (prefer 200+)** | Adopted **60**. | **CONFLICT.** Measured: a 100-trade floor passes 21/45 overall but **0 of 19 at 4h**. It would empty the 4h book on a criterion that is *not* calibrated against anything — the null campaigns do not record per-candidate trade counts, so 100 and 60 are both convention. 60 was chosen as the strictest floor that does not eliminate a timeframe outright. Raising to 100 is defensible but should be a deliberate decision with that cost visible. |
| 5. Parameter sensitivity ±20% | **Exists** — E26 `_parameter_sensitivity`. Note it perturbs `risk_pct`/`commission` only, **not strategy parameters**, so it does not measure what Phase 7.5 intends. | Partial gap, worth its own task. |
| 6. Cost stress 2× | **Exists.** | None. |

**Recommendation:** Phase 7 should be rewritten against `docs/STAGE0_FINDINGS.md` before it is
executed, reducing to (a) CPCV, (b) a decision on the trade floor with the cost table in hand, and
(c) extending parameter sensitivity to strategy parameters.

---

## 12. Suggested priority (input to Phase 15, not a roadmap)

| # | Item | Why first |
|---|---|---|
| P0 | **S1** API auth + bind address + CORS | Only finding with an external attack surface |
| P0 | **§9** Tests for E47/E48 | The Rule 5 guarantee is currently unverified |
| P1 | **W1** Route the 6 engines through E02 | Removes a silent, differentiated failure mode |
| P1 | **§11** Reconcile Phase 7 with Stage 0 | Prevents undoing evidence-backed work |
| P2 | **W4** Consolidate Sharpe | Correctness-of-record |
| P2 | **W2/W3** Split `api/main.py` and E51 | Maintainability, not correctness |

---

## 13. What this audit did not cover

- Runtime profiling beyond the sweep timings already measured.
- UTC/timestamp discipline (constraint 25) — asserted by convention, not verified.
- Dashboard accessibility, contrast, or colour-blind safety (Phase 12 territory).
- Whether the three drawdown computations agree numerically.
- Any third-party repository — that is Phase 2, and **none has been cloned or inspected.**

**No project code was modified in this phase.** Files added: `docs/UPGRADE_BRIEF.md` (copied
verbatim from `TIS/data/`) and this document.
