# Upgrade Roadmap — PROJECT TITAN-X

**docs/UPGRADE_BRIEF.md Phase 15.** Every item below is a REAL, already-
evidenced finding from Phases 1-14's own work this session — nothing
here is invented to fill out the P0-P3 buckets. Per the brief's own
instruction: **this phase stops here. No implementation happens until
the owner approves specific items below.**

Per-task fields follow the brief's template (feature · source · reason ·
files affected · dependencies · complexity · risk · testing requirements
· expected benefit). "Source" is either an external reference repo (Group
A-E) or an internal finding, cited to the phase/doc that surfaced it.

---

## P0 — Critical

### 1. Make Stage 0 validation the DEFAULT for new promotions, not an opt-in tag
- **Source:** Internal finding, recurred twice this session (Phase 8/9
  work and again during Phase 11) — `docs/STAGE0_FINDINGS.md`,
  CLAUDE.md's "Stage 0 validation" sections.
- **Reason:** `_load_strategy_override`'s missing-`stage0`-tag-defaults-
  to-`active` design means every time an external promotion process
  writes a fresh override file, it is LIVE (treated as validated) until
  a separate tagging pass runs. This session had to manually re-run
  `research/score_overrides_stage0.py` + `scripts/apply_stage0_tags.py`
  twice this session alone after an external process's promotion sweep
  silently re-opened the gap (once for 2 overrides, once for all 45).
  The tag is reversible-by-design and the pipeline itself is sound; the
  DEFAULT is the actual defect.
- **Files affected:** `engines/e24_strategy_research/engine.py`
  (`_promote`), `engines/e51_signals/engine.py`
  (`_load_strategy_override`'s missing-tag branch).
- **Dependencies:** None new.
- **Complexity:** Low (invert one default; the scoring/tagging pipeline
  itself needs no change).
- **Risk:** Low technically, but changes behavior for any override
  currently relying on the "missing tag = active" default — must audit
  all 45 live overrides' current tag state before flipping the default,
  so nothing that's ACTUALLY validated gets silently disabled.
- **Testing requirements:** Unit test asserting a freshly-promoted
  override (no `stage0` key) is NOT live until explicitly tagged;
  regression test over all 45 current override files confirming none
  silently changes live/dead status the moment this ships.
- **Expected benefit:** Closes a real, structurally-recurring safety gap
  instead of manually re-patching it a third time.

---

## P1 — High value

### 2. Port CRT (Candle Range Theory) into E07
- **Source:** `NadirAliOfficial/STAR-EA-v11.20` (MIT) via
  `docs/ICT_SPEC_PHASE5.md` §1 — fully reverse-engineered into a
  deterministic Python spec already, including two source bugs
  identified and explicitly flagged NOT to reproduce (`CRT_RequireBreak`
  dead code; a translation trap on which bar index to emit at).
- **Reason:** The single most build-ready ICT concept in the codebase's
  own backlog — mathematical definition, detection algorithm, timeframe
  guidance (1h/4h first), confirmation logic, and backtesting
  requirements are all already written down; no ambiguity left to
  resolve before implementation.
- **Files affected:** New `engines/e07_technical/crt.py` (mirrors
  `smart_money.py`'s module shape), `engine.py`'s `TechnicalSnapshot` to
  add a `crt_setups` field, `research/` for the initial ablation.
- **Dependencies:** None new.
- **Complexity:** Medium (a new deterministic detector, same shape as
  existing ones, but needs its own no-lookahead multi-truncation tests
  per Rule 7).
- **Risk:** Low to the existing system (purely additive, `research/`
  first, E24→E26→explicit-promotion before it can ever reach a live
  signal, same as every other concept this session ported).
- **Testing requirements:** Multi-truncation no-lookahead tests (Rule 7,
  Phase 17's own mandate), solo ablation against real data before any
  strategy candidate uses it, same discipline as every other E07
  detector.
- **Expected benefit:** A new, well-specified, real candidate signal
  input — the platform's own next concrete ICT concept to test, not a
  speculative one.

### 3. Re-ablate `eqh_eql` and `power_of_three` once more trade history is available
- **Source:** Internal finding, `docs/ICT_SPEC_PHASE5.md` §3 (rejection
  register) — `research/ablation_{BTCUSD,ETHUSD,GOLD}_4h.json`.
- **Reason:** Both concepts are **positive solo expectancy on all three
  tested assets** (`eqh_eql`: +0.619/+0.079/+0.610; `power_of_three`:
  +0.113/+0.095/+0.022) but sit on only 20-50 trades each, below Stage
  0's own 60-trade floor — genuinely promising, not yet statistically
  admissible, not a rejection.
- **Files affected:** None yet — this is a data-accrual/re-run item, not
  a code change, until the sample crosses the floor.
- **Dependencies:** More real historical bars (either wait for them to
  accrue, or fetch a longer lookback window if the provider supports it).
- **Complexity:** Low (re-run an existing ablation script once enough
  data exists).
- **Risk:** None — read-only re-measurement.
- **Testing requirements:** None beyond the ablation script's own
  existing output format.
- **Expected benefit:** Two already-promising concepts get a fair,
  eventual verdict instead of sitting permanently below the evidence bar.

### 4. Decide how (or whether) Portfolio Engine (E31/E32) joins the live per-signal pipeline
- **Source:** Internal finding, `docs/ARCHITECTURE_SYNTHESIS.md`
  (Phase 13) — "What the brief's diagram gets right that isn't built yet."
- **Reason:** E45 (Risk) sits directly in the live signal→size path;
  E31/E32 (Portfolio) do not — position sizing today comes entirely from
  E45's own Kelly/risk-percent sizing, never from a portfolio-level
  allocation step, despite E31/E32 being real and substantial.
- **Files affected:** Likely `engines/e45_risk/engine.py` (sizing call
  site) and/or `engines/e32_capital_allocation/engine.py`, `api/main.py`'s
  signal-generation route — exact scope depends on the design decision
  below, which is why this is flagged for a decision, not pre-scoped.
- **Dependencies:** A real design decision from the owner: should E32's
  capital-allocation plan GATE/ADJUST E45's sizing (a structural pipeline
  change with real behavior implications for every live signal), or
  should Portfolio stay a deliberately separate, parallel analysis
  surface (current state, just better-labeled)? This is exactly the kind
  of judgment call this session has flagged rather than decided
  unilaterally in the past (e.g. the CPCV-to-block-bootstrap pivot).
- **Complexity:** High if wired into the live path (touches every
  signal's sizing); Low if the decision is "leave it separate, document
  the boundary clearly."
- **Risk:** Medium-high if wired live (changes real position sizes for
  every future signal) — needs its own dedicated design/approval pass,
  not a drive-by change.
- **Testing requirements:** If wired live: full E45 regression suite
  (49 tests today) plus new tests for the interaction; property-based
  invariant tests (Phase 17) that position size never changes sign or
  exceeds existing caps.
- **Expected benefit:** Closes the one clear architectural gap Phase 13
  found, OR formally documents that it's an intentional, permanent
  separation rather than an oversight.

### 5. Add option-chain snapshot storage to enable real "OI change" tracking
- **Source:** Internal finding, CLAUDE.md's Phase 10 section (2026-09-13)
  — flagged and explicitly left open at the time.
- **Reason:** `docs/UPGRADE_BRIEF.md` Phase 10's own checklist asks for
  "OI change," which needs a persisted PRIOR snapshot to diff against;
  this platform has no option-chain snapshot storage today, so every
  chain read is stateless.
- **Files affected:** New DB table (a `NewsEvent`-shaped precedent already
  exists from Phase 11 for "persist enriched external data" — same
  pattern applies), `core/data_providers/kite_option_chain.py`
  (`assemble_option_chain`), `api/main.py`'s option-chain route,
  `dashboard/pages/options.html` (Phase 12) to surface it.
- **Dependencies:** None new (same Postgres/SQLAlchemy stack already in
  use).
- **Complexity:** Medium (new table + migration + diff logic + one new
  field on the existing response).
- **Risk:** Low — additive, no existing behavior changes.
- **Testing requirements:** Synthetic before/after snapshot diff test;
  real-DB verification (log two real snapshots, confirm OI-change
  computed correctly, clean up test rows) — same discipline as Phase
  9/11/12's own real-DB verification passes.
- **Expected benefit:** Closes the one item Phase 10 itself flagged as
  honestly incomplete.

---

## P2 — Useful

### 6. Build CISD (Change in State of Delivery)
- **Source:** `NadirAliOfficial/STAR-EA-v11.20` via
  `docs/ICT_SPEC_PHASE5.md` §2 — fully specified, but with the spec's own
  explicit caveat.
- **Reason:** Its core component (`inverse_fvg`) measured negative on all
  three tested assets (−0.208/−0.569/−0.270); CISD is a stricter filter
  on the same failed population, so the honest prior is unfavorable and
  trade count will likely be thin (possibly below the 60-trade Stage 0
  floor regardless of expectancy). The spec's own recommendation:
  "specify it (done), but rank it below CRT. Build it only if the
  ablation on `inverse_fvg` is worth revisiting."
- **Files affected:** Same shape as item 2 (new `engines/e07_technical/`
  module).
- **Dependencies:** Item 2 (CRT) should land first per the spec's own
  ranking.
- **Complexity:** Medium, same as CRT.
- **Risk:** Low (additive, same E24→E26→promotion gate).
- **Testing requirements:** Same as item 2, plus the spec's own
  requirement to "report trade count prominently" since thin-sample
  unmeasurability, not wrongness, is its most likely failure mode.
- **Expected benefit:** Low-to-moderate, honestly stated by the spec
  itself — build for completeness/curiosity, not high expectation.

### 7. Extend colorblind-safe direction/P&L rendering to the original dashboard
- **Source:** Internal finding, Phase 12's own UI audit — `dashboard/
  index.html` differentiates buy/sell and P&L by color only.
- **Reason:** Phase 12 fixed this in all 6 NEW pages (`dirBadge()`/
  `pnlValue()` in `dashboard/shared/common.js`) but could not touch
  `dashboard/index.html` itself (Rule 9, binding for this pass). The
  original 5-page SPA — the platform's primary, most-used dashboard
  surface — still has the gap the brief calls mandatory to fix.
- **Files affected:** `dashboard/index.html` (explicitly off-limits
  without new authorization), or a full replacement file if the owner
  prefers a clean cutover to the same shared tokens/helpers Phase 12
  built.
- **Dependencies:** Explicit owner sign-off to edit/replace the one file
  Rule 9 protected this whole session.
- **Complexity:** Medium (swap `.tag.bullish/.negative`/`.positive` call
  sites for `dirBadge()`/`pnlValue()` across ~2000 lines of inline JS;
  mechanical but needs care not to break the 32 existing endpoint
  integrations).
- **Risk:** Medium — this is the file every other change this session
  was told never to touch; any edit needs the same Playwright-verified,
  byte-diffed discipline the original 2026-08-21 Aurora redesign used.
- **Testing requirements:** Live browser verification (Playwright or
  manual) confirming zero console errors and identical underlying data
  before/after, specifically because this file has no automated test
  coverage of its own.
- **Expected benefit:** Closes the brief's colorblind-safety mandate on
  the dashboard surface real users actually see first, not just the new
  Phase 12 pages.

### 8. Black-Litterman / volatility-target forms on the Portfolio page
- **Source:** Internal finding, Phase 12's own scope note in
  `dashboard/pages/portfolio.html`.
- **Reason:** Both routes are real and already work
  (`POST /api/v1/portfolio/black-litterman`, `.../volatility-target`) but
  need caller-supplied view matrices (P/Q) or a weight vector that don't
  suit a quick form — deliberately left as an API-only capability with an
  in-page note rather than a bad form.
- **Files affected:** `dashboard/pages/portfolio.html` only.
- **Dependencies:** A real UI design decision for how a non-technical
  form collects a P/Q view matrix (e.g., "I believe GOLD will outperform
  SILVER by X%" style structured inputs translated to P/Q under the
  hood) — genuine design work, not a mechanical add.
- **Complexity:** Medium-high (the hard part is the form design, not the
  API call).
- **Risk:** Low (additive to an already-shipped page).
- **Testing requirements:** Real-data verification that the constructed
  P/Q matches user intent for a couple of hand-checked cases.
- **Expected benefit:** Completes Portfolio Engine's UI coverage of E31's
  full real capability set.

### 9. Revisit the 3 newly-flagged copyleft dependencies if distribution posture ever changes
- **Source:** Internal finding, `docs/DEPENDENCY_LICENSE_AUDIT.md`
  (Phase 14) — pymupdf (AGPL-3.0/commercial dual), ebooklib (AGPL-3.0+),
  wbdata (GPL-2.0+), all confirmed actually imported in live engine code.
- **Reason:** Currently low-risk because this platform is private,
  single-user, and never distributed/hosted/sold — but that's a
  POSTURE, not a permanent guarantee, and the audit explicitly says to
  revisit if it changes.
- **Files affected:** `engines/e01_knowledge/loaders.py` (pymupdf/
  ebooklib), `engines/e04_macro/engine.py` (wbdata), `requirements.txt`.
- **Dependencies:** A decision to actually change distribution posture
  first — this item is conditional, not scheduled.
- **Complexity:** Medium per swap (pymupdf → `pypdf`/keep `pdfplumber`;
  wbdata → a direct World Bank API client; ebooklib has no obvious
  drop-in replacement, narrow feature, may just be dropped).
- **Risk:** Low today; only relevant at all if triggered by the
  dependency above.
- **Testing requirements:** Full E01/E04 regression if ever swapped.
- **Expected benefit:** Removes a licensing constraint that would only
  ever matter if this platform is ever shared beyond its current
  single-user, private use.

### 10. Implement E25 Strategy Lifecycle's "retired" stage
- **Source:** Internal finding, verified via this session's own Phase 13
  engine-purpose audit (`docs/ARCHITECTURE_SYNTHESIS.md`).
- **Reason:** E25 mechanically derives researched/live/validated/decaying
  stages from other engines' file outputs, but "retired" is an
  acknowledged, unimplemented gap in that state machine.
- **Files affected:** `engines/e25_strategy_lifecycle/engine.py`.
- **Dependencies:** A definition of what "retired" should mean
  mechanically (e.g., an override explicitly withdrawn, matching the
  precedent CLAUDE.md's "bottleneck audit" section already set when one
  live override was manually withdrawn).
- **Complexity:** Low-medium.
- **Risk:** Low (read-only classification engine, no live-signal impact).
- **Testing requirements:** Unit tests for the new state transition,
  same style as E25's existing tests.
- **Expected benefit:** Completes an already-mostly-built state machine.

---

## P3 — Optional

### 11. Reduce E44/E46 naming-vs-authority confusion
- **Source:** Internal finding, `docs/ARCHITECTURE_SYNTHESIS.md`
  (Phase 13).
- **Reason:** `e46_chief_risk_officer` has zero veto power (that's
  entirely E45's) and `e44_chief_investment_officer` is a thin narrative
  wrapper with no independent judgment — both already self-documented as
  such in their own docstrings, but the names alone invite exactly the
  misreading this synthesis had to explicitly correct.
- **Files affected:** Possibly just docstrings/naming; a rename is a
  bigger, riskier change than clarifying comments.
- **Dependencies:** None.
- **Complexity:** Low if docs-only; medium-high if an actual rename
  (touches registry keys, any API routes, tests referencing the engine
  IDs).
- **Risk:** Low if docs-only; a real rename risks breaking anything
  keyed on the current `engine_id` strings.
- **Testing requirements:** Full suite if renamed; none if docs-only.
- **Expected benefit:** Clarity, not functionality — genuinely optional.

### 12. Drop `vectorbt` from requirements.txt (declared, never imported)
- **Source:** Internal finding, `docs/DEPENDENCY_LICENSE_AUDIT.md`
  (Phase 14) — confirmed via grep, not imported anywhere in `engines/`,
  `core/`, or `api/`.
- **Reason:** Dead weight in the dependency tree, and its Commons-Clause
  license term is a real (if currently moot) constraint not worth
  carrying for an unused package.
- **Files affected:** `requirements.txt`, `pyproject.toml` if listed
  there too.
- **Dependencies:** Confirm no `research/` or `scripts/` one-off still
  uses it before removing (not checked in this pass — this item's own
  due diligence).
- **Complexity:** Trivial.
- **Risk:** Low, pending that one grep.
- **Testing requirements:** Full suite after removal.
- **Expected benefit:** Smaller, cleaner dependency surface.

### 13. AI/LLM layer
- **Source:** Internal finding, `docs/ARCHITECTURE_SYNTHESIS.md`
  (Phase 13) — the brief's own proposed "Supporting: ... AI/LLM Layer"
  currently has nothing behind it; every "committee"/"CIO"/"world model"
  -style engine is rule-based or template-narration, never an actual
  LLM call.
- **Reason:** Flagged as an observation, **not a recommendation** — this
  platform's whole design philosophy (Rule 21: "prefer deterministic
  algorithms for ICT/SMC concepts," and the same discipline applied
  throughout every phase this session touched) runs counter to
  introducing a non-deterministic, harder-to-audit generative layer
  without the owner deliberately deciding that trade-off is worth it.
- **Files affected:** Unscoped — depends entirely on what the owner would
  actually want an LLM to do, which has not been asked for anywhere in
  the brief or CLAUDE.md.
- **Dependencies:** An explicit decision and use case from the owner;
  this item should not be built speculatively.
- **Complexity:** Unknown until scoped.
- **Risk:** Unknown until scoped — likely touches explainability,
  determinism, and cost/latency trade-offs this codebase has avoided
  everywhere else.
- **Testing requirements:** Unknown until scoped.
- **Expected benefit:** Unknown — listed for completeness against the
  brief's own diagram, not because it's judged worth building.

---

## Explicitly not on this list

Per Phase 16's own rule ("do not duplicate functionality," "do not
rewrite working systems unnecessarily"): the 5 real, working `dashboard/
index.html` pages, E45's veto authority, E26's backtesting laboratory,
the E22/E24 research-mode split, and every other item Phase 13 flagged
as "preserve exactly as-is" are deliberately absent from this roadmap —
they are not gaps, they are the parts of the system already judged
superior to any proposed change.

---

**Stopping here per the brief's Phase 15 instruction.** Nothing above has
been implemented. Awaiting explicit approval on which item(s), if any,
to move into Phase 16.
