# Titan-X Runbook

Everything built during the 2026-09-20/21 audit, what it answers, and when to
run it. Written so the answers survive without anyone remembering the session.

---

## The one command that matters

```
.venv\Scripts\python.exe scripts\live_readiness_gate.py
```

Answers **"can real money go on this?"** from evidence. Five gates, every one a
veto. Current state: **2 of 5 pass.**

| Gate | State 2026-09-21 |
|---|---|
| Forward evidence | FAIL — 1 resolved trade, need 30 |
| Beats synthetic null | FAIL — 0 of 46 overrides clear 95.0 |
| Net positive after costs | FAIL — −0.0527% equity/trade |
| Deflated Sharpe | PASS — 1 candidate ≥ 0.95 |
| Drawdowns are real | PASS — median 8.07% |

Run it any time. It exists so the encouraging results cannot be remembered while
the disqualifying ones are forgotten.

---

## Running unattended

Both survive session death, reboots and closed terminals.

| Task | Schedule | Log |
|---|---|---|
| `TitanX Option Chains` | hourly | `logs\chain_recorder.log` |
| `TitanX Null Queue` | on demand | `logs\null_queue.log` |

```
schtasks /query /tn "TitanX Option Chains"
schtasks /run   /tn "TitanX Null Queue"      # resumes from checkpoint
```

The API server also runs a forward test every 6 hours and its own chain job —
but only while it is up, which is why the chain recorder was moved to a task.

---

## Diagnostic scripts

| Script | Question it answers |
|---|---|
| `live_readiness_gate.py` | Can real money go on this? |
| `recheck_calibration.py` | Has the generator changed since 2026-09-21? |
| `calibrate_signal_confidence.py` | What does a confidence number actually mean? |
| `feature_information_test.py` | Which price features predict outcomes? |
| `cross_asset_feature_test.py` | Do other instruments add information? |
| `net_edge_surface.py` | Is there any trade construction that beats costs? |
| `report_edge_lift.py` | How much of a pass rate is earned vs free? |
| `resweep_all.py` | Re-backtest the book (`--resume`, timeframe-major) |
| `record_option_chains.py` | `--status` shows the options history |
| `scan_high_profile.py` | Live scan for the published ORB setup, in the platform's signal shape |
| `fetch_transcripts.py` | Pull YouTube transcripts into `data/knowledge/transcripts/` (`--status` lists them) |

## Setups (`setups/`, deliberately separate from `strategies.py`)

| Runner | Question it answers |
|---|---|
| `run_setup_backtest.py` | Does the composed Titan setup survive walk-forward? |
| `run_orb_backtest.py` | `--orb-minutes 5 --entry-model retest` tests the YouTube rules exactly |
| `run_high_profile.py` | Does the published "stocks in play" ORB reproduce here? |
| `run_challenge.py` | What fraction of $100 accounts reach $1,000 on this edge? |
| `run_ml_audit.py` | Purged/embargoed CV across the model zoo |

Reports: `HIGH_PROFILE_RESEARCH.md` (all sources decoded and measured),
`CHALLENGES.md` (the growth ladder), `HIGH_PROFILE_SETUP.md` (the RVOL claim
tested), `ORB_BACKTEST_5m_retest.md` (the YouTube rules).

---

## What was found, and what it cost

Six independent methods, one verdict: **no demonstrable edge.**

| Finding | Before | After |
|---|---|---|
| Trading calendar | one 24/7 table | asset-class aware — intraday equity Sharpe was inflated **2.31×** |
| Position sizing | 1% *notional* | 1% *risk* — drawdowns went from a fictional 0.08% to a real 8.07% |
| Drawdown gate | never fired once | **22,570** candidates now fail it |
| Grade caps | documented, unenforced | enforced — A grades **2,906 → 4** |
| Deflated Sharpe | field existed, never computed | gates A+ |
| ETH null percentile | 100.0 | **80.7** — fails |
| BTC null percentile (live) | 98.0 | **60.0** — fails |

Leads tested and killed: more price indicators (redundant), cross-asset
(mostly beta), relative strength (sign flips yearly), wider stops
(**65% of trades excluded as unresolved**), long bias (+0.5 in 2022, −3.6 in 2026).

**Economics:** +0.0076 R gross per trade against 0.0603 R of cost — losing ~8×.
At *zero* cost the rule earns **+2.76%/yr**, below risk-free. Execution cannot
fix a gap that large; the edge is ~10× too small for 363 trades/year.

---

## What would change the answer

Only two things, and both need time rather than code.

1. **Forward evidence — ~95 days.** Running. The only evidence not measured on
   the decade everything was fitted to.
2. **Option surface — ~7 months.** Recording hourly. BTC/ETH only (all Deribit
   lists), which is why it is months not weeks. The first genuinely non-price
   input this platform will ever have had.

When either matures, re-run the readiness gate. If it still says NOT READY,
nothing has changed regardless of how it feels.

---

## Standing caveats

- Every backtest number is in-sample over the decade the strategies were fitted to.
- Bars containing both stop and target are scored **losses** — results are never
  worse than reported, and may be better.
- `promote_if_validated` stays `False`. Nothing in this repo can tag itself live;
  that needs a deliberate Stage 0 tag.
- 143 tests cover backtesting, scoring, look-ahead, risk, research and stress.
  Run them before trusting any change.
