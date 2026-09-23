# Final Upgrade Report — PROJECT TITAN-X

**docs/UPGRADE_BRIEF.md Phase 18.** Covers the full 18-phase brief,
2026-09-08 through 2026-09-13 (6 days, 55 commits from `a006202` "Phase
1: PROJECT_AUDIT.md" through this report). Every claim below is grounded
in a specific commit, doc, or test file — nothing here is a summary of
intentions, only of what was actually verified and shipped.

---

## What was discovered

- **15 reference repositories** (Groups A-E: ICT/SMC, Quant, Risk,
  Journal, Indian options) fully audited against the brief's own
  per-repo template — `docs/REPOSITORY_INTELLIGENCE.md`. Two were
  **confirmed malware** (PropGuard-Trailing-Equity-Armor, Risk-Nexus-
  Command — an hourly cron GitHub Action fabricating commits), not
  merely low-quality.
- **CRT (Candle Range Theory) and CISD (Change in State of Delivery)**
  fully reverse-engineered into deterministic specifications
  (`docs/ICT_SPEC_PHASE5.md`) from MQL5 source and prose respectively —
  including two source bugs identified and deliberately NOT reproduced,
  and a real "translation trap" (series-indexed MQL5 arrays reading
  backwards from a naive ascending-index port) that is the exact same
  defect class as a real, previously-shipped order-block lookahead bug
  that once reported a 94.8% win rate.
- **A structural Stage 0 gating gap that recurred three times**: every
  time an override was promoted (by this session's own E24 pipeline, or
  by an external process running concurrently against the same
  repository throughout this work), it went live immediately because
  the missing-tag-defaults-to-active design meant tagging was a separate,
  forgettable pass. Root-caused and fixed (not re-patched a fourth time).
- **A real Kelly-sizing bug**: `average_win_loss_r()`'s own convention
  returns `avg_loss_r` as a signed-negative mean, but E12's real
  `kelly_criterion` requires `avg_loss` as a positive magnitude and
  silently rejects negative input via an internal guard — the mistake-
  tag this fed (`kelly_sizing_exceeded`) would have never fired for any
  strategy, indefinitely, with zero test failures, since pure unit tests
  never exercised the real computation path.
- **A parallel gap in E45's own risk-floor logic**: found while fixing
  the Stage 0 issue above — `_load_min_confidence_override` never
  checked Stage 0 status at all, so it was relaxing the platform's risk
  floor for the same 43-of-45 statistically-unvalidated overrides E51
  itself already refused to drive a live signal from.
- **This platform's dependency tree carries 3 previously-unflagged
  copyleft licenses actually in live use**: pymupdf (AGPL-3.0/commercial
  dual, E01 PDF ingestion), ebooklib (AGPL-3.0+, E01 EPUB ingestion),
  wbdata (GPL-2.0+, E04 World Bank data) — `docs/
  DEPENDENCY_LICENSE_AUDIT.md`. Low practical risk today (private,
  non-distributed, no execution engine) but real and worth knowing.
- **The brief's own "AI/LLM Layer" doesn't exist anywhere in this
  codebase** — verified directly: every "committee"/"CIO"/"world model"-
  style engine is rule-based threshold logic or template-string
  narration over already-computed numbers, never an actual model call.

## What was reused

- **freqtrade's RSI/TEMA/Bollinger rule**, reimplemented from its public
  strategy documentation (GPL-3.0 — no source copied, concept only) and
  live-validated against this platform's own E26 bar.
- **TradeNote's unified-tag-category pattern** → `TradeTag.category`
  (`rule_adherence`/`behavioral`/`psychology`).
- **tradicted-journal's negative-tag concept** → `TradeTag.negative`.
- **STAR-EA's breaker-block concept** → `OrderBlock.breaker` (built
  before this session; killzones improved beyond the source with a real
  IANA `zoneinfo` implementation instead of a manual DST table).
- **mlfinpy** (the MIT-licensed reimplementation of a since-relicensed
  López de Prado toolset) is present in the environment per `docs/
  DEPENDENCY_LICENSE_AUDIT.md`, comparison/validation work against this
  platform's own hand-built Stage 0 tooling, not yet wired into any
  engine.

## What was reimplemented

- **CRT** (`engines/e07_technical/crt.py`) — full spec implementation,
  multi-truncation no-lookahead verified, ablated solo: mixed (negative
  on GOLD/BTCUSD, positive and well-sampled on ETHUSD at +0.467
  expectancy / PF 1.35). Not promoted to live signals on a 2-of-3 result.
- **CISD** (`engines/e07_technical/cisd.py`) — composed from three
  already-live primitives (FVG detection, IFVG, swing points), same
  translation-trap discipline as CRT. Ablated solo: mixed and weak
  (GOLD −0.144, BTCUSD +0.053 PF 1.05, ETHUSD +0.130 PF 1.07) — healthy
  sample sizes, contrary to the spec's own prediction, but not promoted.
- **Option chain analytics** (`core/data_providers/kite_option_chain.py`)
  — PCR, max pain, ATM/ITM/OTM classification, Greeks inverted from real
  traded price via Black-Scholes, all computed from definition rather
  than copied from any reference repo.
- **News/sentiment enrichment pipeline** (`engines/e03_news/
  enrichment.py`) — deterministic entity extraction against this
  platform's own 29-symbol universe, keyword-based event classification,
  a documented (not fitted) market-impact weighting, content-hash dedup.

## What was rejected

- **PropGuard-Trailing-Equity-Armor, Risk-Nexus-Command** — confirmed
  malware, rejected outright regardless of license.
- **profittown-sniper-smc's `detect_bos()`** — a Donchian breakout
  mislabeled as Break of Structure, not a real BOS implementation.
- **14 ICT/SMC concepts** already measured and rejected before this
  continued session (`docs/ICT_SPEC_PHASE5.md` §3 rejection register):
  `inverse_fvg`, `ce`, `bpr`, `turtle_soup`, `displacement` (solo),
  `premium_discount`, `ote`, `liquidity_raid_d` — all negative on 2-3 of
  3 tested assets. `killzone` is live with no measured solo edge of its
  own (kept for its real, separate purpose as a confluence filter).
- **backtrader's analyzer pattern** — considered, declined: E26 already
  computes its own metrics inline with no measurable gap.
- **QuantConnect Lean, freqtrade-as-a-framework** — declined on cost/
  benefit against this platform's own E24's measured 2.46x parallel
  sweep, not on license grounds (both are otherwise reusable).
- **Speculative AI/LLM layer** — explicitly NOT built; flagged in `docs/
  UPGRADE_ROADMAP.md` P3 as a deliberate non-recommendation, not an
  oversight, given this platform's whole design philosophy (Rule 21)
  prefers deterministic, explainable algorithms.

## What was improved

- **Risk Engine (E45)**: funded-account green/yellow/red zone sizing
  (replacing a binary full-size-until-100%-then-veto design), a max-
  open-positions check, Stage 0 deny-by-default (closing a real,
  recurring gap), the Kelly-sign bug fix's downstream mistake-tag.
- **Journal/Performance (E35)**: real MAE/MFE from actual OHLCV,
  Calmar/CVaR/recovery_factor reusing E26/E31's own existing formulas,
  signal-conversion-rate, the disagreeing-confluence-layer mistake tag.
- **Indian Options (E13)**: volume, moneyness, PCR, max pain, a
  `runtime_checkable` `OptionChainProvider` Protocol replacing a hard-
  coded broker dependency, and (this final round) real OI-change
  tracking via a new persisted snapshot table.
- **News + Sentiment (E03/E09)**: the full brief-required pipeline
  (entity extraction, event detection, market impact) closing what was
  previously bare RSS ingestion plus raw-text sentiment scoring with no
  enrichment stage at all.
- **UI**: 6 new dashboard pages (Market Structure, Risk, Portfolio, News
  & Sentiment, Options, Strategy Lab) without touching the one existing
  UI file, plus a genuine colorblind-safety helper (`dirBadge`/
  `pnlValue`) for all of them — and, on direct re-inspection this final
  round, confirmation that the existing dashboard did NOT actually need
  the same fix (every color-coded element there already carries a text
  alternative), closing that item by verification rather than
  unnecessary edits to a file under a standing "do not touch" rule.
- **E25 Strategy Lifecycle**: closed its own long-documented "retired"
  gap with a real `retired_at` tombstone that BOTH E51 and E45 now
  check and refuse to treat as live — not cosmetic bookkeeping.

## New architecture

`docs/ARCHITECTURE_SYNTHESIS.md` maps all 55 real engines onto the
brief's proposed `Data → Normalization → Feature Engineering → Market
Intelligence → Strategy → Signal → Risk → Portfolio → Analytics → UI/API`
layering, verified against each engine's actual code rather than its
directory name (several names — `chief_risk_officer`, `world_model`,
`causal_intelligence`, `chief_investment_officer` — turned out thinner
or narrower than they sound, flagged explicitly). Two honest findings
kept, not smoothed over: the AI/LLM layer doesn't exist, and Portfolio
Engine (E31/E32) has no seat in the live per-signal pipeline the way
Risk (E45) does — a decision was made this round to keep that separation
intentional rather than restructure live sizing without explicit
sign-off on that specific behavioral change.

## New dependencies

Only one dependency change from this session's own work: **`vectorbt`
removed** (confirmed via whole-codebase grep to be imported nowhere;
also turned out to be "Apache-2.0 WITH Commons Clause," not plain
Apache-2.0 as its PyPI listing implies). Everything else audited in
`docs/DEPENDENCY_LICENSE_AUDIT.md` (`purgedcv`, `skfolio`, `mlfinpy`,
`quantstats`, `hypothesis`, etc.) was already present in the environment
from work outside this session's own scope — audited for license
compatibility, not newly added here.

## License considerations

Full audit in `docs/DEPENDENCY_LICENSE_AUDIT.md`. Summary: 3 of 15
reference repos are GPL-3.0 (freqtrade, backtrader, TradeNote) — all
already handled correctly with zero source code copied. 3 of this
platform's OWN ~90 dependencies carry copyleft terms actually in live
use (pymupdf/ebooklib = AGPL, wbdata = GPL) — low risk today given this
platform's private, non-distributed, single-user posture; worth
revisiting only if that posture ever changes.

## Security considerations

- 2 reference repos confirmed as **active malware** (fabricated commit
  history via a cron GitHub Action) — rejected, not merely deprioritized.
- The API's `X-API-Key` gate, CORS allowlist, and loopback-bind default
  (pre-existing this session, verified still intact throughout) remain
  the platform's real exposure controls.
- No execution engine exists anywhere (Rule 5) — verified as part of
  `e47_governance`'s own mechanical check, not just asserted.
- `dashboard/shared/common.js`'s `safeUrl()` allowlists only http/https
  schemes for any externally-sourced link (news headlines, etc.),
  consistent with the existing dashboard's own established pattern.

## Performance improvements

- E24/E26: a numpy-array bar loop plus opt-out robustness computation
  (measured, real speedup — see CLAUDE.md's own dated entry; not
  re-benchmarked in this report to avoid restating a stale number).
- E02: merge-dedup collapsing duplicate calendar-day rows on daily+
  timeframes (a real correctness fix with a performance side-benefit).
- Phase 12's dashboard pages load lazily per-page-visit (matching the
  existing dashboard's own established idiom), not eagerly on shell load.

## Testing results

**1215 non-network tests passed, 87 network-marked tests (verified
separately, all passing) — 1302 total**, up from the brief's own stated
854-test baseline. Zero regressions introduced across every phase's own
full-suite run (each phase in this session ran the complete suite before
committing, not just its own new tests). Property-based (Hypothesis) and
adversarial-case coverage detailed in this same CLAUDE.md's Phase 17
section — two genuinely new property/adversarial gaps were found and
closed (an unclamped confidence value; an already-correct-but-unverified
NaN/zero-volume/extreme-volatility behavior in E40), the rest of the
brief's own named catalog was found to already have real coverage on
direct inspection rather than duplicated.

## Remaining weaknesses

Everything below is a genuine, currently-open item, not resolved by this
report — see `docs/UPGRADE_ROADMAP.md` for full detail on each:

1. **`eqh_eql` and `power_of_three`** (two ICT concepts) are positive
   solo expectancy on all three tested assets but sit on 20-50 trades,
   below the 60-trade Stage 0 floor — re-checked with fresh data this
   round, still below the floor on all three assets. Needs more history
   or a longer lookback, not more code.
2. **Portfolio Engine has no live pipeline seat** — a deliberate,
   documented decision this round, not an oversight, but still a real
   architectural gap relative to the brief's own proposed diagram if a
   future need calls for portfolio-aware live sizing.
3. **The 3 flagged copyleft dependencies** (pymupdf, ebooklib, wbdata)
   are fine today but would need revisiting if this platform is ever
   distributed, open-sourced, or offered as a hosted service.
4. **`pyproject.toml`'s own dependency list is stale** relative to
   `requirements.txt` (missing ~30 packages `requirements.txt` declares)
   — noticed while removing `vectorbt` from both files, not fixed beyond
   that one line, since a full reconciliation is a separate, real task
   of its own.
5. **CRT/CISD's ETHUSD-specific positive results** are real but not yet
   pursued as dedicated E24 candidates — a genuinely separate, larger
   step (a real strategy function, IS/OOS split, Stage 0 check) than the
   ablation screening this session did.

## Recommended next steps

In priority order, per `docs/UPGRADE_ROADMAP.md`'s own P0-P3 structure
(all P0 and the well-scoped P1/P2/P3 items are now closed; what's left
either needs more data, a specific design decision, or is conditional
on a future event):

1. Let more real market history accrue, then re-ablate `eqh_eql`/
   `power_of_three` — a data-accrual wait, not new code.
2. If ETHUSD-specific CRT/CISD performance remains interesting, build
   them as dedicated E24 candidates (real strategy functions, IS/OOS
   split, Stage 0 check) rather than leaving them as ablation-only
   findings.
3. Revisit the Portfolio Engine pipeline-wiring decision only if a real,
   specific need for portfolio-aware live sizing is identified — don't
   build it speculatively.
4. Reconcile `pyproject.toml`'s dependency list against
   `requirements.txt` as its own small, dedicated cleanup task.
5. Watch for the Stage 0 gating gap's root pattern recurring in a NEW
   form even though this session closed the specific instance found —
   any future promotion/tagging pipeline should default-deny, not
   default-allow, from the start.
