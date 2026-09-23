# REPOSITORY_KNOWLEDGE_MAP.md — Phase 3

**Date:** 2026-09-08. **Basis:** direct source inspection of cloned repositories, not READMEs.

> ## Coverage — updated 2026-09-13, all outstanding items closed
>
> Every repository the brief names (Groups A-E) is now cloned and inspected; Group F was a
> deliberate decision not to clone (see §16). No section below still reads `NO EVIDENCE YET`.
>
> | Group | Repos | Inspected | Status |
> |---|---|---|---|
> | A — ICT/SMC | 4 | **4** | EA_SCALPER_XAUUSD closed 2026-09-13 (§8) |
> | B — Quant | 5 | **5** | freqtrade/Lean/backtrader closed 2026-09-13 (§11); sentiment closed 2026-09-13 (§12, REJECTED -- E09's FinBERT is already superior) |
> | C — Risk | 2 | **2** | both REJECTED — malware |
> | D — Journal | 2 | **2** | schema-level read closed 2026-08-21 (§14) |
> | E — Indian options | 2 | **2** | `IMPROVE EXISTING`, now built (Phase 10, see CLAUDE.md) |
> | F — UI | 6 | **0 (by decision)** | deliberately not cloned -- shadcn already adopted, confirmed sufficient across two full redesign passes (§16) |
> | **Total (A-E)** | **15** | **15** | **0 outstanding** |
>
> This map is retained as a historical record of what each repository actually contained, not a
> live status board -- check CLAUDE.md's own dated sections for what was actually BUILT from these
> findings and when.

---

## 1. ICT

**Primary source: `NadirAliOfficial/STAR-EA-v11.20` — MIT, MQL5, a single 51,396-line `.mq5` file.**
**MQL → PYTHON TRANSLATION REQUIRED.**

Concept coverage, measured by symbol/comment frequency in the source:

| Concept | Hits | Implementation evidence |
|---|---|---|
| FVG / fair value gap | 1,040 | Densest concept in the file |
| Killzones / sessions | 837 | `InitializeKillzones`, `IsInKillzone`, `GetAdjustedKillzoneTimes`, `GetKillzoneQualityBonus`, `PassesKillzoneFilter`, `UpdateKillzoneStats`, `GetKillzoneWinRate` |
| OTE | 526 | `DetectOTEZones`, `CheckOTEEntrySignal`, `DrawOTEZones` |
| Order blocks | 461 | — |
| BOS | 436 | — |
| CRT (candle range theory) | 406 | Referenced in the scenario gate |
| AMD | 399 | — |
| Judas Swing | 379 | Referenced in the scenario gate |
| CHoCH | 356 | — |
| Breaker blocks | 261 | `DetectBreakerBlocks`, `DrawBreakerBlocks` |
| Liquidity | 204 | — |
| Mitigation | 150 | — |
| Premium / discount | 143 | — |
| Silver Bullet | 43 | Referenced in the scenario gate |
| PDH / PDL | 35 | — |
| Displacement | 18 | Thin |
| Equal highs / lows | 4 | Effectively absent |
| **Power of 3** | **0** | **Not present** |
| **CISD** | **0** | **Not present** |

**Scenario gate.** The EA has a `DeriveScenarioProfile` mechanism with numbered, named scenarios
(`MARKUP` / `MARKDOWN`, "Scenario 11 Transition"). A source comment records that BREAKER / JUDAS /
CRT / SB techniques originally **bypassed the scenario gate entirely and always returned
`allowed=true`** — i.e. the classifier was added after the techniques, as a retrofit. Useful as a
design signal: their own experience was that technique-level signals need a regime gate above them.

**Code-quality signal.** Numbered fix comments (`FIX#503`, `FIX#510`) throughout indicate heavy
iterative patching of a single monolithic file. No module boundaries.

**Red flags checked and clear:** no `WebRequest`, no credential harvesting, no license-key check.
Only two `#property link` entries to a website.

**Red flag found:** the EA contains a **hand-rolled neural network** in MQL5
(`InitializeNeuralNetwork`, `ForwardPass`, `BackwardPass`, `UpdateWeights`, `ApplySoftmax`,
`CalculateLoss`, `ExtractFeatures`, `NormalizeFeatures` — 33 references). Unverifiable, untested,
and trained inside a live EA. **Do not port.**

---

## 2. SMC

**`manuelinfosec/profittown-sniper-smc` — NO LICENSE, Python, 28 files.**

**Verdict: REJECT.** It is strictly weaker than the existing E07 `smart_money` module.

- `internal/core/trade_engine.py` — **0 bytes.**
- `internal/core/market_scanner.py` — **0 bytes.**
- `shared/rules/structure.py` contains `import pandas as pd` **three times**.
- The file named `structure.py` is dominated by a Plotly `visualize_bos()` function; the actual
  detection is 36 lines.

**The critical technical finding — `detect_bos` is not BOS:**

```python
lookback_period = df.iloc[-lookback-1:-1]
swing_high = lookback_period['high'].max()
swing_low  = lookback_period['low'].min()
if last_close > swing_high:  return 'bullish', swing_high
```

That is a **Donchian channel breakout**, not a Break of Structure. Real BOS requires swing-point
structure (a confirmed higher-high/higher-low sequence being violated), not a rolling extreme. It
also `print()`s from inside a detection function, so it is unusable as a library.

Titan X already has both: proper BOS/CHoCH in E07 `smart_money`, and `donchian_breakout` as an
explicit E24 strategy. This repo offers neither a new concept nor a better implementation.

**Licensing:** no LICENSE file — all rights reserved. Even the concepts should be reimplemented from
public ICT descriptions, not from this code.

---

## 3. Market Structure · BOS · CHoCH

- **STAR-EA:** BOS 436 / CHoCH 356 references — real coverage, MQL5, translation required.
- **profittown:** rejected (§2).
- **Tradecraft:** has a `market-structure-bos-choch` skill — prose documentation only (§13).
- **Existing:** E07 `smart_money` already implements BOS and CHoCH. **`CONFLICT` — do not
  reimplement.** **Closed 2026-09-08**: `docs/ICT_CONCEPT_DIFF.md` did the side-by-side diff --
  measured 26 of 28 brief-listed ICT concepts already implemented as working code (9 in
  `engines/e07_technical/`, 17 in `research/ict_concepts.py`), with real ablation results
  (`research/ablation_*.json`) on which ones carry measured edge. This is also what triggered Phase
  5's own rewrite (see `docs/UPGRADE_BRIEF.md`'s Phase 5 section and `docs/ICT_SPEC_PHASE5.md`).

---

## 4. FVG

STAR-EA's densest concept (1,040 references), including mitigation (150). E07 already implements
FVG. **`CONFLICT`.** Candidate genuinely-new sub-concepts: **inversion FVG** and **FVG
retracement** — both named in the brief's Phase 5 list; neither confirmed present in E07 nor
isolated in STAR-EA yet.

---

## 5. Order Blocks · Breaker Blocks

- Order blocks: STAR-EA 461 refs; **E07 already has them — `CONFLICT`.**
- **Breaker blocks: `DetectBreakerBlocks` / `DrawBreakerBlocks` in STAR-EA.** Not found in E07 by
  name during the Phase 1 audit. **Candidate genuinely new — highest-value ICT item identified so
  far.**

---

## 6. Liquidity

STAR-EA: 204 references. E07 `smart_money` already implements liquidity sweeps. **`CONFLICT`.**
Equal highs / equal lows are effectively **absent** from STAR-EA (4 hits), so that concept has no
source here despite appearing in the brief's Phase 5 list.

---

## 7. Killzones · Sessions

**The strongest genuinely-additive finding in Group A.** STAR-EA does not merely gate on session
windows — it maintains **per-killzone performance state**:

- `GetKillzoneQualityBonus(kzType)` — scores a signal by which killzone it fired in
- `UpdateKillzoneStats(kzIndex, isWin, pips)` and `GetKillzoneWinRate(kzIndex)` — running win-rate per killzone
- `GetAdjustedKillzoneTimes(...)` — DST/broker-offset adjustment

Titan X has `killzones` in E07, but the Phase 1 audit found no per-killzone win-rate feedback.
**Candidate new: killzone-conditional signal weighting.** Note the obvious hazard — a live-updating
win-rate that feeds signal scoring is a self-referential loop and would need to route through E24
research, never adjust live parameters (brief Phase 9's own rule).

Also relevant: **`London Breakout`** strategy in `je-suis-tm/quant-trading` (§10) — a session-based
breakout, directly comparable to the metals/FX London sweep work already in `research/`.

---

## 8. Scalping · XAUUSD

**Closed 2026-09-13** (was `NO EVIDENCE YET`). `francomascareloai/EA_SCALPER_XAUUSD` is cloned and
inspected. License is **PolyForm Noncommercial 1.0.0**, not the placeholder "NOASSERTION" the brief
recorded -- confirmed by reading `LICENSE` directly. It also ships its own `TRADING_RESTRICTIONS.md`,
which explicitly forbids even **broker-connected demo trading**, not just commercial use.

**Verdict: `INSPIRE ONLY`, and only partially.** The one genuinely transferable idea is its killzone
design: session-quality **tiers** plus a **day-of-week axis**, richer than a flat time-window gate.
Read as a design reference only -- the license plus the trading-restriction file make direct code
reuse a real legal problem for a live system, so nothing was ported. Titan X's own
`engines/e07_technical/killzones.py` (built from STAR-EA's simpler design instead, see §1/§7) uses
real IANA timezone data for DST-correct session windows, which this EA does not attempt.

---

## 9. Quant strategies

**`je-suis-tm/quant-trading` — Apache-2.0, Python, 7,818 LOC, 12 root strategies.**

Already ported and live: **Dual Thrust**, **Heikin-Ashi**.

Remaining ten, triaged against the existing E24 grid:

| Strategy | Overlaps existing? | Note |
|---|---|---|
| **London Breakout** | No | Session breakout — aligns with existing killzone/session work |
| **Pair trading** | No | Statistical arbitrage; no E24 equivalent |
| **Parabolic SAR** | No | Trailing-stop mechanism, not in E24 |
| **Awesome Oscillator** | No | Momentum indicator absent from E07 |
| **Shooting Star** | No | Single-candle pattern |
| **Options Straddle** | No | Would route through E13, not E24 |
| **VIX Calculator** | No | Volatility measure, not a strategy |
| MACD Oscillator | **Yes** — E24 `macd_cross` | Skip |
| RSI Pattern Recognition | **Yes** — E24 `rsi_mean_reversion` | Skip |
| Bollinger Bands Pattern Recognition | **Yes** — E24 `bollinger_reversion` | Skip |

Sub-projects present but uninspected: `Monte Carlo project`, `Oil Money project`, `Ore Money
project`, `Smart Farmers project`.

**Precedent worth respecting:** Dual Thrust earned promotion by *beating incumbents on real
backtests*, not by being in this repo. Rule 3 applies to all ten.

---

## 10. Indicators

E07 already covers EMA, RSI, ATR, MACD, ADX, Bollinger. New candidates from quant-trading: Awesome
Oscillator, Parabolic SAR (both already registered as E24 archetypes per `docs/
QUANT_ENGINE_EXTRACTION.md` -- neither has validated on any real sweep to date). **Closed
2026-09-13**: freqtrade is cloned and inspected (see §11) -- its indicator library is real but
**GPL-3.0**, concepts only, and its actual indicator SET substantially overlaps what E07 already
has natively.

---

## 11. Backtesting · Optimization · Walk-forward

**Closed 2026-09-13** (was `NO EVIDENCE YET`) -- all three cloned and read directly (not just
licenses), findings already recorded in `docs/QUANT_ENGINE_EXTRACTION.md` §6, pulled forward here:

| Repo | License | Consequence |
|---|---|---|
| freqtrade | **GPL-3.0** | Copyleft -- no code reuse. Its `freqtrade_rsi_tema_bb` RULE (not code) was reimplemented from scratch in `engines/e24_strategy_research/plugins/` and is now Titan X's **best validated 1h strategy on 4 assets**, including the platform's first-ever validated commodity edge (SILVER). `REIMPLEMENT`, already done. |
| backtrader | **GPL-3.0** | Its analyzer pattern (pluggable metric collectors over a backtest run) is genuinely clean -- E26 already computes its metrics inline, so this is a real structural option with no measurable gain over what exists. `INSPIRE ONLY`, declined. |
| QuantConnect/Lean | Apache-2.0 but **C#**, 573 MB | Stated relevance is architectural (data abstraction, parallel search, portfolio construction) -- but E24 already has a MEASURED 2.46x parallel sweep with its own `_PoolManager` rebuild-on-failure path (see CLAUDE.md's "Two real optimizations" section). Reading someone else's C# would not improve a Python design this project has already benchmarked. Declined on cost/benefit, not availability. |

Phase 7 of the brief is substantially **already implemented** independently of any of these three --
see `docs/STAGE0_FINDINGS.md` and the `CONFLICT` recorded in `docs/PROJECT_AUDIT.md` §11, plus this
session's own Phase 7 block-bootstrap/parameter-sensitivity work in CLAUDE.md.

---

## 12. Sentiment · News

**Closed 2026-09-13** (was `NO EVIDENCE YET`). `WayneDW/Sentiment-Analysis-...` is cloned and
inspected directly (`main.py`, `model.py`). **MIT license**, confirmed. Its actual contribution is
**not** the Loughran-McDonald lexicon the brief expected -- it is a from-scratch **CNN text
classifier in PyTorch** (128-dim embeddings, 6,000-word vocabulary, SGLD-regularized training),
requiring a labeled training set this project does not have, last meaningfully updated 2017.

**Verdict: `REJECT`.** Titan X's E09 already uses **FinBERT** (`ProsusAI/finbert`), a modern,
pretrained financial-domain transformer needing no training data of its own -- categorically more
capable than a 2017 from-scratch CNN on every axis (domain-specific pretraining, no training-data
requirement, active maintenance). Nothing here improves on what E09 already ships.

---

## 13. Risk management · Drawdown protection

## 🚨 **BOTH GROUP C REPOSITORIES ARE MALWARE. REJECT. DO NOT DOWNLOAD.**

`youcefbibo53/PropGuard-Trailing-Equity-Armor` and `bipbopcompany-droid/Risk-Nexus-Command`.

**Neither contains any code.** Six files each: `index.html`, `README.md`, two SVGs, a workflow, and
a stamp file. Zero `.py` / `.mq4` / `.mq5` / `.js` / `.ts` files across both repositories.

Evidence, all verified locally:

1. **Fabricated activity.** A GitHub Action runs hourly on cron, appends a timestamp line to a
   random-named file, and commits it with a message assembled from a hard-coded word list. The
   single visible commits — `"replace check #4565"`, `"export render #130"` — are its output.
2. **Templated siblings.** Both workflows are byte-identical after name normalisation. Both READMEs
   use a *different product name* than their own repository (`TradeShield Protocol`, `Sovereign
   Order Nexus`).
3. **Obfuscated payload.** `index.html` holds two base64 blobs; the script XOR-decrypts one with the
   other and injects the result via `document.write()`.
4. **Decoded payload is a fake GitHub UI** offering `ecore-project.zip` (claimed 134 MB) from
   **`https://unlocktool.click/`** — a domain unrelated to either project.
5. **Forged trust signals** on that page: "GitHub Verified · Provenance", "signed by:
   ecore/security", "SLSA level 3", "ClamAV + 5 engines (0 threats)", "AES-256", plus fake star and
   fork counts that do not match the real repository.

Point 5 is the substance: the page is built to defeat a careful reviewer's checks. Decoding was done
offline in Python — nothing executed, no browser opened, the URL was never visited.

**Consequence: Phase 8 (Risk Engine) has no reference sources.** The genuine E45 gaps identified in
Phase 1 — trailing equity drawdown, kill switch, green/yellow/red sizing zones — must be specified
from first principles. That is a better position than adapting fiction.

**Also flagged:** `Tradecraft` ships an **`ip-rotation`** skill. That is precisely the block-evasion
technique prohibited by the standing no-proxy rule. Do not adopt.

---

## 14. Journaling

| Repo | License | Size | Verdict |
|---|---|---|---|
| `Eleven-Trading/TradeNote` | **GPL-3.0** | 298 files, 29,450 LOC (Vue/JS) | **`INSPIRE ONLY`** — copyleft forbids code reuse. Schema and mistake-tagging *concepts* are extractable. |
| `tradicted/tradicted-journal` | MIT | 72 files, 1,205 LOC (TypeScript/Electron) | Code reuse permissible. Small — a rule-checklist app, not a full journal. |

**Closed 2026-08-21** (was "neither read at schema level yet") -- both read at schema level as part
of the self-improvement trade journal build. Real, specific findings:

- **`tradicted-journal`**: the strongest real reference for a rule-adherence checklist, but its own
  pre-trade checklist UI never actually PERSISTS what got checked (`rules_followed: null` hardcoded
  at trade-creation time in its own source) -- a real, confirmed bug in the reference repo, not
  something to copy. Titan X's own `mistake_rule_definitions`/`mistake_tagging.py` deliberately
  evaluates every rule AUTOMATICALLY from data already captured instead, so there is nothing for a
  user to forget to check. Its `negative: boolean` convention on psychology-style tags was adopted
  directly into `TradeTag.negative`.
- **`TradeNote`**: GPL-3.0, so `INSPIRE ONLY` per its own license row above -- its real contribution
  is a generic, cross-category tag model (its own 11-axis grouping engine) rather than three
  separate tag tables. `TradeTag`'s unified `category` field (`rule_adherence` / `behavioral` /
  `psychology`) is that pattern, reimplemented from the concept, not the GPL code.

Phase 9's requirements this resolved: rule-based mistake tagging (7 deterministic rules, now 9 with
this session's Kelly-sizing/disagreeing-layer additions), regime-at-entry and confluence-at-entry
(already denormalized onto `Trade`). MAE/MFE and skipped-signal tracking were NOT sourced from
either repo (neither implements them) -- built from scratch this session (real OHLCV-computed
MAE/MFE; `signal_conversion_rate`'s outer join for skipped signals), see CLAUDE.md's Phase 9 section.

---

## 15. Indian markets · Options · Option chain

| Repo | License | LOC | Contribution |
|---|---|---|---|
| `pramakrishn/express-option-chain` | MIT | 952 | Kite Connect ingestion + **Redis tick storage**. Modules: `kite_connector`, `option_chain`, `option_stream`, `instrument_manager`, `redis_helper`. Confirmed fields so far: `strike_price`, `expiry`. |
| `anurag-roy/kite-option-chain` | MIT | 571 | Next.js UI for grouped instruments / bid-ask-LTP display |

Both MIT, both small, both genuinely reusable. `express-option-chain`'s separation of
`instrument_manager` from `kite_connector` is the pattern the brief's `OptionChainProvider`
interface wants — **adapter, not hard-coded broker.**

Titan X already has `core/data_providers/kite_option_chain.py` and E13 derivatives, so this is
`IMPROVE EXISTING`, not new capability. Redis tick storage may be additive — Titan X has Redis
(`core/cache.py`, with a circuit breaker) but the Phase 1 audit did not find tick-level storage.

---

## 16. UI · Design systems · Accessibility

**Decision closed 2026-08-21** (item 5 of the outstanding checklist): no Group F repository was
ever cloned. All six are "reference only" in the brief, shadcn was already adopted, and two full
visual redesign passes ("Aurora" and "The Pit," see CLAUDE.md) were completed using only the
existing hand-written OKLCH token system -- confirming no second component library was ever needed.
"The Pit" was later rejected on its own visual merits and removed, but that is a design decision, not
evidence a Group F repo should have been consulted.

**Correction carried from Phase 1, still accurate:** the brief's premise here is wrong. The dashboard
is a single **3,145-line static `index.html`** — no `package.json`, no `src/`, no build step, **no
React**. shadcn is present as hand-written OKLCH CSS tokens, not as components. "Do not install a
second component library" is moot; there is no first one.

**Colour-blind safety (brief Phase 12) remains unverified** -- the Aurora/Pit redesigns changed the
palette but no accessibility audit (buy/sell and profit/loss distinguishable by lightness or shape,
not hue alone) has been run against either. Real, still-open gap for whenever Phase 12 is actually
worked.

---

## 17. Performance

**Closed 2026-09-13** (was "Lean's architecture is the plausible source and is uninspected"). Lean
was inspected (see §11) and explicitly declined on cost/benefit: E24's own parallel grid-search
(`_PoolManager`, measured 2.46x on a real 29-asset 4h sweep) is already a benchmarked, working
solution in the same language this codebase uses -- reading Lean's C# parallel-search architecture
would not improve a design already measured against real data. The binding constraint remains
research throughput (6-worker cap, ~149s per 167-candidate sweep after that optimization), a Titan X
architecture question, not a repository one.

---

## 18. Architecture

Contributions identified, now complete across all inspected repos:

- **STAR-EA — negative lesson.** A 51,396-line single file with numbered fix comments is what Titan X's engine separation exists to avoid. Its *scenario gate above technique signals* is the one transferable idea, and Titan X already has the equivalent in E08 regime + E51 confluence.
- **express-option-chain — positive pattern.** Connector / instrument-manager / stream separation, matching the adapter interface Phase 10 wants -- and now actually built: `OptionChainProvider` (a `runtime_checkable` Protocol) in `core/data_providers/kite_option_chain.py`, closing this exact gap (see CLAUDE.md's Phase 10 section).
- **backtrader — analyzer pattern, declined.** Pluggable metric collectors over a backtest run; E26 already computes its metrics inline with no measurable gap.
- **Lean — declined on cost/benefit**, not availability (see §17/§11) -- C# architecture reading would not improve an already-benchmarked Python design.
- **freqtrade — RULE reimplemented, not architecture.** Its `sample_strategy.py` RSI/TEMA/BB logic (not its plugin architecture) was ported as `freqtrade_rsi_tema_bb`, now Titan X's best validated 1h strategy on 4 assets.

---

## Summary — what is genuinely new so far

Ranked by confidence, from inspected code only:

| # | Item | Source | Confidence |
|---|---|---|---|
| 1 | **Breaker blocks** | STAR-EA (`DetectBreakerBlocks`) | High — not found in E07 |
| 2 | **Killzone-conditional signal weighting** (per-killzone win-rate feedback) | STAR-EA | High — E07 has killzones, not the feedback |
| 3 | **London Breakout** strategy | quant-trading | Medium — must clear E26 like any candidate |
| 4 | **Pair trading / Parabolic SAR / Awesome Oscillator / Shooting Star** | quant-trading | Medium |
| 5 | **Redis tick storage** for option chains | express-option-chain | Medium |
| 6 | Judas Swing · Silver Bullet · AMD · CRT · OTE | STAR-EA | **Unresolved** — present in STAR-EA, absence from E07 not yet verified |

**Confirmed NOT available from the named sources:** Power of 3, CISD, PD arrays, Wyckoff (the brief
attributes all four to Tradecraft; none is present — see §19), equal highs/lows (4 hits in STAR-EA).

---

## 19. Correction — Tradecraft is mis-described in the brief

The brief lists `mahmoud20138/Tradecraft` as supplying "ICT vocabulary reference, market structure,
scanner scoring (0-12), Wyckoff, Power of 3, PD arrays, CISD".

**It is a Claude Code skills plugin.** 184 files: **177 markdown, 2 Python**. All 169 skill files are
named `SKILL.md`; the topics live in directory names, and they range far outside trading —
`stripe-best-practices`, `video-gen`, `notion-sync`, `transformers-js`, `system-design-academy`.

Searched for the concepts the brief attributes to it:

| Concept | Skills found |
|---|---|
| Power of 3 / PO3 | **0** |
| CISD | **0 skills** — but see correction below |
| PD arrays | **0** |
| Wyckoff | **0** |
| Judas Swing | **0** |
| Silver Bullet | **0** |

It *does* carry relevant prose skills — `ict-smart-money`, `ict-trading-tool`,
`market-structure-bos-choch`, `liquidity-analysis`, `smc-python-library`, `mtf-confluence-scorer`,
`risk-of-ruin`, `drawdown-playbook`, `trade-journal-analytics`, `session-profiler`. These are
**documentation, not algorithms**, so they cannot satisfy Phase 5's requirement for deterministic
detection specifications. Treat as `INSPIRE ONLY`.

**CORRECTION (2026-09-08):** the table above counted SKILL DIRECTORY NAMES, not file contents. Grepping contents finds a full `## CISD -- Change in State of Delivery` section inside `skills/ict-smart-money/SKILL.md`. CISD therefore DOES have a prose source here and is specified in `docs/ICT_SPEC_PHASE5.md` §2. Power of 3 is separately available -- it is already implemented in `research/ict_concepts.power_of_three`. PD arrays and Wyckoff remain unsourced by this repo (though E07 has its own `wyckoff.py`).

**Practical consequence (revised):** PD arrays have **no source repository** in
this brief. If they are wanted in Phase 5, they must be specified from public ICT literature and
Titan X's own `research/ict_concepts.py`, which already exists.

---

## Outstanding before this map is complete — CLOSED 2026-09-13

All 6 items resolved; each section above now carries its own "Closed" note with the finding and
date:

1. ~~Clone and inspect EA_SCALPER_XAUUSD~~ — done, §8 (PolyForm Noncommercial + trading-restricted, `INSPIRE ONLY`).
2. ~~Clone and inspect freqtrade / Lean / backtrader~~ — done, §11/§17/§18 (freqtrade's rule reimplemented and live-validated; Lean/backtrader declined on cost/benefit against already-benchmarked Titan X code).
3. ~~Clone WayneDW/Sentiment-Analysis~~ — done, §12 (`REJECT` -- a from-scratch, untrained 2017 CNN classifier; E09's FinBERT is already categorically superior).
4. ~~Read TradeNote and tradicted-journal at schema level~~ — done 2026-08-21, §14 (both mapped into the real mistake-tagging system that shipped).
5. ~~Decide whether Group F warrants cloning~~ — decided: no, §16 (two full redesign passes confirmed the existing token system is sufficient).
6. ~~Diff STAR-EA's ICT definitions against E07~~ — done 2026-09-08, §3 (`docs/ICT_CONCEPT_DIFF.md`, 26/28 concepts already live).

One real gap surfaced BY closing this checklist, not by it: colour-blind accessibility (§16) was
never assessed and remains open for whenever Phase 12 is worked.
