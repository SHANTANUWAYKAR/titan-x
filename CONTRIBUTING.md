# Contributing

**Bring a measurement, not an opinion.**

This project exists because trading claims are cheap and evidence is not. A
pull request that adds a strategy, a filter or an "improvement" needs to say
what it scored, what it was scored against, and what it cost.

---

## The bar

A change that touches a strategy, a signal or a statistic must come with:

| Required | Why |
|---|---|
| **Trade count** | Below ~100 trades a result is arithmetic. This repo once graded 2,906 candidates "A" on no null evidence at all. |
| **Net expectancy after costs** | Gross edge is easy. `cost_R = cost / stop_frac` is what decides outcomes. |
| **A null comparison** | 150 of 150 pure-noise paths once produced "passing" candidates here. Beating zero is not the bar; beating *noise* is. |
| **Year-by-year results** | The cut that killed five leads in this project. |
| **Unresolved-trade fraction** | If trades that never hit a barrier are excluded, say so and say how many. One lead here looked profitable until 65% of its trades turned out to have silently vanished. |

`setups/concept_lab.py` and `setups/trade_journal.py` compute all of these.
Use them rather than writing a new evaluator — comparability is the point.

## Things that will be asked about

These aren't gotchas; they're the specific mistakes already made in this
codebase, each of which shipped and had to be found later.

- **Look-ahead.** Does a signal at bar `i` change when later bars arrive?
  `tests/unit/test_concept_lab.py` has the negative control — parametrise your
  concept into it.
- **Swing confirmation.** A pivot at `i` is not knowable until `k` more bars
  print. Marking it at `i` is the most common look-ahead in swing code.
- **The leverage cap.** When the cap binds, the position is smaller — so the
  realised R **and** the cost must both shrink. This exact omission appeared
  three separate times here and now has a test.
- **Bars containing stop and target.** OHLC cannot order two touches inside one
  bar. Score it a loss. Assuming the favourable order is how backtests flatter
  themselves.
- **Path-dependent statistics.** Drawdown and losing streaks must be computed
  on **chronologically sorted** trades. Pooling by asset and running a cumsum
  produces a concatenation, not an equity curve.
- **Division by `stop_frac`.** Guard it. Tight stops make this explode.

## Workflow

```bash
git checkout -b feature/short-description
# ... change ...
pytest tests/ -q                       # all of them
git commit -m "..."                    # say what you measured
git push origin feature/short-description
```

Open a PR against `main`. CI runs the suite on every push.

### Commit messages

Say what changed and what it measured. If you fixed a bug, say what the bug
produced, because that is how the next person recognises it:

> ```
> journal: fix drawdown measured over asset-ordered rows
>
> compute_stats ran np.cumsum over rows pooled asset by asset, so
> "164.9 R drawdown, 46-trade losing streak" was unrelated losing
> tails glued end to end. No account could have experienced it.
> Path-dependent stats now sort by date first.
> ```

## Versioning

[Semantic versioning](https://semver.org/). `VERSION` holds the current number,
and every merged PR adds a line to `CHANGELOG.md` under `[Unreleased]`.

| Bump | When |
|---|---|
| **MAJOR** | a public API changes, or a measurement's *meaning* changes |
| **MINOR** | new engine, setup, script or report |
| **PATCH** | bug fix, docs, test |

A bug fix that changes previously published numbers is **MAJOR**, not PATCH —
anyone who acted on the old figure needs to notice.

## Style

- Match the surrounding code; it is deliberately plain.
- Comments explain **why**, especially why an approach was rejected. The
  comment density here is high on purpose: most of it records a trap.
- Docstrings state what a function will **not** do, and what it cannot tell you.
- No new runtime dependency without saying what it replaces.

## Reporting a result that kills something

**These are the most valuable pull requests.** If you show that a strategy in
this repo does not work, that is a contribution, not an attack — the project
has already retracted several of its own findings and documents them alongside
the successes. Open a PR that adds the measurement and updates the report.

## What is not accepted

- Strategies with no measurement.
- Results from a different evaluator, cost model or sample, presented as
  comparable to these.
- Parameter tuning that improves in-sample numbers with no out-of-sample test.
- Anything requiring paid data the CI cannot reach, unless it degrades cleanly.
- Removing a caveat from a report without a measurement that retires it.

## Security

Never commit credentials. `.env` is gitignored; `.env.example` shows the shape.
If you find a committed secret, email rather than opening a public issue.
