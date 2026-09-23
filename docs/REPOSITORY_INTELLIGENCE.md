# REPOSITORY_INTELLIGENCE.md — Phase 2

**Date:** 2026-09-13. **Basis:** direct source inspection of all 15 cloned repositories (Groups A-E)
under `external/`. This document restructures findings already verified and dated in
`docs/REPOSITORY_KNOWLEDGE_MAP.md` (Phase 3, organized by ICT/quant/risk/etc. category) and
`docs/REPOSITORY_FEATURE_MATRIX.md` (Phase 4, organized by feature) into the per-repository template
Phase 2 of `docs/UPGRADE_BRIEF.md` specifies. No new research was done to produce this file — every
claim below traces to one of those two documents, `docs/ICT_CONCEPT_DIFF.md`, or a dated CLAUDE.md
section; see those for the underlying evidence and methodology. Group F (6 UI repos) was never
cloned — see `REPOSITORY_KNOWLEDGE_MAP.md` §16 for why that is a deliberate decision, not a gap.

---

## Group A — ICT / SMC

### Repository: `NadirAliOfficial/STAR-EA-v11.20`
- **Category:** ICT/SMC
- **Purpose:** A retail MetaTrader 5 scalping EA implementing a large ICT/SMC concept library.
- **Architecture:** Single 51,396-line `.mq5` file. No module boundaries. Numbered fix comments
  (`FIX#503`, `FIX#510`) throughout indicate heavy iterative patching in place.
- **Key modules:** None (monolithic) — functional groupings by comment only.
- **Key algorithms:** `DetectBreakerBlocks`, `InitializeKillzones`/`IsInKillzone`,
  `DetectOTEZones`/`CheckOTEEntrySignal`, `DeriveScenarioProfile` (a named-scenario regime gate
  above technique signals), a hand-rolled neural network (`ForwardPass`/`BackwardPass`/
  `ApplySoftmax`) trained live inside the EA.
- **Useful features:** Breaker-block detection (not in E07 at the time this was read); per-killzone
  session-quality tiers; the scenario-gate-above-techniques design pattern.
- **Potential reuse (code):** None — MQL5, MQL → PYTHON TRANSLATION REQUIRED for anything ported.
- **Potential reimplementation (concept only):** Breaker blocks (built — `OrderBlock.breaker` in
  E07), killzones (built, and IANA-`zoneinfo`-based, better than STAR-EA's manual DST table), CRT
  (Candle Range Theory — built `engines/e07_technical/crt.py` 2026-09-13 per `docs/
  ICT_SPEC_PHASE5.md`; ablated solo at 4h and found MIXED, not a general edge: negative on GOLD
  (−0.161) and BTCUSD (−0.084), positive and well-sampled on ETHUSD (+0.467, 153 trades, PF 1.35).
  Not added to `DEFAULT_STRATEGY_GRID` on this result — see `ICT_SPEC_PHASE5.md` §1.11.1).
- **Dependencies:** MetaTrader 5 runtime only.
- **License:** MIT.
- **Security concerns:** None found — no `WebRequest`, no credential harvesting, no license-key
  check. The in-EA neural network is a correctness/reliability concern (untested, trained live) but
  not a security one.
- **Code quality:** Low structurally (single file, no modules) but functionally dense and real —
  not templated or fabricated.
- **Testing quality:** None visible in the repo itself.
- **Performance:** Not benchmarked; not relevant (MQL5, not portable).
- **Compatibility with Titan X:** High conceptually, zero directly (language barrier + this
  project's own no-Selenium/no-broker-automation stance is unrelated but reinforces "adapt the
  concept, not the code").
- **Red flags:** The live-trained neural network (`InitializeNeuralNetwork` etc., 33 references) —
  unverifiable and inappropriate to port regardless of language.
- **Decision:** `ADAPT` (concepts only) for breaker blocks (done) and killzones (done, and improved
  on); CRT `REIMPLEMENT` done, ablated, mixed result (not promoted); `REJECT` the neural network entirely.

### Repository: `manuelinfosec/profittown-sniper-smc`
- **Category:** ICT/SMC
- **Purpose:** Claims a Python SMC (BOS/CHoCH) detection library.
- **Architecture:** 28 files. `internal/core/trade_engine.py` and `internal/core/market_scanner.py`
  are both **0 bytes**. The file named `structure.py` is dominated by a Plotly visualization
  function; actual detection logic is 36 lines.
- **Key modules:** `shared/rules/structure.py` (the only file with real logic).
- **Key algorithms:** `detect_bos()` — but this is a **Donchian channel breakout mislabeled as Break
  of Structure** (`if last_close > swing_high: return 'bullish'` against a rolling max/min, not a
  confirmed swing-point structure violation).
- **Useful features:** None found.
- **Potential reuse (code):** None.
- **Potential reimplementation (concept only):** None — offers neither a new concept nor a better
  implementation than E07's existing, correct BOS/CHoCH.
- **Dependencies:** pandas (imported three times redundantly in one file), Plotly.
- **License:** **None** — no LICENSE file, all rights reserved by default.
- **Security concerns:** None found, but irrelevant given the license blocks reuse regardless.
- **Code quality:** Poor — zero-byte core files, `print()` inside a detection function (unusable as
  a library), a mislabeled algorithm.
- **Testing quality:** None found.
- **Performance:** Not assessed — not viable regardless.
- **Compatibility with Titan X:** None — E07 `smart_money` already has correct BOS/CHoCH and
  `donchian_breakout` already exists as its own named E24 strategy.
- **Red flags:** No license; a core algorithm that doesn't implement what it claims to.
- **Decision:** `REJECT`.

### Repository: `mahmoud20138/Tradecraft`
- **Category:** ICT/SMC (per the brief's own description) — actually a Claude Code skills plugin.
- **Purpose:** The brief describes it as providing "ICT vocabulary reference, market structure,
  scanner scoring, Wyckoff, Power of 3, PD arrays, CISD." **This is a mis-attribution** (see
  `REPOSITORY_KNOWLEDGE_MAP.md` §19) — it is a Claude Code skills/documentation plugin, not a
  trading library, and ranges far outside trading (`stripe-best-practices`, `video-gen`,
  `notion-sync`).
- **Architecture:** 184 files: 177 markdown (`SKILL.md` files), 2 Python.
- **Key modules:** `skills/ict-smart-money/`, `skills/ict-trading-tool/`,
  `skills/market-structure-bos-choch/`, `skills/liquidity-analysis/`, `skills/smc-python-library/`,
  `skills/mtf-confluence-scorer/`, `skills/risk-of-ruin/`, `skills/drawdown-playbook/`,
  `skills/trade-journal-analytics/`, `skills/session-profiler/`.
- **Key algorithms:** None — every skill is prose documentation, not executable detection logic.
  One correction found on re-check: `skills/ict-smart-money/SKILL.md` DOES contain a full
  "CISD — Change in State of Delivery" prose section (missed on an initial directory-name-only
  search), specified into `docs/ICT_SPEC_PHASE5.md` §2 as a result. Power of 3, PD arrays, and
  Wyckoff are confirmed absent from this repo despite the brief's attribution.
- **Useful features:** CISD's prose definition (the one real find); the vocabulary/documentation
  itself as a reference.
- **Potential reuse (code):** None — there is essentially no code.
- **Potential reimplementation (concept only):** CISD, composable from existing FVG/IFVG/
  displacement primitives — built `engines/e07_technical/cisd.py` 2026-09-13, ablated solo at 4h:
  GOLD −0.144 (123 trades), BTCUSD +0.053 (168 trades, PF 1.05), ETHUSD +0.130 (158 trades, PF
  1.07). Sample sizes were healthy (contrary to the spec's own prediction of a likely-thin sample)
  but expectancy is weak/mixed — negative on GOLD, barely above breakeven on the other two. Not
  added to `DEFAULT_STRATEGY_GRID` on this result (see `ICT_SPEC_PHASE5.md` §2.7).
- **Dependencies:** None (documentation only).
- **License:** MIT.
- **Security concerns:** **`ip-rotation` skill** — a block-evasion technique, flagged as violating
  this project's own standing no-proxy-evasion rule. Not adopted.
- **Code quality:** N/A (not a code repository in practice).
- **Testing quality:** N/A.
- **Performance:** N/A.
- **Compatibility with Titan X:** Documentation/reference only — cannot satisfy Phase 5's
  requirement for deterministic, algorithmic specifications on its own.
- **Red flags:** The `ip-rotation` skill; three of the brief's four attributed concepts for this
  repo (Power of 3, PD arrays, Wyckoff) are simply not present.
- **Decision:** CISD `REIMPLEMENT` done, ablated, mixed/weak result (not promoted); `REJECT` the
  `ip-rotation` skill outright.

### Repository: `francomascareloai/EA_SCALPER_XAUUSD`
- **Category:** ICT/SMC, scalping/XAUUSD-specific.
- **Purpose:** A gold-scalping MetaTrader EA with a killzone/session-quality system.
- **Architecture:** MQL5, single large EA (license-blocked from a full download — classified via a
  405 KB blobless clone metadata pull, 1,054 files / 549 MQL, sufficient to classify without the
  full 1.14 GB).
- **Key modules:** Killzone/session-quality tiering with a day-of-week axis (richer than a flat
  time-window gate).
- **Key algorithms:** Session-quality-tiered killzone classification.
- **Useful features:** The tiered killzone design (day-of-week axis) — read as a design reference
  only.
- **Potential reuse (code):** None — license-blocked.
- **Potential reimplementation (concept only):** Considered for killzones; Titan X's own
  `engines/e07_technical/killzones.py` (built from STAR-EA's simpler design plus real IANA timezone
  data) was judged sufficient and already superior on the DST-correctness axis this repo doesn't
  attempt.
- **Dependencies:** MetaTrader 5 runtime.
- **License:** **PolyForm Noncommercial 1.0.0** (the brief's brief recorded "NOASSERTION," which was
  wrong — corrected on direct inspection 2026-09-13).
- **Security concerns:** None found in the metadata pulled; full source not downloaded.
- **Code quality:** Not assessed at the code level (license-blocked before that mattered).
- **Testing quality:** Not assessed.
- **Performance:** Not assessed.
- **Compatibility with Titan X:** N/A — license forbids commercial use.
- **Red flags:** Ships its own `TRADING_RESTRICTIONS.md`, explicitly forbidding even
  **broker-connected demo trading**, a step beyond a normal noncommercial license.
- **Decision:** `REJECT` for code; `INSPIRE ONLY` for the killzone-tiering design idea (not acted
  on — Titan X's own implementation already covers the DST-correctness gap this repo doesn't solve).

---

## Group B — Quant

### Repository: `je-suis-tm/quant-trading`
- **Category:** Quant strategies.
- **Purpose:** A collection of 12 root trading strategies plus sub-projects.
- **Architecture:** 7,818 LOC, Python, one file per strategy, no shared framework.
- **Key modules:** Dual Thrust, Heikin-Ashi, London Breakout, Pair trading, Parabolic SAR, Awesome
  Oscillator, Shooting Star, Options Straddle, VIX Calculator, MACD/RSI/Bollinger pattern strategies.
  Sub-projects present but uninspected: Monte Carlo, Oil Money, Ore Money, Smart Farmers.
- **Key algorithms:** Each strategy is a standalone, readable rule — no novel architecture beyond
  the strategy logic itself.
- **Useful features:** Dual Thrust and Heikin-Ashi (already ported and live in Titan X, predating
  this audit pass). London Breakout, Pair trading, Parabolic SAR, Awesome Oscillator, Shooting Star
  do not overlap the existing E24 grid.
- **Potential reuse (code):** Yes — Apache-2.0 permits direct reuse. London Breakout is the
  highest-priority remaining candidate (session-breakout, aligns with existing killzone/session
  work).
- **Potential reimplementation (concept only):** N/A — license already permits code reuse directly.
- **Dependencies:** pandas/numpy-level, no heavy framework.
- **License:** Apache-2.0.
- **Security concerns:** None found.
- **Code quality:** Adequate — straightforward, readable strategy scripts, not production-hardened.
- **Testing quality:** Minimal/none visible per strategy.
- **Performance:** Not benchmarked; strategies are simple enough that performance is not a concern.
- **Compatibility with Titan X:** High (license, language, and paradigm all compatible) — but every
  candidate must still clear E26 + Stage 0 like any E24 grid entry (Rule 3).
- **Red flags:** None.
- **Decision:** `KEEP EXISTING` (Dual Thrust, Heikin-Ashi, and the 3 MACD/RSI/Bollinger overlaps);
  `ADAPT` (London Breakout — P1; Pair trading, Parabolic SAR, Awesome Oscillator, Shooting Star —
  P2/P3, none promoted yet, none validated).

### Repository: `freqtrade/freqtrade`
- **Category:** Backtesting / strategy framework.
- **Purpose:** A full-featured, widely-used crypto trading bot with a mature strategy/backtest
  architecture.
- **Architecture:** Plugin-style `IStrategy` interface separating indicator population, entry/exit
  signal logic, and ROI/stoploss/trailing rules into distinct, overridable methods.
- **Key modules:** `custom_stoploss`/`custom_roi` hooks; `@informative` multi-timeframe data merge
  decorator; pluggable hyperopt loss functions; execution hooks (`confirm_trade_entry`,
  `order_filled`, `custom_entry_price`).
- **Key algorithms:** `sample_strategy.py`'s RSI-cross entry gated by TEMA/Bollinger-Band guards —
  reimplemented rule-for-rule (not copied) as `freqtrade_rsi_tema_bb` in
  `engines/e24_strategy_research/plugins/`.
- **Useful features:** Barrier-aware exit simulation (stoploss/ROI actually tested inside the
  backtester, not signal-flip-only) — the **single highest-value finding across all 15 repos**: it
  closes a real, previously-documented E26 gap (backtest exits were signal-flip only, never testing
  E51's own published stop/target levels). `@informative` multi-timeframe merge parallels what E02's
  own resampling already does.
- **Potential reuse (code):** None — GPL-3.0 forbids it.
- **Potential reimplementation (concept only):** `custom_stoploss`/`custom_roi`-style barrier-aware
  exits — **built** as E26's opt-in `stop_atr_mult`/`tp_atr_mult` parameters (see CLAUDE.md's
  "E26 gains opt-in barrier exits" section), which found barriers make every live override's
  numbers WORSE, a real and significant finding. The `sample_strategy.py` RSI/TEMA/BB rule — built,
  live, and now Titan X's best validated 1h strategy on 4 assets (SILVER, ETHUSD, SP500, BTCUSD),
  including the platform's first-ever validated commodity edge.
- **Dependencies:** ccxt, pandas, a substantial framework footprint.
- **License:** **GPL-3.0** — copyleft, incompatible with this MIT/Apache stack for direct code.
- **Security concerns:** Execution hooks that place real orders — **violates Rule 5** (no execution
  engine) if adopted as-is; correctly rejected wholesale, only the barrier-exit and rule CONCEPTS
  were extracted.
- **Code quality:** High — mature, widely-used, well-tested open-source project.
- **Testing quality:** High (extensive upstream test suite, not inspected in depth here since no
  code was reused).
- **Performance:** Not benchmarked against Titan X directly — irrelevant since only concepts were
  taken.
- **Compatibility with Titan X:** High conceptually, zero directly (GPL).
- **Red flags:** Execution hooks (Rule 5 conflict) — the entire execution layer was correctly never
  touched.
- **Decision:** `INSPIRE ONLY` — and unusually productive for it: two real, shipped, validated
  outcomes (barrier-exit measurement, `freqtrade_rsi_tema_bb`) came from concept extraction alone.

### Repository: `mementum/backtrader`
- **Category:** Backtesting framework.
- **Purpose:** A general-purpose Python backtesting engine.
- **Architecture:** An analyzer pattern — pluggable metric-collector objects attached to a backtest
  run, rather than metrics computed inline.
- **Key modules:** The analyzer/observer subsystem.
- **Key algorithms:** N/A — this is a framework, not a strategy source.
- **Useful features:** The analyzer pattern itself (clean separation of metric computation from
  simulation).
- **Potential reuse (code):** None — GPL-3.0.
- **Potential reimplementation (concept only):** Considered and declined — E26 already computes its
  metrics inline with no measurable gap versus the analyzer pattern; no real gain identified.
- **Dependencies:** Standard Python data-science stack.
- **License:** **GPL-3.0**.
- **Security concerns:** None found.
- **Code quality:** High — mature, widely used.
- **Testing quality:** High (upstream).
- **Performance:** Not benchmarked against Titan X — declined before that became relevant.
- **Compatibility with Titan X:** Architecturally compatible in concept; GPL blocks code reuse.
- **Red flags:** None.
- **Decision:** `INSPIRE ONLY`, declined — no action taken, real structural option with no
  measurable gain over what E26 already does.

### Repository: `QuantConnect/Lean`
- **Category:** Backtesting / algorithmic trading platform.
- **Purpose:** A full institutional-grade algorithmic trading engine (data abstraction, portfolio
  construction, parallel research).
- **Architecture:** Large C# solution (`Algorithm`, `Algorithm.Framework`, `Brokerages`, `Api`,
  `Common`, `Compression`, and more) — 573 MB.
- **Key modules:** Not read in depth — declined on cost/benefit before deep inspection (see below).
- **Key algorithms:** Not assessed in depth.
- **Useful features:** Parallel-search architecture was the stated reason for interest.
- **Potential reuse (code):** None — C#, this platform is Python.
- **Potential reimplementation (concept only):** Declined. E24 already has a MEASURED, working
  parallel grid-search (`_PoolManager` with rebuild-on-worker-death, 2.46x speedup on a real 29-asset
  4h sweep) — reading Lean's C# parallel-search design would not improve a Python design this
  project has already built and benchmarked against real data.
- **Dependencies:** .NET runtime, large.
- **License:** Apache-2.0 (permits reuse in principle).
- **Security concerns:** Not assessed — declined before that became relevant.
- **Code quality:** Presumed high (major, actively maintained institutional project) — not verified
  directly.
- **Testing quality:** Not assessed.
- **Performance:** Not benchmarked against Titan X.
- **Compatibility with Titan X:** Low practically (different language) despite a permissive license.
- **Red flags:** None identified — simply not pursued.
- **Decision:** `INSPIRE ONLY`, declined on cost/benefit, not availability or license.

### Repository: `WayneDW/Sentiment-Analysis-...`
- **Category:** Sentiment / news.
- **Purpose:** The brief describes this as providing "financial sentiment, Loughran-McDonald
  lexicon, event-driven pipeline." **This is a mis-attribution**, confirmed on direct inspection.
- **Architecture:** 10 files, a from-scratch PyTorch CNN text classifier.
- **Key modules:** `main.py` (CLI/training driver), `model.py` (the CNN), `tokenize_news.py`,
  `create_label.py`, `util.py`.
- **Key algorithms:** A CNN-based financial-news classifier (128-dim embeddings, 6,000-word
  vocabulary, SGLD-regularized training) over one-hot-encoded Reuters headlines — **not**
  Loughran-McDonald (that name appears only in the README's "future work" and reference sections,
  never implemented).
- **Useful features:** None beyond the general "event-driven pipeline shape," which E03/E09 already
  have their own version of.
- **Potential reuse (code):** Permitted by license but not worthwhile — see decision.
- **Potential reimplementation (concept only):** None identified — the model itself is inferior to
  what already exists (see compatibility).
- **Dependencies:** PyTorch, numpy.
- **License:** MIT.
- **Security concerns:** None found.
- **Code quality:** Dated (2017-era idioms) but functional; requires training data this project does
  not have.
- **Testing quality:** Not assessed — irrelevant to the decision.
- **Performance:** Not benchmarked — the architecture itself (a from-scratch, untrained-here CNN) is
  categorically weaker than what's already in production.
- **Compatibility with Titan X:** Low-value — **E09 already uses FinBERT** (`ProsusAI/finbert`), a
  modern, pretrained financial-domain transformer requiring no training data of its own, strictly
  more capable on every relevant axis.
- **Red flags:** None beyond the brief's own mis-attribution of what this repo contains.
- **Decision:** `REJECT`.

---

## Group C — Risk

### Repository: `youcefbibo53/PropGuard-Trailing-Equity-Armor`
- **Category:** Risk management.
- **Purpose:** Claims to be a trailing-equity/drawdown-protection tool.
- **Architecture:** Six files total: `index.html`, `README.md`, two SVGs, a GitHub Actions workflow,
  a stamp file. **Zero `.py`/`.mq4`/`.mq5`/`.js`/`.ts` files.**
- **Key modules:** None — no real code exists.
- **Key algorithms:** None.
- **Useful features:** None.
- **Potential reuse (code):** None.
- **Potential reimplementation (concept only):** None — there is no real mechanism to extract a
  concept from.
- **Dependencies:** N/A.
- **License:** None.
- **Security concerns:** **Confirmed malware.** An hourly cron GitHub Action fabricates commit
  activity (random-named files, hard-coded word-list commit messages). `index.html` contains two
  base64 blobs that XOR-decrypt each other and `document.write()` the result — a fake GitHub UI
  offering `ecore-project.zip` from `unlocktool.click` (unrelated to this repo), with forged trust
  badges ("GitHub Verified · Provenance," "SLSA level 3," "ClamAV + 5 engines (0 threats)") and fake
  star/fork counts. Decoded entirely offline in Python; nothing was executed, no browser opened, the
  URL was never visited.
- **Code quality:** N/A — no functional code.
- **Testing quality:** N/A.
- **Performance:** N/A.
- **Compatibility with Titan X:** None.
- **Red flags:** Everything above — this is the definitive red flag case.
- **Decision:** `REJECT` — malware.

### Repository: `bipbopcompany-droid/Risk-Nexus-Command`
- **Category:** Risk management.
- **Purpose:** Same claimed purpose as PropGuard above.
- **Architecture:** Byte-identical structure to PropGuard after name normalization — same six files,
  same fabricated-activity workflow.
- **Key modules / algorithms / features:** None — same finding as PropGuard.
- **Potential reuse / reimplementation:** None.
- **Dependencies:** N/A.
- **License:** None.
- **Security concerns:** **Confirmed malware**, identical mechanism to PropGuard (different product
  name in the fake UI: "Sovereign Order Nexus" vs. "TradeShield Protocol," otherwise the same
  obfuscated-payload/forged-badge pattern).
- **Code quality / Testing quality / Performance:** N/A.
- **Compatibility with Titan X:** None.
- **Red flags:** Templated sibling of a confirmed-malware repo.
- **Decision:** `REJECT` — malware. **Consequence for Phase 8:** no mechanism exists to compare
  against E45; the genuine gaps (trailing equity drawdown zones, kill switch) were built from first
  principles instead (see CLAUDE.md's Phase 8 section — done 2026-09-13).

---

## Group D — Journal

### Repository: `Eleven-Trading/TradeNote`
- **Category:** Trade journal.
- **Purpose:** A full-featured trading journal web application.
- **Architecture:** Vue/JS, 298 files, 29,450 LOC.
- **Key modules:** An 11-axis trade-grouping/analytics engine.
- **Key algorithms:** Generic, cross-category tagging rather than several separate single-purpose
  tag tables.
- **Useful features:** The unified-tag-category pattern.
- **Potential reuse (code):** None — GPL-3.0.
- **Potential reimplementation (concept only):** **Built** — `TradeTag`'s unified `category` field
  (`rule_adherence`/`behavioral`/`psychology`) is this pattern, reimplemented from the concept, not
  the GPL source.
- **Dependencies:** Vue/JS web stack.
- **License:** **GPL-3.0**.
- **Security concerns:** None found.
- **Code quality:** Substantial, real, functioning application.
- **Testing quality:** Not assessed in depth.
- **Performance:** Not assessed — irrelevant, no code reused.
- **Compatibility with Titan X:** Concept-compatible; GPL blocks direct reuse; also JS/Vue vs.
  Titan X's static-HTML dashboard.
- **Red flags:** None.
- **Decision:** `INSPIRE ONLY` — done; the tag-category concept shipped in `TradeTag`.

### Repository: `tradicted/tradicted-journal`
- **Category:** Trade journal.
- **Purpose:** A rule-checklist-focused trading journal.
- **Architecture:** TypeScript/Electron, 72 files, 1,205 LOC — small, a rule-checklist app rather
  than a full journal.
- **Key modules:** A pre-trade rule checklist UI.
- **Key algorithms:** None distinctive — the checklist is user-filled, not computed.
- **Useful features:** The `negative: boolean` convention on psychology-style tags.
- **Potential reuse (code):** Permitted by license (MIT) but not taken directly — see decision.
- **Potential reimplementation (concept only):** The `negative` boolean convention — **adopted**
  directly into `TradeTag.negative`.
- **Dependencies:** Electron/TypeScript stack.
- **License:** MIT.
- **Security concerns:** None found.
- **Code quality:** Adequate for its scope.
- **Testing quality:** Not assessed in depth.
- **Performance:** Not assessed — irrelevant.
- **Compatibility with Titan X:** High license-wise; low practically (Electron desktop app vs. this
  platform's API+dashboard shape).
- **Red flags:** **A real, confirmed bug in the reference implementation**: its own pre-trade
  checklist UI never actually PERSISTS what got checked — `rules_followed: null` is hardcoded at
  trade-creation time in its own source. Titan X's `mistake_rule_definitions`/`mistake_tagging.py`
  deliberately evaluates every rule AUTOMATICALLY from data already captured instead, specifically
  to avoid this exact failure mode.
- **Decision:** `INSPIRE ONLY` (the `negative` field convention); the checklist-UI PATTERN itself was
  explicitly rejected in favor of automatic rule evaluation, precisely because of the bug found here.

---

## Group E — Indian options

### Repository: `pramakrishn/express-option-chain`
- **Category:** Indian options / option chain.
- **Purpose:** Kite Connect-based NSE option chain ingestion with Redis tick storage.
- **Architecture:** 952 LOC, Python. Clean separation: `kite_connector`, `option_chain`,
  `option_stream`, `instrument_manager`, `redis_helper`.
- **Key modules:** `instrument_manager` (separated from the broker connector itself) —
  **the exact adapter-vs-hard-coded-broker pattern** Phase 10 of the brief asks for.
- **Key algorithms:** Standard option chain assembly (strike/expiry grouping); explicitly disables
  underlying-value lookup for any symbol containing "NIFTY" (a real, confirmed gap in this repo,
  not a feature).
- **Useful features:** The connector/instrument-manager/stream architectural split; Redis tick
  storage for option-chain data (Titan X has Redis with a circuit breaker, but no tick-level
  storage — a real, additive gap, not yet built).
- **Potential reuse (code):** Permitted (MIT) but not taken directly — Titan X's own
  `core/data_providers/kite_option_chain.py` was built from scratch instead, since this repo
  explicitly can't resolve NIFTY/BANKNIFTY (the exact capability needed).
- **Potential reimplementation (concept only):** The connector/adapter split — **built** as
  `OptionChainProvider` (a `runtime_checkable` Protocol), closing Phase 10's explicit "do not
  hard-code a single broker" requirement (done 2026-09-13, see CLAUDE.md's Phase 10 section).
- **Dependencies:** kiteconnect SDK, Redis.
- **License:** MIT.
- **Security concerns:** None found.
- **Code quality:** Adequate, real, functioning for its scope.
- **Testing quality:** Not assessed in depth.
- **Performance:** Not benchmarked.
- **Compatibility with Titan X:** High architecturally; the specific NIFTY/BANKNIFTY gap it left
  unfilled is exactly what Titan X's own implementation closes.
- **Red flags:** Disables the exact index lookups (NIFTY) this platform needs — confirmed by
  reading the code directly, not assumed.
- **Decision:** `IMPROVE EXISTING` — Titan X's own from-scratch implementation supersedes this repo
  for the core capability; its architecture (adapter split) and Redis-tick-storage idea remain
  `INSPIRE ONLY`/`ADAPT` respectively (tick storage not yet built).

### Repository: `anurag-roy/kite-option-chain`
- **Category:** Indian options / option chain UI.
- **Purpose:** A Next.js UI for viewing grouped option-chain instruments (bid/ask/LTP display).
- **Architecture:** 571 LOC, Next.js/React.
- **Key modules:** A grouped-instrument display component.
- **Key algorithms:** None distinctive — a display layer, not a computation engine. Never touches
  index instruments at all (equity-watchlist only).
- **Useful features:** None beyond the general "what an option chain UI should show" reference.
- **Potential reuse (code):** None practical — this platform's dashboard is static HTML, not React/
  Next.js (see Group F correction, `REPOSITORY_KNOWLEDGE_MAP.md` §16).
- **Potential reimplementation (concept only):** The display fields it surfaces (bid/ask/LTP
  grouped by strike) informed what Titan X's own `/derivatives/india-option-chain` route returns,
  though no UI code was taken.
- **Dependencies:** Next.js, an unofficial `kiteconnect-ts` wrapper.
- **License:** MIT.
- **Security concerns:** None found.
- **Code quality:** Adequate for its scope.
- **Testing quality:** Not assessed.
- **Performance:** Not assessed.
- **Compatibility with Titan X:** Low practically (Next.js/React vs. static HTML dashboard).
- **Red flags:** Never supports index instruments (NIFTY/BANKNIFTY) at all — confirmed by reading
  the code, another real gap both audited option-chain repos shared.
- **Decision:** `INSPIRE ONLY` — no code or UI framework adopted.

---

## Cross-cutting summary (see `REPOSITORY_FEATURE_MATRIX.md` §10 for the full ranked list)

**Two of fifteen repos are confirmed malware** (Group C, both). **One repo has no usable license**
(profittown-sniper-smc). **One repo is license-blocked as noncommercial with an explicit
no-trading-use restriction** (EA_SCALPER_XAUUSD). **Three repos are GPL-3.0** (freqtrade,
backtrader, TradeNote) — `INSPIRE ONLY` in every case, and productively so for freqtrade
specifically (two real, shipped, validated outcomes from concept extraction alone). **Three of the
brief's own repository descriptions were factually wrong** (Tradecraft's attributed ICT concepts,
the sentiment repo's attributed Loughran-McDonald lexicon, and the "FastAPI + React" dashboard
premise) — each corrected on direct inspection rather than assumed correct.
