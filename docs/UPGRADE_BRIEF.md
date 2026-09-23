# CRAFT MASTER BRIEF — Repository Intelligence & Engine Upgrade
## Project Titan X

> **How to use this file:** Save to `TIS/project_titan_x/docs/UPGRADE_BRIEF.md`.
> Then in Claude Code, run one phase at a time:
> `Read docs/UPGRADE_BRIEF.md. Execute PHASE 1 only. Stop and report.`

---

# C — CONTEXT

## The system being upgraded

Project Titan X is an existing trading intelligence system. **55 engines, 23 strategies, a 167-candidate research grid, 45 live strategy overrides, 854 tests.** Python, Windows, FastAPI + React.

### Signal pipeline (current)

```
E02 Market Data   → fetch OHLCV (Yahoo → ccxt → nselib → Alpha Vantage fallback)
E40 Data Quality  → repair gaps/bad bars
E07 Technical     → EMA, RSI, ATR, MACD, ADX, Bollinger
                    + smart_money (BOS/CHoCH, sweeps, order blocks, FVG)
                    + killzones, order_flow (CVD), wyckoff, volume_profile
E08 Regime        → classify trending / ranging / volatile
E51 Signals       → _load_strategy_override(symbol, timeframe)
                      ├─ override exists? → run THAT validated strategy fn
                      └─ no override?     → baseline composite rule
                    _apply_confluence_adjustments()
                    ← E10 cross-asset, E03 news, E09 sentiment, E13 derivatives,
                      E16 commodity, E17 crypto, E14 fixed income, E19 liquidity
E51 edge gate     → validate_historical_edge() vetoes proven-negative edges
E45 Risk          → confidence floor → R:R → daily/weekly/monthly loss →
                    drawdown → portfolio heat → risk-of-ruin → correlation →
                    consecutive-loss breaker → funded-account rules
                    → position size (capped at max_position_leverage)
                  ↓
SIGNAL (direction, confidence 0-100, entry/stop/target, size)
```

### Promotion loop (current)

```
E24 Research → 167 candidates × asset × timeframe
             → E26 Backtesting: IS/OOS walk-forward split
             → bar: IS trades≥30, IS Sharpe>0.5, maxDD<25%, OOS Sharpe>0
             → best = max(min(IS, OOS))   ← consistency, not luckiest split
             → promote_if_validated=True writes {SYMBOL}_{TF}_strategy_override.json
             → E51 picks it up automatically on the next signal
```

### Markets covered
Forex · Gold/XAUUSD · Silver · Crypto · Indian indices (NIFTY/BANKNIFTY/FINNIFTY) · Indian equities · Options (NSE/BSE F&O via Zerodha Kite Connect)

### Target capability set
Technical analysis · ICT/SMC · quantitative strategies · market structure · risk management · sentiment · news intelligence · macro intelligence · backtesting · walk-forward validation · strategy research · portfolio/risk analytics · trading journal · future MT5 integration · advanced dashboard

---

## ALREADY INTEGRATED — do not redo

| Item | Source | Status |
|---|---|---|
| `dual_thrust` | je-suis-tm/quant-trading | **Live** |
| `heikin_ashi` | je-suis-tm/quant-trading | **Live** |
| shadcn OKLCH design tokens | shadcn-ui/ui | **In use** |
| hummingbot | hummingbot/hummingbot | **Deliberately SKIPPED** — execution engine, violates Rule 5 |

Existing E07 `smart_money` module already implements BOS/CHoCH, liquidity sweeps, order blocks, and FVG. Do not reimplement these — only identify what is genuinely *new* in the source repos.

---

## Repository sources

### Group A — ICT / SMC
| # | Repo | Concepts to extract |
|---|---|---|
| 1 | `NadirAliOfficial/STAR-EA-v11.20` | ICT FVG, FVG retracement, killzones, sessions, EA architecture, 12-scenario classifier, Judas Swing, Silver Bullet, AMD, CRT, OTE |
| 2 | `manuelinfosec/profittown-sniper-smc` | SMC, BOS, order blocks, confluence, signal logic |
| 3 | `mahmoud20138/Tradecraft` | ICT vocabulary reference, market structure, scanner scoring (0-12), Wyckoff, Power of 3, PD arrays, CISD |
| 4 | `francomascareloai/EA_SCALPER_XAUUSD` | XAUUSD-specific logic, scalping entry/exit |

### Group B — Quant / frameworks
| # | Repo | Concepts to extract |
|---|---|---|
| 5 | `je-suis-tm/quant-trading` | Research structure, remaining strategies (Dual Thrust + Heikin Ashi already live) |
| 6 | `freqtrade/freqtrade` | Strategy framework, indicators, backtesting, hyperopt, strategy lifecycle |
| 7 | `QuantConnect/Lean` | **Architecture reference only** — data abstraction, parallel search, portfolio construction |
| 8 | `mementum/backtrader` | **Architecture reference only** — strategy engine, analyzers, event-driven design |
| 9 | `WayneDW/Sentiment-Analysis-in-Event-Driven-Stock-Price-Movement-Prediction` | Financial sentiment, Loughran-McDonald lexicon, event-driven pipeline |

### Group C — Risk
| # | Repo | Concepts to extract |
|---|---|---|
| 10 | `youcefbibo53/PropGuard-Trailing-Equity-Armor` | Trailing drawdown, equity protection, prop-firm controls |
| 11 | `bipbopcompany-droid/Risk-Nexus-Command` | Risk monitoring, kill-switch, multi-account equity sync |

### Group D — Journal
| # | Repo | Concepts to extract |
|---|---|---|
| 12 | `Eleven-Trading/TradeNote` | Journal schema, mistake tagging, trade pattern analysis |
| 13 | `tradicted/tradicted-journal` | Trading-plan rule checklist, rule-adherence analytics |

### Group E — Indian options
| # | Repo | Concepts to extract |
|---|---|---|
| 14 | `pramakrishn/express-option-chain` | Option chain ingestion, Kite API, Redis tick storage |
| 15 | `anurag-roy/kite-option-chain` | Option chain UI, grouped instruments, bid/ask/LTP |

### Group F — UI / design systems
| # | Repo | Use |
|---|---|---|
| 16 | `shadcn-ui/ui` | **Primary component architecture — already adopted** |
| 17 | `radix-ui/primitives` | Accessible primitives, component behaviour — reference |
| 18 | `uber/baseweb` | Enterprise/data-heavy patterns — reference only |
| 19 | `mui/material-ui` | Data-dense dashboard patterns, a11y — reference only |
| 20 | `darelova/Awesome-Design-Resources-List` | Inspiration only |
| 21 | `bradtraversy/design-resources-for-developers` | Inspiration only |

---

# R — ROLE

Act as a combined **Principal Quant Engineer · Quantitative Researcher · ICT/SMC systems researcher · Risk-management engineer · Financial data engineer · Backend architect · Frontend architecture specialist · Code auditor · Security engineer · Open-source licensing auditor.**

Think like an engineer building a production-grade quantitative platform, not a trading bot.

**Priority order — never invert this:**

1. Correctness
2. Risk control
3. Data integrity
4. Reproducibility
5. Backtest validity
6. Architecture
7. Maintainability
8. Performance
9. UI/UX
10. Feature quantity

Never sacrifice correctness to add features.

---

# A — ACTION

Execute phases **in order**. Stop and report after each phase. Do not proceed to implementation until the roadmap is approved.

---

## PHASE 1 — AUDIT MY PROJECT FIRST

Inspect the existing project before touching any repository or writing any code.

Identify: languages, frameworks, directory structure, services, APIs, databases, data models, strategy engine, signal engine, indicator engine, backtesting engine, risk engine, portfolio engine, news engine, sentiment engine, AI/ML components, UI, auth, configuration, logging, testing, containerization, WebSocket architecture, external APIs, environment variables, dependency management.

**Produce `PROJECT_AUDIT.md`** covering:
- Existing capabilities (map each to its engine number where possible)
- Missing capabilities
- Architectural weaknesses
- Duplicate systems
- Technical debt
- Performance bottlenecks
- Security risks
- Data-quality risks
- Testing gaps (note current: 854 tests)
- Scalability problems

**Do not modify the project during this phase.**

---

## PHASE 2 — REPOSITORY INTELLIGENCE

Clone each repo to `./external/<name>`. Inspect actual source code — **not just READMEs**. For MQL repos, read the `.mq4` / `.mq5` files directly.

For each repository produce:

```
Repository:
Category:
Purpose:
Architecture:
Key modules:
Key algorithms:
Useful features:
Potential reuse (code):
Potential reimplementation (concept only):
Dependencies:
License:
Security concerns:
Code quality:
Testing quality:
Performance:
Compatibility with Titan X:
Red flags:
Decision: KEEP EXISTING / IMPROVE / ADAPT / REIMPLEMENT / INSPIRE ONLY / REJECT
```

**Red flags to actively hunt for:** single-commit history, templated/auto-generated README, unverified performance claims, near-identical clones of sibling repos, code requesting broker credentials directly, Selenium-based broker automation.

**Mark `**MQL → PYTHON TRANSLATION REQUIRED**`** on every MetaTrader repo. These cannot be imported — only reimplemented.

If a repository cannot be accessed, **say so. Do not invent its contents.**

---

## PHASE 3 — REPOSITORY KNOWLEDGE MAP

**Produce `REPOSITORY_KNOWLEDGE_MAP.md`**, organising every discovery under:

ICT · SMC · Market Structure · FVG · Order Blocks · BOS · CHoCH · Liquidity · Killzones · Sessions · Scalping · XAUUSD · Quant strategies · Indicators · Backtesting · Optimization · Walk-forward · Sentiment · News · Risk management · Drawdown protection · Journaling · Indian markets · Options · Option chain · UI · Design systems · Accessibility · Performance · Architecture

---

## PHASE 4 — FEATURE MATRIX & DEDUPLICATION

**Produce `REPOSITORY_FEATURE_MATRIX.md`:**

| Feature | Repository | Exists in Titan X? | Engine | Quality | Compatibility | Priority | Action |
|---|---|---|---|---|---|---|---|

Classify every feature: `KEEP EXISTING` / `IMPROVE EXISTING` / `ADAPT` / `REIMPLEMENT` / `INSPIRE ONLY` / `REJECT`

**Mandatory conflict resolution before anything is proposed:**

- **Group A conflict:** STAR-EA, profittown-sniper-smc, Tradecraft, and EA_SCALPER all overlap with each other *and* with existing E07 `smart_money`. Compare all four against my current BOS/CHoCH/order-block/FVG implementations. Report what is genuinely NEW (likely: killzone time-windows, Judas Swing, AMD cycle, CRT, OTE) versus what already exists. **Do not integrate duplicates.**
- **Group C conflict:** PropGuard and Risk-Nexus-Command overlap with each other and with E45's existing drawdown / loss-limit / funded-account logic. Pick the **best mechanism per rule type** (static vs trailing drawdown, daily reset timing, kill-switch trigger) and justify each choice. **Do not merge all three blindly.**
- **Group F:** shadcn is already the primary component architecture. Radix, Base Web, and MUI are **reference only** — do not install a second component library.

Flag every conflict in **bold `CONFLICT`**.

Do not import code merely because a repository contains it.

---

## PHASE 5 — ICT / SMC FORMAL SPECIFICATION *(REWRITTEN 2026-09-08)*

> **Why this phase was rewritten.** The original asked for deterministic specifications of 28 ICT
> concepts. `docs/ICT_CONCEPT_DIFF.md` measured what already exists: **26 of the 28 are already
> implemented as working code** — 9 live in `engines/e07_technical/`, 17 in
> `research/ict_concepts.py`. Specifying all 28 would mostly re-specify software that already runs,
> and the measurement that matters (which concepts actually carry edge) has already been done in
> `research/ablation_*.json`.
>
> The original text is preserved verbatim at the bottom of this section.

### Revised scope

**1. Specify only what has no implementation.**

| Concept | Status | Action |
|---|---|---|
| **CRT (Candle Range Theory)** | Only source is STAR-EA (MIT). Not in Titan X. Unmeasured. | **Full deterministic spec + ablation before any port** |
| **CISD** | Prose source in Tradecraft's `ict-smart-money` skill (found on re-check). Not in Titan X. Composable from existing FVG/IFVG/displacement primitives. | **Specified** — see `ICT_SPEC_PHASE5.md` §2. Ranked below CRT: its core component `inverse_fvg` measured negative on all three assets |

**2. Do not specify the 9 concepts already live in E07** — FVG, FVG mitigation, order blocks,
breaker blocks, BOS, CHoCH, liquidity sweeps, killzones, Silver Bullet. `KEEP EXISTING`.

**3. Do not port the 14 stranded concepts the ablation rejected.** `inverse_fvg`
(−0.208/−0.569/−0.270), `ce`, `bpr`, `turtle_soup` and `displacement` are negative on all three
tested assets; `premium_discount`, `ote`, `liquidity_raid_d` and `draw_on_liquidity` are negative or
mixed. Porting them would subtract expectancy. **Record them as rejected** so they are not
re-proposed from the same repositories later.

**4. Two concepts remain open decisions, not specification work.** `eqh_eql` and `power_of_three`
are positive on all three assets but rest on 20–50 trades — below the 60-trade floor Stage 0
adopted. Porting them means accepting evidence this project has already judged too thin. That is a
standards decision for the owner, not something a specification resolves.

**5. `mss` is done** — ported to `engines/e07_technical/smart_money.py` on 2026-09-08 with
discriminating no-lookahead tests.

### Deliverable

`docs/ICT_SPEC_PHASE5.md` — for CRT only, at the full depth the original demanded (mathematical
definition, detection algorithm, required data, timeframes, confirmation logic, edge cases,
false-positive conditions, backtesting requirements, example signal structure), plus an explicit
decision record for CISD and the rejected set.

### What did NOT change

Rule 3 still applies in full: CRT enters as an E24 candidate and must clear E26 **and** the Stage 0
timeframe floors like anything else. A specification is not a promotion.

---

<details>
<summary><strong>Original Phase 5 text (superseded, kept for reference)</strong></summary>


Build a deterministic specification for every ICT/SMC concept found:

Fair Value Gap · FVG mitigation · FVG retracement · Inversion FVG · Breaker blocks · Order blocks · BOS · CHoCH · Liquidity sweeps · Equal highs · Equal lows · Previous day high/low · Previous week high/low · Session highs/lows · Premium/discount · Dealing ranges · Displacement · Market structure · Killzones · London/NY/Asian sessions · ICT time concepts · Judas Swing · Silver Bullet · AMD cycle · OTE · CRT · Power of 3 · CISD

For **each** concept define:
- Mathematical / algorithmic definition
- Detection algorithm
- Required OHLCV data
- Timeframe(s)
- Confirmation logic
- Edge cases
- False-positive conditions
- Backtesting requirements
- Example signal structure

**Convert subjective ICT terminology into deterministic algorithms.** Do not implement vague natural-language rules. Every signal must be explainable and reproducible.

---

</details>

---

## PHASE 6 — QUANT ENGINE EXTRACTION

Analyse the quant repos for: strategy interfaces, indicator architecture, signal generation, position sizing, portfolio management, backtesting, optimization, parameter management, transaction-cost modelling, slippage, commission, walk-forward analysis, Monte Carlo, performance metrics, strategy comparison.

Extract concepts from: RSI · TEMA · Bollinger Bands · momentum · mean reversion · trend following · volatility strategies · event-driven strategies. (Dual Thrust and Heikin Ashi already live — skip.)

Define a **standardised internal strategy interface** so every strategy conforms to:

```
Data → Features → Signal → Risk → Position → Analytics
```

*(Note: no Execution stage — see Rule 5.)*

---

## PHASE 7 — BACKTESTING ENGINE

Compare E26's existing architecture against Freqtrade, LEAN, backtrader, and quant-trading. Determine which best suits Titan X. **Do not combine frameworks unnecessarily.**

The unified backtest must support: historical OHLCV · multi-timeframe · tick data where available · spread · commission · slippage · latency assumptions · partial fills · position sizing · SL/TP/trailing stop · risk limits · multiple simultaneous positions · portfolio-level risk · walk-forward validation · out-of-sample testing · Monte Carlo simulation.

Explicitly detect: **look-ahead bias · survivorship bias · data leakage · overfitting · future information leakage · unrealistic fills.**

### Institutional validation upgrades (highest priority in this phase)

The current E26 bar is statistically insufficient for a 167-candidate grid. Implement:

1. **Deflated Sharpe Ratio (DSR)** with an **effective N** — cluster candidates by return correlation and use the cluster count, never the raw 167. Require DSR > 0.95.
2. **Synthetic-null baseline** — run the entire E24→E26 promotion loop on block-bootstrapped/shuffled returns to measure the real false-positive rate. The live bar must sit above whatever the null promotes.
3. **CPCV** (Combinatorial Purged Cross-Validation) with 21-day purge and embargo, replacing the single IS/OOS split. Judge on the *distribution* of OOS paths.
4. **Raise minimum trade count** from 30 to 100 (prefer 200+).
5. **Parameter sensitivity** — report performance at ±20% on key parameters. Knife-edge performance = overfitting.
6. **Cost stress test** — rerun at 2× spread/slippage. (Existing kill criterion already does this — keep it.)

Report metrics **per instrument**, never blended.

---

## PHASE 8 — RISK ENGINE (E45)

Using Group C as reference, strengthen the centralised risk engine. It must support:

Fixed-percentage risk · ATR-based sizing · volatility-based sizing · max daily loss · max weekly loss · max drawdown · **trailing equity drawdown** · consecutive-loss protection · max open positions · correlation exposure · sector exposure · asset exposure · leverage limits · margin limits · risk-per-trade · portfolio VaR · position concentration · **kill switch**

Funded-account module must distinguish **static vs trailing** drawdown models and implement a green/yellow/red zone system that reduces size as daily losses accumulate, with a hard stop at 80% of the daily limit (buffer for slippage).

**Risk management must be independent of individual strategies. A strategy must NEVER be able to bypass global risk controls.**

---

## PHASE 9 — JOURNAL / PERFORMANCE INTELLIGENCE

Design a unified journal (new module — touches neither E45 nor E51) capturing:

Entry · exit · instrument · direction · strategy · setup · timeframe · risk · R-multiple · P&L · screenshot refs · **market regime (from E08)** · **confluence score at entry** · **which signal layers agreed/disagreed** · mistake classification · context tags · execution quality · slippage · MAE · MFE

**Also log signals that were NOT taken** — skipped-signal data is where discipline is measured.

Analytics: win rate · profit factor · expectancy · average R · max drawdown · Sharpe · Sortino · Calmar · CVaR · recovery factor · performance by strategy / setup / session / time-of-day / instrument / mistake tag.

**Rule-based mistake tagging** (deterministic, not AI-guessed): traded below own confluence threshold · traded outside killzone · size exceeded Kelly recommendation · traded in red daily-loss zone · revenge pattern (multiple trades within minutes of a loss, increasing size) · overrode a disagreeing layer.

The journal feeds E24 research as a **suggestion only** — it must never auto-adjust live parameters.

---

## PHASE 10 — INDIAN OPTIONS ENGINE

From Group E, extract: option chain ingestion · expiry handling · strike selection · CE/PE · open interest · volume · IV · Greeks where available · PCR · OI change · max pain · ATM/ITM/OTM classification.

Design a clean **`OptionChainProvider`** interface with adapters. **Do not hard-code a single broker into the application.**

**Indian F&O lot sizes, expiry conventions, and brokerage must stay isolated from crypto/forex position-sizing assumptions.** These are not interchangeable.

---

## PHASE 11 — NEWS + SENTIMENT

Design: `News → Entity Extraction → Event Detection → Sentiment → Market Impact → Signal Context`

Fields: bullish/bearish/neutral · confidence · event type · entity · timestamp · source · instrument relationship.

- Prevent duplicate news events.
- Store **source timestamp and publication timestamp separately.**
- **Never allow future news to contaminate historical backtests.**
- Sentiment feeds E09 as a **confirming filter only** — never a primary signal trigger.

---

## PHASE 12 — UI / DESIGN SYSTEM

shadcn/ui with OKLCH tokens is already the primary architecture. **Do not install a second component library.** Radix / Base Web / MUI / the awesome-lists are reference only.

Dashboard surfaces: market overview · watchlist · charts · market structure · ICT/SMC signals · quant signals · risk dashboard · portfolio · positions · trade journal · news · sentiment · economic calendar · option chain · backtesting · strategy laboratory · AI research assistant.

Maintain: consistent spacing · typography · responsive layouts · WCAG AA contrast · keyboard navigation · semantic components · design tokens · dark trading environment.

**Colour-blind safety is mandatory**, not optional: buy/sell and profit/loss must differ in **lightness or shape (▲/▼)**, not hue alone. Roughly 1 in 12 men have red-green colour blindness and this is a UI where that failure is dangerous.

**Do not touch the existing UI file.** New work goes in new files.

---

## PHASE 13 — ARCHITECTURAL SYNTHESIS

Propose the improved architecture:

```
Data Layer → Normalization → Feature Engineering → Market Intelligence →
Strategy Engine → Signal Engine → Risk Engine → Portfolio Engine →
Analytics → UI / API
```

Supporting: News Intelligence · Sentiment · Macro Intelligence · Economic Calendar · Knowledge Base · AI/LLM Layer · Research Lab · Journal.

Map every existing engine (E02, E03, E07, E08, E09, E10, E13, E14, E16, E17, E19, E24, E26, E40, E45, E51 …) onto this architecture. **Preserve the existing structure where it is already superior** — this is a synthesis, not a rewrite.

---

## PHASE 14 — DEPENDENCY & LICENSE AUDIT (mandatory)

For every repository determine: license · commercial-use permission · attribution requirements · copyleft obligations · dependency licenses · whether direct code reuse is safe · whether reimplementation is safer.

My stack is MIT/Apache. **Flag every GPL/AGPL/proprietary repo before integrating.**

Where licensing is unclear → **`REIMPLEMENT / INSPIRE ONLY`**.

Do not assume GitHub code is free to copy.

---

## PHASE 15 — IMPLEMENTATION ROADMAP

**Produce `UPGRADE_ROADMAP.md`**, split into P0 (critical) / P1 (high value) / P2 (useful) / P3 (optional).

Per task: feature · source repo · reason · files affected · dependencies · complexity · risk · testing requirements · expected benefit.

**Stop here. Wait for my approval before implementing anything.**

---

## PHASE 16 — IMPLEMENT (only after approval)

Rules:
- Do not rewrite working systems unnecessarily
- Do not duplicate functionality
- Do not introduce unnecessary dependencies
- Do not break APIs without migration
- Preserve backward compatibility where practical
- Add tests for new functionality
- Add documentation and type hints
- Use structured logging; handle errors explicitly
- Keep secrets out of source; never hard-code API keys or broker credentials
- Never disable existing safety controls

Per implementation: (1) explain what's changing → (2) implement → (3) run tests → (4) lint/type check → (5) verify imports → (6) verify app startup → (7) verify affected APIs → (8) verify migrations → (9) confirm nothing unrelated broke.

Report format:
```
Feature:
Source:
Reason:
Implementation:
Files changed:
Tests:
Validation:
Risks:
Status:
```

---

## PHASE 17 — TESTING

Unit · integration · strategy · backtest-validation · risk-engine · data-provider · API · UI tests.

**Adversarial cases required:** missing candles · duplicate candles · incorrect timestamps · market gaps · zero volume · extreme volatility · NaN values · API failure · partial data · duplicate news · invalid option chain · max drawdown breach · multiple simultaneous signals · conflicting strategies.

**No-lookahead tests at MULTIPLE truncation points are mandatory** for every new strategy. A single midpoint cut once missed a real order-block lookahead bug that showed a false 94.8% win rate.

Add **property-based tests (Hypothesis)** on the risk layer asserting invariants: confidence always 0-100 · stop always on the correct side of entry for both directions · no feature at bar *t* uses data from *t+k*.

**854 tests must still pass. Report the count after changes.**

---

## PHASE 18 — FINAL AUDIT

**Produce `FINAL_UPGRADE_REPORT.md`:** what was discovered · reused · reimplemented · rejected · improved · new architecture · new dependencies · license considerations · security considerations · performance improvements · testing results · remaining weaknesses · recommended next steps.

---

# F — FORMAT

Maintain these documents in `docs/`:

- `PROJECT_AUDIT.md`
- `REPOSITORY_KNOWLEDGE_MAP.md`
- `REPOSITORY_FEATURE_MATRIX.md`
- `UPGRADE_ROADMAP.md`
- `FINAL_UPGRADE_REPORT.md`

Use the per-repository and per-feature templates given in Phases 2 and 16. Flag **`CONFLICT`** and **`MQL → PYTHON TRANSLATION REQUIRED`** in bold wherever they apply.

---

# T — TIGHT CONSTRAINTS

## Titan X architectural rules — violating any of these fails the task

1. **Rule 5: NO execution engine.** This system reports; I trade. Reject any extracted code that places orders. Keep execution architecture isolated behind interfaces if ever needed.
2. **`engines/` must NEVER import `research/`.** Research code stays in `research/` until deliberately ported with tests.
3. **Nothing extracted goes live by shortcut.** Every new strategy enters as an E24 candidate and must clear E26 like any other. No repo's backtest claim substitutes for my own validation.
4. **Never weaken the E26 bar** to accommodate an extracted strategy. If nothing validates, that is the answer.
5. **Promotion is explicit** — `promote_if_validated=True`, never automatic.
6. **Kill criterion, no re-tuning.** Fails walk-forward or 2× costs → dropped, not re-optimised.
7. **Multi-truncation no-lookahead tests** required on every new strategy.
8. **Indian F&O logic stays isolated** from crypto/forex position sizing.
9. **Do not touch the existing UI file.**
10. **854 tests must pass.**

## General engineering constraints

11. Do not blindly clone or copy entire repositories.
12. Do not overwrite working systems without comparison.
13. Do not assume repository code is production-ready or profitable.
14. Do not assume backtest results are reliable. **Never treat historical backtest performance as proof of future profitability.**
15. Separate research code from production code.
16. Separate strategy logic from risk management. **Risk controls have higher authority than strategies.**
17. Do not introduce live trading merely because a repository supports it.
18. Never expose or hard-code API keys, credentials, or tokens.
19. Do not install unnecessary frameworks or a second UI component library.
20. Prefer adapters over vendor-specific implementations.
21. Prefer deterministic algorithms for ICT/SMC concepts.
22. **Every signal must be explainable.**
23. Every backtest must state its assumptions, including transaction costs and slippage.
24. **Never use future candles or future news for historical signal generation.**
25. Preserve timestamp integrity. Use UTC internally; convert at presentation boundaries only.
26. Preserve reproducibility through configuration and versioning (log seed, git SHA, data checksum per promotion).
27. Add tests before declaring a subsystem complete.
28. If a repository cannot be accessed, **do not invent its contents.**
29. If code quality is poor, use it as a conceptual reference — do not import it.
30. If licensing is unclear, do not copy code.
31. Do not add complexity for its own sake. **Prefer fewer high-quality modules over dozens of loosely connected features.**
32. Do not modify OS networking, firewall, DNS, hosts files, drivers, or system configuration.
33. Do not perform destructive operations (deleting files, databases, environments, configs) without explicit approval.
34. **A shorter honest list beats a longer credulous one.** Where a repo duplicates something I already have, or can't be verified as sound, say so and skip it.

---

# TARGET

Titan X's architecture intact and its engines upgraded with the **single best version** of each mechanism found across these repositories — not a mashup of all of them, and not trust placed in whichever repo claims the best numbers.

I should be able to read the resulting documents and understand exactly what each repository contributed, what was rejected and why, and what remains unproven — **without reading the original sources myself.**

Prioritise correctness and honesty over feature count. If a concept doesn't cleanly fit the architecture, say so rather than forcing it in.
