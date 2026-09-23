# REPOSITORY_FEATURE_MATRIX.md — Phase 4

**Date:** 2026-09-08. **Basis:** source inspection of cloned repositories plus the concept diff in
`docs/ICT_CONCEPT_DIFF.md`. Nothing here is inferred from a README.

**Coverage:** 14 of 21 repositories inspected. Group F (6 UI repos) deliberately not cloned — see
§6. `QuantConnect/Lean` not cloned — see §7.

---

## 1. Licence gate — applied before any feature is considered

This decides the ceiling on every row below, so it comes first.

| Repository | Licence | Ceiling |
|---|---|---|
| `NadirAliOfficial/STAR-EA-v11.20` | MIT | Code reuse permitted (MQL→Python translation still required) |
| `je-suis-tm/quant-trading` | Apache-2.0 | Code reuse permitted |
| `pramakrishn/express-option-chain` | MIT | Code reuse permitted |
| `anurag-roy/kite-option-chain` | MIT | Code reuse permitted |
| `tradicted/tradicted-journal` | MIT | Code reuse permitted |
| `WayneDW/Sentiment-Analysis-...` | MIT | Code reuse permitted |
| `freqtrade/freqtrade` | **GPL-3.0** | **`INSPIRE ONLY`** — copyleft, incompatible with this MIT/Apache stack |
| `mementum/backtrader` | **GPL-3.0** | **`INSPIRE ONLY`** |
| `Eleven-Trading/TradeNote` | **GPL-3.0** | **`INSPIRE ONLY`** |
| `francomascareloai/EA_SCALPER_XAUUSD` | **PolyForm Noncommercial 1.0.0** | **`REJECT`** — not open source; forbids commercial use, and ships a `TRADING_RESTRICTIONS.md` |
| `manuelinfosec/profittown-sniper-smc` | **NONE** | **`REJECT`** — no licence = all rights reserved |
| `youcefbibo53/PropGuard-...` | NONE | **`REJECT` — malware** |
| `bipbopcompany-droid/Risk-Nexus-Command` | NONE | **`REJECT` — malware** |
| `mahmoud20138/Tradecraft` | MIT | `INSPIRE ONLY` — documentation, not algorithms |

**Four of fourteen are unusable on licence grounds alone**, before any assessment of quality.

---

## 2. Feature matrix

| Feature | Repository | Exists in Titan X? | Engine | Quality | Compatibility | Priority | Action |
|---|---|---|---|---|---|---|---|
| FVG detection | STAR-EA | **Yes** | E07 `detect_fair_value_gaps` | high both | n/a | — | `KEEP EXISTING` |
| FVG mitigation | STAR-EA | **Yes** | E07 | high both | n/a | — | `KEEP EXISTING` |
| Order blocks | STAR-EA | **Yes** | E07 `detect_order_blocks` | high both | n/a | — | `KEEP EXISTING` |
| Breaker blocks | STAR-EA | **Yes** | E07 `OrderBlock.breaker` | high both | n/a | — | `KEEP EXISTING` |
| BOS / CHoCH | STAR-EA, profittown | **Yes** | E07 `detect_structure_events` | STAR high; profittown **broken** | n/a | — | `KEEP EXISTING` |
| Liquidity sweeps | STAR-EA | **Yes** | E07 `detect_liquidity_sweeps` | high both | n/a | — | `KEEP EXISTING` |
| Killzones | STAR-EA | **Yes** | E07 `killzones.py` | Titan X **better** (IANA tz vs manual DST table) | n/a | — | `KEEP EXISTING` |
| Silver Bullet | STAR-EA | **Yes** | E07 killzone sub-windows | high both | n/a | — | `KEEP EXISTING` |
| MSS | — | **Yes (new)** | E07 `market_structure_shift` | ported 2026-09-08 | n/a | — | `KEEP EXISTING` |
| Killzone win-rate feedback | STAR-EA | No | — | medium | **poor** — self-referential | P3 | `INSPIRE ONLY` (§4) |
| CRT (Candle Range Theory) | STAR-EA | **No** | — | real enums, unmeasured | good | **P2** | `REIMPLEMENT` — MQL→Python + ablation first |
| CISD | none | No | — | — | — | — | **No source anywhere** |
| Neural network in EA | STAR-EA | No | — | **poor** — untested MQL5 NN | **poor** | — | `REJECT` |
| Judas / AMD / OTE / PO3 / EQH-EQL | STAR-EA + `research/` | **In `research/`** | `ict_concepts.py` | measured | — | — | `KEEP EXISTING` — ablation says most are negative (§3) |
| London Breakout | quant-trading | No | — | unknown | good (Apache) | **P1** | `ADAPT` — must clear E26 + Stage 0 |
| Pair trading | quant-trading | No | — | unknown | good | P2 | `ADAPT` |
| Parabolic SAR | quant-trading | No | — | unknown | good | P3 | `ADAPT` |
| Awesome Oscillator | quant-trading | No | — | unknown | good | P3 | `ADAPT` |
| Shooting Star | quant-trading | No | — | unknown | good | P3 | `ADAPT` |
| Options Straddle | quant-trading | Partly | E13 | unknown | medium | P3 | `INSPIRE ONLY` |
| VIX Calculator | quant-trading | Partly | E13/E12 | unknown | medium | P3 | `INSPIRE ONLY` |
| MACD / RSI / Bollinger strategies | quant-trading | **Yes** | E24 grid | — | — | — | `KEEP EXISTING` |
| Indicator/entry/exit separation | freqtrade | No | E24 combines them | high | good | **P1** | `INSPIRE ONLY` (GPL) |
| `@informative` multi-timeframe merge | freqtrade | Partial | E02 resamples | high | good | **P1** | `INSPIRE ONLY` (GPL) |
| **`custom_stoploss` / `custom_roi`** | freqtrade | **No** | — | high | good | **P0** | `INSPIRE ONLY` — closes a known E26 gap (§5) |
| Pluggable hyperopt loss function | freqtrade | Partial | Stage 0 fixed rule | high | good | P2 | `INSPIRE ONLY` |
| Execution hooks (`confirm_trade_entry`, `order_filled`, `custom_entry_price`) | freqtrade | No | — | — | **violates Rule 5** | — | `REJECT` |
| Event-driven analyzers | backtrader | Partial | E26/E35 | high | GPL | P3 | `INSPIRE ONLY` |
| Bayesian DNN on headlines | sentiment repo | No | E09 uses **FinBERT** | 2018-era, inferior | poor | — | `REJECT` (§8) |
| Loughran-McDonald lexicon | sentiment repo | No | — | **not implemented** | — | — | **Mis-attributed** (§8) |
| Trailing equity drawdown | Group C | Partial | E45 | **no source** | — | **P0** | Build from scratch (§9) |
| Kill switch | Group C | **No** | — | **no source** | — | **P0** | Build from scratch (§9) |
| Green/yellow/red sizing zones | Group C | No | — | **no source** | — | P1 | Build from scratch (§9) |
| Option chain ingestion (Kite) | express-option-chain | **Yes** | `core/data_providers/kite_option_chain.py` | comparable | good (MIT) | — | `KEEP EXISTING` |
| Redis tick storage for chains | express-option-chain | No | Redis exists, no tick store | medium | good | P2 | `ADAPT` |
| Connector/instrument-manager split | express-option-chain | **Yes** | already adapter-shaped | — | — | — | `KEEP EXISTING` |
| Option chain UI | kite-option-chain | No | dashboard has no chain view | medium | **poor** — Next.js, no React here | P3 | `INSPIRE ONLY` |
| Journal schema | TradeNote | **Yes** | E35 + `trade_tags` | comparable | GPL | — | `KEEP EXISTING` |
| MAE / MFE capture | TradeNote | **No** | — | medium | GPL | P2 | `REIMPLEMENT` |
| Skipped-signal logging | — | **No** | — | — | — | P2 | Build from scratch |
| Rule-adherence checklist | tradicted-journal | **Yes** | `mistake_tagging.py` | Titan X **better** (theirs never persists) | — | — | `KEEP EXISTING` |
| ICT vocabulary docs | Tradecraft | n/a | — | prose only | — | — | `INSPIRE ONLY` |
| `ip-rotation` skill | Tradecraft | No | — | — | **violates no-evasion rule** | — | `REJECT` |

---

## 3. **`CONFLICT`** — Group A (STAR-EA / profittown / Tradecraft / EA_SCALPER vs E07)

**Resolved with measurement, in `docs/ICT_CONCEPT_DIFF.md`.** Summary:

- **9 concepts already live in E07** — FVG, FVG mitigation, order blocks, breaker blocks, BOS, CHoCH, liquidity sweeps, killzones, Silver Bullet. **Do not integrate duplicates.**
- **17 concepts sit in `research/ict_concepts.py`**, unreachable by any engine. Of these, the ablation found only `mss`, `eqh_eql` and `power_of_three` positive on all three tested assets. `mss` was ported 2026-09-08. The rest measured **negative or mixed** — `inverse_fvg` −0.208/−0.569/−0.270, plus `ce`, `bpr`, `turtle_soup`, `displacement` negative on all three. **Integrating them would subtract expectancy.**
- **1 concept genuinely new: CRT**, from STAR-EA only. Unmeasured.
- **CISD has no source** in any of the four repos.
- **Titan X's killzone implementation is better than STAR-EA's**: IANA `zoneinfo` handles DST automatically, where STAR-EA maintains a manual UTC-offset table that is wrong for 1–2 weeks each spring and autumn (EU and US shift on different dates).
- **profittown contributes nothing** — `trade_engine.py` and `market_scanner.py` are 0 bytes, and its `detect_bos` is a Donchian breakout mislabelled as Break of Structure.
- **Tradecraft contributes nothing algorithmic** — 177 markdown files, 2 Python; the four concepts the brief credits it with (Power of 3, CISD, PD arrays, Wyckoff) are all absent.
- **EA_SCALPER is licence-blocked** regardless of content.

**Net: one candidate (CRT) out of four repositories, and it needs an ablation before it means anything.**

---

## 4. Killzone win-rate feedback — why `INSPIRE ONLY`, not `ADAPT`

STAR-EA maintains a running win rate per killzone and feeds it back into signal scoring
(`GetKillzoneQualityBonus`, `UpdateKillzoneStats`). Titan X has killzones without that feedback.

It is downgraded from a candidate to `INSPIRE ONLY` for two reasons:

1. **It is self-referential.** A live-updating win rate that feeds signal scoring changes the rule that generates the trades that update the win rate. The brief's own Phase 9 forbids exactly this: the journal "feeds E24 research as a suggestion only — it must never auto-adjust live parameters."
2. **The ablation says killzones have no solo edge** on this platform's data: −0.125 / −0.182 / +0.032. Weighting signals by killzone performance builds on a component with no demonstrated standalone value.

If wanted, the correct shape is an offline E24 research input, not a live feedback loop.

---

## 5. **`P0`** — the one finding that closes a known gap

`freqtrade`'s `custom_stoploss` / `custom_roi` hooks, and a backtester that actually simulates them,
address a gap **CLAUDE.md already documents as real and unfixed**:

> "E26's backtest exits are signal-flip only — E51's own stop_loss/take_profit_1/take_profit_2
> levels shown in every live signal are NEVER actually tested by the backtest that 'validates' that
> signal's edge."

So every Sharpe, win rate and Stage 0 percentile on this platform describes a strategy that exits on
signal flip — **not the strategy a human following the stated stop and target would actually run.**
freqtrade demonstrates the shape of the fix (barrier-aware exits evaluated inside the simulator).

**GPL-3.0, so concepts only — no code.** And CLAUDE.md is right that this is a structural change
needing explicit sign-off: it redesigns E26's exit logic, decides barrier-vs-signal-flip precedence,
handles intrabar touches under the next-bar-open fill convention, and re-validates every shipped
default again. **Highest-value item in this matrix, and the least safe to start casually.**

---

## 6. **`CONFLICT`** — Group F resolved by deletion, not comparison

The brief says shadcn is the primary component architecture and Radix/Base Web/MUI are reference
only. **Both halves are moot.** Phase 1 established the dashboard is a single 3,145-line static
`index.html` — no `package.json`, no `src/`, no build step, **no React**. shadcn exists as
hand-written OKLCH CSS tokens, not components.

"Do not install a second component library" cannot be violated when there is no first one. **None of
the six Group F repositories was cloned**, because no feature comparison against a non-existent
component layer would mean anything. Phase 12 needs re-scoping before any of them is worth reading.

---

## 7. Not inspected, and why

| Repo | Reason |
|---|---|
| `QuantConnect/Lean` | Apache-2.0 but **C#**, 573 MB. Concept transfer only, and its main relevance (parallel search architecture) addresses research throughput, which is a Titan X design question — not answerable by reading someone else's C#. |
| Group F ×6 | §6 |
| `EA_SCALPER_XAUUSD` source | Licence-blocked (§1). Metadata pulled at 405 KB via a blobless clone — 1,054 files, 549 MQL — enough to classify without downloading 1.14 GB. |

---

## 8. Correction — the sentiment repo is mis-described in the brief

The brief credits `WayneDW/Sentiment-Analysis-...` with "financial sentiment, **Loughran-McDonald
lexicon**, event-driven pipeline."

**It does not implement Loughran-McDonald.** The name appears twice in the README — once in a
"future work" paragraph ("we need to dig into these words") and once in the reference list. The
actual implementation is 10 files: a PyTorch Bayesian DNN over one-hot-encoded Reuters headlines.

**E09 already uses FinBERT** — a transformer fine-tuned on financial text, strictly more capable than
a 2018 one-hot + DNN model. `REJECT` for the model; the event-driven *pipeline shape* is the only
transferable idea, and E03 already has one.

That makes **three brief mis-attributions** found so far: Tradecraft (Power of 3, CISD, PD arrays,
Wyckoff), this repo (Loughran-McDonald), and the "FastAPI + React" premise.

---

## 9. **`CONFLICT`** — Group C resolved by rejection

The brief asks to "pick the best mechanism per rule type" across PropGuard, Risk-Nexus-Command and
E45. **Both repositories are malware** (see `REPOSITORY_KNOWLEDGE_MAP.md` §13): zero code files, an
hourly cron Action fabricating commit history, and an XOR-obfuscated fake GitHub UI serving
`ecore-project.zip` from `unlocktool.click` behind forged "SLSA level 3" and "ClamAV 0 threats"
badges.

There is no mechanism to compare. **Phase 8's three genuine gaps — trailing equity drawdown, kill
switch, green/yellow/red sizing zones — must be built from first principles.**

Partial credit where due: E45 already implements `FundedAccountProfile` with static/trailing
drawdown, UTC daily reset, and a consecutive-loss circuit breaker, and consistency-rule enforcement
was added 2026-08-21. The gaps are narrower than the brief assumes.

---

## 10. What this matrix actually recommends

Ranked by value, with the licence and evidence constraints applied:

| # | Item | Action | Why |
|---|---|---|---|
| 1 | **Barrier-aware exits in E26** | Build (freqtrade as concept reference) | Every validation number on the platform currently describes a strategy nobody trades |
| 2 | **Kill switch + trailing DD + sizing zones** | Build from scratch | No source exists; Group C was malware |
| 3 | **London Breakout** | `ADAPT` from quant-trading | Apache-licensed, aligns with existing session/killzone work, must clear E26 + Stage 0 |
| 4 | **CRT** | `REIMPLEMENT` + ablate | The only genuinely new ICT concept found in 21 repositories |
| 5 | MAE/MFE + skipped-signal logging | Build | Phase 9 requirements with no usable source |
| 6 | Redis tick storage for option chains | `ADAPT` | MIT, small, additive |

**Everything else is `KEEP EXISTING`, `INSPIRE ONLY`, or `REJECT`.**

The honest summary of Phase 2–4: **21 repositories yielded one genuinely new tradeable concept
(CRT, unmeasured), a handful of Apache-licensed strategy candidates, and one high-value
architectural insight that is GPL and therefore concepts-only.** Four repositories were unusable on
licence grounds, two were malware, and three of the brief's own descriptions were wrong. That is a
shorter and more honest list than the brief anticipated, which is the outcome its own constraint 34
asks for.
