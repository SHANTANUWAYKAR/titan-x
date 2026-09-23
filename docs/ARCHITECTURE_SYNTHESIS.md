# Architecture Synthesis — PROJECT TITAN-X

**docs/UPGRADE_BRIEF.md Phase 13.** Maps all 55 real, currently-registered
engines (verified against `engines/e<NN>_*/engine.py` and
`engines/registry.py` directly — not inferred from directory names) onto
the brief's proposed layered architecture. Per the brief's own
instruction, this is a **synthesis, not a rewrite**: the goal is showing
how the existing system already realizes (or doesn't yet realize) the
proposed layering, and calling out honestly where a name overstates what
an engine actually does — several engine names in this codebase are far
more ambitious than their implementation (`chief_risk_officer`,
`world_model`, `causal_intelligence`), a pattern this session has run
into repeatedly and verified against source each time rather than assumed.

## Methodology

Every engine below was checked directly: `engine_name`, class/module
docstring, constructor dependencies (which other engines it takes as
collaborators — distinguishes an orchestrator from a leaf analysis
engine), and a skim of its main public methods. Two engines
(`e46_chief_risk_officer`, `e44_chief_investment_officer`) turned out to
be thin reporting/narrative layers with **no independent authority** over
what their names imply — flagged explicitly below so nobody mistakes
E46 for having veto power it does not have.

## The proposed architecture (brief's diagram)

```
Data Layer → Normalization → Feature Engineering → Market Intelligence →
Strategy Engine → Signal Engine → Risk Engine → Portfolio Engine →
Analytics → UI / API

Supporting: News Intelligence · Sentiment · Macro Intelligence ·
Economic Calendar · Knowledge Base · AI/LLM Layer · Research Lab · Journal
```

## Layer-by-layer mapping

### Data Layer
- **E02 Market Data** — OHLCV fetch with a real multi-provider fallback
  chain (Yahoo → ccxt → nselib → Alpha Vantage), the platform's one
  actual entry point for price data. Everything downstream depends on it.

### Normalization
- **E40 Data Quality** — repairs gaps/bad bars in E02's output before
  anything else touches it. This is exactly the brief's "Normalization"
  step already, in the platform's own real pipeline order
  (E02 → E40 → E07, per CLAUDE.md's documented signal pipeline) — no
  renaming or restructuring needed, the layer already exists and already
  sits in the right place.

### Feature Engineering
- **E21 Feature Engineering** — the platform's dedicated feature-prep
  engine.
- **E07 Technical** straddles this layer and Market Intelligence below:
  its indicator computation (EMA/RSI/ATR/MACD/ADX/Bollinger) is feature
  engineering in substance; its structure/pattern detection (order
  blocks, FVGs, liquidity sweeps, Wyckoff, harmonics, RSI divergence —
  see Phase 12's own findings) is genuinely Market Intelligence. Not
  worth splitting E07 into two engines for a layering diagram's sake —
  the existing single-engine boundary is more cohesive than a
  layer-purity split would be (Rule: preserve what's already superior).

### Market Intelligence
- **E06 Fundamental**, **E07 Technical** (structure half — see above),
  **E08 Regime**, **E10 Cross-Asset**, **E11 Microstructure**,
  **E13 Derivatives**, **E14 Fixed Income**, **E15 Credit**,
  **E16 Commodity**, **E17 Crypto**, **E19 Global Liquidity** (FRED
  balance-sheet/M2/real-yield regime classifier),
  **E63 Market Memory** (append-only daily-snapshot log per asset +
  z-scored "find similar historical days" search — genuinely new
  capability, no other engine persists a queryable state history),
  **E64 Causal Intelligence** (real Granger-causality tests via
  statsmodels — verified real statistics, but scoped to 4 hardcoded
  macro-asset pairs, not a general causal-inference system despite the
  name), **E65 World Model** (a pure composition layer over E04 + E10 +
  E19 + E64's outputs — computes nothing itself; the name suggests more
  than a narrative aggregator), **E84 Counterfactual** (real historical
  episode lookup — "every past date this condition held, what happened
  next" — genuinely distinct from scenario/forecast engines, not a
  simulated alternate history despite the name).

### Strategy Engine
- **E24 Strategy Research** — grid-searches parameters of known strategy
  archetypes against E26's IS/OOS validation bar; owns the strategy
  candidate universe (235 real reports on disk, Phase 12 surfaced these).
- **E22 Alpha Research Factory** — a distinct, complementary role from
  E24: tests broader NAMED MARKET HYPOTHESES ("gold performs better
  risk-off") via Welch's t-test on forward returns, not strategy
  parameters. Genuinely two different research modes, not duplication.
- **E25 Strategy Lifecycle** — mechanically derives a strategy's
  researched/live/validated/decaying stage purely from the
  existence/fields of files E24/E51/E38 already wrote — no analysis of
  its own; "retired" stage is an acknowledged, unimplemented gap.
- **E37 Meta-Learning** — attributes E26's real backtest trades to their
  entry-bar regime (trending/ranging) and determines regime-dependence; a
  genuine leaf analysis, feeds a live confidence nudge.
- **E74 Conflict Resolution** — reframes "compare trading philosophies"
  honestly as backtesting two real strategy archetypes (trend-following
  vs. mean-reversion) and comparing regime-conditional expectancy — not
  modeling any real trader's actual private rules, a deliberate and
  correct scope decision already made.
- **E36 Learning** — turns E34's attribution stats into plain-language
  lessons + a named hypothesis pointing at which engine should validate
  it next; thin templating over E34's real numbers, never deploys
  anything itself.

### Signal Engine
- **E51 Signals** — the actual signal generator: strategy override
  resolution, confluence adjustments (pulling in E10/E03/E09/E13/E16/E17/
  E14/E19), the historical-edge gate. This is the platform's real
  decision point for direction/confidence/entry-stop-target.
- **E33 Opportunity Ranking** — runs E51's own workflow across every
  supported asset (not just tradeable ones) and ranks by conviction;
  reuses E51's scoring, owns none of its own.
- **E43 Committee** — a fixed roster of RULE-BASED threshold checks
  (macro/technical/quant/portfolio/risk/knowledge/CIO) voting on one
  signal, with a templated (non-LLM) past-verdict reflection loop. "AI
  committee" is threshold heuristics, not autonomous or learned agents —
  worth stating plainly since the name implies more.
- **E42 Confidence Calibration** — measures whether E51's own
  confidence_at_entry actually predicts win rate (Brier score, ECE); it
  measures calibration, it doesn't calibrate anything itself.
- **E41 Explainable AI** — pure narrative/formatting layer over evidence
  fields other engines already attached to a signal. Computes nothing
  new, by design — "explainable" here means "readably summarized," not
  a model-interpretability technique.

### Risk Engine
- **E45 Risk (CRO)** — the platform's real, sole veto and position-sizing
  authority: confidence floor, R:R, daily/weekly/monthly loss,
  drawdown, portfolio heat, risk-of-ruin, correlation, consecutive-loss
  breaker, funded-account rules.
- **E46 Chief Risk Officer** — **despite the name, has zero veto power.**
  It is a read-only classifier that re-reads E45's own tracked
  `PortfolioRiskState` against E45's own thresholds and reports a
  posture label. Its own docstring already flags the E45/E46 naming
  overlap as a deliberate, documented resolution rather than an
  oversight — repeated here so this synthesis doesn't imply E46 is a
  second real authority.
- **E39 Model Risk** — inventories/hashes every file under `data/models/`
  and verifies every live strategy override carries required governance
  provenance fields (`validated_at`, `oos_sharpe`, etc.) before it's
  trusted — a real, mechanical safeguard against an unvetted file
  silently driving live decisions.
- **E47 Governance** — a compliance checklist (no engine exposes an
  order-placement method, risk-limit config sanity, "no execution engine
  exists"); its most substantive check is entirely delegated to E39, not
  independent policy logic.
- **E48 Execution Readiness** — pre-trade cost/timing estimate combining
  E11's spread/liquidity read with a standard square-root market-impact
  model. Real formula-based estimation, explicitly informational-only,
  never places an order (Rule 5).
- **E28 Stress Testing**, **E29 Scenario Analysis**, **E30 Adversarial
  Testing** — all three orchestrate E26's backtest engine under adverse
  conditions (real historical crisis windows, best/base/worst trade
  outcomes, parameter-perturbation/Monte-Carlo-reorder/single-trade-
  removal robustness checks respectively) rather than owning separate
  math of their own. Correctly categorized under Risk (not Research Lab)
  because their output directly informs whether a strategy/trade should
  be trusted, the same question E45 asks of a single trade.

### Portfolio Engine
- **E31 Portfolio Construction** — min-variance, max-Sharpe, risk-parity,
  efficient frontier, Black-Litterman, volatility targeting, HRP, NCO,
  CVaR/CDaR/Kelly-growth optimization. The most complete implementation
  of any layer in this diagram.
- **E32 Capital Allocation** — orchestrates E33 (ranking) + E51 (signal
  resizing) + E26 (backtest stats) + E12 (Kelly) + E45 (veto) into a
  cross-opportunity capital-deployment plan with opportunity-cost
  reporting for rejected candidates; owns no analysis logic itself.
- **E79 Portfolio Simulation** — forward-looking historical-bootstrap
  Monte Carlo of TODAY'S actual open positions (caller-supplied), genuinely
  distinct from E26 (historical replay) and E28 (crisis replay) by being
  forward/current-position-based.
- **E44 Chief Investment Officer** — a thin narrative/aggregation wrapper
  around E33 + E32's already-computed numbers (net long/short stance,
  top conviction ideas). No LLM, no independent judgment, despite the
  "Chief Investment Officer" name — template string-building over real
  numbers, same pattern as E46.

  **Real gap, stated honestly**: unlike Risk (E45 sits directly in the
  live per-signal pipeline) and Signal (E51 sits directly in it),
  **Portfolio Engine is not yet wired into the live signal-generation
  pipeline at all.** E31/E32/E79/E44 are real, substantial, independently
  useful capabilities (Phase 12 built a UI page against E31+E33+E44's
  logged-intent stand-in) but today they are ad-hoc/API-triggered
  analytics, not a stage every signal passes through the way E45 is. This
  is the single clearest place where the brief's proposed layer diagram
  is aspirational rather than descriptive of current wiring — worth
  flagging as a genuine, not-yet-closed architectural gap rather than
  glossing over it.

### Analytics
- **E12 Quantitative Research** — Sharpe/Sortino/Calmar/CVaR, Kelly,
  correlation, cointegration, Bayesian win-rate. Used as a shared utility
  across nearly every other layer (Risk, Portfolio, Signal, Strategy) —
  genuinely cross-cutting rather than a single-layer citizen, listed here
  because its own primary purpose is measurement, not decisioning.
- **E20 Factor Research** — real Fama-French 5-factor + Carhart momentum
  regression (Newey-West HAC standard errors) — narrow scope (8
  hardcoded US equities only, no forex/crypto/commodities).
- **E23 Forecasting** — empirical historical-bootstrap return-percentile
  distributions, explicitly never a point prediction; feeds E29's
  best/base case.
- **E34 Trade Attribution**, **E35 Performance Analytics** — the trade
  journal's real analytics layer (win rate, profit factor, expectancy,
  Calmar/CVaR/recovery-factor, MAE/MFE, mistake tagging, signal
  conversion rate — see this session's own Phase 9 work).
- **E38 Alpha Decay Monitor** — recent-vs-baseline journal comparison via
  non-overlapping Bayesian CI / Welch's t-test, not just a losing streak.

### UI / API
- **api/main.py** — the FastAPI layer; ~90 routes as of this pass
  (Phase 12 added the last 11: 3 new backend routes + 8 dashboard-page/
  shared-asset routes).
- **dashboard/** — `index.html` (the original 5-page SPA: Overview, Scan
  & Signals, Market Backdrop, Knowledge Base, System Status) plus Phase
  12's 6 new standalone pages (Market Structure, Risk, Portfolio, News &
  Sentiment, Options, Strategy Lab).
- **E00 Titan Brain (Master Orchestrator)** — sits just below this layer,
  coordinating cross-engine workflows the API's own routes call into.

## Supporting lanes (per the brief's own diagram)

- **News Intelligence**: E03.
- **Sentiment**: E09.
- **Macro Intelligence**: E04.
- **Economic Calendar**: E05.
- **Knowledge Base**: E01 (document/trader-profile RAG — hybrid
  vector+keyword search, extractive Q&A, never generative).
- **AI/LLM Layer**: **currently empty.** Verified directly, not assumed:
  no engine anywhere on this platform calls an LLM. E43's "committee
  agents" are rule-based threshold checks; E44/E46/E65's "CIO"/"CRO"/
  "world model" outputs are template-string narration over real numbers;
  E01's document answer endpoint is explicitly extractive (best-matching
  passage + citations), not generated. The brief's proposed layer is
  aspirational relative to the current codebase — stating this plainly
  rather than force-mapping something onto it that isn't there.
- **Research Lab**: the platform's largest supporting cluster —
  E20, E22, E23, E24, E26, E27, E28, E29, E30, E36, E37, E63, E64, E74,
  E79, E84. This is intentionally broad: "Research Lab" isn't a separate
  silo so much as the validation/backtesting/hypothesis-testing
  discipline that cuts across Strategy, Risk, and Market Intelligence —
  E26 (Backtesting Laboratory) and E27 (Walk-Forward Validation) are its
  structural core, everything else in this list either feeds them
  scenarios to test or consumes their output.
- **Journal**: E34 + E35 + the `Trade`/`TradeIntent`/`TradeTag`/
  `SignalContextSnapshot`/`MistakeRuleDefinition` database tables
  together — the engines are the analytics layer over the journal, not
  the journal itself.

## What to preserve exactly as-is (already superior to a rewrite)

Per the brief's own instruction ("preserve the existing structure where
it is already superior — this is a synthesis, not a rewrite"):

1. **E45 as sole veto/sizing authority.** Splitting risk logic across
   multiple engines would only recreate the E45/E46 naming confusion
   this synthesis just had to explicitly untangle. Keep one real
   authority; keep E46 explicitly read-only and say so in its own
   position in any future diagram.
2. **E07's single-engine boundary** (feature computation + structure
   detection together) over a layer-pure split — cohesion over
   diagram-purity.
3. **The E22/E24 split** (named-hypothesis testing vs. strategy-parameter
   grid search) — two genuinely different research modes, not
   duplication; don't merge them into one "Research" engine.
4. **E26 as the single Backtesting Laboratory** every stress/scenario/
   adversarial/portfolio-simulation engine orchestrates, rather than each
   of E28/E29/E30/E79 reimplementing its own backtest loop — already the
   right amount of reuse.
5. **The Stage 0 gate discipline in E51** (missing-tag-defaults-to-
   validated, hand-tagged via `research/score_overrides_stage0.py`) — a
   real, working safety mechanism this whole session has repeatedly had
   to re-verify/re-apply after an external process's promotions strip
   the tag; it's fragile in the sense of needing re-application, but the
   underlying design (data-driven, reversible, auditable) is sound and
   should not be replaced with a code-level change.

## What the brief's diagram gets right that isn't built yet

Only one real gap, stated once rather than repeated per-engine above:
**Portfolio Engine has no live pipeline seat.** E45 (Risk) sits directly
between every generated signal and its final size; E31/E32 (Portfolio)
do not sit anywhere in that path today — they're real, useful, and
reachable via API/UI, but a signal's position size today comes from
E45's own `calculate_position_size`/`calculate_kelly_position_size`, not
from a portfolio-level allocation step. Closing this (deciding whether
E32's capital-allocation plan should gate/adjust E45's sizing, or stay a
separate parallel analysis surface) is a real design decision for a
future phase, not something this synthesis pass should decide unilaterally.
