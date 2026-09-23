# Changelog

All notable changes are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [Semantic Versioning](https://semver.org/).

**A bug fix that changes previously published numbers is a MAJOR bump, not a
patch** — anyone who acted on the old figure needs to notice.

## [Unreleased]

_Contributions land here. Add a line under the right heading in your PR._

### Added
### Changed
### Fixed
### Retracted

---

## [1.0.0] - 2026-09-23

First public release. The platform and the evidence it produced.

### Added

- **Measurement labs**
  - `setups/concept_lab.py` — ten retail-education concepts through one shared
    evaluator, each scored against its own shuffled null.
  - `setups/trade_journal.py` — per-trade records (date, pair, session, HTF
    bias, entry/SL/TP, R:R, result in R, reason for entry, reason for failure)
    plus win rate, average win/loss, expectancy, profit factor, maximum
    drawdown, longest losing streak, and best/worst session and pair.
  - `setups/enhance.py` — volatility targeting and regime filtering, built so
    their effect on drawdown is measured rather than assumed.
  - `setups/high_profile_setup.py` — the published "stocks in play" opening
    range breakout, rebuilt to its own specification and tested.
  - `setups/challenge.py` — account-growth ladders with a minimum-ticket floor
    and a zero-expectancy null.
  - `scripts/build_playbook.py` — best strategy per asset per trading style,
    with the gate each one fails.
  - `scripts/diagnose_intraday.py` — reports the first stage that stopped each
    asset instead of collapsing eight outcomes into one silent `None`.
- **Statistical machinery**: synthetic-null testing, deflated Sharpe,
  purged/embargoed walk-forward CV, triple-barrier labelling, meta-labelling.
- ~1,700 tests, including look-ahead negative controls on every concept.

### Findings at release

- Six signal families measured **net-negative after costs**.
- **0 of 87** (asset × style) cells clear all four validation gates.
- Best deflated Sharpe across **155,017** candidates: **0.702** — below the
  0.95 bar, meaning the edge is not clearly separable from search luck.
- Published ORB rules: **0 of 24** profitable years on this data.
- A candlestick pattern **at a level** beats the same pattern **anywhere** by
  roughly **80×** in gross edge (+0.0331 R vs +0.0004 R).

### Retracted before release

Kept in the reports rather than deleted, because a retraction is a result:

- **Wider stops with a scaled time barrier.** Reached +0.2988 R net, then
  failed its own null: random entries with the same exits scored +0.1807 R,
  and longs (+0.3400) almost exactly mirrored shorts (−0.3365). Beta, not edge.
- **Relative-volume top-N ranking.** Credited with a monotone dose-response
  until each variable was swept alone: the cross-sectional ranking does
  nothing, and the effect belongs to the threshold.

### Fixed before release

- Drawdown and losing streaks were computed over trades pooled **by asset**,
  producing figures no account could have experienced. Now chronological.
- Cost was charged **uncapped** against a **capped** position, overstating it
  by up to 1.7× on tight stops. Found three separate times; now pinned by test.
- Empty intraday scans returned a silent `0`. They now report how many
  candidates were suppressed and why.
