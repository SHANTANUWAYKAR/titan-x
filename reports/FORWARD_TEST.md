# Forward Test

Generated: 2026-09-19T15:29:14.749057+00:00
Inception: **2026-09-15T07:49:28.318429+00:00**
Predictions: **2** · Resolved: **0**

Every row below was written **before its outcome was knowable**. `engines/e24_strategy_research/forward_test.py` refuses any record dated before this log's inception, dated in the future, or written more than three bars after its own bar closed — so this file cannot be padded with replayed history, which is the only thing that separates it from the backtests that already exist.

Only overrides carrying an explicit `stage0.status == "VALIDATED"` tag are tracked, matching the deny-by-default rule that governs live signals.

## Series

| Instrument | TF | Strategy | Predicted | Resolved | Fwd win% | Fwd exp. (R) | Total R | Backtest win% | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| BTC-USD | 1d | `dual_thrust` | 2 | 0 | — | — | — | 52.5% | **no_forward_evidence** |

## How long until this means anything

- **BTC-USD 1d**: 19 resolved forward trades would be needed to detect a fall from the claimed 52.5% to breakeven (33.3%, implied by the planned 2.00:1 reward:risk) — at the observed signal rate, roughly **95 days**. Currently 0.

## Notes

**BTC-USD 1d · dual_thrust**

- No resolved forward trades yet. Nothing here supports or contradicts the backtest; the strategy is running on historical evidence alone.
- Backtest claim read against its own breakeven (33.3%): p=0.00032. Against a 50% baseline the same claim reads p=0.37 -- quoting either number without its baseline invites the wrong conclusion. Both describe the BACKTEST, not forward evidence.

## What this does and does not establish

- A `consistent` verdict means the backtest claim has not yet been contradicted. It is not confirmation, and with a thin sample it is barely evidence — the credible interval does the talking, not the point estimate.
- Ambiguous bars (range containing both stop and target) are counted as **stops**. OHLC cannot order two touches inside one bar, so the true result is never worse than what is reported here and may be better.
- Bars with no signal are not logged. They are real observations about the strategy, but they are not trades, and padding a win-rate denominator with them would understate it.
- Missed runs are lost, not backfilled. A gap in the log is a gap in the evidence.

## Keeping this accumulating

Evidence only accrues on bars that were actually observed. The scheduled job inside the API server fires **immediately on startup** and then every 6 hours, so starting the server at any point during a day captures that day's bar. Days when the server never runs are lost permanently — `record_signal` refuses bars more than three bars stale, which is the rule that makes this a forward test rather than a backtest.

To accumulate without depending on the server being up, register the CLI as a daily Windows task (run it yourself; it changes system state, so it is not done for you):

```
schtasks /create /tn "TitanX Forward Test" /sc daily /st 02:00 \
        /tr "<repo>/.venv/Scripts/python.exe <repo>/scripts/run_forward_test.py"
```

Either route is enough on its own; running both is harmless, because a second call inside the same bar is a deduplicated no-op.
