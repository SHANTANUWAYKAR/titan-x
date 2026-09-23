# Titan-X

A measurement platform for trading strategies. It exists to answer one question
honestly — **does this edge survive contact with costs, noise and out-of-sample
data?** — and it is published with the answers it actually produced, including
the ones nobody wants.

> ### ⚠️ Nothing here is a trading recommendation
> Of **155,017** backtested candidates, **zero** clear this project's own
> validation gates. Six signal families measured net-negative after costs. The
> reports below document that in full. See [`LICENSE`](LICENSE) for the
> disclaimer in detail. **Do not trade this.**

---

## What makes this different

Most backtesting frameworks help you find a strategy that looks good. This one
is built to find out whether the good-looking thing is real — and it is
unusually willing to say no.

| It measures | Because |
|---|---|
| **Cost in R**, not percent | `cost_R = cost / stop_frac`. A tight stop buys more notional per unit of risk, so it pays more cost per R. This single line explains most failed intraday strategies. |
| **Break-even cost** | Not "is it profitable" but "at what cost does it stop being profitable" — then compare that to what you actually pay. |
| **A synthetic null** | At proper grid size, **150 of 150 pure-noise paths** produced "passing" candidates here. A result that hasn't beaten noise is unproven, not good. |
| **Deflated Sharpe** | The best of 155,017 draws looks extraordinary by construction. DSR is the correction for exactly that. |
| **Year-by-year** | The cut that killed five separate leads in this project. A strategy that works in some years is regime exposure wearing a costume. |
| **Unresolved trades** | Excluding trades that never hit a barrier once made a losing idea look profitable — 65% of its trades had silently vanished. |

## Quick start

```bash
git clone https://github.com/YOUR_USERNAME/titan-x.git
cd titan-x
python -m venv .venv && .venv/Scripts/activate      # Windows
pip install -r requirements.txt
cp .env.example .env                                 # add keys if you have them

python scripts/fetch_all_data.py                     # populate data/
pytest tests/ -q                                     # ~1,700 tests
```

`data/` ships empty — see [`data/README.md`](data/README.md).

## The tooling

```
engines/     50+ analysis engines (signals, regime, risk, backtesting, ...)
setups/      the measurement labs — this is the interesting part
scripts/     runnable entry points
research/    synthetic nulls, ablations, IC analysis
tests/       ~1,700 tests, including look-ahead negative controls
reports/     measured results (the evidence)
```

### The labs

| Module | Question it answers |
|---|---|
| `setups/concept_lab.py` | Ten retail concepts, **one shared evaluator**, each against its own shuffled null |
| `setups/trade_journal.py` | Per-trade records + win rate, expectancy, profit factor, drawdown, streaks, by-session/pair |
| `setups/enhance.py` | Does volatility targeting or a regime filter actually reduce drawdown? |
| `setups/high_profile_setup.py` | The published "stocks in play" ORB, rebuilt to spec and tested |
| `setups/challenge.py` | $1→$100 growth ladders, with a minimum-ticket floor and a zero-edge null |
| `scripts/build_playbook.py` | Best strategy per asset per style — and the gate each one fails |

```bash
python setups/run_concept_lab.py --timeframe 1d --sweep-stop 1,2,4
python setups/run_trade_journal.py --timeframes 1d,4h --export-csv
python scripts/build_playbook.py
```

## Selected findings

Every number below is reproducible from this repository.

**Every concept has real gross edge; cost eats all of it.** Ten concepts, one
evaluator, 29 assets:

| Concept | Trades | Gross R | Net R |
|---|---|---|---|
| `failure_test` | 7,137 | **+0.1164** | −0.0842 |
| `round_number` | 102,830 | **+0.1000** | −0.0682 |
| `engulfing_anywhere` | 8,530 | **+0.0004** | −0.1770 |

**Location is worth 80×.** The most-repeated claim in retail education — *a
pattern in the middle of nowhere is noise* — is testable, and it holds:

| | Trades | Gross R |
|---|---|---|
| engulfing **at a level** | 906 | **+0.0331** |
| engulfing **anywhere** | 8,530 | **+0.0004** |

**Osler's microstructure mechanism reproduces.** `round_number` — pure
arithmetic, no chart reading — scores +0.1000 R gross on 102,830 trades.
Take-profit orders cluster *at* round numbers, stop-losses *just beyond*
([Osler, J. Finance 2003](https://onlinelibrary.wiley.com/doi/abs/10.1111/1540-6261.00588)).

**A result that died under its own null.** Widening stops with a scaled time
barrier produced +0.2988 R net. Then: random entries with the same exits scored
**+0.1807 R**, longs made **+0.3400** while shorts lost **−0.3365**. Beta wearing
a costume. Documented in [`reports/CONCEPT_LAB.md`](reports/CONCEPT_LAB.md)
rather than deleted.

## Reports

| Report | Contents |
|---|---|
| [`PLAYBOOK.md`](reports/PLAYBOOK.md) | Best strategy per asset × style, and the gate each fails |
| [`CONCEPT_LAB.md`](reports/CONCEPT_LAB.md) | Ten concepts through one evaluator |
| [`TRADING_ROADMAP.md`](reports/TRADING_ROADMAP.md) | 16 hours of trading education decoded and measured |
| [`HIGH_PROFILE_RESEARCH.md`](reports/HIGH_PROFILE_RESEARCH.md) | Published ORB papers vs this data |
| [`ENHANCEMENTS.md`](reports/ENHANCEMENTS.md) | Volatility targeting and regime filters, measured |
| [`CHALLENGES.md`](reports/CHALLENGES.md) | Account-growth ladders with minimum-ticket floors |

## Contributing

**This project wants contributions that make it better — including ones that
prove parts of it wrong.**

See [`CONTRIBUTING.md`](CONTRIBUTING.md). The short version: **bring a
measurement, not an opinion.** A pull request that adds a strategy needs the
number it scored, the null it beat, the years it survived, and what fraction of
its trades never resolved.

```
fork  →  branch  →  PR against main  →  CI (tests · secrets · file size)  →  merge
```

The most valuable pull request is one that **kills** something. If you show a
strategy here does not work, that is a contribution, not an attack — several
findings in these reports were retracted by exactly that process and are kept
alongside the successes.

Maintainer notes are in [`MAINTAINING.md`](MAINTAINING.md).

## Licence

[MIT](LICENSE), with an explicit not-financial-advice disclaimer. Please read it.
